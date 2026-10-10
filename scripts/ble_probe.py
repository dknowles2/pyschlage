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
from pyschlage.aio import AiohttpTransport, Schlage, Transport
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


async def find_device(lock: Lock, timeout: float, address: str | None) -> BLEDevice:
    """Scans for the lock, or for anything advertising uWeave."""
    if address:
        log(f"  looking for {address} directly")
        device = await BleakScanner.find_device_by_address(address, timeout=timeout)
        if device is None:
            raise RuntimeError(f"no device at {address} within {timeout}s")
        return device

    log(f"  scanning {timeout}s for the uWeave service {backend.UWEAVE_SERVICE}")
    found = await backend.discover(timeout=timeout)
    for device in found:
        log(f"    {device.address}  {device.name!r}")
    if not found:
        raise RuntimeError(
            "nothing advertised the uWeave service. The lock may be asleep -- "
            "press a key on the keypad and try again -- or it may not "
            "advertise until woken."
        )

    wanted = (lock.mac_address or "").lower()
    for device in found:
        if device.address.lower() == wanted:
            log(f"  matched {device.address} against the lock's MAC")
            return device

    if len(found) == 1:
        log(
            "  one candidate, and it does not match the lock's MAC. On macOS "
            "that is expected: Core Bluetooth reports its own identifiers "
            "rather than MAC addresses. Using it."
        )
        return found[0]

    raise RuntimeError(
        f"{len(found)} devices advertise uWeave and none matches "
        f"{lock.mac_address}. Re-run with --address <one listed above>."
    )


async def probe_connection_request(device: BLEDevice, timeout: float) -> None:
    """Does step 1 of the handshake alone, in its own connection.

    This is the stage most likely to be wrong, and the one whose failure says
    least on its own, so it runs isolated and dumps both directions.
    """
    async with BleakClient(device) as client:
        services = [s.uuid.lower() for s in client.services]
        log(f"  services: {services}")
        chars = [c.uuid.lower() for s in client.services for c in s.characteristics]
        for name, uuid in (("RxData", backend.RX_DATA), ("TxData", backend.TX_DATA)):
            present = uuid.lower() in chars
            log(f"  {name} {uuid}: {'present' if present else 'MISSING'}")
            if not present:
                raise RuntimeError(f"{name} is not on this device")

        channel = backend.GattChannel(client, timeout=timeout)
        await channel.start()
        try:
            client_random = b"\x00" * crypto.RANDOM_LEN
            body = session._CONNECTION_REQUEST_PREAMBLE + client_random
            packet = framing.Packetizer().connection_request(body)
            hexdump("writing connection request", packet)
            log(
                "    header "
                f"{packet[0]:#04x} = ((counter + 8) << 4) | 0, then "
                f"{len(session._CONNECTION_REQUEST_PREAMBLE)} CBOR bytes and "
                f"{crypto.RANDOM_LEN} random bytes"
            )
            await channel.write_connection_request(body)
            response = await channel.read()
            hexdump("lock replied", response)
            flag, server_random = session.parse_connection_response(response)
            log(f"    fresh-CAT flag (byte 4) = {flag}")
            log(
                f"    server_random = {server_random.hex()} ({len(server_random)} bytes)"
            )
            if len(server_random) != crypto.RANDOM_LEN:
                log(
                    f"    NOTE: expected {crypto.RANDOM_LEN} random bytes, got "
                    f"{len(server_random)}. The 5-byte header assumption may "
                    "be wrong."
                )
        finally:
            await channel.stop()


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
            refreshed = await ble.get_state(lock)
            log(
                f"  merged: is_locked={refreshed.is_locked} "
                f"is_jammed={refreshed.is_jammed} "
                f"battery_level={refreshed.battery_level}"
            )
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
            log(f"  reply merged: is_locked={moved.is_locked}")
            if moved.is_locked is not target:
                log(
                    "  NOTE: the lock did not report the state asked for. It "
                    "may still be moving; the report is what it sent."
                )
            detail.append(f"{was_locked} -> {moved.is_locked}")

        if was_locked is not None:
            with attempt(report, "restore the original state") as detail:
                restored = await ble.set_locked(moved, was_locked)
                log(f"  back to is_locked={restored.is_locked}")
                detail.append(f"is_locked={restored.is_locked}")
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

        with attempt(report, "find the lock over Bluetooth") as detail:
            device = await find_device(lock, args.scan_timeout, args.address)
            log(f"  using {device.address} {device.name!r}")
            detail.append(str(device.address))

        with attempt(report, "connection request (handshake step 1)") as detail:
            await probe_connection_request(device, args.timeout)
            detail.append("lock replied with its nonce")

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
