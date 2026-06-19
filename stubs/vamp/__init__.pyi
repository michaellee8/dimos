from collections.abc import Callable, Sequence

import numpy as np
from numpy.typing import NDArray

from . import baxter as baxter, fetch as fetch, panda as panda, sphere as sphere, ur5 as ur5

class Path:
    def numpy(self) -> NDArray[np.float64]: ...

class Environment:
    def add_sphere(self, sphere: Sphere) -> None: ...
    def add_cuboid(self, cuboid: Cuboid) -> None: ...
    def add_capsule(self, capsule: Cylinder) -> None: ...

class Sphere:
    def __init__(self, center: Sequence[float], radius: float) -> None: ...

class Cuboid:
    def __init__(
        self,
        center: Sequence[float],
        euler_xyz: Sequence[float],
        half_extents: Sequence[float],
    ) -> None: ...

class Cylinder:
    def __init__(
        self,
        center: Sequence[float],
        euler_xyz: Sequence[float],
        radius: float,
        length: float,
    ) -> None: ...

class PlanningResult:
    solved: bool
    path: Path
    iterations: int

class PlannerSettings:
    pass

class SimplifySettings:
    pass

class Sampler:
    pass

class RobotModule:
    __name__: str
    def halton(self) -> Sampler: ...
    def validate(
        self,
        configuration: Sequence[float],
        environment: Environment,
        check_bounds: bool,
    ) -> bool: ...
    def validate_motion(
        self,
        configuration_in: Sequence[float],
        configuration_out: Sequence[float],
        environment: Environment,
        check_bounds: bool,
    ) -> bool: ...
    def eefk(self, configuration: Sequence[float]) -> NDArray[np.float64]: ...
    def simplify(
        self,
        path: Path,
        environment: Environment,
        settings: SimplifySettings,
        sampler: Sampler,
    ) -> PlanningResult: ...

PlannerFunction = Callable[
    [Sequence[float], Sequence[float], Environment, PlannerSettings, Sampler],
    PlanningResult,
]

def configure_robot_and_planner_with_kwargs(
    robot_name: str,
    planner_name: str,
    max_iterations: int,
) -> tuple[RobotModule, PlannerFunction, PlannerSettings, SimplifySettings]: ...
