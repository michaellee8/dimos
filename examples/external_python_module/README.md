# External Python Module Example

Plan or prepare from the repository root with:

```bash
uv run python -m dimos.core.deployment.launcher plan examples.external_python_module.deployment:deployment_spec
uv run python -m dimos.core.deployment.launcher prepare examples.external_python_module.deployment:deployment_spec
```

This example includes `python/pixi.toml`, so `prepare` runs `pixi run uv sync`
inside the external package through a local target session. Prepare does not start
an `ExternalWorker` or runtime process.

Run keeps the coordinator alive until interrupted. It performs temporary
`plan + prepare + external-worker bootstrap + runtime launch` until DimOS has a
prepared-plan registry:

```bash
uv run python -m dimos.core.deployment.launcher run examples.external_python_module.deployment:deployment_spec
```

The declaration in `deployment.py` is coordinator-visible and owns the runtime
implementation identity through `ExampleExternalDeclaration.implementation`. The
runtime in `python/example_external/runtime.py` subclasses the declaration and
`Module` and serves the declared `greet` RPC from the packaged Python project.

The example also declares a local stream surface, config value, a normal Python
`ExampleClient` that calls the external module by declared RPC, and a module ref
to the normal Python `ExampleHelper`; `greet_with_helper` proves the external
runtime receives a declared RPC proxy for that ref rather than a live object
instance.

The external runtime imports `humanize`, which is intentionally declared only in
`python/pyproject.toml`. The coordinator-side declaration in `deployment.py` does
not import `humanize`, proving that heavy or unusual runtime dependencies stay in
the external package environment.
