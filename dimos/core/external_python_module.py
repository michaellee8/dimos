# Copyright 2026 Dimensional Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

from typing import ClassVar

from dimos.core.module import Deployment, Module


class ExternalPythonModule(Module):
    """A normal DimOS module whose implementation lives in a local Python project."""

    deployment: ClassVar[Deployment] = "external-python"
    implementation: ClassVar[str]
