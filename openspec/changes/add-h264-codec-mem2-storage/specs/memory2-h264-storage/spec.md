## ADDED Requirements

### Requirement: H.264 image storage is opt-in per memory2 stream
memory2 SHALL allow image streams to opt into H.264 storage through the normal codec configuration path while preserving the default image-storage behavior for streams that do not opt in.

#### Scenario: Stream opts into H.264 storage
- **GIVEN** a memory2 image stream is configured with the H.264 image codec
- **WHEN** the stream appends encoded `Image` values with `encoding="h264"`
- **THEN** memory2 MUST store those image observations using H.264 encoded payloads through the existing backend/blob path
- **AND** queries for the stream must continue to return image observations associated with the original frame timestamps.

#### Scenario: H.264 storage uses the normal codec extension point
- **GIVEN** a store creates an `Image` stream with `codec="h264"`
- **WHEN** memory2 creates the stream backend
- **THEN** memory2 MUST use the normal codec resolution and blob persistence flow
- **AND** the generic store and backend paths must not contain H.264-specific branches or imports.

#### Scenario: Stream uses default image storage
- **GIVEN** a memory2 image stream is created without H.264 image-storage configuration
- **WHEN** the stream appends `Image` values
- **THEN** memory2 MUST preserve the existing default image-storage behavior
- **AND** existing JPEG-backed recordings remain readable through the normal memory2 APIs.

### Requirement: H.264 storage preserves one observation per source frame
memory2 SHALL store H.264-backed image streams with one observation corresponding to each source image frame.

#### Scenario: Recording a sequence of image frames
- **GIVEN** a recorder receives a sequence of `Image` frames on an H.264-backed memory2 stream
- **WHEN** memory2 stores the sequence
- **THEN** memory2 MUST create one queryable observation per source frame
- **AND** each observation must retain its timestamp, frame identifier, pose metadata when available, and tags independently of pixel decode.

### Requirement: Stored H.264 Images are complete frame access units
memory2 SHALL store each H.264 image observation with an encoded `Image` payload that contains the complete Annex B access unit for that source frame.

#### Scenario: Stored encoded Image is inspected or exported
- **GIVEN** an H.264-backed image observation has an encoded `Image` payload
- **WHEN** the payload is inspected by storage tooling or exported to a compatible video-message format
- **THEN** the `Image.data` payload MUST represent all NAL units emitted for that source frame in Annex B form
- **AND** the `Image.codec_metadata` MUST include H.264 frame metadata such as sequence, keyframe state, keyframe reference, presentation timestamp, dimensions, codec, and bitstream
- **AND** memory2 MUST avoid exposing individual RTP fragments as the stored observation payload.

### Requirement: Decode starts from valid keyframe state
H.264 decoded views over memory2 replay SHALL use the same best-effort H.264 decode policy as live subscribers: decode starts without GOP state and suppresses delta frames until a keyframe at or after the start point establishes valid decoder state.

#### Scenario: Replay seeks into the middle of a GOP
- **GIVEN** a user starts replay or a decoded view at a timestamp whose first stored H.264 packet is a delta frame
- **WHEN** a H.264 decode session decodes the replayed encoded images from that start point
- **THEN** the decode session MUST suppress undecodable delta frames until the first keyframe at or after the start point
- **AND** the decoded view MUST emit decoded `Image` values for that keyframe and following decodable delta frames.

#### Scenario: Required GOP state is missing
- **GIVEN** an H.264 encoded image requires prior GOP state to decode
- **WHEN** a decode session has no usable keyframe state
- **THEN** the decode session MUST fail or suppress the decode with a clear decode error
- **AND** DimOS MUST avoid returning corrupted pixels as a valid decoded `Image`.

### Requirement: Metadata queries do not force pixel decode
memory2 SHALL allow metadata and encoded-payload access for H.264-backed image observations without decoding image pixels.

#### Scenario: Query reads observation metadata only
- **GIVEN** a memory2 store contains H.264-backed image observations
- **WHEN** a user queries observations and reads timestamps, frame identifiers, pose metadata, tags, `Image.encoding`, or H.264 codec metadata
- **THEN** memory2 MUST provide that information without requiring H.264 pixel decode
- **AND** the stored `obs.data` value for a H.264 stream MUST be an encoded `Image`, not a decoded pixel image.

### Requirement: H.264 codec stores and restores encoded Images
memory2 SHALL store and restore H.264 observations as encoded `Image` values through the H.264 image codec.

#### Scenario: User accesses observation data from an H.264 stream
- **GIVEN** a queried H.264-backed image observation was stored with the H.264 image codec
- **WHEN** the user accesses `obs.data`
- **THEN** memory2 MUST return an `Image` value with `encoding="h264"`
- **AND** pixel decoding MUST require an explicit H.264 decode session outside the generic memory2 backend.

### Requirement: H.264-backed replay emits encoded Images
memory2 SHALL replay H.264-backed image streams as encoded `Image` values on the existing replay schedule.

#### Scenario: Replaying a stored H.264 image stream
- **GIVEN** a memory2 store contains an H.264-backed image stream
- **WHEN** replay is started for that stream
- **THEN** replay MUST emit encoded `Image` values in observation timestamp order
- **AND** an explicit H.264 decode session MAY convert those encoded images to raw decoded `Image` values for visualization or consumers
- **AND** that decode session MUST skip undecodable deltas before the first valid keyframe at or after the replay start point.

### Requirement: H.264 storage survives store reopen
memory2 SHALL persist H.264 codec configuration and encoded image metadata so a reopened store can query and replay H.264-backed image streams.

#### Scenario: Reopen and decode
- **GIVEN** a memory2 store was written with an H.264-backed image stream
- **WHEN** the process closes and a later process reopens the store
- **THEN** memory2 MUST recognize the stream as H.264-backed
- **AND** the reopened store must return encoded `Image` values from query and replay
- **AND** explicit decode sessions must retain the same best-effort keyframe-start behavior after reopen.
