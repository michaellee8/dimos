## 1. Implementation

- [x] 1.1 Audit `dimos/hardware/manipulators/openarm_rs/test_adapter.py`, `dimos/hardware/manipulators/openarm/test_adapter.py`, `dimos/hardware/manipulators/damiao/test_base_adapter.py`, and `dimos/hardware/manipulators/test_registry.py` for tests that only assert construction shape, private fields, full metadata snapshots, or unrelated backend command details.
- [x] 1.2 Delete or collapse tests whose behavior cannot be stated clearly in the test name.
- [x] 1.3 Rewrite retained manipulator adapter tests so each follows setup, execute functionality, and check desired result through public adapter or fake-backend observations.
- [x] 1.4 Preserve behavior coverage while limiting OpenArm RS unit tests to non-control-binding metadata, registration, limits, and validation behavior.
- [x] 1.5 Keep safety-critical command assertions only when they are the smallest meaningful proof of the named safety behavior.

## 2. OpenSpec Prompt Guidance

- [x] 2.1 Remove the behavior-focused testing section from `docs/coding-agents/testing.md`.
- [x] 2.2 Update `openspec/schemas/dimos-capability/schema.yaml` tasks instructions with behavior-focused testing guidance.
- [x] 2.3 Update `openspec/schemas/dimos-capability/schema.yaml` apply instructions so implementation agents avoid low-value object-shape tests.

## 3. Verification

- [x] 3.1 Run `openspec validate improve-behavior-focused-test-guidelines`.
- [x] 3.2 Run `uv run pytest dimos/hardware/manipulators/openarm_rs/test_adapter.py dimos/hardware/manipulators/openarm/test_adapter.py dimos/hardware/manipulators/damiao/test_base_adapter.py dimos/hardware/manipulators/test_registry.py -q`.
- [x] 3.3 Run `openspec validate improve-behavior-focused-test-guidelines` after OpenSpec prompt changes.
- [x] 3.4 Manually QA the test-quality change by reviewing the final changed tests and confirming each retained test has an explicit setup, execution step, and desired behavioral result.
