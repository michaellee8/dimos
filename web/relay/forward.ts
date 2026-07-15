// Robot->viewer forwarding: per-(viewer, channel) delivery policies over a
// transport-blind ViewerSink, so the policy logic is unit-testable without
// QUIC. The relay never parses payloads; it routes on the frame header only.
import { type Delivery, MAX_HEADER_LEN, peekDataFrameLengths } from "@dimos/shared";

// Upper bound for a single data frame accepted from the robot; guards the
// relay against buffering a hostile/corrupt payloadLen (policies bound
// per-viewer memory separately).
export const MAX_DATA_FRAME_BYTES = 64 * 1024 * 1024;

// Reliable channels: a viewer this far behind is dead weight; kick it so it
// reconnects with a clean slate (T5 hardens and tunes these).
const RELIABLE_MAX_QUEUE = 64;
const RELIABLE_MAX_BYTES = 16 * 1024 * 1024;

/** Transport surface a policy writes to: one uni stream per sendFrame call. */
export interface ViewerSink {
  sendFrame(bytes: Uint8Array): Promise<void>;
  kick(reason: string): void;
}

interface ChannelPolicy {
  readonly delivery: Delivery;
  sent: number;
  dropped: number;
  queued(): number;
  offer(bytes: Uint8Array): void;
}

/**
 * Latest-wins: a 1-slot pending buffer. A frame arriving while a write is in
 * flight replaces the pending one (newest wins); the final frame is always
 * eventually delivered. A slow viewer sheds its own frames and nothing else.
 */
export class LatestChannel implements ChannelPolicy {
  readonly delivery: Delivery = "latest";
  sent = 0;
  dropped = 0;
  #pending: Uint8Array | null = null;
  #writing = false;

  constructor(readonly sink: ViewerSink) {}

  queued(): number {
    return this.#pending ? 1 : 0;
  }

  offer(bytes: Uint8Array): void {
    if (this.#pending) this.dropped++;
    this.#pending = bytes;
    this.#drain();
  }

  #drain(): void {
    if (this.#writing) return;
    this.#writing = true;
    (async () => {
      while (this.#pending) {
        const bytes = this.#pending;
        this.#pending = null;
        await this.sink.sendFrame(bytes);
        this.sent++;
      }
    })()
      .catch(() => this.sink.kick("write failed"))
      .finally(() => {
        this.#writing = false;
      });
  }
}

/**
 * Reliable: bounded per-viewer FIFO, no drops, delivery order preserved. On
 * overflow the viewer is kicked (better a visible reconnect than silent loss).
 */
export class ReliableChannel implements ChannelPolicy {
  readonly delivery: Delivery = "reliable";
  sent = 0;
  dropped = 0;
  #fifo: Uint8Array[] = [];
  #bytes = 0;
  #writing = false;

  constructor(readonly sink: ViewerSink) {}

  queued(): number {
    return this.#fifo.length;
  }

  offer(bytes: Uint8Array): void {
    this.#fifo.push(bytes);
    this.#bytes += bytes.byteLength;
    if (this.#fifo.length > RELIABLE_MAX_QUEUE || this.#bytes > RELIABLE_MAX_BYTES) {
      this.sink.kick("reliable channel overflow");
      return;
    }
    this.#drain();
  }

  #drain(): void {
    if (this.#writing) return;
    this.#writing = true;
    (async () => {
      for (let bytes = this.#fifo.shift(); bytes; bytes = this.#fifo.shift()) {
        this.#bytes -= bytes.byteLength;
        await this.sink.sendFrame(bytes);
        this.sent++;
      }
    })()
      .catch(() => this.sink.kick("write failed"))
      .finally(() => {
        this.#writing = false;
      });
  }
}

export interface ViewerHandle {
  id: number;
  sink: ViewerSink;
  channels: Map<string, ChannelPolicy>;
}

interface ChannelInStats {
  delivery: Delivery;
  framesIn: number;
  bytesIn: number;
}

/** Routes robot frames to every viewer through its per-channel policy. */
export class Forwarder {
  #viewers = new Set<ViewerHandle>();
  #channelsIn = new Map<string, ChannelInStats>();
  #nextViewerId = 1;

  addViewer(sink: ViewerSink): ViewerHandle {
    const handle: ViewerHandle = { id: this.#nextViewerId++, sink, channels: new Map() };
    this.#viewers.add(handle);
    return handle;
  }

  removeViewer(handle: ViewerHandle): void {
    this.#viewers.delete(handle);
  }

  get viewerCount(): number {
    return this.#viewers.size;
  }

  /** Route one robot data frame (raw bytes, already length-complete). */
  onRobotFrame(bytes: Uint8Array): void {
    const lens = peekDataFrameLengths(bytes);
    if (lens === null) return;
    let header: { ch?: unknown; delivery?: unknown };
    try {
      header = JSON.parse(new TextDecoder().decode(bytes.subarray(8, 8 + lens.headerLen)));
    } catch {
      return; // not our framing; drop
    }
    const ch = typeof header.ch === "string" ? header.ch : "?";
    const delivery: Delivery = header.delivery === "reliable" ? "reliable" : "latest";

    const stats = this.#channelsIn.get(ch) ?? { delivery, framesIn: 0, bytesIn: 0 };
    stats.delivery = delivery;
    stats.framesIn++;
    stats.bytesIn += bytes.byteLength;
    this.#channelsIn.set(ch, stats);

    for (const viewer of this.#viewers) {
      let policy = viewer.channels.get(ch);
      if (policy === undefined || policy.delivery !== delivery) {
        policy = delivery === "reliable"
          ? new ReliableChannel(viewer.sink)
          : new LatestChannel(viewer.sink);
        viewer.channels.set(ch, policy);
      }
      policy.offer(bytes);
    }
  }

  stats(): unknown {
    return {
      viewers: this.#viewers.size,
      channels: Object.fromEntries(this.#channelsIn),
      perViewer: [...this.#viewers].map((v) => ({
        id: v.id,
        channels: Object.fromEntries(
          [...v.channels].map(([ch, p]) => [
            ch,
            { sent: p.sent, dropped: p.dropped, queued: p.queued() },
          ]),
        ),
      })),
    };
  }
}

/**
 * Read one length-prefixed data frame from a robot stream, stopping at the
 * frame's byte count - never at EOF (Deno 2.6.x delays FIN by up to ~1 s, and
 * a reset-stale writer may never send one). BYOB reader: default readers were
 * observed to never deliver on Deno 2.6.10 incoming WT streams.
 */
export async function readDataFrameBytes(rs: ReadableStream<Uint8Array>): Promise<Uint8Array> {
  const reader = rs.getReader({ mode: "byob" });
  const chunks: Uint8Array[] = [];
  let size = 0;
  let total: number | null = null;
  try {
    while (total === null || size < total) {
      const { value, done } = await reader.read(new Uint8Array(64 * 1024));
      if (value && value.byteLength) {
        chunks.push(value);
        size += value.byteLength;
        if (total === null && size >= 8) {
          const head = concat(chunks, Math.min(size, 8 + MAX_HEADER_LEN + 8));
          const lens = peekDataFrameLengths(head);
          if (lens !== null) {
            if (lens.total > MAX_DATA_FRAME_BYTES) {
              throw new Error(`data frame too large: ${lens.total} bytes`);
            }
            total = lens.total;
          }
        }
      }
      if (done) break;
    }
  } finally {
    reader.releaseLock();
  }
  if (total === null || size < total) {
    throw new Error(`robot stream ended mid-frame (${size} bytes)`);
  }
  return concat(chunks, total);
}

function concat(chunks: Uint8Array[], limit: number): Uint8Array {
  const out = new Uint8Array(limit);
  let off = 0;
  for (const c of chunks) {
    if (off >= limit) break;
    const take = Math.min(c.byteLength, limit - off);
    out.set(take === c.byteLength ? c : c.subarray(0, take), off);
    off += take;
  }
  return out;
}
