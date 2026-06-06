## User-Facing Docs

- Update `docs/capabilities/manipulation/openarm_integration.md` to describe two OpenArm adapter paths:
  - `openarm`: stable in-tree SocketCAN OpenArm adapter.
  - `openarm_rs`: explicit Rust-backed / `can_motor_control` binding path for OpenArm.
- Replace `dm_motor_arm` and `coordinator-dm-motor-openarm*` user-facing references with `openarm_rs` and the renamed blueprint names.
- Clarify that existing OpenArm blueprints continue to use `adapter_type="openarm"` unless a user explicitly selects the binding-backed path.
- Clarify staged validation for the `openarm_rs` path: binding install, mock/vcan, one-arm state read, low-rate hold/gravity compensation, then trajectory validation.

## Contributor Docs

- Update contributor-facing manipulation docs only if they currently recommend `dm_motor_arm` as a generic Damiao extension point.
- If `dimos/hardware/manipulators/README.md` is changed, describe `damiao/specs.py` as typed metadata/validation for Damiao-based adapters and `openarm_rs` as an OpenArm-specific binding-backed adapter.

## Coding-Agent Docs

- No AGENTS.md update is expected.
- Update `docs/coding-agents/` only if existing guidance mentions the `dm_motor_arm` adapter key or recommends editing the original `openarm` adapter for binding-backed OpenArm work.

## Doc Validation

- Run docs link validation if links or blueprint names are changed in user-facing docs.
- Run `md-babel-py run docs/capabilities/manipulation/openarm_integration.md` if executable code blocks are added or changed.
- If only prose/table names change and no executable blocks are touched, focused review plus repository docs validation is sufficient.

## No Docs Needed

Documentation changes are needed because this cleanup renames user-facing adapter and blueprint selection surfaces and clarifies hardware bring-up guidance.
