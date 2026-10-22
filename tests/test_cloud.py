import struct
from unittest.mock import Mock

import pytest

from custom_components.changhuxi.cloud import Client, data_points


def test_typed_data_points():
    assert data_points(bytes.fromhex("1fa0040000000120a00400000003")) == {31: 1, 32: 3}


@pytest.mark.parametrize(
    "data", [b"\x01", bytes.fromhex("1fa0040000"), bytes.fromhex("1f300400000001")]
)
def test_truncated_or_wrong_type_rejected(data):
    with pytest.raises(ValueError):
        data_points(data)


def test_command_has_one_publish_and_no_blind_retry():
    c = Client({"device_id": 123})
    c.mid = 10
    c.send = Mock()
    c.receive = Mock(return_value=(0x40, b"\x00\x0b"))
    # First recv fails after PUBACK; the caller must not publish the command again.
    c.receive.side_effect = [(0x40, b"\x00\x0b"), TimeoutError()]
    with pytest.raises(TimeoutError):
        c.set({31: 1})
    assert c.send.call_count == 1
    header, payload = c.send.call_args.args
    assert header == 0x32
    assert b"$7/123" in payload
    assert payload.endswith(bytes.fromhex("0007000a000b601fa00400000001"))


def test_response_matches_message_id():
    c = Client({"device_id": 123})
    c.mid = 10
    c.send = Mock()

    def packet(mid):
        return struct.pack("!HHHB", 8, 3, mid, 0)

    c.receive = Mock(side_effect=[(0x30, ("$8/123", packet(99))), (0x30, ("$8/123", packet(11)))])
    c.set({31: 1})
    assert c.receive.call_count == 2


def test_rejected_command_is_not_success():
    c = Client({"device_id": 123})
    c.mid = 10
    c.send = Mock()
    c.receive = Mock(return_value=(0x30, ("$8/123", struct.pack("!HHHB", 8, 3, 11, 2))))
    with pytest.raises(ConnectionError):
        c.set({31: 1})
