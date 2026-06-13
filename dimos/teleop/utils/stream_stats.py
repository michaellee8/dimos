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

"""Stat helpers for teleop streams (latency / jitter / rate).

Two flavors live here:

* **`pcts`** — a pure percentile helper shared by the post-hoc report writer
  (``teleop/utils/report.py``) and any live stats consumer.
* **`LiveStreamStats`** — a rolling-window class for always-on consumers that
  only need a recent snapshot (e.g. the operator HUD's command-plane telemetry).

Packet loss / reorder are transport-layer concerns and are intentionally not
computed here from an application sequence number. TODO: surface command-plane
loss from datachannel/SCTP stats (same source as VideoStats.loss_pct), not a
per-message seq.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from itertools import pairwise
import threading
import time

import numpy as np


def pcts(values: Sequence[float]) -> dict[str, float] | None:
    """p50/p95/p99/max of *values* in their native unit, or None if empty."""
    if not values:
        return None
    a = np.asarray(values, dtype=float)
    return {
        "p50": float(np.percentile(a, 50)),
        "p95": float(np.percentile(a, 95)),
        "p99": float(np.percentile(a, 99)),
        "max": float(a.max()),
    }


def loss_pct(seqs: Sequence[int]) -> float | None:
    """Loss % from gaps in a monotonic sequence; None if fewer than 2 seqs.

    ``loss = 1 - distinct_received / (max_seq - min_seq + 1)``. Reorders and
    duplicates don't inflate it — only genuinely missing seq values count.
    Tail loss (packets after the last one seen) is invisible: we can only
    measure gaps inside the observed ``[min, max]`` range.
    """
    valid = [s for s in seqs if s is not None]
    if len(valid) < 2:
        return None
    expected = max(valid) - min(valid) + 1
    received = len(set(valid))
    return max(0.0, (1.0 - received / expected) * 100.0)


def reorder_count(seqs: Sequence[int]) -> int:
    """Count messages that arrived with a seq below an already-seen maximum."""
    count = 0
    running_max = -1
    for s in seqs:
        if s is None:
            continue
        if s < running_max:
            count += 1
        else:
            running_max = s
    return count


class LiveStreamStats:
    """Rolling-window health for an always-on stream consumer.

    Records ``(wall, ts, seq, nbytes)`` per arrival in a bounded deque so old
    samples fall off automatically; ``snapshot()`` returns the window's median
    E2E latency, median inter-arrival jitter, seq-gap loss, reorder count,
    arrival rate, and throughput. Thread-safe — ``record()`` runs on the
    transport callback, ``snapshot()`` on a separate reader.

    ``seq`` enables loss/reorder (the sender's monotonic counter, read off the
    wire); ``nbytes`` enables throughput. Both optional — unstamped streams
    still get rate + jitter.
    """

    def __init__(self, window: int = 120) -> None:
        self._lock = threading.Lock()
        # (wall_arrival, ts, seq, nbytes); ts/seq/nbytes are None when absent.
        self._samples: deque[tuple[float, float | None, int | None, int | None]] = deque(
            maxlen=window
        )

    def record(
        self, ts: float | None, seq: int | None = None, nbytes: int | None = None
    ) -> None:
        """Note an inbound message's send-stamp, seq, and wire size (any None)."""
        with self._lock:
            self._samples.append((time.time(), ts, seq, nbytes))

    def snapshot(self) -> dict[str, float | None] | None:
        """Median latency/jitter (ms), loss (%), reorder, rate (Hz), throughput.

        Returns ``None`` until at least two samples have landed (one inter-arrival
        interval is needed). Uses the module's shared ``pcts``/``loss_pct`` so the
        math matches the report writer.
        """
        with self._lock:
            samples = list(self._samples)
        if len(samples) < 2:
            return None

        arrivals = [w for w, _, _, _ in samples]
        intervals_ms = [(b - a) * 1000.0 for a, b in pairwise(arrivals)]
        # `is not None` — ts=0.0 / seq=0 are real values, only None means absent.
        e2e_ms = [(w - ts) * 1000.0 for w, ts, _, _ in samples if ts is not None]
        seqs = [s for _, _, s, _ in samples if s is not None]
        sizes = [n for _, _, _, n in samples if n is not None]

        e2e = pcts(e2e_ms)
        jit = pcts(intervals_ms)
        span = arrivals[-1] - arrivals[0]
        return {
            "latency_ms": e2e["p50"] if e2e else None,
            "jitter_ms": jit["p50"] if jit else None,
            "loss_pct": loss_pct(seqs),
            "reorder": float(reorder_count(seqs)) if seqs else None,
            "rate_hz": (len(samples) - 1) / span if span > 0 else None,
            "throughput_bps": (sum(sizes) / span) if (sizes and span > 0) else None,
        }


__all__ = ["LiveStreamStats", "loss_pct", "pcts", "reorder_count"]
