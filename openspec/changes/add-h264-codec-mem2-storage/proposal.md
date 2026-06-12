## Why

DimOS image streams currently use full `Image` objects over typed transports and memory2 stores images as independent JPEG payloads. That is simple and compatible, but inefficient for long-running camera streams and remote subscribers because each frame is compressed independently and no shared video codec state is reused.

DimOS needs an opt-in H.264 image-stream path that preserves the public `Image` stream contract while allowing live transports and memory2 storage to carry compact encoded image payloads. The design should make H.264 reusable across carriers such as LCM first, and DDS/WebRTC later, while keeping memory2 queries, pose/tag alignment, and replay frame timing intact.

## What Changes

- Add encoded `Image` support for RGB/BGR-style image streams, with one H.264 Annex B access unit per source frame and codec metadata on the `Image`.
- Add stateful H.264 encode/decode behavior that produces periodic self-contained keyframes, rejects unsupported image formats clearly, detects sequence gaps, and resumes delivery only after a valid keyframe.
- Add an opt-in live transport path for H.264 image streams, starting with LCM, that can expose decoded raw `Image` values or encoded H.264 `Image` values depending on subscriber configuration.
- Add memory2 H.264 image storage through a normal `H264ImageCodec` so streams can store one encoded `Image` observation per frame without a special storage backend.
- Preserve the existing JPEG image codec and JPEG-backed memory2 storage as the default behavior.
- No hardware-safety behavior changes are intended.
- No public robot-control, skill, or MCP breaking changes are intended.

## Affected DimOS Surfaces

- Modules/streams: typed `Image` streams, image-specific transport adapters, memory2 Recorder ingestion, memory2 Stream/Observation payload access, and replay output of encoded images for H.264-backed streams.
- Blueprints/CLI: blueprints may opt image streams into H.264-capable transports or memory2 H.264 storage; existing blueprint behavior remains unchanged unless configured.
- Skills/MCP: no direct skill or MCP behavior changes expected.
- Hardware/simulation/replay: camera-heavy hardware and simulation streams may benefit from reduced bandwidth/storage; H.264 replay emits encoded `Image` values on the same schedule and explicit decode sessions convert them to decoded frames for consumers.
- Docs/generated registries: memory2 and transport docs need updates; generated blueprint registries are not expected to change unless new demo blueprints are added.

## Capabilities

### New Capabilities

- `h264-image-streams`: Covers encoded H.264 `Image` payloads, live image-stream encode/decode behavior, keyframe/GOP handling, sequence-gap behavior, and transport compatibility expectations.
- `memory2-h264-storage`: Covers opt-in H.264-backed memory2 image observation storage through `H264ImageCodec`, per-frame encoded image persistence, replay of encoded images, and explicit best-effort decode sessions.

### Modified Capabilities

- None.

## Impact

Users and developers gain a more bandwidth- and storage-efficient option for camera streams while keeping existing `Image` stream consumers and memory2 query/replay behavior familiar. Existing JPEG-backed recordings, default transports, and non-image streams remain compatible.

Compatibility risk centers on adding optional video codec dependencies, keeping encoded images from accidentally flowing into raw-pixel operations, making GOP recovery deterministic after packet loss or replay seek, and avoiding silent corruption when frames cannot be decoded. Documentation and QA should cover opt-in configuration, supported image formats, dependency installation, LCM live-stream behavior, memory2 append/query/replay behavior, packet-loss recovery, and a small synthetic image-stream demo.
