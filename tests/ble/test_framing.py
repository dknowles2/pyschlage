"""Tests for uWeave's GATT packet framing."""

import pytest

from pyschlage.ble import framing


class TestPacketizer:
    def test_single_packet_record(self) -> None:
        packets = framing.Packetizer().split(b"hello")
        assert packets == [bytes([0x0C]) + b"hello"]

    def test_record_that_exactly_fills_one_packet(self) -> None:
        record = bytes(range(framing.PAYLOAD_SIZE))
        packets = framing.Packetizer().split(record)
        assert len(packets) == 1
        assert len(packets[0]) == framing.PACKET_SIZE

    def test_empty_record(self) -> None:
        assert framing.Packetizer().split(b"") == [bytes([0x0C])]

    def test_two_packet_record(self) -> None:
        record = bytes(framing.PAYLOAD_SIZE + 1)
        packets = framing.Packetizer().split(record)
        assert [p[0] for p in packets] == [0x08, 0x14]
        assert packets[0][1:] == record[: framing.PAYLOAD_SIZE]
        assert packets[1][1:] == record[framing.PAYLOAD_SIZE :]

    def test_three_packet_record_has_a_middle(self) -> None:
        record = bytes(framing.PAYLOAD_SIZE * 2 + 1)
        packets = framing.Packetizer().split(record)
        assert [p[0] & 0x0F for p in packets] == [
            framing.FIRST,
            framing.MIDDLE,
            framing.LAST,
        ]

    def test_counter_increments_per_packet(self) -> None:
        packetizer = framing.Packetizer()
        headers = [packetizer.split(b"x")[0][0] for _ in range(3)]
        assert headers == [0x0C, 0x1C, 0x2C]

    def test_counter_wraps_at_eight(self) -> None:
        packetizer = framing.Packetizer()
        headers = [packetizer.split(b"x")[0][0] >> 4 for _ in range(9)]
        assert headers == [0, 1, 2, 3, 4, 5, 6, 7, 0]

    def test_connection_request_sets_the_high_bit(self) -> None:
        packet = framing.Packetizer().connection_request(b"body")
        assert packet == bytes([0x80]) + b"body"

    def test_connection_request_is_not_fragmented(self) -> None:
        body = bytes(framing.PACKET_SIZE * 3)
        packet = framing.Packetizer().connection_request(body)
        assert packet[1:] == body

    def test_connection_request_shares_the_counter(self) -> None:
        packetizer = framing.Packetizer()
        packetizer.split(b"x")
        assert packetizer.connection_request(b"")[0] == 0x90


class TestReassembler:
    def test_single_packet(self) -> None:
        assert framing.Reassembler().feed(bytes([0x0C]) + b"hello") == b"hello"

    def test_lock_initiated_connection_request_completes_a_record(self) -> None:
        packet = bytes([0x81]) + b"body"
        assert framing.Reassembler().feed(packet) == b"body"

    def test_multi_packet(self) -> None:
        reassembler = framing.Reassembler()
        assert reassembler.feed(bytes([0x08]) + b"one") is None
        assert reassembler.feed(bytes([0x10]) + b"two") is None
        assert reassembler.feed(bytes([0x24]) + b"three") == b"onetwothree"

    def test_a_new_record_starts_fresh(self) -> None:
        reassembler = framing.Reassembler()
        reassembler.feed(bytes([0x08]) + b"abandoned")
        assert reassembler.feed(bytes([0x08]) + b"one") is None
        assert reassembler.feed(bytes([0x04]) + b"two") == b"onetwo"

    def test_a_single_packet_discards_a_partial_record(self) -> None:
        reassembler = framing.Reassembler()
        reassembler.feed(bytes([0x08]) + b"partial")
        assert reassembler.feed(bytes([0x0C]) + b"whole") == b"whole"
        assert reassembler.feed(bytes([0x04]) + b"tail") == b"tail"

    def test_rejects_an_empty_packet(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            framing.Reassembler().feed(b"")

    def test_rejects_an_unknown_role(self) -> None:
        with pytest.raises(ValueError, match="unknown packet role"):
            framing.Reassembler().feed(bytes([0x02]) + b"x")

    @pytest.mark.parametrize("size", [0, 1, 19, 20, 38, 39, 100, 1024])
    def test_round_trip(self, size: int) -> None:
        record = bytes(range(256)) * (size // 256) + bytes(range(size % 256))
        record = record[:size]
        reassembler = framing.Reassembler()
        got = None
        for packet in framing.Packetizer().split(record):
            assert len(packet) <= framing.PACKET_SIZE
            got = reassembler.feed(packet)
        assert got == record
