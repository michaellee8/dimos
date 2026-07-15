# Copyright 2026 Dimensional Inc.

from __future__ import annotations

from dimos.core.external_python_runtime import ExternalPythonRuntime


class ExternalPythonWorker:
    """Private one-process worker for one external declaration."""

    def __init__(self, declaration: type, global_config: object, kwargs: dict[str, object]) -> None:
        self.runtime = ExternalPythonRuntime(declaration, global_config, kwargs)
        self.declaration = declaration

    def start(self) -> None:
        self.runtime.start()

    def stop(self) -> None:
        self.runtime.stop()

    @property
    def pid(self) -> int | None:
        return self.runtime.pid

    def diagnostics(self) -> str:
        return self.runtime.diagnostics()
