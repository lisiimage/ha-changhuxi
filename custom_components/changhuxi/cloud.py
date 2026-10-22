"""Xlink v5 cloud MQTT transport recovered from Changhuxi v1.3.3 APK.

One connection per operation; commands never retry. No Android dependency.
"""

import secrets
import socket
import struct
import time


def string(value):
    data = value.encode()
    return struct.pack("!H", len(data)) + data


def tlv(kind, payload):
    return struct.pack("!HH", kind, len(payload)) + payload


def data_points(data):
    result = {}
    while data:
        if len(data) < 3:
            raise ValueError("truncated datapoint header")
        index, descriptor = struct.unpack("!BH", data[:3])
        length = descriptor & 4095
        if len(data) < 3 + length:
            raise ValueError("truncated datapoint value")
        if descriptor >> 12 != 10 or length != 4:
            raise ValueError("unexpected purifier datapoint type")
        result[index] = int.from_bytes(data[3 : 3 + length], "big", signed=True)
        data = data[3 + length :]
    return result


class ProtocolError(Exception):
    """Malformed or rejected Xlink message."""


class CloudAuthenticationError(ProtocolError):
    """Cloud identity is no longer valid."""


class Client:
    def __init__(self, config):
        self.config = config
        self.socket = None
        self.mid = secrets.randbelow(65000) + 1
        self.points = {}

    def send(self, header, data):
        size = len(data)
        remaining = bytearray()
        while True:
            digit = size % 128
            size //= 128
            remaining.append(digit | (128 if size else 0))
            if not size:
                break
        self.socket.sendall(bytes([header]) + remaining + data)

    def read(self, size):
        data = b""
        while len(data) < size:
            chunk = self.socket.recv(size - len(data))
            if not chunk:
                raise ConnectionError("MQTT connection closed")
            data += chunk
        return data

    def receive(self):
        header = self.read(1)[0]
        size = 0
        for shift in range(0, 28, 7):
            digit = self.read(1)[0]
            size |= (digit & 127) << shift
            if not digit & 128:
                break
        else:
            raise ValueError("invalid MQTT remaining length")
        if size > 1048576:
            raise ValueError("oversized MQTT frame")
        data = self.read(size)
        if header >> 4 == 3:
            if len(data) < 2:
                raise ValueError("truncated MQTT topic length")
            topic_length = int.from_bytes(data[:2], "big")
            if not topic_length or len(data) < 2 + topic_length:
                raise ValueError("truncated MQTT topic")
            topic = data[2 : 2 + topic_length].decode()
            offset = 2 + topic_length
            qos = (header >> 1) & 3
            if qos == 1:
                if len(data) < offset + 2:
                    raise ValueError("missing MQTT message identifier")
                self.send(0x40, data[offset : offset + 2])
                offset += 2
            elif qos:
                raise ValueError("unsupported MQTT QoS")
            return header, (topic, data[offset:])
        return header, data

    def __enter__(self):
        try:
            return self.connect()
        except Exception:
            if self.socket:
                self.socket.close()
            raise

    def connect(self):
        c = self.config
        self.socket = socket.create_connection((c["host"], c["port"]), timeout=10)
        self.socket.settimeout(10)
        self.send(
            0x10,
            string("MQTT")
            + b"\x04\xc2\x00\x3c"
            + string("X:APP;A:4;V:2;" + ("RES:" + c["resource"] + ";" if c.get("resource") else ""))
            + string(str(c["user_id"]))
            + string(c["password"]),
        )
        header, data = self.receive()
        if header != 0x20 or len(data) != 2:
            raise ConnectionError("Invalid MQTT connection acknowledgement")
        if data[1] in (4, 5):
            raise CloudAuthenticationError("MQTT authentication failed")
        if data != b"\x00\x00":
            raise ConnectionError("MQTT connection refused")
        device = c["device_id"]
        topics = [f"${kind}/{device}" for kind in ("6", "8", "a", "x", "y")]
        self.send(0x82, struct.pack("!H", self.mid) + b"".join(string(t) + b"\x01" for t in topics))
        while True:
            header, data = self.receive()
            if header == 0x90:
                if (
                    len(data) != 2 + len(topics)
                    or data[:2] != struct.pack("!H", self.mid)
                    or any(v not in (0, 1) for v in data[2:])
                ):
                    raise ConnectionError("MQTT subscription refused")
                break
        return self

    def __exit__(self, *args):
        if self.socket:
            try:
                self.send(0xE0, b"")
            except OSError:
                pass
            self.socket.close()

    def request(self, kind, payload, expected):
        self.mid = self.mid % 65535 + 1
        request_id = self.mid
        packet = tlv(kind, struct.pack("!H", request_id) + payload)
        self.send(
            0x32,
            string(f"${kind:x}/{self.config['device_id']}")
            + struct.pack("!H", request_id)
            + packet,
        )
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            header, message = self.receive()
            if header >> 4 != 3:
                continue
            topic, data = message
            if len(data) < 4:
                continue
            packet_type, size = struct.unpack("!HH", data[:4])
            if size != len(data) - 4:
                raise ValueError("invalid Xlink TLV length")
            body = data[4:]
            if (
                packet_type == expected
                and topic == f"${expected:x}/{self.config['device_id']}"
                and len(body) >= 3
                and int.from_bytes(body[:2], "big") == request_id
            ):
                if body[2]:
                    raise ConnectionError(f"Xlink device rejected request: {body[2]}")
                return body[3:]
        raise TimeoutError("Xlink response timed out")

    def get(self):
        body = self.request(9, b"\x80", 10)
        if not body:
            raise ValueError("missing datapoint flags")
        flag, body = body[0], body[1:]
        if flag & 128:
            if len(body) < 2:
                raise ValueError("missing Xlink device name length")
            length = int.from_bytes(body[:2], "big")
            if len(body) < 2 + length:
                raise ValueError("truncated Xlink device name")
            body = body[2 + length :]
        if not flag & 64:
            raise ValueError("response contains no datapoints")
        self.points = data_points(body)
        if self.points.get(31) not in (0, 1, 2):
            raise ValueError("response contains no valid purifier power state")
        return self.points

    def set(self, points):
        payload = b"".join(
            struct.pack("!BHI", index, 0xA004, value) for index, value in points.items()
        )
        self.request(7, b"\x60" + payload, 8)
