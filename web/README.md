# DimOS web

Deno workspace for the robot web stack: `relay/` (WebTransport relay), `shared/` (protocol, mirrored
in `dimos/web/relay_bridge/protocol.py`). The Cockpit browser app joins as `cockpit/` in a later
ticket.

Everything runs on Deno 2.6.10, pinned in `dimos/utils/deno.py` and CI.

```bash
deno task dev            # relay on http://127.0.0.1:7780 (debug page at /debug.html)
deno task test           # unit + loopback e2e tests
deno task check          # type-check; deno fmt + deno lint for style
```

Python side, from the repo root:

```bash
uv run python -m dimos.web.relay_bridge.smoke   # spawns a relay, pushes synthetic data
uv run pytest -m web_e2e dimos/web/relay_bridge # e2e against a real relay child
```

Browsers: Chrome and Firefox. Safari ships WebTransport behind a feature flag and its draft-13
negotiation is rejected by Deno's `web-transport-proto 0.2.7`; it is not a target (fallbacks would
come with T12-era work).

## Protocol shape, and why it is odd

The framing is defined once in `shared/protocol.ts`, mirrored in Python, and pinned by golden
vectors in `shared/fixtures/` (regenerate via
`deno run --allow-write=shared/fixtures shared/fixtures/gen.ts`; tested from both `deno test` and
pytest).

Several choices are workarounds for upstream bugs, verified 2026-07-10..15 on Deno 2.6.10 + aioquic
1.3 (details and probes in the spike branch `paul/experiment/webtransport`):

1. **Robot data rides one-shot bidi streams, not uni.** Deno never delivers payloads of incoming uni
   streams (server-side receive; even from Deno's own client). Relay->viewer uni streams are
   unaffected.
2. **Every message is length-prefixed; EOF is never a message boundary.** Deno's `writer.close()`
   sends FIN lazily (~1 s, on GC). Receivers count bytes:
   `u32-LE headerLen | u32-LE payloadLen | header JSON | payload`.
3. **The relay never writes on robot-opened streams** and aborts its send half (RESET). aioquic
   parses server bytes on client-initiated bidi WT streams as H3 frames and kills the connection
   (H3_FRAME_UNEXPECTED). Robot-leg control (hello/welcome/ping/pong) rides datagrams instead; the
   robot retries hello until welcomed (datagrams are lossy).
4. **aioquic must set `max_datagram_frame_size=65536`** or the session dies at SETTINGS time.
5. **Relay installs an `unhandledrejection` guard** (deno#28406) or it dies ~30 s after a browser
   tab closes.
6. **WT URLs use `https://127.0.0.1`, never `localhost`** (Chrome resolves localhost to ::1 first;
   the endpoint binds IPv4).
7. **Relay->viewer uni streams use `waitUntilAvailable` + decreasing `sendOrder`.** Without the
   former, a slow page exhausts stream credit and the create call throws; without the latter, quinn
   round-robins in-flight streams and completions arrive in ~1 s waves.
8. **Reading incoming streams server-side needs a BYOB reader**; default readers never deliver on
   Deno 2.6.10.
9. **aioquic `reset_stream()` on an already-discarded stream corrupts the stream-id allocator**
   (`_get_or_create_stream_for_send` recreates the stream and rewinds `_local_next_stream_id_*`, so
   the next stream reuses a FIN'd id). The bridge only resets ids still present in `_quic._streams`,
   checked and reset in the same event-loop turn.

One-stream-per-message delivers out of order by design; consumers keep the newest frame by `seq` and
loss metrics are span-based (`maxSeq - minSeq + 1 - received`).

## Certificates

The relay generates an ephemeral self-signed ECDSA P-256 cert at startup (validity now-1h .. now+9d;
Chrome caps hash-pinned certs at 14 days) and serves its SHA-256 via `GET /api/info`. Browsers
connect with `serverCertificateHashes`; the Python bridge connects insecurely to loopback only. Real
TLS for remote access is T12.

## Packaging

The wheel ships this directory as `dimos/web/relay_bridge/_relay_dist/` (copied by the `build_py`
hook in `setup.py`; `graft web` in `MANIFEST.in` covers the sdist).
`dimos.web.relay_bridge.locate.find_web_dir()` resolves a checkout first, then the packaged copy;
`DIMOS_WEB_DIR` overrides.
