// Pure video-stats math shared by the Cloudflare (webrtc.js) and LiveKit
// (livekit.js) getStats paths. No DOM, no timers.

// Active ICE path from a getStats() report: host→'direct', srflx/prflx→'stun',
// relay→'turn'. null when no active pair.
export function selectedIceType(report) {
    let pair = null;
    report.forEach((r) => {
        if (r.type !== 'candidate-pair') return;
        // `selected` (Chrome) or nominated+succeeded (spec) marks the active pair.
        if (r.selected || (r.nominated && r.state === 'succeeded')) pair = r;
    });
    if (!pair) return null;
    const local = report.get(pair.localCandidateId);
    if (!local) return null;
    return local.candidateType === 'relay' ? 'turn'
        : local.candidateType === 'srflx' || local.candidateType === 'prflx' ? 'stun'
        : 'direct';
}

export function findVideoInbound(report) {
    let inbound = null;
    report.forEach((r) => {
        if (r.type === 'inbound-rtp' && r.kind === 'video') inbound = r;
    });
    return inbound;
}

// Negotiated codec short name ('H264'/'VP8'/...) or '' when unavailable.
export function videoCodec(report, inbound) {
    if (!inbound?.codecId) return '';
    const codec = report.get?.(inbound.codecId);
    const mime = codec?.mimeType || '';
    return mime.includes('/') ? mime.split('/')[1] : mime;
}

// Delta two inbound-rtp samples into the video_stats payload. null when a delta
// isn't computable yet (first sample or non-advancing stats clock).
export function computeVideoStats(prev, inbound, e2eLatencyMs = 0, codec = '') {
    if (!prev || !inbound) return null;
    const dt = (inbound.timestamp - prev.timestamp) / 1000;
    if (dt <= 0) return null;

    const dFrames = (inbound.framesDecoded ?? 0) - (prev.framesDecoded ?? 0);
    const dBytes = (inbound.bytesReceived ?? 0) - (prev.bytesReceived ?? 0);
    const dLost = (inbound.packetsLost ?? 0) - (prev.packetsLost ?? 0);
    const dRecv = (inbound.packetsReceived ?? 0) - (prev.packetsReceived ?? 0);
    const lossDen = dLost + dRecv;
    const dDecode = (inbound.totalDecodeTime ?? 0) - (prev.totalDecodeTime ?? 0);
    const decodeMs = dFrames > 0 ? +((dDecode / dFrames) * 1000).toFixed(1) : 0;

    return {
        type: 'video_stats',
        fps: +(dFrames / dt).toFixed(1),
        kbps: +((dBytes * 8) / dt / 1000).toFixed(1),
        width: inbound.frameWidth ?? 0,
        height: inbound.frameHeight ?? 0,
        loss_pct: lossDen > 0 ? +((dLost / lossDen) * 100).toFixed(2) : 0,
        jitter_ms: +((inbound.jitter ?? 0) * 1000).toFixed(1),
        frames_dropped: inbound.framesDropped ?? 0,
        freezes: inbound.freezeCount ?? 0,
        jitter_buffer_ms:
            inbound.jitterBufferEmittedCount
                ? +((inbound.jitterBufferDelay / inbound.jitterBufferEmittedCount) * 1000).toFixed(1)
                : 0,
        decode_ms: decodeMs,
        e2e_latency_ms: e2eLatencyMs,  // glass-to-glass, 0 if not stamping
        codec,
        decoder: inbound.decoderImplementation ?? '',  // HW name vs 'libvpx' = latency tell
    };
}
