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

"""Replay a pcap through fastlio2 with per-section timing instrumentation.

Counterpart to live_record_with_timing.py — same orchestrator+worker
shape, same per-section timing summaries on stderr (routed through the
NativeModule logger), but with the binary in REPLAY mode pointed at a
hardcoded pcap path. Lets us read out the same `[timing]` lines for a
replay run and diff them against the live baseline.

By default points at the most recent ``live_record_with_timing``
attempt_000 pcap so both modes process bit-identical wire data.

Run from the dimos venv:

    cd ~/repos/dimos
    source .venv/bin/activate
    python -m dimos.hardware.sensors.lidar.fastlio2.tools.replay_with_timing
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from dimos.core.module import Module, ModuleConfig
from dimos.core.stream import In
from dimos.msgs.nav_msgs.Odometry import Odometry

# ---------------- Configuration (hardcoded; bump and recommit to change) -----

PCAP_PATH = Path("/media/dimos/USB/fastlio_recordings/live_timing_records/attempt_000/mid360.pcap")

RUNS_ROOT = Path("/media/dimos/USB/fastlio_recordings/replay_timing_records")

# Plumbing-only env var the worker reads.
_ATTEMPT_DIR_ENV = "_REPLAY_TIMING_ATTEMPT_DIR"

# Hard ceiling on a single run's wall-clock. The un-hoisted binary on
# this box runs ~5-20x slower than realtime depending on the pcap; 600 s
# is enough to fully process the ~30 s pcap that the live tool records.
MAX_WALL_SEC = 600.0


# ---------------- attempt-dir auto-increment --------------------------------


def _next_attempt_dir() -> Path:
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    existing = sorted(p.name for p in RUNS_ROOT.iterdir() if p.name.startswith("attempt_"))
    n = 0
    for name in existing:
        try:
            n = max(n, int(name.split("_", 1)[1]) + 1)
        except ValueError:
            continue
    attempt = RUNS_ROOT / f"attempt_{n:03d}"
    attempt.mkdir()
    return attempt


def _commit_hash() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(Path(__file__).resolve().parents[6]), "rev-parse", "HEAD"],
            text=True,
        ).strip()
    except subprocess.CalledProcessError:
        return "unknown"


# ---------------- Rec module (module-level so multiprocessing can pickle) --


class RecConfig(ModuleConfig):
    """Configures Rec with the per-attempt sqlite db path."""

    db_path: str = ""


_EPS = 1e-9


class Rec(Module):
    """Mirror replay FastLio2 odometry into a SqliteStore at config.db_path."""

    config: RecConfig
    fastlio_odometry: In[Odometry]
    _last_o: float = 0.0

    async def main(self) -> AsyncIterator[None]:
        from dimos.memory2.store.sqlite import SqliteStore

        self._store = SqliteStore(path=self.config.db_path)
        self._os = self._store.stream("fastlio_odometry", Odometry)
        yield
        self._store.stop()

    async def handle_fastlio_odometry(self, v: Odometry) -> None:
        ts = max(getattr(v, "ts", None) or time.time(), self._last_o + _EPS)
        self._last_o = ts
        pose = getattr(v, "pose", None)
        pose_inner = getattr(pose, "pose", None) if pose is not None else None
        self._os.append(v, ts=ts, pose=pose_inner)


# ---------------- orchestrator (parent) -------------------------------------


def _orchestrate() -> int:
    if not PCAP_PATH.exists():
        print(f"[replay_timing] missing pcap: {PCAP_PATH}", file=sys.stderr)
        return 2
    attempt_dir = _next_attempt_dir()
    stdout_path = attempt_dir / "stdout.txt"
    stderr_path = attempt_dir / "stderr.txt"
    meta = {
        "attempt_dir": str(attempt_dir),
        "pcap_path": str(PCAP_PATH),
        "commit": _commit_hash(),
        "started_at": time.time(),
    }
    print(f"[replay_timing] attempt {attempt_dir.name}  commit {meta['commit'][:8]}", flush=True)
    t0 = time.time()
    env = {**os.environ, _ATTEMPT_DIR_ENV: str(attempt_dir)}
    with stdout_path.open("w") as out, stderr_path.open("w") as err:
        rc = subprocess.run(
            [sys.executable, "-m", __spec__.name, "--worker"],
            stdout=out,
            stderr=err,
            env=env,
            check=False,
        ).returncode
    meta["finished_at"] = time.time()
    meta["wall_sec"] = meta["finished_at"] - t0
    meta["worker_rc"] = rc
    (attempt_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    print(
        f"[replay_timing] done attempt {attempt_dir.name} rc={rc} wall={meta['wall_sec']:.1f}s",
        flush=True,
    )
    return rc


# ---------------- worker (child) --------------------------------------------


def _worker() -> int:
    """Run the replay inside the dimos Coordinator with debug=True."""
    attempt_dir = Path(os.environ[_ATTEMPT_DIR_ENV])
    db_path = attempt_dir / "fastlio.db"
    if db_path.exists():
        db_path.unlink()
    db_path_str = str(db_path)

    from dimos.core.coordination.blueprints import autoconnect
    from dimos.core.coordination.module_coordinator import ModuleCoordinator
    from dimos.hardware.sensors.lidar.fastlio2.module import FastLio2

    # Kill orphan dimos / fastlio2_native / tcpdump processes so the new
    # run starts clean.
    subprocess.run(["kd"], check=False)
    time.sleep(1.0)

    bp = autoconnect(
        FastLio2.blueprint(
            frame_id="world",
            map_freq=-1,
            replay_pcap=PCAP_PATH,
            deterministic_clock=True,
            debug=True,
        ).remappings(
            [
                (FastLio2, "odometry", "fastlio_odometry"),
            ]
        ),
        Rec.blueprint(db_path=db_path_str),
    ).global_config(n_workers=4, robot_model="mid360_fastlio2_replay_timing")
    coord = ModuleCoordinator.build(bp)

    import sqlite3

    t0 = time.time()
    last_ts_seen = 0.0
    stagnant_since: float | None = None
    saw_first_row = False
    try:
        while time.time() - t0 < MAX_WALL_SEC:
            time.sleep(1.0)
            if not db_path.exists():
                continue
            try:
                con = sqlite3.connect(f"file:{db_path_str}?mode=ro", uri=True, timeout=0.5)
                row = con.execute("SELECT MAX(ts), COUNT(*) FROM fastlio_odometry").fetchone()
                con.close()
            except Exception:
                continue
            last_ts = row[0] if row and row[0] else 0.0
            cnt = row[1] if row else 0
            if cnt > 0:
                saw_first_row = True
            if not saw_first_row:
                continue
            # Stagnation by ts progress: WAL can grow without new rows.
            if last_ts == last_ts_seen:
                if stagnant_since is None:
                    stagnant_since = time.time()
                elif time.time() - stagnant_since > 3.0:
                    break  # no new rows for 3 s = binary done
            else:
                last_ts_seen = last_ts
                stagnant_since = None
    finally:
        coord.stop()

    if db_path.exists():
        size_mb = db_path.stat().st_size / 1e6
        print(
            f"[replay_timing.worker] db_size={size_mb:.2f}MB wall={time.time() - t0:.1f}s",
            flush=True,
        )
    return 0


# ---------------- entry -----------------------------------------------------


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "--worker":
        return _worker()
    return _orchestrate()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
