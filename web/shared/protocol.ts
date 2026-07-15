// Wire protocol shared by the relay (Deno) and the Cockpit (browser).
// Mirrored in Python at dimos/web/relay_bridge/protocol.py and pinned by the
// golden vectors in ./fixtures/ (tested from both deno test and pytest).
//
// Framing (see web/README.md for the upstream-bug rationale):
// - Control stream frame: u32-LE length | UTF-8 JSON.
// - Datagram: raw UTF-8 JSON, no length prefix.
// - Data frame (one message per stream): u32-LE headerLen | u32-LE payloadLen
//   | header JSON | payload. Receivers count bytes and must never treat
//   stream EOF as a message boundary (Deno 2.6.x delays FIN by up to ~1 s).

export const PROTOCOL_VERSION = 1;

// Reject absurd header lengths before allocating (a data frame arrives from
// the network; its payload length is bounded by the relay's policies instead).
export const MAX_HEADER_LEN = 65536;

export type Role = "robot" | "viewer";
export type Delivery = "latest" | "reliable";

export interface HelloMsg {
  t: "hello";
  v: number;
  role: Role;
}

export interface WelcomeMsg {
  t: "welcome";
  v: number;
}

export interface PingMsg {
  t: "ping";
  n: number;
  ts: number;
}

export interface PongMsg {
  t: "pong";
  n: number;
  ts: number;
}

export interface ErrorMsg {
  t: "error";
  code: string;
  message: string;
}

// Teleop datagrams (carried from T6 on; declared here so the wire format is
// pinned by fixtures from day one).
export interface TwistMsg {
  t: "twist";
  vx: number;
  wz: number;
  seq: number;
  ts: number;
}

export interface StopMsg {
  t: "stop";
  seq: number;
  ts: number;
}

export type ControlMsg = HelloMsg | WelcomeMsg | PingMsg | PongMsg | ErrorMsg;
export type TeleopMsg = TwistMsg | StopMsg;
export type Msg = ControlMsg | TeleopMsg;

// Data-plane frame header. `delivery` tells the relay how to forward the
// frame without a manifest (T1 only; the T2+ manifest replaces it). `meta`
// carries encoding-specific extras (e.g. {w, h} for images).
export interface FrameHeader {
  ch: string;
  seq: number;
  ts: number;
  delivery: Delivery;
  meta?: Record<string, unknown>;
}

export interface DataFrame {
  header: FrameHeader;
  payload: Uint8Array;
}

const enc = new TextEncoder();
const dec = new TextDecoder();

// ---------- control stream framing: u32-LE length | JSON ----------

export function encodeControlFrame(msg: Msg): Uint8Array {
  const body = enc.encode(JSON.stringify(msg));
  const out = new Uint8Array(4 + body.length);
  new DataView(out.buffer).setUint32(0, body.length, true);
  out.set(body, 4);
  return out;
}

/** Incremental parser for a control stream (frames may split across chunks). */
export class ControlFrameReader {
  #buf = new Uint8Array(0);

  push(chunk: Uint8Array): Msg[] {
    const merged = new Uint8Array(this.#buf.length + chunk.length);
    merged.set(this.#buf, 0);
    merged.set(chunk, this.#buf.length);
    this.#buf = merged;
    const msgs: Msg[] = [];
    while (this.#buf.length >= 4) {
      const len = new DataView(this.#buf.buffer, this.#buf.byteOffset).getUint32(0, true);
      if (len > MAX_HEADER_LEN) throw new Error(`control frame too large: ${len}`);
      if (this.#buf.length < 4 + len) break;
      msgs.push(JSON.parse(dec.decode(this.#buf.subarray(4, 4 + len))));
      this.#buf = this.#buf.subarray(4 + len);
    }
    return msgs;
  }
}

// ---------- datagrams: raw JSON ----------

export function encodeDatagram(msg: Msg): Uint8Array {
  return enc.encode(JSON.stringify(msg));
}

/** Returns null for datagrams that are not our JSON messages. */
export function decodeDatagram(data: Uint8Array): Msg | null {
  try {
    const msg = JSON.parse(dec.decode(data));
    return typeof msg === "object" && msg !== null && typeof msg.t === "string" ? msg : null;
  } catch {
    return null;
  }
}

// ---------- data frames: u32 headerLen | u32 payloadLen | header | payload ----------

export function encodeDataFrame(header: FrameHeader, payload: Uint8Array): Uint8Array {
  const hdr = enc.encode(JSON.stringify(header));
  const out = new Uint8Array(8 + hdr.length + payload.length);
  const dv = new DataView(out.buffer);
  dv.setUint32(0, hdr.length, true);
  dv.setUint32(4, payload.length, true);
  out.set(hdr, 8);
  out.set(payload, 8 + hdr.length);
  return out;
}

/** Byte lengths of a data frame, or null if fewer than 8 bytes are available. */
export function peekDataFrameLengths(
  buf: Uint8Array,
): { headerLen: number; payloadLen: number; total: number } | null {
  if (buf.length < 8) return null;
  const dv = new DataView(buf.buffer, buf.byteOffset);
  const headerLen = dv.getUint32(0, true);
  const payloadLen = dv.getUint32(4, true);
  if (headerLen > MAX_HEADER_LEN) throw new Error(`data frame header too large: ${headerLen}`);
  return { headerLen, payloadLen, total: 8 + headerLen + payloadLen };
}

export function decodeDataFrame(frame: Uint8Array): DataFrame {
  const lens = peekDataFrameLengths(frame);
  if (lens === null || frame.length < lens.total) {
    throw new Error(`truncated data frame: ${frame.length} bytes`);
  }
  const header = JSON.parse(dec.decode(frame.subarray(8, 8 + lens.headerLen)));
  return { header, payload: frame.subarray(8 + lens.headerLen, lens.total) };
}

/**
 * Incremental reader for a single-message stream. Returns the frame as soon
 * as headerLen + payloadLen bytes have arrived; never waits for EOF. Bytes
 * past the frame are ignored.
 */
export class DataFrameReader {
  #buf = new Uint8Array(0);
  #done = false;

  push(chunk: Uint8Array): DataFrame | null {
    if (this.#done) return null;
    const merged = new Uint8Array(this.#buf.length + chunk.length);
    merged.set(this.#buf, 0);
    merged.set(chunk, this.#buf.length);
    this.#buf = merged;
    const lens = peekDataFrameLengths(this.#buf);
    if (lens === null || this.#buf.length < lens.total) return null;
    this.#done = true;
    const frame = decodeDataFrame(this.#buf);
    this.#buf = new Uint8Array(0);
    return frame;
  }
}
