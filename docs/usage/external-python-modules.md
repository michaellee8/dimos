---
title: "External Python Modules"
---

# Local packaged-Python external modules

DimOS can run a local packaged-Python module outside the coordinator's Python
environment while keeping the coordinator-visible module shape lightweight. The
coordinator imports an `ExternalModule` declaration that declares streams,
config, lifecycle RPCs, other `@rpc` methods, skills, module refs, and
`implementation = "package.module:RuntimeClass"`. The packaged runtime class
subclasses that declaration and `Module` and serves the existing DimOS RPC
backend.

The example package pins `humanize` only in the external `python/pyproject.toml`.
The coordinator imports the declaration/spec without importing `humanize`; the
external runtime imports it and returns a formatted value through RPC and stream
roundtrip paths. This proves dependency isolation and the intended deployment
structure: `ModuleCoordinator -> WorkerManagerExternal -> TargetSession ->
ExternalWorker -> packaged-Python runtime entrypoint`.

Supported package layouts are:

- `python/pyproject.toml` → launched as `uv run python ...`
- `python/pyproject.toml` plus `python/pixi.toml` → launched as
  `pixi run uv run python ...`

`prepare` materializes the external package environment without launching the
runtime. Uv-only packages run `uv sync`; Pixi+uv packages run
`pixi run uv sync`.

Use a module-level `DeploymentSpec` and the temporary launcher from the
repository root:

```bash
uv run python -m dimos.core.deployment.launcher plan examples.external_python_module.deployment:deployment_spec
uv run python -m dimos.core.deployment.launcher prepare examples.external_python_module.deployment:deployment_spec
uv run python -m dimos.core.deployment.launcher run examples.external_python_module.deployment:deployment_spec
```

This launcher is an integration harness, not a stable replacement for `dimos
run` or a deployment registry. The canonical runnable reference is
`examples/external_python_module/`.

External module proxies expose declared `@rpc` methods only. Arbitrary Python
object access and live instance passthrough across the package boundary are not
supported.

A plain blueprint containing an `ExternalModule` fails clearly. Use
`ModuleCoordinator.build_deployment(DeploymentSpec(...))` so planning can carry
the module policy, convention-discovered package, target, external worker route,
and serialized launch envelope.
