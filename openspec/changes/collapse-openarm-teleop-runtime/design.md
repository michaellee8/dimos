## Context

`dimos.teleop.runtime.TeleopModule` owns a polling thread, stale-command gate, publish-rate gate, generic command envelope, and output hook. The only production subclass is `OpenArmMiniTeleopModule`, whose Feetech leader input is synchronously polled. Other teleop implementations use WebSocket, WebRTC, pygame, callback, asyncio, or frontend-owned loops and therefore cannot safely share this runtime.

The current OpenArm Mini command is created immediately after a local serial read. Its envelope timestamp is consequently fresh by construction, while the configured polling period already limits publication frequency. The stale and independent publish-rate policies do not provide useful behavior for this source.

## Goals / Non-Goals

**Goals:**

- Make OpenArm Mini explicitly own its polling lifecycle and `JointState` publication.
- Remove the misleading generic polling base and generic command envelope.
- Retain deterministic synchronous polling through `tick()`.
- Validate polling configuration and ensure a module owns at most one polling worker.
- Preserve calibration, authority, mapping, jump rejection, transient read-failure, and output behavior.

**Non-Goals:**

- Unify phone, Quest, hosted Quest, or keyboard teleop lifecycle.
- Introduce an optional-loop teleop superclass.
- Introduce shared periodic-worker, freshness, rate-limit, or latest-value helpers before multiple consumers share identical semantics.
- Change OpenArm Mini calibration, serial protocol, joint mapping, or blueprint behavior.
- Define universal actuator halt semantics.

## Decisions

### OpenArm Mini directly subclasses `Module`

`OpenArmMiniTeleopModule` will inherit from `Module`, and `OpenArmMiniTeleopModuleConfig` will inherit from `ModuleConfig`. The concrete module will own its stop event, polling thread, start/stop RPCs, `tick()`, and polling loop.

This is preferred over renaming the existing base to `PollingTeleopModule` because there is only one polled implementation. A base becomes justified when another pull-based device shares the same lifecycle and policies.

### Commands are concrete `JointState` values

The read method will return `JointState | None`, and `tick()` will publish a returned value directly on `joint_command`. This removes `TeleopCommand`, runtime payload type checks, stop envelopes, stale checks, and the generic `object` publishing hook.

This is preferred over retaining an envelope because OpenArm Mini has one output type, creates commands synchronously, and represents inactivity or failed reads as no command.

### One polling period controls reads and publication opportunities

The OpenArm Mini config will retain a positive polling period. Separate `max_publish_rate_hz` and `stale_command_timeout_s` settings will be removed because each successful polling tick produces at most one immediately published command.

### Lifecycle remains concrete and defensive

`start()` will reject or avoid creating a second worker, connect the selected leaders before launching the worker, and clean up if startup fails. `stop()` will signal and join the worker, clear the thread reference, disconnect leaders, and then delegate to `Module.stop()`.

Expected Feetech read failures remain handled by the existing command-read path so the worker continues on later ticks. Unexpected worker failures will be logged rather than disappearing silently.

### Shared helpers are deferred

No helper is extracted in this change. A future helper must have at least two real consumers with matching ownership semantics. Likely candidates are a periodic worker lifecycle utility or local-monotonic freshness gate, but current teleop modules differ in thread affinity, halt behavior, and scheduling ownership.

## Risks / Trade-offs

- **Internal imports of the runtime classes break** → Search the repository for all imports and subclasses, update the sole production consumer, and remove obsolete tests.
- **Inlining duplicates mechanics found elsewhere** → Accept small duplication until another module has the same runtime shape; extract from demonstrated duplication later.
- **Lifecycle behavior may change during the move** → Preserve focused tests for connection, publication, read failure recovery, one-worker ownership, and cleanup.
- **Removing stale/rate settings changes configuration surface** → Confirm no blueprint or documentation overrides those fields and remove stale references.
- **Unexpected worker exceptions could repeatedly log** → Keep the fixed polling wait between attempts and test the chosen failure behavior.

## Migration Plan

1. Add concrete polling configuration and lifecycle to `OpenArmMiniTeleopModule`.
2. Replace envelope-returning command reads with `JointState | None` and direct publication.
3. Update OpenArm Mini tests and blueprints/config references.
4. Remove runtime base, envelope, and dedicated runtime tests after repository-wide reference checks.
5. Run focused tests, blueprint validity checks, Ruff, and mypy.

Rollback is a normal source revert because the change affects internal Python APIs only and introduces no persisted data migration.

## Open Questions

None. Shared helper extraction is intentionally deferred until a second matching consumer exists.
