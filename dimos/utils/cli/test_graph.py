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

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import re
import threading

import pytest
import requests

SNAPSHOT_PATH = Path(__file__).with_name("test_graph_snapshot.html")


def _normalize_html(html: str) -> str:
    html = re.sub(
        r"<script>.{1000,}?</script>",
        "<script>/* mermaid.min.js */</script>",
        html,
        count=1,
        flags=re.DOTALL,
    )
    return "\n".join(line.rstrip() for line in html.splitlines())


def _serve_and_fetch(html: str) -> str:
    html_bytes = html.encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html_bytes)))
            self.end_headers()
            self.wfile.write(html_bytes)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]

    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    response = requests.get(f"http://127.0.0.1:{port}/", timeout=10)
    body = response.text

    thread.join(timeout=5)
    server.server_close()
    return body


def test_graph_server_snapshot() -> None:
    blueprint_file = str(Path(__file__).with_name("test_graph_blueprints.py"))

    from dimos.utils.cli.graph import _build_html

    html = _build_html(blueprint_file, show_disconnected=True)

    html_normalized = _normalize_html(html)

    assert "<!DOCTYPE html>" in html_normalized
    assert "CameraModule" in html_normalized
    assert "mermaid" in html_normalized

    served_html = _serve_and_fetch(html)
    served_normalized = _normalize_html(served_html)
    assert served_normalized == html_normalized

    if SNAPSHOT_PATH.exists():
        snapshot = SNAPSHOT_PATH.read_text().rstrip("\n")
        if snapshot != html_normalized.rstrip("\n"):
            SNAPSHOT_PATH.write_text(html_normalized.rstrip("\n") + "\n")
            pytest.fail(
                f"Snapshot mismatch — updated {SNAPSHOT_PATH.name}. "
                "Re-run to confirm the new snapshot passes."
            )
    else:
        SNAPSHOT_PATH.write_text(html_normalized.rstrip("\n") + "\n")
