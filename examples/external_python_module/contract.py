"""Host-side declaration contract for the external Python example."""

from __future__ import annotations

from typing import Protocol

from dimos.agents.annotation import skill
from dimos.core.core import rpc
from dimos.core.external_python_module import ExternalPythonModule
from dimos.core.stream import In, Out
from dimos.msgs.std_msgs.Int32 import Int32
from dimos.spec.utils import Spec


class ExampleExternal(ExternalPythonModule):
    """Declaration implemented by the isolated sibling runtime project."""

    implementation = "example_external.runtime:ExampleExternalRuntime"

    value: In[Int32]
    doubled: Out[Int32]

    @rpc
    def get_multiplier(self) -> int:
        """Return the multiplier used by the external implementation."""
        raise NotImplementedError

    @skill
    def set_multiplier(self, multiplier: int) -> str:
        """Set the multiplier used for values received on ``value``."""
        raise NotImplementedError


class ExampleExternalSpec(Spec, Protocol):
    """RPC contract consumed by a regular DimOS module."""

    @rpc
    def get_multiplier(self) -> int: ...
