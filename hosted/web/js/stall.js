// Video-freshness drive gate: once video has played (armed), if the frame clock
// stops advancing for STALL_MS block drive + show overlay. On resume, keep drive
// blocked until all drive keys release (neutral gate) so a held W can't lunge.
// Liveness signal is video.currentTime (works on both transports); NOT the e2e
// stamp (benchmark-only) or getStats (absent on LiveKit).

export const STALL_MS = 1000;  // ms of frozen frame clock before lockout

export function createStallGate({ stallMs = STALL_MS } = {}) {
    let lastMediaTime = -1;
    let lastProgressMs = null;
    let armed = false;           // no lockout before first frame (no-video robots drive as before)
    let stalled = false;
    let resumePending = false;   // frames back but drive keys still held

    return {
        // mediaTime: video.currentTime or -1 (no video); nowMs: performance.now();
        // keysHeld: any drive input engaged. → {stalled, blocked, armed}.
        sample(mediaTime, nowMs, keysHeld) {
            if (mediaTime >= 0 && mediaTime > lastMediaTime) {
                lastMediaTime = mediaTime;
                lastProgressMs = nowMs;
                armed = true;
                if (stalled) {
                    stalled = false;
                    resumePending = true;  // auto-resume, gated on neutral below
                }
            }
            if (armed && !stalled && lastProgressMs !== null &&
                nowMs - lastProgressMs > stallMs) {
                stalled = true;
                resumePending = false;
            }
            if (resumePending && !keysHeld) resumePending = false;
            return { stalled, blocked: stalled || resumePending, armed };
        },
    };
}

// -1 when the element can't have a frame yet.
export function videoMediaTime(v) {
    return v && v.readyState >= 2 ? v.currentTime : -1;
}
