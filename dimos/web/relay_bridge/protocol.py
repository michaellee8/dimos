# Copyright 2026 Dimensional Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Wire-protocol mirror of web/shared/protocol.ts.

Pinned by the golden vectors in web/shared/fixtures/ (tested from both pytest
and deno test). Stdlib-only on purpose: importable without aioquic.

Framing (see web/README.md for the upstream-bug rationale):
- Control stream frame: u32-LE length | UTF-8 JSON.
- Datagram: raw UTF-8 JSON, no length prefix.
- Data frame (one message per stream): u32-LE headerLen | u32-LE payloadLen |
  header JSON | payload. Receivers count bytes and must never treat stream
  EOF as a message boundary (Deno 2.6.x delays FIN by up to ~1 s).
"""

from __future__ import annotations

from dataclasses import dataclass, fields
import json
import struct
from typing import Any, ClassVar, Literal, Union

PROTOCOL_VERSION = 1

# Reject absurd header lengths before allocating (mirrors protocol.ts).
MAX_HEADER_LEN = 65536

Role = Literal["robot", "viewer"]
Delivery = Literal["latest", "reliable"]


class ProtocolError(ValueError):
    pass


@dataclass
class Hello:
    t: ClassVar[str] = "hello"
    v: int
    role: Role


@dataclass
class Welcome:
    t: ClassVar[str] = "welcome"
    v: int


@dataclass
class Ping:
    t: ClassVar[str] = "ping"
    n: int
    ts: float


@dataclass
class Pong:
    t: ClassVar[str] = "pong"
    n: int
    ts: float


@dataclass
class Error:
    t: ClassVar[str] = "error"
    code: str
    message: str


# Teleop datagrams (carried from T6 on; declared so the wire format is pinned
# by fixtures from day one).
@dataclass
class Twist:
    t: ClassVar[str] = "twist"
    vx: float
    wz: float
    seq: int
    ts: float


@dataclass
class Stop:
    t: ClassVar[str] = "stop"
    seq: int
    ts: float


Msg = Union[Hello, Welcome, Ping, Pong, Error, Twist, Stop]

_MSG_TYPES: dict[str, type[Any]] = {
    cls.t: cls for cls in (Hello, Welcome, Ping, Pong, Error, Twist, Stop)
}


@dataclass
class FrameHeader:
    """Data-plane frame header.

    `delivery` tells the relay how to forward without a manifest (T1 only; the
    T2+ manifest replaces it). `meta` carries encoding-specific extras.
    """

    ch: str
    seq: int
    ts: float
    delivery: Delivery
    meta: dict[str, Any] | None = None


@dataclass
class DataFrame:
    header: FrameHeader
    payload: bytes


def _dump_json(obj: dict[str, Any]) -> bytes:
    # Canonical form shared with JSON.stringify: compact separators, raw UTF-8.
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode()


def _msg_to_dict(msg: Msg) -> dict[str, Any]:
    out: dict[str, Any] = {"t": type(msg).t}
    for f in fields(msg):
        out[f.name] = getattr(msg, f.name)
    return out


def msg_from_dict(data: dict[str, Any]) -> Msg:
    t = data.get("t")
    cls = _MSG_TYPES.get(t) if isinstance(t, str) else None
    if cls is None:
        raise ProtocolError(f"unknown message type: {t!r}")
    try:
        msg: Msg = cls(**{f.name: data[f.name] for f in fields(cls) if f.name in data})
    except TypeError as e:
        raise ProtocolError(f"invalid {t} message: {e}") from e
    return msg


# ---------- control stream framing: u32-LE length | JSON ----------


def encode_control_frame(msg: Msg) -> bytes:
    body = _dump_json(_msg_to_dict(msg))
    return struct.pack("<I", len(body)) + body


class ControlFrameReader:
    """Incremental parser for a control stream (frames may split across chunks)."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def push(self, chunk: bytes) -> list[Msg]:
        self._buf += chunk
        msgs: list[Msg] = []
        while len(self._buf) >= 4:
            (length,) = struct.unpack_from("<I", self._buf, 0)
            if length > MAX_HEADER_LEN:
                raise ProtocolError(f"control frame too large: {length}")
            if len(self._buf) < 4 + length:
                break
            body = json.loads(self._buf[4 : 4 + length].decode())
            if not isinstance(body, dict):
                raise ProtocolError("control frame is not a JSON object")
            msgs.append(msg_from_dict(body))
            del self._buf[: 4 + length]
        return msgs


# ---------- datagrams: raw JSON ----------


def encode_datagram(msg: Msg) -> bytes:
    return _dump_json(_msg_to_dict(msg))


def decode_datagram(data: bytes) -> Msg | None:
    """Returns None for datagrams that are not our JSON messages."""
    try:
        body = json.loads(data.decode())
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(body, dict):
        return None
    try:
        return msg_from_dict(body)
    except ProtocolError:
        return None


# ---------- data frames: u32 headerLen | u32 payloadLen | header | payload ----------


def _header_to_dict(header: FrameHeader) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ch": header.ch,
        "seq": header.seq,
        "ts": header.ts,
        "delivery": header.delivery,
    }
    if header.meta is not None:
        out["meta"] = header.meta
    return out


def encode_data_frame(header: FrameHeader, payload: bytes) -> bytes:
    hdr = _dump_json(_header_to_dict(header))
    return struct.pack("<II", len(hdr), len(payload)) + hdr + payload


def peek_data_frame_lengths(buf: bytes) -> tuple[int, int, int] | None:
    """(headerLen, payloadLen, total) or None if fewer than 8 bytes are available."""
    if len(buf) < 8:
        return None
    header_len, payload_len = struct.unpack_from("<II", buf, 0)
    if header_len > MAX_HEADER_LEN:
        raise ProtocolError(f"data frame header too large: {header_len}")
    return header_len, payload_len, 8 + header_len + payload_len


def decode_data_frame(frame: bytes) -> DataFrame:
    lens = peek_data_frame_lengths(frame)
    if lens is None or len(frame) < lens[2]:
        raise ProtocolError(f"truncated data frame: {len(frame)} bytes")
    header_len, _, total = lens
    body = json.loads(frame[8 : 8 + header_len].decode())
    if not isinstance(body, dict):
        raise ProtocolError("data frame header is not a JSON object")
    header = FrameHeader(
        ch=body["ch"],
        seq=body["seq"],
        ts=body["ts"],
        delivery=body["delivery"],
        meta=body.get("meta"),
    )
    return DataFrame(header=header, payload=bytes(frame[8 + header_len : total]))


class DataFrameReader:
    """Incremental reader for a single-message stream.

    Returns the frame as soon as headerLen + payloadLen bytes have arrived;
    never waits for EOF. Bytes past the frame are ignored.
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self._done = False

    def push(self, chunk: bytes) -> DataFrame | None:
        if self._done:
            return None
        self._buf += chunk
        lens = peek_data_frame_lengths(bytes(self._buf))
        if lens is None or len(self._buf) < lens[2]:
            return None
        self._done = True
        frame = decode_data_frame(bytes(self._buf))
        self._buf = bytearray()
        return frame
