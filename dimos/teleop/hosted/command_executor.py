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

"""Serialized command executor with nonce dedup + safety-epoch fencing.

Robot-agnostic mixin for a hosted-teleop command plane. A single worker thread
runs blocking driver commands off the transport callback, deduped by operator
nonce, bounded backlog, with an urgent bypass (E-STOP) and a safety epoch that
aborts queued/in-flight work after an E-STOP / operator-lost event.

Host contract: call ``_cmd_init()`` in __init__, ``_cmd_start()`` in start(),
``_cmd_stop()`` in stop(); provide ``_send_ack(nonce, ok)`` and the ``_estopped``
latch (True while E-STOP is latched).
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from typing import Any

from dimos.utils.logging_config import setup_logger

logger = setup_logger()


class SerializedCommandMixin:
    """Single-worker command executor + nonce dedup + safety epoch."""

    _MAX_PENDING_CMDS: int = 4
    _NONCE_TTL_SEC: float = 10.0
    _NONCE_CACHE_MAX: int = 64

    # Provided by the host module.
    _send_ack: Callable[[Any, bool], None]
    _estopped: bool

    def _cmd_init(self) -> None:
        """Set up executor state; call from the host module's __init__."""
        self._cmd_executor: ThreadPoolExecutor | None = None
        self._cmd_pending = 0
        self._cmd_lock = threading.Lock()
        self._safety_epoch = 0
        self._nonce_results: dict[Any, tuple[bool | None, float]] = {}

    def _cmd_start(self) -> None:
        """Create the single worker; call from start()."""
        self._cmd_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="HostedCmd")

    def _cmd_stop(self) -> None:
        """Shut down the worker (cancel pending); call from stop()."""
        if self._cmd_executor is not None:
            self._cmd_executor.shutdown(wait=False, cancel_futures=True)
            self._cmd_executor = None

    # ─── safety epoch (E-STOP / operator-lost fence) ──────────────────

    def _bump_safety_epoch(self) -> int:
        """Invalidate any in-flight / queued non-urgent task. Returns new epoch."""
        with self._cmd_lock:
            self._safety_epoch += 1
            return self._safety_epoch

    def _safety_ok(self, epoch: int) -> bool:
        """True while no E-STOP / operator-lost has fired since `epoch`."""
        with self._cmd_lock:
            return self._safety_epoch == epoch

    # ─── submission ───────────────────────────────────────────────────

    def _submit_cmd(
        self, label: str, nonce: Any, task: Callable[[int], bool], *, urgent: bool = False
    ) -> None:
        """Run a blocking command off the loop and ack it. Non-urgent commands
        serialize on one worker (bounded backlog, busy-rejected past
        _MAX_PENDING_CMDS); urgent (Damp/E-STOP) bypasses the queue.

        The task receives the safety epoch captured at SUBMIT time. If E-STOP or
        operator-lost fires before it runs, it is refused; multi-step tasks pass
        the epoch to ``_safety_ok`` between steps so in-flight work can't resume
        motion after the safety event.
        """

        # E-STOP latch: only urgent work (Damp itself) may run while latched.
        if self._estopped and not urgent:
            logger.warning("%s rejected: E-STOP latched", label)
            self._send_ack(nonce, False)
            return

        submit_epoch = self._safety_epoch

        if nonce is not None and not urgent:
            now = time.monotonic()
            with self._cmd_lock:
                self._nonce_results = {
                    n: (r, t)
                    for n, (r, t) in self._nonce_results.items()
                    if now - t < self._NONCE_TTL_SEC
                }
                if nonce in self._nonce_results:
                    prior, _ = self._nonce_results[nonce]
                    logger.info(
                        "%s: duplicate nonce %r — %s",
                        label,
                        nonce,
                        "re-acking" if prior is not None else "in flight",
                    )
                    if prior is not None:
                        self._send_ack(nonce, prior)
                    return
                if len(self._nonce_results) >= self._NONCE_CACHE_MAX:
                    oldest = min(self._nonce_results, key=lambda n: self._nonce_results[n][1])
                    del self._nonce_results[oldest]
                self._nonce_results[nonce] = (None, now)

        def _unwind_nonce() -> None:
            if nonce is not None:
                with self._cmd_lock:
                    self._nonce_results.pop(nonce, None)

        def runner() -> None:
            ok = False
            try:
                # Refuse if a safety event fired between submit and run (a queued
                # command must not resume motion after E-STOP / operator-lost).
                if not urgent and not self._safety_ok(submit_epoch):
                    logger.warning("%s aborted: E-STOP / operator-lost before run", label)
                else:
                    ok = bool(task(submit_epoch))
            except Exception:
                logger.exception("%s failed", label)
            finally:
                if not urgent:
                    with self._cmd_lock:
                        self._cmd_pending -= 1
            if nonce is not None and not urgent:
                with self._cmd_lock:
                    self._nonce_results[nonce] = (ok, time.monotonic())
            self._send_ack(nonce, ok)

        if urgent:
            threading.Thread(target=runner, daemon=True, name=f"HostedCmd-{label}").start()
            return

        executor = self._cmd_executor
        if executor is None:  # not started / already stopped
            _unwind_nonce()
            self._send_ack(nonce, False)
            return
        with self._cmd_lock:
            busy = self._cmd_pending >= self._MAX_PENDING_CMDS
            if busy:
                self._nonce_results.pop(nonce, None)
            else:
                self._cmd_pending += 1
        if busy:
            logger.warning("%s rejected: command backlog full", label)
            self._send_ack(nonce, False)
            return
        try:
            executor.submit(runner)
        except RuntimeError:  # shutdown raced us
            with self._cmd_lock:
                self._cmd_pending -= 1
            _unwind_nonce()
            self._send_ack(nonce, False)
