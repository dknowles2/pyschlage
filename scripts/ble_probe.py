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
from contextlib import asynccontextmanager, contextmanager
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
        else:
            print("Every stage passed. That is the protocol working against")
            print("real hardware for the first time.")


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
    pairs = sorted(found.values(), key=lambda pair: pair[1].rssi, reverse=True)
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

# The manufacturer data, once the company id is stripped: a version byte, two
# bytes of device platform, four the app does not name, then the MAC.
_ADVERTISEMENT_VERSION = 0
_ADVERTISEMENT_PLATFORM = slice(1, 3)
_ADVERTISEMENT_MAC = slice(7, 13)

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


def advertised_platform(adv: Any) -> str | None:
    """Returns the device platform a lock advertises, named if it is known."""
    payload = allegion_payload(adv)
    if payload is None:
        return None
    platform = payload[_ADVERTISEMENT_PLATFORM]
    version = payload[_ADVERTISEMENT_VERSION]
    name = LOCK_PLATFORMS.get(platform, "unknown")
    return f"{name} ({platform.hex()}, advertisement v{version})"


def match_device(lock: Lock, pairs: list[tuple[BLEDevice, Any]]) -> BLEDevice | None:
    """Picks the lock out of a scan, by its MAC and nothing softer.

    Matching on a name would be easy and is how this picked the wrong lock
    once: two locks both advertise as SCHLAGE..., and the one it chose
    answered handshake step 1 happily before going silent at step 2, because
    the SAT it was sent had been issued for the other one. A wrong match looks
    exactly like a protocol bug, so there is no name fallback here.
    """
    wanted = _normalize_address(lock.mac_address or "")
    if not wanted:
        log("  the cloud reports no MAC for this lock, so it cannot be matched")
        return None

    for device, _ in pairs:
        if _normalize_address(device.address) == wanted:
            log(f"  matched {device.address} on the address the platform reports")
            return device

    for device, adv in pairs:
        mac = advertised_mac(adv)
        if mac is not None and _normalize_address(mac.hex()) == wanted:
            log(
                f"  matched {device.address} on the MAC in its manufacturer "
                f"data, advertising as {advertised_platform(adv)}"
            )
            return device
    return None


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
        platform = advertised_platform(adv) or "no Allegion payload"
        log(f"    {device.address}  {adv.local_name!r}")
        log(f"      mac={shown}  platform={platform}")


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

    device = match_device(lock, pairs)
    if device is not None:
        return device

    describe_candidates(pairs)
    raise RuntimeError(
        f"{len(pairs)} devices are in range and none advertises "
        f"{lock.mac_address}, the MAC the cloud reports for {lock.name!r}. "
        "Guessing is worse than stopping: a lock that is not this one will "
        "answer the handshake's first step and then go silent, which looks "
        "like a protocol bug. If a candidate above is the right lock, re-run "
        "with --address <address>; otherwise it is not advertising, so press "
        "a keypad key and re-run."
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


async def try_handshake(
    device: BLEDevice, sat: bytes, timeout: float, variant: str
) -> bool:
    """Runs handshake steps 1 and 2 one way, and says whether step 2 answered.

    Step 2 is the first multi-packet record the protocol ever sends, and the
    lock answers step 1 but not step 2, so how a long record should be written
    is the open question. Each variant is a different answer to it, tried in a
    connection of its own.
    """
    log(f"  variant: {variant}")
    async with BleakClient(device) as client:
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
                # Maybe the outer byte string is a cloud artifact and the lock
                # wants the two macaroon items on their own.
                record = cbor2.loads(record)
                log("    sending the macaroon without its outer byte string")
            hexdump("step 2, record", record)

            if variant in ("fragmented", "unwrapped"):
                packets = packetizer.split(record)
                log(f"    as {len(packets)} framed packets")
                for packet in packets:
                    hexdump("      writing", packet)
                    await client.write_gatt_char(backend.TX_DATA, packet, response=True)
            elif variant == "single":
                # One write, header and all, the way the connection request
                # goes out.
                packet = bytes([framing.SINGLE]) + record
                hexdump("    one framed write", packet)
                await client.write_gatt_char(backend.TX_DATA, packet, response=True)
            else:
                hexdump("    one unframed write", record)
                await client.write_gatt_char(backend.TX_DATA, record, response=True)

            expected = crypto.session_tag(sat_tag, 2, client_random, server_random)
            log(f"    expecting the reply to be {expected.hex()}")
            try:
                reply = await channel.read()
            except Exception as ex:  # noqa: BLE001 - any failure is a result
                log(f"    no usable reply: {type(ex).__name__}: {ex}")
                return False
            hexdump("step 2, lock replied", reply)
            if reply == expected:
                log("    MATCHES -- this variant is the right one")
                return True
            log(
                "    the lock answered but not with the tag expected. The "
                "framing works; the tag or the macaroon does not."
            )
            return False
        finally:
            await channel.stop()


async def find_handshake_variant(
    report: Report, device: BLEDevice, sat: bytes, timeout: float, only: str | None
) -> str | None:
    """Tries each way of writing step 2 until the lock answers."""
    variants = (only,) if only else HANDSHAKE_VARIANTS
    for variant in variants:
        assert variant is not None
        name = f"handshake step 2 as {variant}"
        stage(name)
        try:
            if await try_handshake(device, sat, timeout, variant):
                report.record(name, "ok", "lock answered with the tag")
                return variant
            report.record(name, "FAIL", "no matching reply")
        except Exception as ex:  # noqa: BLE001 - try the next variant anyway
            log(f"  {type(ex).__name__}: {ex}")
            report.record(name, "FAIL", f"{type(ex).__name__}: {ex}")
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

            # The write's reply is the lock describing itself, so a read that
            # agrees is worth more than the reply alone: both would look right
            # even if the state mapping were inverted end to end.
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
            # The beeper is the least consequential setting to change, and a
            # read-back proves the write landed rather than was accepted.
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
                matched = match_device(lock, pairs) if pairs else None
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
            report, device, sat_bytes, args.timeout, args.handshake_variant
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
