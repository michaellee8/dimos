// Throwaway spike cockpit: connects to the relay over WebTransport, renders
// video/odom/lidar, sends teleop + ping datagrams, measures rates.
// Bundle: deno bundle --platform browser -o relay/static/main.js cockpit/main.ts

// Minimal WebTransport typings (lib.dom doesn't ship them everywhere; the
// bundler doesn't typecheck, these are just for editing sanity).
type WT = {
  ready: Promise<void>;
  closed: Promise<unknown>;
  close(): void;
  createBidirectionalStream(): Promise<{ readable: ReadableStream<Uint8Array>; writable: WritableStream<Uint8Array> }>;
  incomingUnidirectionalStreams: ReadableStream<ReadableStream<Uint8Array>>;
  datagrams: {
    readable: ReadableStream<Uint8Array>;
    writable: WritableStream<Uint8Array>;
  };
};

const enc = new TextEncoder();
const dec = new TextDecoder();
const $ = (id: string) => document.getElementById(id)!;
const viewerId = Math.random().toString(36).slice(2, 8);

function setStatus(cls: "ok" | "bad" | "", msg: string) {
  const el = $("status");
  el.className = cls;
  el.textContent = msg;
  if (cls === "bad") console.error(msg);
}

function die(msg: string): never {
  setStatus("bad", msg);
  report("failed:" + msg);
  throw new Error(msg);
}

// ---------- stats ----------

interface ChStat {
  frames: number;
  bytes: number;
  windowFrames: number;
  windowBytes: number;
  hz: number;
  kbPerFrame: number;
  minSeq: number;
  maxSeq: number;
  ooo: number; // arrived after a higher seq (expected: streams are unordered)
}
const stats = new Map<string, ChStat>();
let rttMs = -1;
let state = "init";

function bump(ch: string, bytes: number, seq: number) {
  let s = stats.get(ch);
  if (!s) {
    s = { frames: 0, bytes: 0, windowFrames: 0, windowBytes: 0, hz: 0, kbPerFrame: 0, minSeq: seq, maxSeq: -1, ooo: 0 };
    stats.set(ch, s);
  }
  s.frames++;
  s.bytes += bytes;
  s.windowFrames++;
  s.windowBytes += bytes;
  if (seq < s.maxSeq) s.ooo++;
  else s.maxSeq = seq;
}

// true loss: seqs in [minSeq, maxSeq] that never arrived at all
function lost(s: ChStat): number {
  return Math.max(0, s.maxSeq - s.minSeq + 1 - s.frames);
}

setInterval(() => {
  const tbody = $("stats").querySelector("tbody")!;
  tbody.innerHTML = "";
  for (const [ch, s] of stats) {
    s.hz = 0.6 * s.windowFrames + 0.4 * s.hz; // 1s window EWMA
    s.kbPerFrame = s.windowFrames ? s.windowBytes / s.windowFrames / 1024 : s.kbPerFrame;
    s.windowFrames = 0;
    s.windowBytes = 0;
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${ch}</td><td>${s.hz.toFixed(1)}</td><td>${s.kbPerFrame.toFixed(1)}</td>` +
      `<td>${s.frames}</td><td>${lost(s)}</td><td>${s.ooo}</td>`;
    tbody.appendChild(tr);
  }
  $("rtt").textContent = rttMs < 0 ? "rtt: –" : `rtt: ${rttMs.toFixed(1)} ms`;
}, 1000);

function report(st?: string) {
  if (st) state = st;
  const channels: Record<string, unknown> = {};
  for (const [ch, s] of stats) {
    channels[ch] = { hz: +s.hz.toFixed(1), kbPerFrame: +s.kbPerFrame.toFixed(1), frames: s.frames, lost: lost(s), ooo: s.ooo };
  }
  fetch("/api/report", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      id: viewerId,
      ua: navigator.userAgent,
      state,
      rtt: +rttMs.toFixed(1),
      channels,
      decoded: { odom: lastOdom, lidarPoints, videoSize, jpegFrames, jpegErrors },
      ts: Date.now(),
    }),
  }).catch(() => {});
}
setInterval(() => report(), 3000);

// ---------- panels ----------

// decoded-content evidence for /api/report
let lastOdom: unknown = null;
let lidarPoints = 0;
let videoSize = "";
let jpegFrames = 0;
let jpegErrors = 0;

const videoCtx = ($("video") as HTMLCanvasElement).getContext("2d")!;
let jpegBusy = false;
function drawJpeg(payload: Uint8Array) {
  if (jpegBusy) return; // latest-wins on decode
  jpegBusy = true;
  createImageBitmap(new Blob([payload], { type: "image/jpeg" }))
    .then((bmp) => {
      const c = videoCtx.canvas;
      if (c.width !== bmp.width) {
        c.width = bmp.width;
        c.height = bmp.height;
      }
      videoCtx.drawImage(bmp, 0, 0);
      videoSize = `${bmp.width}x${bmp.height}`;
      jpegFrames++;
      bmp.close();
    })
    .catch(() => jpegErrors++) // synthetic payloads aren't valid JPEG
    .finally(() => (jpegBusy = false));
}

const odomCtx = ($("odom") as HTMLCanvasElement).getContext("2d")!;
const trace: [number, number][] = [];
type Odom = { x: number; y: number; z: number; yaw: number; ts: number };

// Arrival must not drive rendering (the page falls behind and stalls its own
// stream credit): dispatch stashes the latest value, a rAF loop draws it.
let pendingOdom: Odom | null = null;
let pendingLidar: Float32Array | null = null;
function renderLoop() {
  if (pendingOdom) {
    drawOdom(pendingOdom);
    pendingOdom = null;
  }
  if (pendingLidar) {
    drawLidar(pendingLidar);
    pendingLidar = null;
  }
  requestAnimationFrame(renderLoop);
}
requestAnimationFrame(renderLoop);

function drawOdom(p: Odom) {
  lastOdom = p;
  const c = odomCtx.canvas;
  odomCtx.clearRect(0, 0, c.width, c.height);
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const [x, y] of trace) {
    minX = Math.min(minX, x);
    maxX = Math.max(maxX, x);
    minY = Math.min(minY, y);
    maxY = Math.max(maxY, y);
  }
  const span = Math.max(maxX - minX, maxY - minY, 1);
  const scale = (c.width - 30) / span;
  const px = (x: number) => 15 + (x - minX) * scale;
  const py = (y: number) => c.height - 15 - (y - minY) * scale;
  odomCtx.strokeStyle = "#4c9be8";
  odomCtx.beginPath();
  trace.forEach(([x, y], i) => (i ? odomCtx.lineTo(px(x), py(y)) : odomCtx.moveTo(px(x), py(y))));
  odomCtx.stroke();
  // heading arrow
  odomCtx.strokeStyle = "#e8734c";
  odomCtx.beginPath();
  odomCtx.moveTo(px(p.x), py(p.y));
  odomCtx.lineTo(px(p.x + 0.15 * span * Math.cos(p.yaw)), py(p.y + 0.15 * span * Math.sin(p.yaw)));
  odomCtx.stroke();
  $("odomText").textContent = `x=${p.x.toFixed(2)} y=${p.y.toFixed(2)} z=${p.z.toFixed(2)} yaw=${p.yaw.toFixed(2)}`;
}

const lidarCtx = ($("lidar") as HTMLCanvasElement).getContext("2d")!;
function drawLidar(pts: Float32Array) {
  const c = lidarCtx.canvas;
  lidarCtx.clearRect(0, 0, c.width, c.height);
  const n = pts.length / 3;
  lidarPoints = n;
  const stride = Math.max(1, Math.ceil(n / 30000));
  const half = 15; // meters shown from center to edge
  const s = c.width / (2 * half);
  for (let i = 0; i < n; i += stride) {
    const x = pts[i * 3], y = pts[i * 3 + 1], z = pts[i * 3 + 2];
    const cx = c.width / 2 + x * s;
    const cy = c.height / 2 - y * s;
    if (cx < 0 || cy < 0 || cx >= c.width || cy >= c.height) continue;
    const g = Math.max(60, Math.min(255, 140 + z * 60));
    lidarCtx.fillStyle = `rgb(${g},${g},${g})`;
    lidarCtx.fillRect(cx, cy, 2, 2);
  }
  $("lidarText").textContent = `${n} pts (stride ${stride}, ±${half} m)`;
}

// ---------- connect ----------

async function main() {
  if (!("WebTransport" in globalThis)) {
    die("No WebTransport API in this browser. Chrome >= 97 or Firefox >= 114 required.");
  }
  setStatus("", "fetching /api/info…");
  const info = await (await fetch("/api/info")).json();
  const hash = Uint8Array.from(atob(info.certHash), (ch) => ch.charCodeAt(0));
  let wt: WT;
  try {
    // deno-lint-ignore no-explicit-any
    wt = new (globalThis as any).WebTransport(info.wtUrl, {
      serverCertificateHashes: [{ algorithm: "sha-256", value: hash }],
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "NotSupportedError") {
      die(`serverCertificateHashes unsupported here (Firefox < 125?): ${e.message}`);
    }
    throw e;
  }
  wt.closed.then(
    (info) => die("session closed: " + JSON.stringify(info)),
    (e) => die("session died: " + e),
  );
  setStatus("", `connecting WebTransport to ${info.wtUrl}…`);
  await wt.ready.catch((e: unknown) => die(`WebTransport handshake failed: ${e}`));
  setStatus("ok", `connected to ${info.wtUrl} — ${navigator.userAgent.match(/(Chrome|Firefox)\/[\d.]+/)?.[0] ?? ""}`);
  report("connected");

  // control stream: hello -> welcome
  const ctrl = await wt.createBidirectionalStream();
  const cw = ctrl.writable.getWriter();
  const hello = enc.encode(JSON.stringify({ t: "hello", v: 1, role: "viewer", id: viewerId }));
  const frame = new Uint8Array(4 + hello.length);
  new DataView(frame.buffer).setUint32(0, hello.length, true);
  frame.set(hello, 4);
  await cw.write(frame);
  (async () => {
    for await (const chunk of ctrl.readable) {
      // spike: assume one whole frame per chunk on the control stream
      const len = new DataView(chunk.buffer, chunk.byteOffset).getUint32(0, true);
      console.log("control:", dec.decode(chunk.subarray(4, 4 + len)));
    }
  })().catch(() => {});

  // datagrams: teleop 20 Hz + ping 1 Hz out; pong in -> RTT
  const dgw = wt.datagrams.writable.getWriter();
  const keys = new Set<string>();
  addEventListener("keydown", (e) => keys.add(e.key.toLowerCase()));
  addEventListener("keyup", (e) => keys.delete(e.key.toLowerCase()));
  let teleopSeq = 0;
  setInterval(() => {
    const vx = (keys.has("w") ? 1 : 0) + (keys.has("s") ? -1 : 0);
    const wz = (keys.has("a") ? 1 : 0) + (keys.has("d") ? -1 : 0);
    dgw.write(enc.encode(JSON.stringify({ t: "teleop", vx, wz, seq: teleopSeq++ }))).catch(() => {});
    if (vx || wz) $("teleop").textContent = `teleop: sending vx=${vx} wz=${wz} (seq ${teleopSeq})`;
  }, 50);
  const pings = new Map<number, number>();
  let pingId = 0;
  setInterval(() => {
    const id = pingId++;
    pings.set(id, performance.now());
    if (pings.size > 20) pings.delete(id - 20);
    dgw.write(enc.encode(JSON.stringify({ t: "ping", id, from: viewerId }))).catch(() => {});
  }, 1000);
  (async () => {
    for await (const d of wt.datagrams.readable) {
      try {
        const m = JSON.parse(dec.decode(d));
        if (m.t === "pong" && pings.has(m.id)) {
          rttMs = performance.now() - pings.get(m.id)!;
          pings.delete(m.id);
        }
      } catch {
        // ignore non-JSON datagrams
      }
    }
  })().catch(() => {});

  // data plane: one message per incoming uni stream
  for await (const rs of wt.incomingUnidirectionalStreams) {
    readAll(rs)
      .then((msg) => {
        const hlen = new DataView(msg.buffer, msg.byteOffset).getUint32(0, true);
        const hdr = JSON.parse(dec.decode(msg.subarray(4, 4 + hlen)));
        const payload = msg.subarray(4 + hlen);
        bump(hdr.ch, payload.byteLength, hdr.seq);
        if (hdr.ch === "video") drawJpeg(payload); // has its own busy-skip
        else if (hdr.ch === "odom") {
          const p = JSON.parse(dec.decode(payload)) as Odom;
          trace.push([p.x, p.y]);
          if (trace.length > 3000) trace.shift();
          pendingOdom = p;
        } else if (hdr.ch === "lidar") {
          pendingLidar = new Float32Array(payload.slice().buffer); // slice() realigns
        }
      })
      .catch(() => {});
  }
}

async function readAll(rs: ReadableStream<Uint8Array>): Promise<Uint8Array> {
  const chunks: Uint8Array[] = [];
  let total = 0;
  for await (const c of rs) {
    chunks.push(c);
    total += c.length;
  }
  const out = new Uint8Array(total);
  let off = 0;
  for (const c of chunks) {
    out.set(c, off);
    off += c.length;
  }
  return out;
}

main().catch((e) => setStatus("bad", "fatal: " + e));
