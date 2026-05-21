"""SDP introspection helpers — minimal regex-based extraction.

Not a full SDP parser. Only covers what the broker needs: finding the first
publishable m=video section in a peer's offer so we can register it with CF
Realtime's `/sessions/{id}/tracks/new` endpoint.
"""

from __future__ import annotations

import re


def extract_video_track(sdp: str) -> tuple[str, str] | None:
    """Return (mid, track_name) for the first sendonly/sendrecv m=video.

    Returns None if the offer has no m=video, if every m=video is recvonly
    or inactive, or if the matching section lacks `a=mid` or `a=msid`.
    ``track_name`` is the *second* token of ``a=msid:<stream> <track>`` —
    aiortc emits both. CF Realtime's add_tracks(location="local") expects
    this trackId as ``trackName``.
    """
    for section in re.split(r"(?m)^(?=m=)", sdp):
        if not section.startswith("m=video"):
            continue
        if re.search(r"(?m)^a=(recvonly|inactive)\s*$", section):
            continue
        mid = re.search(r"(?m)^a=mid:(\S+)", section)
        msid = re.search(r"(?m)^a=msid:\S+\s+(\S+)", section)
        if mid and msid:
            return mid.group(1), msid.group(1)
    return None
