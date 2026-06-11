## 1. Implementation

- [x] 1.1 Extract or create a sidecar runtime entrypoint that can run the existing LCM catalog, selected-only Rerun logging path, selector API, Reflex selector frontend/backend, and Rerun web viewer without being embedded in a DimOS blueprint.
- [x] 1.2 Add robust local port allocation for the monitor-owned Rerun gRPC/proxy, Rerun web viewer, selector API, selector frontend, and Reflex backend services; fail loudly for any explicit port conflict.
- [x] 1.3 Add `dimos topic monitor` under the existing topic CLI namespace, with foreground lifecycle, Ctrl-C/SIGTERM cleanup, active-run metadata lookup, no-run bus-only mode, and clear printed URLs.
- [x] 1.4 Implement automatic browser opening for the selector UI by default, plus a documented `--no-open` option and non-fatal fallback when browser opening fails.
- [x] 1.5 Ensure the monitor discovers all visible LCM topics by default and preserves selected-only decode/convert/log semantics for the monitor's own Rerun viewer.
- [x] 1.6 Ensure missing visualization dependencies fail with an actionable `uv sync --extra visualization` message.
- [x] 1.7 Remove selector-specific wiring from normal/simulation blueprints and remove or deprecate `vis_module_with_selector(...)` as a documented/public composition path.
- [x] 1.8 Keep a dedicated hardware-free selector demo capability and update it if needed so it remains a self-contained smoke/demo path.
- [x] 1.9 Regenerate `dimos/robot/all_blueprints.py` if blueprint exports or demo registry inputs change.

## 2. Documentation

- [x] 2.1 Update `docs/usage/visualization.md` to make `dimos topic monitor` the recommended selector workflow and document bus-only mode, active-run context, auto-open, isolated ports, selected-only logging, and v1 generic LCM rendering scope.
- [x] 2.2 Update CLI docs where `dimos topic` subcommands are documented, including examples for `dimos topic monitor` and `--no-open`.
- [x] 2.3 Update contributor guidance for sidecar lifecycle, generated Reflex artifacts, blueprint wiring removal, and registry regeneration expectations.
- [x] 2.4 Update coding-agent guidance only if implementation introduces new generated artifacts or cleanup rules not already covered by contributor docs.

## 3. Verification

- [x] 3.1 Run `openspec validate add-topic-monitor-sidecar`.
- [x] 3.2 Run focused unit tests for port allocation, run metadata/bus-only selection, connected Rerun URL generation, dependency error messages, and selected-only monitor bridge behavior.
- [x] 3.3 Run focused CLI tests or smoke checks for `dimos topic monitor --no-open` startup and Ctrl-C/SIGTERM cleanup.
- [x] 3.4 Run `uv run reflex compile` for the selector app after any UI/runtime changes.
- [x] 3.5 Run focused selector regression tests, including Reflex state/event tests, Rerun viewer URL tests, topic catalog tests, and selected-only bridge tests.
- [x] 3.6 Run `CI=true uv run pytest dimos/robot/test_all_blueprints_generation.py -q` if blueprint registry inputs or generated registry output change.
- [x] 3.7 Run lint/format checks for changed Python files.
- [x] 3.8 Run docs validation from `docs.md`, including `doclinks` and `md-babel-py` for changed user-facing docs.
- [x] 3.9 Manually QA `dimos topic monitor` with an active normal DimOS run: confirm browser opens, topics appear, stage/apply logs selected data to the monitor viewer, clear/apply stops monitor logging, and Ctrl-C cleans up child processes.
- [x] 3.10 Manually QA no-run bus-only mode with a manual or demo LCM publisher: confirm the monitor starts without an active run and catalogs visible traffic.
- [x] 3.11 Manually QA port isolation by starting the monitor while default Rerun/selector ports are occupied or an embedded visualization is running, confirming the monitor chooses isolated ports and owns its viewer.
