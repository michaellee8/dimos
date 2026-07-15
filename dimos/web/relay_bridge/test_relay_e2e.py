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

"""End-to-end tests against a real relay child process (aioquic both legs).

Marked web_e2e: excluded from the default matrix (needs Deno); the CI `web`
job runs them. One file on purpose: --dist=loadfile keeps the module-scoped
relay on a single xdist worker.
"""

import asyncio
from collections.abc import Callable, Iterator
import hashlib
import json
import statistics
import time
import urllib.request

import pytest

from dimos.web.relay_bridge.protocol import DataFrame
from dimos.web.relay_bridge.relay_launcher import RelayProcess, RelayReadyInfo
from dimos.web.relay_bridge.wt_client import RelayClient

pytestmark = pytest.mark.web_e2e


@pytest.fixture(scope="module")
def relay() -> Iterator[RelayReadyInfo]:
    process = RelayProcess()
    try:
        yield process.start()
    finally:
        process.stop()


async def collect_until(
    viewer: RelayClient,
    done: Callable[[list[DataFrame]], bool],
    timeout: float = 10.0,
) -> list[DataFrame]:
    """Consume viewer frames until `done(frames)` or `timeout` (returns what arrived)."""
    frames: list[DataFrame] = []

    async def _consume() -> None:
        async for frame in viewer.frames():
            frames.append(frame)
            if done(frames):
                return

    try:
        await asyncio.wait_for(_consume(), timeout)
    except asyncio.TimeoutError:
        pass
    return frames


def test_info_matches_ready_line(relay: RelayReadyInfo) -> None:
    with urllib.request.urlopen(f"http://127.0.0.1:{relay.http_port}/api/info") as response:
        info = json.load(response)
    assert info == {"wtUrl": f"{relay.wt_url}/viewer", "certHash": relay.cert_hash, "v": relay.v}
    assert relay.wt_url.startswith("https://127.0.0.1:")


async def test_robot_handshake_and_datagram_rtt(relay: RelayReadyInfo) -> None:
    async with await RelayClient.connect(relay.wt_url, "robot") as robot:
        await robot.hello()
        rtts = [await robot.ping() for _ in range(20)]
    assert statistics.median(rtts) < 0.1


async def test_reliable_channel_is_complete_and_intact(relay: RelayReadyInfo) -> None:
    async with (
        await RelayClient.connect(relay.wt_url, "robot") as robot,
        await RelayClient.connect(relay.wt_url, "viewer") as viewer,
    ):
        await robot.hello()
        await viewer.hello()
        count = 100
        payloads = [seq.to_bytes(4, "little") * 256 for seq in range(count)]
        for seq, payload in enumerate(payloads):
            robot.send_frame("odom", payload, delivery="reliable", meta={"i": seq})

        frames = await collect_until(
            viewer,
            lambda fs: len({f.header.seq for f in fs if f.header.ch == "odom"}) >= count,
        )
        odom = {f.header.seq: f for f in frames if f.header.ch == "odom"}
        # Reliable = complete, no drops. One-stream-per-message may reorder;
        # completeness is the contract, headers carry the sequence.
        assert sorted(odom) == list(range(count))
        assert all(bytes(odom[seq].payload) == payloads[seq] for seq in range(count))
        assert odom[0].header.delivery == "reliable"
        assert odom[0].header.meta == {"i": 0}


async def test_latest_channel_newest_wins(relay: RelayReadyInfo) -> None:
    async with (
        await RelayClient.connect(relay.wt_url, "robot") as robot,
        await RelayClient.connect(relay.wt_url, "viewer") as viewer,
    ):
        await robot.hello()
        await viewer.hello()
        writer = robot.latest_writer("cam")
        offered = 200
        for i in range(offered):
            writer.offer(i.to_bytes(4, "little") + b"\xab" * 2000)

        def newest_arrived(frames: list[DataFrame]) -> bool:
            return any(
                f.header.ch == "cam" and f.payload[:4] == (offered - 1).to_bytes(4, "little")
                for f in frames
            )

        frames = await collect_until(viewer, newest_arrived)
        cam = [f for f in frames if f.header.ch == "cam"]
        markers = [int.from_bytes(bytes(f.payload[:4]), "little") for f in cam]
        # The newest offered frame always lands; the mailbox shed the rest.
        assert newest_arrived(frames), f"newest frame missing; got markers {markers}"
        assert writer.dropped + writer.sent == offered
        assert 0 < len(cam) <= offered
        # Everything the writer actually sent arrived (loopback: no transport loss).
        assert len(cam) == writer.sent


async def test_large_frame_1mib(relay: RelayReadyInfo) -> None:
    async with (
        await RelayClient.connect(relay.wt_url, "robot") as robot,
        await RelayClient.connect(relay.wt_url, "viewer") as viewer,
    ):
        await robot.hello()
        await viewer.hello()
        payload = bytes(range(256)) * 4096  # 1 MiB
        robot.send_frame("blob", payload, delivery="reliable")
        frames = await collect_until(viewer, lambda fs: any(f.header.ch == "blob" for f in fs))
        blob = next(f for f in frames if f.header.ch == "blob")
        assert len(blob.payload) == len(payload)
        assert hashlib.sha256(blob.payload).hexdigest() == hashlib.sha256(payload).hexdigest()


async def test_reset_stale_discards_partial_frame(relay: RelayReadyInfo) -> None:
    """A reset mid-frame must drop the partial on the relay and nothing else."""
    async with (
        await RelayClient.connect(relay.wt_url, "robot") as robot,
        await RelayClient.connect(relay.wt_url, "viewer") as viewer,
    ):
        await robot.hello()
        await viewer.hello()
        # 8 MiB cannot be flushed + ACKed within the same event-loop turn, so
        # the reset below reliably lands mid-transfer.
        big = robot.send_frame("cam", b"\xcd" * (8 * 1024 * 1024), delivery="latest")
        assert robot._session.reset_if_in_flight(big)
        small = b"\x01\x02\x03\x04" * 8
        robot.send_frame("cam", small, delivery="latest")

        frames = await collect_until(viewer, lambda fs: any(f.header.ch == "cam" for f in fs))
        cam = [f for f in frames if f.header.ch == "cam"]
        assert [bytes(f.payload) for f in cam] == [small]

        # The relay survived the reset: control still answers.
        assert await robot.ping() < 5.0


async def test_stats_reflect_traffic(relay: RelayReadyInfo) -> None:
    async with (
        await RelayClient.connect(relay.wt_url, "robot") as robot,
        await RelayClient.connect(relay.wt_url, "viewer") as viewer,
    ):
        await robot.hello()
        await viewer.hello()
        robot.send_frame("odom", b"{}", delivery="reliable")
        await collect_until(viewer, lambda fs: len(fs) >= 1, timeout=5.0)

        def fetch_stats() -> dict:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{relay.http_port}/api/stats"
            ) as response:
                return json.load(response)

        stats = await asyncio.to_thread(fetch_stats)
        assert stats["robot"] is True
        assert stats["viewers"] >= 1
        assert stats["channels"]["odom"]["framesIn"] >= 1
        assert stats["channels"]["odom"]["delivery"] == "reliable"


async def test_send_frame_paces_with_wait_delivered(relay: RelayReadyInfo) -> None:
    async with await RelayClient.connect(relay.wt_url, "robot") as robot:
        await robot.hello()
        start = time.monotonic()
        stream_id = robot.send_frame("odom", b"x" * 1000, delivery="reliable")
        assert await robot.wait_delivered(stream_id, timeout=5.0)
        assert time.monotonic() - start < 5.0
