# Copyright 2025-2026 Dimensional Inc.
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

import os
from pathlib import Path

import pytest

from dimos.robot.assets.declarations import ROBOT_ASSETS
from dimos.robot.assets.git_cache import GitAssetCache, GitAssetCheckout
from dimos.robot.assets.manager import (
    ArtifactRole,
    RobotAssetDeclaration,
    RobotAssetError,
    RobotAssetManager,
    RobotAssetPackagePath,
    RobotAssetPath,
    robot_asset_package_paths,
    robot_asset_xacro_args,
    set_default_robot_asset_manager,
)


class RecordingGitAssetCache(GitAssetCache):
    def __init__(self, checkout_path: Path) -> None:
        self.checkout_path = checkout_path
        self.resolve_calls: list[tuple[str, str]] = []

    def resolve(self, repo_url: str, ref: str) -> GitAssetCheckout:
        self.resolve_calls.append((repo_url, ref))
        return GitAssetCheckout(path=self.checkout_path, repo_url=repo_url, ref=ref)


@pytest.fixture()
def asset_manager(tmp_path: Path) -> tuple[RobotAssetManager, RecordingGitAssetCache]:
    checkout = tmp_path / "checkout"
    (checkout / "robots" / "testbot").mkdir(parents=True)
    (checkout / "robots" / "testbot" / "model.urdf").write_text("<robot name='testbot'/>")
    (checkout / "packages" / "testbot_description").mkdir(parents=True)
    (checkout / "packages" / "testbot_description" / "package.xml").write_text("<package/>")

    declaration = RobotAssetDeclaration(
        model="testbot",
        repo_url="https://example.invalid/testbot.git",
        ref="main",
        artifacts={"urdf": "robots/testbot/model.urdf"},
        package_roots={"testbot_description": "packages/testbot_description"},
    )
    git_cache = RecordingGitAssetCache(checkout)
    manager = RobotAssetManager(
        {"testbot": declaration},
        git_cache=git_cache,
    )
    return manager, git_cache


def test_resolves_artifact_paths_and_package_roots(
    asset_manager: tuple[RobotAssetManager, RecordingGitAssetCache],
) -> None:
    manager, _git_cache = asset_manager

    artifact = manager.resolve_artifact("testbot", ArtifactRole.URDF)
    package_root = manager.resolve_package_root("testbot", "testbot_description")

    assert artifact.name == "model.urdf"
    assert artifact.read_text() == "<robot name='testbot'/>"
    assert package_root.name == "testbot_description"
    assert (package_root / "package.xml").exists()


def test_unknown_model_and_undeclared_artifact_role_raise(
    asset_manager: tuple[RobotAssetManager, RecordingGitAssetCache],
) -> None:
    manager, _git_cache = asset_manager

    with pytest.raises(RobotAssetError, match="Unknown robot asset model 'missing'"):
        manager.resolve_artifact("missing", ArtifactRole.URDF)

    with pytest.raises(RobotAssetError, match="does not declare artifact role 'mjcf'"):
        manager.resolve_artifact("testbot", ArtifactRole.MJCF)


def test_lazy_asset_paths_defer_checkout_until_path_operations(
    asset_manager: tuple[RobotAssetManager, RecordingGitAssetCache],
) -> None:
    manager, git_cache = asset_manager

    artifact_path = RobotAssetPath("testbot", ArtifactRole.URDF, manager=manager)
    package_path = RobotAssetPackagePath("testbot", "testbot_description", manager=manager)

    assert git_cache.resolve_calls == []

    artifact_string = str(artifact_path)
    assert artifact_string.endswith("robots/testbot/model.urdf")
    assert git_cache.resolve_calls == [("https://example.invalid/testbot.git", "main")]

    assert os.fspath(package_path).endswith("packages/testbot_description")
    assert git_cache.resolve_calls == [
        ("https://example.invalid/testbot.git", "main"),
        ("https://example.invalid/testbot.git", "main"),
    ]

    assert artifact_path.exists()
    assert (package_path / "package.xml").exists()


def test_default_manager_can_be_injected(
    asset_manager: tuple[RobotAssetManager, RecordingGitAssetCache],
) -> None:
    manager, _git_cache = asset_manager

    set_default_robot_asset_manager(manager)
    try:
        assert robot_asset_package_paths("testbot")["testbot_description"].exists()
        assert robot_asset_xacro_args("testbot") == {}
    finally:
        set_default_robot_asset_manager(None)


def test_robot_asset_declarations_are_static_and_consistent() -> None:
    assert set(ROBOT_ASSETS) == {"a750", "piper", "xarm6", "xarm7"}
    known_roles = {role.value for role in ArtifactRole} | {"urdf_ik"}

    for key, declaration in ROBOT_ASSETS.items():
        assert key == declaration.model
        assert declaration.repo_url
        assert declaration.ref
        assert declaration.artifacts

        for role, relative_path in declaration.artifacts.items():
            assert role in known_roles
            assert relative_path
            assert not Path(relative_path).is_absolute()

        for package_name, relative_path in declaration.package_roots.items():
            assert package_name
            assert relative_path
            assert not Path(relative_path).is_absolute()
