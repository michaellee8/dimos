## User-Facing Docs

- Add or update `docs/usage/modules.md` with a short section explaining that DimOS can run local packaged-Python external modules through a deployment spec while preserving declared streams, lifecycle, RPCs, skills, and module refs.
- Add a focused guide under `docs/usage/` for authoring a local packaged-Python external module:
  - lightweight `ExternalModule` declaration imported by the coordinator;
  - module-owned `implementation = "package.module:RuntimeClass"` reference;
  - packaged runtime implementation that is a real `Module` subclass and subclasses the declaration;
  - convention discovery from the declaration class file to a sibling `python/` implementation directory;
  - supported project layouts: `python/pyproject.toml` and optional `python/pixi.toml`;
  - supported launch behavior: `uv run python ...` or `pixi run uv run python ...`;
  - `DeploymentSpec` usage with `modules: dict[type[ModuleBase], ModuleDeployment]`, default local policy for external modules, and clear failure for plain blueprints containing `ExternalModule` declarations;
  - temporary launcher usage for `plan`, `prepare`, and `run`.
- Link to `examples/external_python_module/` as the canonical runnable reference for declaration/runtime split, deployment spec references, convention layout, and declared RPC calls.
- Document that the temporary launcher is not a stable public replacement for `dimos run`, `dimos deploy`, or a prepared-plan registry.
- Document that duplicate active instances of the same external declaration class are rejected in v1 because external RPC identity is not instance-scoped yet.

## Contributor Docs

- Update `docs/development/dimos_run.md` or add a development note describing the temporary deployment launcher and how it differs from the stable DimOS CLI.
- Add contributor notes for testing local packaged-Python external modules, including expected missing-tool, missing-file, multiple-implementation-directory, missing-implementation-reference, duplicate-instance, and readiness-timeout failures.
- Document the local structural topology: `ModuleCoordinator -> WorkerManagerExternal -> TargetSession -> ExternalWorkerClient -> ExternalWorker -> packaged-Python runtime entrypoint`.
- Document the phase split:
  - `plan` validates and reports without mutation;
  - `prepare` uses target sessions and does not launch `ExternalWorker` or runtime handles;
  - temporary `run` performs idempotent prepare, bootstraps `ExternalWorker`, launches runtime handles, waits for readiness, and wires the coordinator.
- Document how external worker and runtime logs integrate with existing DimOS run logging and how startup failure output tails appear in errors.
- Document how to run `examples/external_python_module/` through the temporary launcher in `plan`, `prepare`, and `run` modes without setting `PYTHONPATH` from the repository root.

## Coding-Agent Docs

- Update `docs/coding-agents/` or `AGENTS.md` if implementation introduces new conventions that coding agents must follow when adding external modules.
- Candidate guidance:
  - do not import heavy external runtime dependencies in coordinator-visible declarations;
  - put module implementation identity on the `ExternalModule` declaration, not in deployment policy;
  - use the sibling `python/` convention for packaged-Python implementations;
  - use `DeploymentSpec` for any graph that contains an `ExternalModule`;
  - use declared RPCs/skills/refs only;
  - do not rely on arbitrary Python object passthrough, pickled live class objects, or direct subprocess launch from `WorkerManagerExternal`;
  - after adding public blueprints, regenerate `dimos/robot/all_blueprints.py` with the existing blueprint generation test.

## Doc Validation

- Run docs link validation if available for changed markdown files.
- For executable Python snippets in docs, run the repository's documented markdown Python validation command if those snippets are marked executable.
- Run the focused external deployment tests referenced in `tasks.md` to ensure docs examples match behavior.
- Run the `examples/external_python_module/` package through the temporary launcher as manual QA.

## No Docs Needed

Documentation changes are needed because this introduces a new developer-facing module authoring and deployment path, even though it does not add a stable public CLI command yet.
