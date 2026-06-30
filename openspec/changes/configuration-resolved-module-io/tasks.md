## 1. Core IO Contract API

- [ ] 1.1 Add public `StreamDecl` and `ModuleIOContract` types with stream-name uniqueness validation.
- [ ] 1.2 Add shared validation helpers so construction-time and resolution-time checks use the same rules.
- [ ] 1.3 Add default `Module.io_contract(config)` that returns annotation-derived IO.
- [ ] 1.4 Add tests proving annotation-only modules resolve the same streams as before.

## 2. Module Stream Registries

- [ ] 2.1 Add explicit internal input/output registries to `Module`.
- [ ] 2.2 Register annotated streams in the registries while preserving existing annotated attributes.
- [ ] 2.3 Instantiate custom configuration-resolved streams into registries without creating arbitrary attributes.
- [ ] 2.4 Update `inputs`, `outputs`, `set_transport()`, `connect_stream()`, and related stream lookup paths to use registries.
- [ ] 2.5 Add tests proving configuration-resolved streams are available through `self.inputs` and `self.outputs`.

## 3. Resolved Blueprint Planning

- [ ] 3.1 Add an internal resolved module plan that stores final module config, final kwargs, and resolved IO contract.
- [ ] 3.2 Resolve final per-module config before stream conflict checks, deployment, and wiring in `build()`.
- [ ] 3.3 Resolve final per-module config before stream conflict checks, deployment, and wiring in blueprint load paths.
- [ ] 3.4 Pass final per-module kwargs into worker deployment instead of late-merging `blueprint_args` inside the worker manager.
- [ ] 3.5 Add tests proving CLI/build overrides affect resolved IO before wiring.

## 4. Remapping and Conflict Validation

- [ ] 4.1 Validate remappings against resolved stream names.
- [ ] 4.2 Fail blueprint resolution when a remapping references a stream absent from the resolved IO contract.
- [ ] 4.3 Preserve existing same-name/same-type autoconnect behavior after remapping.
- [ ] 4.4 Preserve existing same-name/different-type conflict behavior after remapping.
- [ ] 4.5 Add tests for valid remapping, stale remapping, autoconnect, and type-conflict scenarios.

## 5. Teaching Demo

- [ ] 5.1 Add `examples/configuration_resolved_io.py` demonstrating a module whose config selects between two different IO shapes.
- [ ] 5.2 Document how to run the demo in the example file or nearby README text.
- [ ] 5.3 Add a verification command for the demo and ensure it passes locally.

## 6. Verification Gates

- [ ] 6.1 Run the focused configuration-resolved IO unit tests.
- [ ] 6.2 Run the existing affected core blueprint/module tests.
- [ ] 6.3 Run the teaching demo successfully.
- [ ] 6.4 Run the standard project test command if practical for the implementation scope.
