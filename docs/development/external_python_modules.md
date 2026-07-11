---
title: "Developing External Python Modules"
---

# Temporary external Python deployment launcher

The `dimos.core.deployment.launcher` module is a contributor integration harness
for local packaged-Python modules. It is not a stable public replacement for
`dimos run` and does not write a deployment registry.

Useful QA commands for the example package:

```bash
uv run python -m dimos.core.deployment.launcher plan examples.external_python_module.deployment:deployment_spec
uv run python -m dimos.core.deployment.launcher prepare examples.external_python_module.deployment:deployment_spec
timeout 10s uv run python -m dimos.core.deployment.launcher run examples.external_python_module.deployment:deployment_spec
```

`run` intentionally blocks after the coordinator reaches steady state, so a
timeout wrapper is expected for manual smoke checks.

`prepare` creates or updates the external package environment through a local
target session without launching `ExternalWorker` or the runtime. Uv-only
packages run `uv sync` from `python/`; packages with `python/pixi.toml` run
`pixi run uv sync` and then launch with `pixi run uv run python ...`.

`run` is temporarily `plan + idempotent prepare + external-worker bootstrap +
runtime launch`. The external worker owns packaged runtime subprocesses and
readiness waits; `WorkerManagerExternal` must not directly spawn runtime
entrypoints.

Troubleshooting notes:

- Missing `python/pyproject.toml` fails during prepare before launch.
- Multiple known implementation conventions (`python/`, `rust/`, `cpp/`) fail
  during planning because v1 supports only one sibling implementation.
- Duplicate active instances of the same external declaration class fail during
  planning because external RPC identity is not instance-scoped yet.
- Missing `uv` or `pixi` appears as a local tool launch failure; Pixi is used
  only when `python/pixi.toml` exists.
- Startup timeout means the external process did not answer the declared
  `dimos_ready` RPC before `readiness_timeout_s`. Check the raised startup
  context, package import paths, and runtime class declaration/`Module`
  inheritance.
- Dependency-isolation examples should import runtime-only packages from the
  packaged implementation, not from the coordinator-visible declaration.
- Generated local artifacts such as `examples/external_python_module/python/.venv`,
  `uv.lock`, and `__pycache__` are test/runtime byproducts and should not be
  committed unless intentionally added later.
