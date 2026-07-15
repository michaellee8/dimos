# Copyright 2026 Dimensional Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from typing import cast

from dimos.core.coordination.blueprints import autoconnect
from dimos.core.coordination.module_coordinator import ModuleCoordinator
from dimos.core.core import rpc
from dimos.core.module import Module
from dimos.core.rpc_client import RPCClient
from examples.external_python_module.contract import ExampleExternal, ExampleExternalSpec


class ExampleConsumer(Module):
    """A normal module that holds a reference to the external declaration."""

    _external: ExampleExternalSpec

    @rpc
    def start(self) -> None:
        super().start()
        print("external multiplier:", self._external.get_multiplier())


def run_example() -> None:
    """Run the example's build, RPC, restart, and deterministic shutdown path."""
    coordinator = ModuleCoordinator.build(
        autoconnect(
            ExampleExternal.blueprint(),
            ExampleConsumer.blueprint(),
        )
    )
    proxies = [cast("RPCClient", proxy) for proxy in coordinator._deployed_modules.values()]
    try:
        external = coordinator.get_instance(ExampleExternal)
        print("external multiplier:", external.get_multiplier())

        coordinator.restart_module(ExampleExternal, reload_source=False)
        restarted = coordinator.get_instance(ExampleExternal)
        proxies.append(restarted)
        print("restarted external multiplier:", restarted.get_multiplier())
    finally:
        coordinator.stop()
        for proxy in proxies:
            proxy.stop_rpc_client()
        for transport in coordinator._transport_registry.values():
            transport.stop()


if __name__ == "__main__":
    run_example()
