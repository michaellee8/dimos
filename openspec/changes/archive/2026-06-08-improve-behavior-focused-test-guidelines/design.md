## Context

The branch adds and changes manipulator adapter tests around Damiao/OpenArm/OpenArm RS adapters and lazy manipulator adapter discovery. Several tests currently over-assert details such as private adapter fields, full default gain tables, motor-spec internals, and command-matrix columns. These details may be relevant inside an implementation, but tests that assert all of them at construction time do not communicate the behavior being protected.

The repository already has testing guidance in `docs/development/testing.md` and stricter coding-agent guidance in `docs/coding-agents/testing.md`. The current guidance covers fixtures, cleanup, imports, sleeps, prints, and deterministic assertions, but it does not explicitly warn against low-value object-shape tests.

## Goals / Non-Goals

**Goals:**

- Refine manipulator tests so each test has a clear setup, execution step, and observable expected result.
- Preserve coverage for behavior that matters while excluding fake control-binding behavior from OpenArm RS unit tests.
- Remove or collapse tests that only assert implementation shape or every minor detail of constructed objects.
- Add coding-agent documentation that describes behavior-focused test structure and an over-assertion review checklist.

**Non-Goals:**

- Change runtime adapter behavior, hardware protocol behavior, CLI behavior, streams, blueprints, or public APIs.
- Add new manipulator features.
- Require real hardware, simulation, or replay QA for this docs/test-only refinement.
- Turn every existing repository test into the new style in this change.

## DimOS Architecture

This change is limited to tests and contributor/coding-agent documentation.

- Manipulator adapter Protocol surface: OpenArm RS tests should exercise constructor-time public metadata and validation only, without mocking or driving `can_motor_control`.
- Manipulator adapter registry: tests should exercise `available()` and selected `create()` behavior without importing unselected hardware SDKs.
- Modules/streams/transports/blueprints/RPC: no production architecture changes.
- Skills/MCP/CLI: no changes.
- Generated registries: no expected regeneration.

## Decisions

1. **Test behavior through public surfaces rather than private fields.**
   - Rationale: private fields and construction details are refactor-sensitive and often do not reveal which behavior matters.
   - Alternative considered: retain broad object snapshots as regression tests. Rejected because they increase maintenance cost and hide the real behavioral contract.

2. **Use fakes to observe effects at integration boundaries.**
   - Rationale: adapter tests need to verify that calls reach backend abstractions without real hardware. Fake backends should expose small observations such as "last position target" or "transport fd mode" rather than requiring tests to inspect every internal matrix cell.
   - Alternative considered: keep direct assertions on backend command matrix columns. Some targeted matrix assertions may remain when they are the smallest way to prove a safety behavior, but they should be named and scoped to that behavior.

3. **Prune tests that cannot name the desired behavior.**
   - Rationale: if a test name cannot state the behavior it protects, the test is likely asserting object shape rather than functionality.
   - Alternative considered: rename all tests without deleting any. Rejected because renamed over-assertive tests still constrain implementation unnecessarily.

4. **Document the mistake in coding-agent guidance.**
   - Rationale: the issue was produced by agent-written tests, so the durable fix needs guidance where coding agents look before writing tests.

## Safety / Simulation / Replay

No runtime hardware behavior changes are intended. Test refinement must preserve safety-relevant behavioral checks, especially:

- OpenArm/OpenArm RS commands that hold or stop hardware safely.
- Gravity-compensation behavior where the adapter intentionally sends torque/damping behavior instead of a stiff position command.
- Lazy registry behavior so partial installations remain safe and understandable without OpenArm RS tests simulating the control binding.

Manual QA surface is the focused pytest suite for changed manipulator tests plus inspection of documentation rendering/link validity. Real hardware, MuJoCo, replay, and MCP surfaces are out of scope.

## Risks / Trade-offs

- **Risk: pruning too much coverage.** Mitigation: keep tests for named behavior contracts and error boundaries before removing detail assertions.
- **Risk: hiding safety-critical constants.** Mitigation: if a constant table is safety-critical, test the resulting command behavior and name the safety reason explicitly.
- **Risk: documentation becomes generic advice.** Mitigation: include concrete bad/good examples that mirror DimOS adapter tests.

## Migration / Rollout

- Update only test files and `docs/coding-agents/testing.md`.
- Run focused manipulator tests after implementation.
- Run documentation link validation if available for the changed docs.
- No data migration, generated registry update, dependency change, or deployment step is required.

## Open Questions

- Which existing over-assertive tests should be deleted outright versus collapsed into broader behavior tests will be decided during implementation by mapping each assertion to a named behavior.
