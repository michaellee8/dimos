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

"""python-can Bus for gs_usb CAN adapters via libusb - works on macOS.

SocketCAN is Linux-only; this bus drives gs_usb-protocol adapters (candlelight
class, including the HHS "CANFD Analyser" Galaxea ships) entirely from
userspace over libusb, so the A1Z runs natively on macOS. Validated on an
M4 Pro at a sustained 250 Hz control loop (p99 cycle 5.2 ms, 0/7500 cycles
over the SDK's 12.5 ms limit, ~100% feedback from all 7 motors).

Device quirks handled here:
- TX endpoint is discovered from the descriptors (this adapter uses 0x01;
  the gs_usb library assumes 0x02)
- macOS has no kernel driver to detach; the detach call is skipped
- TX echo frames are filtered out of recv()

Requires: pip install pyusb gs_usb (plus libusb, e.g. brew install libusb).
Lives in galaxea_a1z/ because it is the only user today; promote to a shared
location when a second CAN arm needs it.
"""

from __future__ import annotations

import time
from typing import Any

import can

# HHS USB-CANFD adapter bundled with the Galaxea A1Z
GALAXEA_VENDOR_ID = 0xA8FA
GALAXEA_PRODUCT_ID = 0x8598

_GS_USB_NONE_ECHO_ID = 0xFFFFFFFF
_GS_CAN_MODE_LISTEN_ONLY = 1 << 0


class GsUsbMacBus(can.BusABC):
    """CAN bus over a gs_usb adapter through libusb (macOS-friendly)."""

    def __init__(
        self,
        channel: str = "gs_usb",
        *,
        vendor_id: int = GALAXEA_VENDOR_ID,
        product_id: int = GALAXEA_PRODUCT_ID,
        bitrate: int = 1_000_000,
        listen_only: bool = False,
        discover_timeout: float = 5.0,
        **_: Any,
    ) -> None:
        from gs_usb.gs_usb import GS_CAN_MODE_HW_TIMESTAMP, GsUsb
        import usb.core

        # The adapter drops off the USB bus for a few seconds after a
        # close (firmware reset on reopen, observed on hardware) - retry
        # discovery instead of failing the first reconnect.
        deadline = time.perf_counter() + discover_timeout
        device = usb.core.find(idVendor=vendor_id, idProduct=product_id)
        while device is None and time.perf_counter() < deadline:
            time.sleep(0.25)
            device = usb.core.find(idVendor=vendor_id, idProduct=product_id)
        if device is None:
            raise can.CanInitializationError(
                f"gs_usb adapter {vendor_id:04x}:{product_id:04x} not found on USB "
                f"(waited {discover_timeout:.0f}s)"
            )
        # No kernel driver claims the interface on macOS; gs_usb's detach
        # call would raise, so neutralize it.
        device.detach_kernel_driver = lambda intf: None  # type: ignore[method-assign]

        # The gs_usb library hardcodes TX endpoint 0x02; discover the real
        # bulk OUT endpoint from the active configuration instead.
        cfg = device.get_active_configuration()
        intf = cfg[(0, 0)]
        out_eps = [ep for ep in intf if not (ep.bEndpointAddress & 0x80)]
        if not out_eps:
            raise can.CanInitializationError("gs_usb adapter has no OUT endpoint")
        self._out_endpoint = out_eps[0].bEndpointAddress

        self._gs = GsUsb(device)
        if not self._gs.set_bitrate(bitrate):
            raise can.CanInitializationError(f"failed to set bitrate {bitrate}")
        self._hw_timestamp_flag = GS_CAN_MODE_HW_TIMESTAMP
        self._gs.start(_GS_CAN_MODE_LISTEN_ONLY if listen_only else 0)
        self._flush_rx()

        self.channel_info = f"gs_usb {vendor_id:04x}:{product_id:04x} @ {bitrate}"
        super().__init__(channel=channel)

    def _flush_rx(self, max_frames: int = 1024) -> int:
        """Discard frames queued in the device from a previous session.

        The device keeps its RX queue across open/close; stale frames (e.g.
        disable-command acks) parse as motor feedback with garbage velocity
        values and trip startup safety checks. Observed on hardware.
        """
        from gs_usb.gs_usb_frame import GsUsbFrame

        frame = GsUsbFrame()
        flushed = 0
        while flushed < max_frames and self._gs.read(frame, 5):
            flushed += 1
        if flushed:
            print(f"GsUsbMacBus: flushed {flushed} stale frames from device queue")
        return flushed

    @property
    def state(self) -> can.BusState:
        return can.BusState.ACTIVE

    def send(self, msg: can.Message, timeout: float | None = None) -> None:
        from gs_usb.gs_usb_frame import GsUsbFrame

        frame = GsUsbFrame(can_id=msg.arbitration_id, data=bytes(msg.data))
        hw_ts = bool(self._gs.device_flags & self._hw_timestamp_flag)
        self._gs.gs_usb.write(self._out_endpoint, frame.pack(hw_ts))

    def _recv_internal(self, timeout: float | None) -> tuple[can.Message | None, bool]:
        from gs_usb.gs_usb_frame import GsUsbFrame

        # python-can treats timeout<=0 as a poll. gs_usb reads block for at
        # least 1 ms, so a poll costs up to 1 ms when the queue is empty
        # (returns immediately when a frame is pending). The SDK's feedback
        # drain relies on recv(timeout=0.0) returning pending frames.
        if timeout is not None and timeout <= 0:
            timeout = 0.001
        deadline = None if timeout is None else time.perf_counter() + timeout
        frame = GsUsbFrame()
        while True:
            if deadline is None:
                wait_ms = 1000
            else:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    return None, False
                wait_ms = max(1, int(remaining * 1000))

            if not self._gs.read(frame, wait_ms):
                if deadline is None:
                    continue
                return None, False
            if frame.echo_id != _GS_USB_NONE_ECHO_ID:
                continue  # our own TX echo, not bus traffic

            msg = can.Message(
                arbitration_id=frame.can_id & 0x1FFFFFFF,
                is_extended_id=bool(frame.can_id & 0x80000000),
                data=bytes(frame.data[: frame.can_dlc]),
                dlc=frame.can_dlc,
            )
            return msg, False

    def shutdown(self) -> None:
        try:
            self._gs.stop()
        except Exception:
            pass
        super().shutdown()
