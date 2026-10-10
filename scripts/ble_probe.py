#!/usr/bin/env python3
"""Exercise the Bluetooth LE protocol against a real lock.

Nothing in :mod:`pyschlage.ble` has been tried against hardware. This walks
the protocol one stage at a time so that a failure says which stage broke
rather than only that something did, and prints enough raw bytes to diagnose
the stages most likely to be wrong.

Read-only by default: it reads the lock's identity, firmware, battery and
state, and writes nothing. Locking and unlocking a real door is behind
``--allow-state-change``, which restores the state it found.

Usage::

    uv run python scripts/ble_probe.py --list
    uv run python scripts/ble_probe.py --device-id <id>
    uv run python scripts/ble_probe.py --device-id <id> --allow-state-change

Credentials come from ``--user`` and a prompt, from ``SCHLAGE_USER`` and
``SCHLAGE_PASSWORD``, or from ``~/.schlage``::

    username=someone@example.com
    password=hunter2
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import dataclass, field
import getpass
import os
from pathlib import Path
import secrets
import stat
import sys
import time
import traceback
from typing import Any

import aiohttp
from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
import cbor2

from pyschlage import request
from pyschlage.aio import AiohttpTransport, Schlage, Setting, Transport
from pyschlage.aio.lock import Lock
from pyschlage.auth import Auth
from pyschlage.ble import backend, crypto, framing, session, uweave

# Reads that change nothing, as (label, trait, attribute).
_IDENTITY_READS = (
    ("manufacturer", uweave.TRAIT_LOCK_DATA, uweave.MANUFACTURER_NAME),
    ("model", uweave.TRAIT_LOCK_DATA, uweave.MODEL_NAME),
    ("serial", uweave.TRAIT_LOCK_DATA, uweave.SERIAL_NUMBER),
    ("firmware", uweave.TRAIT_LOCK_DATA, uweave.FIRMWARE_VERSION),
    ("battery level", uweave.TRAIT_LOCK_DATA, uweave.BATTERY_LEVEL),
    ("current time", uweave.TRAIT_LOCK_DATA, uweave.CURRENT_TIME),
)

# Settings reads, which go through the method a lock config group uses.
_SETTING_READS = (
    ("beeper enabled", uweave.BEEPER_ENABLED[0]),
    ("auto-lock time", uweave.AUTO_LOCK_TIME[0]),
    ("lock-and-leave", uweave.LOCK_AND_LEAVE_ENABLED[0]),
    ("access code length", uweave.ACCESS_CODE_LENGTH[0]),
)


DEFAULT_CREDENTIALS = "~/.schlage"


def read_credentials(path: str) -> dict[str, str]:
    """Reads ``key=value`` lines from a credentials file.

    A missing or unreadable file yields nothing rather than failing, since the
    caller can still prompt. Blank lines and ``#`` comments are skipped, keys
    are matched case-insensitively, and only the first ``=`` splits a line, so
    a password may contain one.

    :param path: Where to look, ``~`` included.
    :type path: str
    :rtype: dict[str, str]
    """
    expanded = Path(path).expanduser()
    try:
        text = expanded.read_text()
    except FileNotFoundError:
        return {}
    except OSError as ex:
        log(f"  WARNING: cannot read {expanded}: {ex}")
        return {}

    mode = expanded.stat().st_mode
    if mode & (stat.S_IRGRP | stat.S_IROTH):
        log(
            f"  WARNING: {expanded} is readable by others "
            f"({stat.filemode(mode)}). chmod 600 it."
        )

    values = {}
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            log(f"  WARNING: {expanded}:{number} has no '=', ignoring it")
            continue
        values[key.strip().lower()] = value.strip()
    return values


@dataclass
class Report:
    """What each stage did, for a summary at the end."""

    results: list[tuple[str, str, str]] = field(default_factory=list)

    def record(self, stage: str, outcome: str, detail: str = "") -> None:
        self.results.append((stage, outcome, detail))

    @property
    def failed(self) -> bool:
        return any(outcome == "FAIL" for _, outcome, _ in self.results)

    @property
    def opened_a_session(self) -> bool:
        """Whether anything actually spoke the protocol.

        A run that stops at the scan proves nothing about the protocol, and
        said otherwise until this existed.
        """
        return any(
            stage == "open a session" and outcome == "ok"
            for stage, outcome, _ in self.results
        )

    def summarize(self) -> None:
        print("\n" + "=" * 72)
        print("SUMMARY")
        print("=" * 72)
        width = max(len(stage) for stage, _, _ in self.results)
        for stage, outcome, detail in self.results:
            line = f"  {outcome:5}  {stage:{width}}"
            if detail:
                line += f"  {detail}"
            print(line)
        print()
        if self.failed:
            print("Something failed. The stage above is where to look; the")
            print("output further up has the bytes.")
        elif self.opened_a_session:
            print("Every stage passed, and a session was opened, so the")
            print("protocol works against this lock.")
        else:
            print("Nothing failed, but no session was opened, so this says")
            print("nothing about whether the protocol works. Only the stages")
            print("listed above ran.")


def log(message: str = "") -> None:
    print(message, flush=True)


def stage(name: str) -> None:
    log()
    log("-" * 72)
    log(f"STAGE: {name}")
    log("-" * 72)


def hexdump(label: str, data: bytes) -> None:
    log(f"  {label} ({len(data)} bytes)")
    for offset in range(0, len(data), 16):
        chunk = data[offset : offset + 16]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        log(f"    {offset:04x}  {hexpart:<47}  {text}")


@contextmanager
def attempt(report: Report, name: str) -> Iterator[list[str]]:
    """Runs a stage, recording what happened instead of unwinding."""
    stage(name)
    detail: list[str] = []
    started = time.monotonic()
    try:
        yield detail
    except Exception as ex:
        elapsed = time.monotonic() - started
        log(f"  FAILED after {elapsed:.1f}s: {type(ex).__name__}: {ex}")
        log()
        traceback.print_exc()
        report.record(name, "FAIL", f"{type(ex).__name__}: {ex}")
        raise SystemExit(1) from ex
    report.record(name, "ok", "; ".join(detail))


# -- Cloud ------------------------------------------------------------------


@asynccontextmanager
async def cloud(user: str, password: str) -> Any:
    """Yields an authenticated client and the transport underneath it."""
    async with aiohttp.ClientSession() as http:
        transport = AiohttpTransport(Auth(user, password), http)
        yield await Schlage.from_transport(transport), transport


def describe_lock(lock: Lock) -> str:
    return (
        f"{lock.device_id}  {lock.device_type:12}  {lock.name!r}  "
        f"model={lock.model_name!r}  mac={lock.mac_address}  "
        f"sat={len(lock._sat)} chars  cat={len(lock._cat)} chars"
    )


def cat_minter(transport: Transport, device_id: str) -> Callable[[str], Awaitable[str]]:
    """Returns a minter that asks the catStar service for a fresh CAT."""

    async def mint(value: str) -> str:
        log(f"  lock asked for a fresh CAT; posting value={value}")
        response = await transport.send(request.mint_cat(device_id, value))
        log(f"  catStar returned keys {sorted(response)}")
        return str(response["CAT"])

    return mint


# -- Bluetooth --------------------------------------------------------------


def _normalize_address(value: str) -> str:
    """Strips a MAC down to bare hex so formats can be compared."""
    return "".join(c for c in value.lower() if c.isalnum())


async def scan(timeout: float) -> list[tuple[BLEDevice, Any]]:
    """Scans without filtering, and reports everything in range.

    Filtering on the uWeave service would be the obvious thing and is wrong:
    bleak drops any advertisement that carries no service UUIDs at all, and an
    advertisement has only 31 bytes to spend, so a device that holds a service
    need not name it there. The filter hides the very locks it is meant to
    find.
    """
    log(f"  scanning {timeout}s, unfiltered")
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    # bleak reports 127 when a platform gives it no RSSI, which would sort to
    # the top as though it were the closest thing in the room.
    pairs = sorted(
        found.values(),
        key=lambda pair: -200 if pair[1].rssi == 127 else pair[1].rssi,
        reverse=True,
    )
    if not pairs:
        log("  nothing at all, not even unrelated devices")
        return pairs

    log(f"  {len(pairs)} devices in range:")
    for device, adv in pairs:
        bits = [f"rssi={adv.rssi}"]
        if adv.local_name:
            bits.append(f"name={adv.local_name!r}")
        if adv.service_uuids:
            bits.append(f"services={adv.service_uuids}")
        if adv.manufacturer_data:
            vendors = ", ".join(
                f"{company:#06x}:{payload.hex()}"
                for company, payload in adv.manufacturer_data.items()
            )
            bits.append(f"manufacturer={{{vendors}}}")
        if adv.service_data:
            bits.append(f"service_data={sorted(adv.service_data)}")
        log(f"    {device.address}  {'  '.join(bits)}")
    return pairs


ALLEGION_COMPANY_ID = 0x013B
"""Company id the locks advertise their manufacturer data under."""

# The manufacturer data, once the company id is stripped. These offsets hold
# for advertisement version 1; a later version packs the same information into
# TLV blocks from offset 3 on, and the app dispatches on the version byte
# before reading any of it. Version 1's flat bytes happen to parse as a TLV
# chain as well, so the version check is what keeps that misreading out.
#
# Offsets 5 and 6 and the bytes after the MAC are read nowhere in the app.
# Across four scans of one lock the pair at 5-6 went 00:49, 00:49, 00:49,
# 00:4a and another lock's went 00:04, 00:05, 00:05, so they look like a
# slow counter -- which is an observation, not a meaning, and nothing here
# depends on it. The MAC is the only field that held still.
_ADVERTISEMENT_VERSION = 0
_ADVERTISEMENT_PLATFORM = slice(1, 3)
_ADVERTISEMENT_COMMISSIONING = 3
_ADVERTISEMENT_SECURITY_VERSION = 4
# The scanner reads the MAC at this offset whatever the version says.
_ADVERTISEMENT_MAC = slice(7, 13)

_FLAT_ADVERTISEMENT_VERSION = 1

COMMISSIONING_STATES = {
    1: "awaiting factory reset",
    2: "commissioned",
    3: "unconnected",
}

# Platforms that are locks. The app's enum carries many more Allegion
# products; these are the ones that matter here.
LOCK_PLATFORMS = {
    b"\x00\x08": "Leopard",
    b"\x00\x09": "Denali",
    b"\x00\x17": "Jackalope",
    b"\x00\x18": "Encode Lever",
    b"\x00\x29": "WKD",
    b"\x00\x30": "Walton",
    b"\x00\x31": "Gainsborough Selene Entrance",
    b"\x00\x32": "Gainsborough Selene Secure",
    b"\x00\x41": "Schlage Selene Entrance",
}


def allegion_payload(adv: Any) -> bytes | None:
    """Returns a lock's manufacturer data, if it has any."""
    payload = (adv.manufacturer_data or {}).get(ALLEGION_COMPANY_ID)
    if payload is None or len(payload) <= _ADVERTISEMENT_MAC.stop - 1:
        return None
    return bytes(payload)


def advertised_mac(adv: Any) -> bytes | None:
    """Returns the MAC a lock advertises, if its payload looks like one.

    The locks put their MAC at a fixed offset in the manufacturer data, and it
    is the only identifier that survives macOS, where Core Bluetooth reports
    its own handles instead of addresses. The app reads it by slicing the raw
    advertisement at absolute positions, which only lands on it because
    everything ahead is fixed-length; going through the manufacturer data by
    company id is the same bytes, found more robustly.
    """
    payload = allegion_payload(adv)
    return None if payload is None else payload[_ADVERTISEMENT_MAC]


def describe_advertisement(adv: Any) -> str | None:
    """Describes what a lock says about itself before anything connects.

    Only the flat version-1 layout is decoded. A later version carries the
    same fields as TLV blocks, and since version 1's bytes also parse as a
    TLV chain, reading one as the other would produce confident nonsense.
    """
    payload = allegion_payload(adv)
    if payload is None:
        return None
    version = payload[_ADVERTISEMENT_VERSION]
    if version != _FLAT_ADVERTISEMENT_VERSION:
        return f"advertisement v{version}, which this does not decode"
    platform = payload[_ADVERTISEMENT_PLATFORM]
    state = payload[_ADVERTISEMENT_COMMISSIONING]
    return (
        f"{LOCK_PLATFORMS.get(platform, 'unknown')} ({platform.hex()}), "
        f"{COMMISSIONING_STATES.get(state, f'commissioning state {state}')}, "
        f"security v{payload[_ADVERTISEMENT_SECURITY_VERSION]}"
    )


def describe_candidates(pairs: list[tuple[BLEDevice, Any]]) -> None:
    """Lists what looks like a lock, and which MAC each one claims."""
    candidates = [
        (device, adv)
        for device, adv in pairs
        if advertised_mac(adv) is not None
        or "schlage" in (adv.local_name or device.name or "").lower()
    ]
    if not candidates:
        log("  nothing in range looks like a Schlage lock")
        return
    log(f"  {len(candidates)} device(s) look like a lock:")
    for device, adv in candidates:
        mac = advertised_mac(adv)
        shown = mac.hex(":") if mac else "no MAC in its payload"
        described = describe_advertisement(adv) or "no Allegion payload"
        log(f"    {device.address}  {adv.local_name!r}")
        log(f"      mac={shown}")
        log(f"      {described}")


async def find_device(lock: Lock, timeout: float, address: str | None) -> BLEDevice:
    """Finds the lock, or explains what was in range instead."""
    if address:
        log(f"  looking for {address} directly")
        device = await BleakScanner.find_device_by_address(address, timeout=timeout)
        if device is None:
            raise RuntimeError(f"no device at {address} within {timeout}s")
        return device

    pairs = await scan(timeout)
    if not pairs:
        raise RuntimeError(
            "the scan saw no Bluetooth devices at all. A Mac in a normal room "
            "sees several, so this is more likely a permission problem than an "
            "empty room: check System Settings > Privacy & Security > "
            "Bluetooth for your terminal."
        )

    for candidate, adv in pairs:
        if backend.matches(lock, candidate, adv):
            log(f"  matched {candidate.address}")
            log(f"    it says: {describe_advertisement(adv)}")
            return candidate

    describe_candidates(pairs)
    raise RuntimeError(
        f"{len(pairs)} devices are in range and none is {lock.name!r}, "
        f"which advertises either {lock.mac_address} or "
        f"{backend.advertised_name(lock)!r}. Guessing is worse than stopping: "
        "a lock that is not this one answers the handshake's first step and "
        "then goes silent, which looks like a protocol bug.\n\n"
        "If a candidate above is the right lock, --address <address> settles "
        "it, since only the lock a SAT was issued for can answer step 2.\n\n"
        "Otherwise it is not advertising: press a keypad key and re-run."
    )


HANDSHAKE_VARIANTS = ("fragmented", "single", "raw", "unwrapped")


async def describe_connection(client: BleakClient) -> None:
    """Reports what the link looks like before anything is written."""
    log(f"  MTU: {client.mtu_size} bytes")
    chars = [c.uuid.lower() for s in client.services for c in s.characteristics]
    for name, uuid in (("RxData", backend.RX_DATA), ("TxData", backend.TX_DATA)):
        present = uuid.lower() in chars
        log(f"  {name} {uuid}: {'present' if present else 'MISSING'}")
        if not present:
            raise RuntimeError(f"{name} is not on this device")


NO_CONNECTION = "could not connect"
NO_REPLY = "connected, no reply to step 2"
WRONG_TAG = "connected, replied with the wrong tag"
MATCHED = "matched"


async def connect_with_retries(
    device: BLEDevice, attempts: int, timeout: float
) -> BleakClient:
    """Connects, retrying, since a distant lock often refuses the first try."""
    for attempt in range(1, attempts + 1):
        client = BleakClient(device, timeout=timeout)
        try:
            await client.__aenter__()
        except Exception as ex:  # noqa: BLE001 - retrying is the point
            log(f"    connect attempt {attempt}/{attempts}: {type(ex).__name__}: {ex}")
            continue
        log(f"    connected on attempt {attempt}")
        return client
    raise RuntimeError(f"could not connect in {attempts} attempts")


async def try_handshake(
    device: BLEDevice, sat: bytes, timeout: float, variant: str, attempts: int
) -> str:
    """Runs handshake steps 1 and 2 one way, and says what came back.

    Returns one of :data:`NO_CONNECTION`, :data:`NO_REPLY`,
    :data:`WRONG_TAG` or :data:`MATCHED`, because those mean entirely
    different things: only the last two say anything about the protocol, and
    the first says nothing at all.
    """
    log(f"  variant: {variant}")
    try:
        client = await connect_with_retries(device, attempts, timeout)
    except RuntimeError as ex:
        log(f"    {ex}")
        return NO_CONNECTION

    try:
        await describe_connection(client)
        channel = backend.GattChannel(client, timeout=timeout)
        await channel.start()
        try:
            packetizer = framing.Packetizer()
            client_random = secrets.token_bytes(crypto.RANDOM_LEN)
            body = session._CONNECTION_REQUEST_PREAMBLE + client_random
            request_packet = packetizer.connection_request(body)
            hexdump("step 1, writing", request_packet)
            await client.write_gatt_char(backend.TX_DATA, request_packet, response=True)
            response = await channel.read()
            hexdump("step 1, lock replied", response)
            flag, server_random = session.parse_connection_response(response)
            log(f"    flag={flag}  server_random={server_random.hex()}")

            record, sat_tag = crypto.extend_sat(sat, client_random, server_random)
            if variant == "unwrapped":
                record = cbor2.loads(record)
                log("    sending the macaroon without its outer byte string")
            log(f"    step 2 record is {len(record)} bytes")

            if variant in ("fragmented", "unwrapped"):
                packets = packetizer.split(record)
                log(f"    as {len(packets)} framed packets")
                for packet in packets:
                    await client.write_gatt_char(backend.TX_DATA, packet, response=True)
            elif variant == "single":
                packet = bytes([framing.SINGLE]) + record
                log(f"    as one framed write of {len(packet)} bytes")
                await client.write_gatt_char(backend.TX_DATA, packet, response=True)
            else:
                log(f"    as one unframed write of {len(record)} bytes")
                await client.write_gatt_char(backend.TX_DATA, record, response=True)

            expected = crypto.session_tag(sat_tag, 2, client_random, server_random)
            try:
                reply = await channel.read()
            except Exception as ex:  # noqa: BLE001 - any failure is a result
                log(f"    no usable reply: {type(ex).__name__}: {ex}")
                return NO_REPLY
            hexdump("step 2, lock replied", reply)
            if reply == expected:
                log("    the tag matches: this lock holds the SAT's secret")
                return MATCHED
            log("    answered, but not with the expected tag")
            return WRONG_TAG
        finally:
            # The lock drops the link when it rejects a session, and
            # unsubscribing then raises. Letting that through would replace
            # the finding with a complaint about service discovery.
            with suppress(Exception):
                await channel.stop()
    finally:
        with suppress(Exception):
            await client.__aexit__(None, None, None)


async def find_handshake_variant(
    report: Report,
    device: BLEDevice,
    sat: bytes,
    timeout: float,
    only: str | None,
    attempts: int,
) -> str | None:
    """Tries each way of writing step 2 until the lock answers.

    A variant that could not connect has said nothing about the protocol, so
    it is reported as such rather than as a failed framing.
    """
    variants = (only,) if only else HANDSHAKE_VARIANTS
    outcomes = {}
    for variant in variants:
        assert variant is not None
        name = f"handshake step 2 as {variant}"
        stage(name)
        try:
            outcome = await try_handshake(device, sat, timeout, variant, attempts)
        except Exception as ex:  # noqa: BLE001 - try the next variant anyway
            log(f"  {type(ex).__name__}: {ex}")
            outcome = f"{type(ex).__name__}: {ex}"
        outcomes[variant] = outcome
        if outcome == MATCHED:
            report.record(name, "ok", outcome)
            return variant
        report.record(name, "FAIL", outcome)

    if all(outcome == NO_CONNECTION for outcome in outcomes.values()):
        log()
        log("Nothing connected, so none of this says anything about the")
        log("protocol. A weak link or a lock that drops connections looks")
        log("the same as a lock refusing to talk. Move closer, or raise")
        log("--connect-attempts, and try again.")
    elif NO_CONNECTION in outcomes.values():
        log()
        log("Some variants never connected, so they were not tested at all:")
        for variant, outcome in outcomes.items():
            log(f"  {variant}: {outcome}")
        log("Only a variant that connected and got no reply is evidence")
        log("against that framing.")
    return None


async def run_session_stages(
    args: argparse.Namespace,
    report: Report,
    lock: Lock,
    device: BLEDevice,
    user_id: str,
    mint: Callable[[str], Awaitable[str]],
) -> None:
    """Opens a session and runs everything that needs one."""
    with attempt(report, "open a session") as detail:
        client = BleakClient(device)
        await client.__aenter__()
        channel = backend.GattChannel(client, timeout=args.timeout)
        await channel.start()
        sess = session.Session(channel, mint)
        await sess.open(lock._sat, lock._cat)
        detail.append("handshake verified, CAT authorized")
        log("  session open: the lock proved it holds the SAT's secret")

    try:
        ble = backend.BleBackend(sess, user_id)

        with attempt(report, "read identity and firmware") as detail:
            for label, trait, attribute in _IDENTITY_READS:
                value = await sess.read_trait(trait, attribute)
                log(f"  {label:18} = {value!r}")
            detail.append(f"{len(_IDENTITY_READS)} reads")

        with attempt(report, "read settings") as detail:
            for label, attribute in _SETTING_READS:
                value = await sess.read_trait(
                    uweave.TRAIT_LOCK_CONFIG, attribute, uweave.METHOD_ADD
                )
                log(f"  {label:18} = {value!r}")
            detail.append(f"{len(_SETTING_READS)} reads")

        with attempt(report, "read lock state") as detail:
            raw = await sess.read_lock_state()
            log(f"  report = {raw!r}")
            if isinstance(raw, dict):
                known = {
                    value
                    for name, value in vars(uweave).items()
                    if name.startswith("REPORT_")
                }
                unknown = sorted(set(raw) - known)
                if unknown:
                    log(
                        "  keys nothing has identified: "
                        + ", ".join(f"{k}={raw[k]!r}" for k in unknown)
                    )
            refreshed = await ble.get_state(lock)
            log(
                f"  merged: is_locked={refreshed.is_locked} "
                f"is_jammed={refreshed.is_jammed} "
                f"battery_level={refreshed.battery_level} "
                f"battery_low_state={refreshed.battery_low_state} "
                f"alarm_mode={refreshed.alarm_mode} "
                f"operating_mode={refreshed.operating_mode} "
                f"door_state={refreshed.door_state}"
            )

            # The radio and the cloud should agree about the bolt. If they do
            # not, one of the two readings is wrong, and the report above is
            # the evidence for which.
            if lock.is_locked is None:
                log("  the cloud has no lock state to compare against")
            elif lock.is_locked == refreshed.is_locked:
                log(f"  agrees with the cloud (is_locked={lock.is_locked})")
            else:
                log(
                    f"  DISAGREES with the cloud: cloud says "
                    f"is_locked={lock.is_locked}, the lock says "
                    f"{refreshed.is_locked}. Look at the bolt to see which is "
                    "right."
                )
                detail.append("disagrees with the cloud")
            detail.append(f"is_locked={refreshed.is_locked}")
            lock = refreshed

        if not args.allow_state_change:
            log()
            log("Skipping lock and unlock. Pass --allow-state-change to try")
            log("them; the bolt will move, and the original state is restored.")
            report.record("operate the bolt", "skip", "--allow-state-change off")
            return

        was_locked = lock.is_locked
        with attempt(report, "operate the bolt") as detail:
            target = not was_locked
            log(f"  lock reports is_locked={was_locked}; asking for {target}")
            moved = await ble.set_locked(lock, target)
            log(f"  the write's own reply says is_locked={moved.is_locked}")

            # Re-reading catches a write that was accepted but did not take,
            # or a bolt still moving. It cannot catch an inverted state
            # mapping: an implementation that writes and reads the same wrong
            # way round reads back exactly what it meant to. Only the bolt
            # settles that, which is why this says to go and look.
            confirmed = await ble.get_state(moved)
            log(f"  a fresh read says is_locked={confirmed.is_locked}")
            if confirmed.is_locked is not target:
                log(
                    "  NOTE: the lock did not settle on the state asked for. "
                    "It may still be moving."
                )
            log(
                f"  LOOK AT THE BOLT: it should now be {'locked' if target else 'unlocked'}."
            )
            detail.append(f"{was_locked} -> {confirmed.is_locked}")
            moved = confirmed

        if was_locked is not None:
            with attempt(report, "restore the original state") as detail:
                restored = await ble.set_locked(moved, was_locked)
                log(f"  back to is_locked={restored.is_locked}")
                detail.append(f"is_locked={restored.is_locked}")

        with attempt(report, "write a setting and put it back") as detail:
            # The beeper is the least consequential setting to change. The
            # read-back proves the write landed rather than was merely
            # accepted, and has the same blind spot as the bolt: a
            # consistently inverted int-boolean round-trips cleanly. Checking
            # the phone app agrees is the equivalent of looking at the bolt.
            before = await sess.read_trait(
                uweave.TRAIT_LOCK_CONFIG, uweave.BEEPER_ENABLED[0], uweave.METHOD_ADD
            )
            log(f"  beeper enabled is {before!r}")
            target_value = 0 if before else 1
            log(f"  writing {target_value}")
            await ble.set_setting(lock, Setting.BEEPER_ENABLED, target_value)
            after = await sess.read_trait(
                uweave.TRAIT_LOCK_CONFIG, uweave.BEEPER_ENABLED[0], uweave.METHOD_ADD
            )
            log(f"  reads back as {after!r}")
            if int(after) != target_value:
                raise RuntimeError(
                    f"wrote {target_value} but the lock reports {after!r}"
                )
            log(f"  putting it back to {before!r}")
            await ble.set_setting(lock, Setting.BEEPER_ENABLED, int(before))
            final = await sess.read_trait(
                uweave.TRAIT_LOCK_CONFIG, uweave.BEEPER_ENABLED[0], uweave.METHOD_ADD
            )
            log(f"  restored to {final!r}")
            detail.append(f"{before!r} -> {after!r} -> {final!r}")
    finally:
        await channel.stop()
        await client.__aexit__(None, None, None)


# -- Driver -----------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--user", help="Schlage account email.")
    parser.add_argument(
        "--credentials",
        default=DEFAULT_CREDENTIALS,
        help=(
            "File holding username= and password= lines "
            f"(default: {DEFAULT_CREDENTIALS})."
        ),
    )
    parser.add_argument("--list", action="store_true", help="List locks and exit.")
    parser.add_argument("--device-id", help="Which lock to probe.")
    parser.add_argument(
        "--address",
        help="Skip the scan and connect to this address or Core Bluetooth id.",
    )
    parser.add_argument(
        "--scan-timeout", type=float, default=15.0, help="Seconds to scan."
    )
    parser.add_argument(
        "--scan-only",
        action="store_true",
        help="Dump every device in range and stop, without connecting.",
    )
    parser.add_argument(
        "--handshake-variant",
        choices=HANDSHAKE_VARIANTS,
        help="Try only this way of writing handshake step 2.",
    )
    parser.add_argument(
        "--connect-attempts",
        type=int,
        default=4,
        help="How many times to try connecting before giving up on a variant.",
    )
    parser.add_argument(
        "--timeout", type=float, default=30.0, help="Seconds to wait per record."
    )
    parser.add_argument(
        "--allow-state-change",
        action="store_true",
        help="Lock and unlock the lock, then restore the state found.",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    report = Report()

    log(f"pyschlage BLE probe, {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"platform: {sys.platform}")

    # Explicit beats the environment, which beats the file, which beats asking.
    stored = read_credentials(args.credentials)
    if stored:
        log(f"  read credentials from {Path(args.credentials).expanduser()}")
    user = args.user or os.environ.get("SCHLAGE_USER") or stored.get("username")
    password = os.environ.get("SCHLAGE_PASSWORD") or stored.get("password")
    if not user:
        user = input("Schlage account email: ").strip()
    if not password:
        password = getpass.getpass("Schlage password: ")

    async with cloud(user, password) as (schlage, transport):
        with attempt(report, "authenticate and list locks") as detail:
            locks = await schlage.get_locks()
            for candidate in locks:
                log(f"  {describe_lock(candidate)}")
            detail.append(f"{len(locks)} locks")

        if args.list:
            report.summarize()
            return 0

        with attempt(report, "pick a lock and check its tokens") as detail:
            if args.device_id:
                chosen = [lk for lk in locks if lk.device_id == args.device_id]
                if not chosen:
                    raise RuntimeError(f"no lock with id {args.device_id}")
                lock = chosen[0]
            elif len(locks) == 1:
                lock = locks[0]
            else:
                raise RuntimeError(
                    "more than one lock; choose with --device-id (see --list)"
                )
            log(f"  {describe_lock(lock)}")
            if not lock._sat:
                raise RuntimeError(
                    "this lock reports no SAT, so no session can be opened"
                )
            if not lock._cat:
                raise RuntimeError("this lock reports no CAT")
            try:
                sat_bytes = crypto.decode_token(lock._sat)
                cat_bytes = crypto.decode_token(lock._cat)
            except ValueError as ex:
                raise RuntimeError(
                    f"a token is not hex, so the encoding is wrong: {ex}"
                ) from ex
            log(f"  SAT decodes to {len(sat_bytes)} bytes, CAT to {len(cat_bytes)}")
            detail.append(f"sat={len(sat_bytes)}B cat={len(cat_bytes)}B")

        with attempt(report, "parse the SAT macaroon") as detail:
            macaroon = crypto.Macaroon.decode(sat_bytes)
            log(f"  caveats: {macaroon.caveats}")
            log(f"  tag: {macaroon.tag.hex()} ({len(macaroon.tag)} bytes)")

            # The decisive check, and the one that needs no radio: the SAT is
            # one CBOR byte string whose contents are the macaroon, so
            # re-encoding an untouched macaroon has to reproduce those bytes
            # exactly. If it does not, the encoding is wrong and the handshake
            # cannot work.
            inner = cbor2.loads(sat_bytes)
            reencoded = macaroon.encode()
            matches = reencoded == inner
            log(f"  re-encodes to the service's own bytes: {matches}")
            if not matches:
                hexdump("service sent", inner if isinstance(inner, bytes) else b"")
                hexdump("we re-encoded", reencoded)
                raise RuntimeError(
                    "the macaroon does not re-encode to what the service sent, "
                    "so the encoding is wrong"
                )
            detail.append(
                f"{len(macaroon.caveats)} caveats, {len(macaroon.tag)}B tag, "
                "re-encodes exactly"
            )

        if args.scan_only:
            with attempt(report, "scan for anything in range") as detail:
                pairs = await scan(args.scan_timeout)
                matched = next(
                    (d for d, a in pairs if backend.matches(lock, d, a)), None
                )
                detail.append(f"{len(pairs)} devices")
                if matched is not None:
                    detail.append(f"matched {matched.address}")
            report.summarize()
            return 0

        with attempt(report, "find the lock over Bluetooth") as detail:
            device = await find_device(lock, args.scan_timeout, args.address)
            log(f"  using {device.address} {device.name!r}")
            detail.append(str(device.address))

        variant = await find_handshake_variant(
            report,
            device,
            sat_bytes,
            args.timeout,
            args.handshake_variant,
            args.connect_attempts,
        )
        if variant is None:
            log()
            log("No way of writing step 2 got an answer. The hexdumps above")
            log("are what went out and what came back, if anything.")
            report.summarize()
            return 1
        if variant != "fragmented":
            log()
            log(f"NOTE: {variant!r} answered and the library writes")
            log("'fragmented'. pyschlage.ble has to change to match before")
            log("the session stages can run.")
            report.summarize()
            return 1

        await run_session_stages(
            args,
            report,
            lock,
            device,
            schlage.user_id,
            cat_minter(transport, lock.device_id),
        )

    report.summarize()
    return 1 if report.failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
