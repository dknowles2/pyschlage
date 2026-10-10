"""Packet framing for uWeave's GATT transport.

Records are split across 20-byte GATT writes: a one-byte header plus up to 19
bytes of payload. The header's high nibble is a three-bit sequence counter
that increments per packet and wraps at 8; the low nibble says which part of a
record the packet carries.

The 19 bytes are the protocol's, not the link's. The app hardcodes them and
never consults the negotiated MTU -- although it does read a dynamic-MTU bit
out of the advertisement, so it knows when a lock could carry more and frames
at 19 regardless. A BE489WB negotiating a 247-byte MTU still wanted a 37-byte
record split in two.
"""

from __future__ import annotations

PACKET_SIZE = 20
"""Size of a GATT packet, header included."""

PAYLOAD_SIZE = PACKET_SIZE - 1
"""Bytes of a record that a single packet can carry."""

SINGLE = 0xC
"""Low nibble of a packet holding a whole record."""

FIRST = 0x8
"""Low nibble of the first packet of a multi-packet record."""

MIDDLE = 0x0
"""Low nibble of a packet in the middle of a record."""

LAST = 0x4
"""Low nibble of the last packet of a multi-packet record."""

CONNECTION_REQUEST = 0x1
"""Low nibble of a lock-initiated connection request."""

_COUNTER_WRAP = 8


class Packetizer:
    """Splits records into GATT packets, tracking the sequence counter."""

    def __init__(self) -> None:
        self._counter = 0

    def _header(self, role: int) -> int:
        header = (self._counter << 4) | role
        self._counter = (self._counter + 1) % _COUNTER_WRAP
        return header

    def split(self, record: bytes) -> list[bytes]:
        """Splits a record into packets, in the order they should be written.

        :param record: The record to split.
        :type record: bytes
        :rtype: list[bytes]
        """
        chunks = [
            record[i : i + PAYLOAD_SIZE] for i in range(0, len(record), PAYLOAD_SIZE)
        ] or [b""]
        if len(chunks) == 1:
            return [bytes([self._header(SINGLE)]) + chunks[0]]

        packets = []
        last = len(chunks) - 1
        for i, chunk in enumerate(chunks):
            role = FIRST if i == 0 else LAST if i == last else MIDDLE
            packets.append(bytes([self._header(role)]) + chunk)
        return packets

    def connection_request(self, body: bytes) -> bytes:
        """Frames an app-initiated connection request.

        This one is special: it sets the high bit of the counter nibble, uses a
        low nibble of zero rather than the :data:`CONNECTION_REQUEST` the lock
        uses in the other direction, and is written unfragmented however long
        it is.

        :param body: The raw connection request body.
        :type body: bytes
        :rtype: bytes
        """
        header = ((self._counter + _COUNTER_WRAP) << 4) | MIDDLE
        self._counter = (self._counter + 1) % _COUNTER_WRAP
        return bytes([header]) + body


class Reassembler:
    """Reassembles records from the packets a lock sends."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, packet: bytes) -> bytes | None:
        """Adds a received packet.

        :param packet: The packet, header included.
        :type packet: bytes
        :return: The completed record, or None if more packets are needed.
        :rtype: bytes or None
        :raise ValueError: When the packet is empty or its role is unknown.
        """
        if not packet:
            raise ValueError("packet is empty")

        role = packet[0] & 0x0F
        payload = packet[1:]
        match role:
            case _ if role in (SINGLE, CONNECTION_REQUEST):
                self._buffer.clear()
                return bytes(payload)
            case _ if role == FIRST:
                self._buffer = bytearray(payload)
                return None
            case _ if role == MIDDLE:
                self._buffer += payload
                return None
            case _ if role == LAST:
                self._buffer += payload
                record = bytes(self._buffer)
                self._buffer.clear()
                return record
        raise ValueError(f"unknown packet role: {role:#x}")
