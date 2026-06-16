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

from pathlib import Path
import shutil
import subprocess

import pytest

from dimos.utils.git_asset_cache import GitAssetCache, GitAssetCacheWarning


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit(repo: Path, relative_path: str, contents: str, message: str) -> str:
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    _git(repo, "add", relative_path)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def local_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "upstream"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _commit(repo, "asset.txt", "v1", "initial")
    return repo


def test_clone_on_miss_resolves_local_git_repo_at_branch(local_repo: Path, tmp_path: Path) -> None:
    cache = GitAssetCache(tmp_path / "cache")

    checkout = cache.resolve(str(local_repo), "main")

    assert checkout.updated is True
    assert checkout.path.exists()
    assert (checkout.path / "asset.txt").read_text() == "v1"
    assert _git(checkout.path, "rev-parse", "--abbrev-ref", "HEAD") == "main"


def test_clean_cached_repo_updates_when_upstream_branch_changes(
    local_repo: Path, tmp_path: Path
) -> None:
    cache = GitAssetCache(tmp_path / "cache")
    first = cache.resolve(str(local_repo), "main")
    first_commit = _git(first.path, "rev-parse", "HEAD")
    second_commit = _commit(local_repo, "asset.txt", "v2", "update")

    second = cache.resolve(str(local_repo), "main")

    assert second.path == first.path
    assert second.updated is True
    assert _git(second.path, "rev-parse", "HEAD") == second_commit
    assert _git(second.path, "rev-parse", "HEAD") != first_commit
    assert (second.path / "asset.txt").read_text() == "v2"


def test_dirty_cached_repo_skips_update_and_preserves_local_edits(
    local_repo: Path, tmp_path: Path
) -> None:
    cache = GitAssetCache(tmp_path / "cache")
    checkout = cache.resolve(str(local_repo), "main")
    (checkout.path / "asset.txt").write_text("local edit")
    _commit(local_repo, "asset.txt", "upstream edit", "upstream update")

    with pytest.warns(GitAssetCacheWarning, match="local changes"):
        dirty_checkout = cache.resolve(str(local_repo), "main")

    assert dirty_checkout.skipped_dirty_update is True
    assert (dirty_checkout.path / "asset.txt").read_text() == "local edit"


def test_clean_cached_repo_returns_cached_checkout_when_fetch_fails(
    local_repo: Path, tmp_path: Path
) -> None:
    cache = GitAssetCache(tmp_path / "cache")
    checkout = cache.resolve(str(local_repo), "main")
    cached_commit = _git(checkout.path, "rev-parse", "HEAD")
    shutil.rmtree(local_repo)

    with pytest.warns(GitAssetCacheWarning, match="using cached checkout"):
        fallback = cache.resolve(str(local_repo), "main")

    assert fallback.used_cached_fallback is True
    assert fallback.path == checkout.path
    assert _git(fallback.path, "rev-parse", "HEAD") == cached_commit
    assert (fallback.path / "asset.txt").read_text() == "v1"
