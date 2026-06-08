## Why

Recent manipulator adapter tests include low-value assertions that construct objects and verify many incidental details, such as private fields, full default tables, and backend command matrix internals. Those tests are hard to review because the desired behavior is unclear, and they make future refactors feel risky even when public behavior is unchanged.

This change refines the new manipulator tests so they check functionality through the adapter/registry surfaces, and strengthens OpenSpec task/apply prompts so future generated test work follows setup, execute, and verify structure instead of over-asserting implementation shape.

## What Changes

- Refactor low-value manipulator adapter tests into behavior-focused tests with clear setup, action, and desired outcome.
- Remove or collapse tests that only assert object construction details, private attributes, default metadata snapshots, or every minor backend command field.
- Preserve tests for real behavioral contracts while keeping OpenArm RS unit tests limited to non-control-binding behavior.
- Add explicit OpenSpec prompt guidance for writing behavior-focused unit tests and avoiding over-assertive object-shape tests.
- No public API, CLI, stream, hardware protocol, or runtime behavior changes are intended.

## Affected DimOS Surfaces

- Modules/streams: none at runtime; tests exercise manipulator adapter and registry surfaces.
- Blueprints/CLI: none.
- Skills/MCP: none.
- Hardware/simulation/replay: no hardware behavior changes; OpenArm RS unit tests avoid fake `can_motor_control` hardware behavior.
- Docs/generated registries: `openspec/schemas/dimos-capability/schema.yaml`; no generated registries expected.

## Capabilities

### New Capabilities
- `behavior-focused-test-guidelines`: Contributor and coding-agent expectations for writing unit tests that verify observable behavior rather than incidental object shape.

### Modified Capabilities
- `dm-motor-manipulator-adapters`: Clarify test coverage expectations for manipulator adapter behavior without changing adapter requirements.
- `manipulator-adapter-discovery`: Clarify test coverage expectations for lazy registry discovery without changing registry requirements.
- `openarm-rs-adapter-selection`: Clarify test coverage expectations for OpenArm RS adapter behavior without changing adapter selection requirements.

## Impact

Developers get a clearer, smaller test suite that fails when functionality regresses rather than when implementation details shift. OpenSpec-driven implementation agents get concrete guidance to avoid repeating the over-assertion mistake.

Compatibility risk is low because the change is limited to tests and documentation. Test/QA scope is the focused manipulator test set plus a documentation review of the new behavior-focused testing guidance.
