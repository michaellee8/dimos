# Local External Python Modules

## Outcome

Allow a DimOS module author to run a separately packaged local Python implementation in its own managed dependency environment while it remains an ordinary Blueprint participant. Authors declare one `module:Class` implementation import reference; the contract is a normal import from the existing DimOS distribution, not a separate package or `PYTHONPATH` source. Blueprint composition, typed streams, RPC, skills, module references, configuration, and restart behavior remain unchanged.

## Problem

An isolated Python dependency environment currently requires machinery aimed at future remote deployment. The local use case does not need targets, sessions, deployment plans, artifact transfer, or a second public lifecycle model. It needs a deterministic runtime-project convention and a private worker path that preserves the existing coordinator contract.

## System Shape

**Primary shape: pipeline.** The implementation crosses the declaration, worker, runtime bootstrap, and normal coordinator lifecycle.

```text
Blueprint declaration
  configuration + In/Out streams + RPC/skills + module references
  implementation = "package.module:RuntimeClass"
                     │
                     ▼
ModuleCoordinator deploys through WorkerManagerExternalPython
                     │
                     ▼
Private external-Python worker
  1. resolves <declaration-dir>/python/
  2. validates pyproject.toml and detects optional pixi.toml
  3. prepares the managed runtime environment
  4. launches a bootstrap in that environment
                     │
                     ▼
Runtime bootstrap
  imports implementation → validates declaration contract
  → serves RPC under declaration identity
                     │
                     ▼
Normal coordinator lifecycle
  connect streams → inject module references → build → start
```

The worker returns the existing coordinator-facing RPC proxy shape. Nothing above `WorkerManagerExternalPython` needs to know that the implementation uses a separate Python environment.

## Final API Shape

```text
my_feature/
├── declaration.py
└── python/
    ├── pyproject.toml
    ├── pixi.toml                   # optional
    └── my_feature_runtime/
        └── runtime.py
```

```python
# declaration.py — lives in the host DimOS environment
class MyFeature(ExternalPythonModule):
    implementation = "my_feature_runtime.runtime:MyFeatureRuntime"

    input: In[Image]
    output: Out[Result]
    _dependency: DependencySpec

    @skill
    def enable(self, enabled: bool) -> str:
        """Enable or disable this feature."""
        ...


# python/my_feature_runtime/runtime.py — lives in the runtime project
class MyFeatureRuntime(MyFeature):
    def start(self) -> None: ...
    def _process(self, image: Image) -> None: ...


# blueprint.py — no external-runtime API
stack = autoconnect(MyFeature.blueprint(), consumer.blueprint())
```

`ExternalPythonModule` is the declaration base. Its only external-runtime field is `implementation`; all normal module configuration, streams, RPC methods, skills, and references stay on the declaration. The runtime extends that declaration, so the bootstrap can validate one contract and serve it under the `MyFeature` identity.

At deployment, the worker resolves `declaration.py`'s sibling `python/` project. `pyproject.toml` is mandatory and declares all runtime Python dependencies. With no `pixi.toml`, DimOS prepares and runs the project through uv. With one, it runs uv through Pixi; Pixi provides the outer tool environment and does not replace the uv project. `PYTHONPATH` is not used. Preparation, import, or contract failures abort deployment before module startup.
