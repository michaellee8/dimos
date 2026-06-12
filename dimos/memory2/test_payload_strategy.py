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

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from dimos.memory2.store.sqlite import SqliteStore
from dimos.memory2.type.observation import _UNLOADED

if TYPE_CHECKING:
    from collections.abc import Iterator

    from dimos.memory2.blobstore.base import BlobStore
    from dimos.memory2.type.observation import Observation


class SuppressMeError(RuntimeError):
    pass


class DoNotSuppressError(RuntimeError):
    pass


class PrefixPayloadStrategy:
    codec_id = "prefix"

    def __init__(self, prefix: str = "encoded:") -> None:
        self.prefix = prefix
        self.started = False
        self.stopped = False
        self.bound_sqlite = False
        self.encoded_values: list[str] = []
        self.blob_rows: list[tuple[str, int, bytes]] = []

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def bind_sqlite(self, _conn: Any) -> None:
        self.bound_sqlite = True

    def encode(self, value: str) -> bytes:
        self.encoded_values.append(value)
        return f"{self.prefix}{value}".encode()

    def after_blob_put(self, stream_name: str, row_id: int, encoded: bytes) -> None:
        self.blob_rows.append((stream_name, row_id, encoded))

    def _decode(self, raw: bytes) -> str:
        value = raw.decode()
        if not value.startswith(self.prefix):
            raise ValueError("payload strategy prefix missing")
        decoded = value.removeprefix(self.prefix)
        if decoded == "skip":
            raise SuppressMeError("skip this payload")
        if decoded == "boom":
            raise DoNotSuppressError("do not suppress this payload")
        return decoded

    def make_loader(self, stream_name: str, row_id: int, blob_store: BlobStore) -> Any:
        def loader() -> str:
            return self._decode(blob_store.get(stream_name, row_id))

        return loader

    def attach_loaders(
        self,
        stream_name: str,
        observations: Iterator[Observation[str]],
        blob_store: BlobStore,
    ) -> Iterator[Observation[str]]:
        for obs in observations:
            obs.data_type = str
            if obs._loader is None and isinstance(obs._data, type(_UNLOADED)):
                row_id = obs.id
                obs._loader = self.make_loader(stream_name, row_id, blob_store)
            yield obs

    def should_suppress_decode_error(self, error: BaseException) -> bool:
        return isinstance(error, SuppressMeError)

    def serialize(self) -> dict[str, Any]:
        return {
            "class": f"{type(self).__module__}.{type(self).__qualname__}",
            "config": {"prefix": self.prefix},
        }


def test_payload_strategy_encodes_loads_and_stops(tmp_path) -> None:
    strategy = PrefixPayloadStrategy(prefix="p:")
    store = SqliteStore(path=str(tmp_path / "strategy.db"))
    stream = store.stream("events", str, payload_strategy=strategy)

    appended = stream.append("hello", ts=1.0)

    assert strategy.bound_sqlite
    assert strategy.started
    assert strategy.encoded_values == ["hello"]
    assert strategy.blob_rows == [("events", appended.id, b"p:hello")]
    queried = stream.first()
    assert queried._data is _UNLOADED
    assert queried.data == "hello"

    store.stop()
    assert strategy.stopped


def test_payload_strategy_persists_and_binds_on_reopen(tmp_path) -> None:
    db = tmp_path / "strategy-reopen.db"
    with SqliteStore(path=str(db)) as store:
        stream = store.stream(
            "events",
            str,
            payload_strategy=PrefixPayloadStrategy(prefix="stored:"),
        )
        stream.append("hello", ts=1.0)

    with SqliteStore(path=str(db), must_exist=True) as reopened:
        stream = reopened.stream("events", str)
        assert stream._source is not None
        strategy = stream._source.payload_strategy
        assert isinstance(strategy, PrefixPayloadStrategy)
        assert strategy.prefix == "stored:"
        assert strategy.bound_sqlite
        assert stream.first().data == "hello"


def test_replay_skips_strategy_suppressed_decode_errors(tmp_path) -> None:
    store = SqliteStore(path=str(tmp_path / "strategy-replay.db"))
    stream = store.stream("events", str, payload_strategy=PrefixPayloadStrategy())
    stream.append("first", ts=1.0)
    stream.append("skip", ts=2.0)
    stream.append("third", ts=3.0)

    assert list(store.replay().streams.events.iterate()) == ["first", "third"]


def test_replay_surfaces_non_suppressed_strategy_errors(tmp_path) -> None:
    store = SqliteStore(path=str(tmp_path / "strategy-replay-error.db"))
    stream = store.stream("events", str, payload_strategy=PrefixPayloadStrategy())
    stream.append("first", ts=1.0)
    stream.append("boom", ts=2.0)

    replay_iter = store.replay().streams.events.iterate()
    assert next(replay_iter) == "first"
    with pytest.raises(DoNotSuppressError):
        next(replay_iter)
