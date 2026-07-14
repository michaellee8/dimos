import { state } from './state.js';

const HUD_GOOD = '#34d399', HUD_WARN = '#ffcc00', HUD_BAD = '#ff5252';

export function statsHealth() {
    // Stalled feed = driving blind → worst state regardless of numbers.
    if (state.videoStall?.stalled) return 'bad';
    const v = state.liveStats.video;
    const c = state.liveStats.cmd;
    if (!v) return 'warn';
    const fps = v.fps ?? 0;
    const rtt = state.liveStats.rttMs ?? Infinity;
    const cmdLat = c ? (c.latency_ms ?? 0) : 0;
    // Go2 source is ~14–15fps: bad < 6/8, warn < 12; rtt/cmdLat in ms.
    if (fps < 6 || rtt > 200 || cmdLat > 200) return 'bad';
    if (fps < 12 || rtt > 100 || (v.loss_pct ?? 0) > 3 || cmdLat > 100) return 'warn';
    return 'good';
}
export function healthColor() {
    return { good: HUD_GOOD, warn: HUD_WARN, bad: HUD_BAD }[statsHealth()];
}

// Roll the shared send counter into cmdHz over dtSec and reset it.
export function sampleCmdHz(dtSec) {
    if (dtSec > 0) state.liveStats.cmdHz = state.cmdSendCount / dtSec;
    state.cmdSendCount = 0;
}

// SOC (%) → health level; shared cutoffs.
export function socHealth(soc) {
    if (soc == null) return null;
    return soc > 40 ? 'good' : soc > 15 ? 'warn' : 'bad';
}

export function transportLabel() {
    return state.activeRobot?.transport === 'livekit' ? 'LiveKit' : 'Cloudflare';
}

export function iceTypeLabel() {
    const t = state.liveStats.iceType;
    return t === 'turn' ? 'TURN' : t === 'stun' ? 'STUN' : t === 'direct' ? 'direct' : '';
}

export function hudSummaryLine() {
    const v = state.liveStats.video;
    const c = state.liveStats.cmd;
    const fps = v ? `${(v.fps ?? 0).toFixed(0)}fps` : '—fps';
    const mbps = v ? `${(((v.kbps ?? 0) / 1000)).toFixed(1)}mbps` : '—mbps';
    const rtt = state.liveStats.rttMs != null ? `RTT ${state.liveStats.rttMs.toFixed(0)}ms` : 'RTT —';
    const cmd = c && c.latency_ms != null ? `cmd ${c.latency_ms.toFixed(0)}ms` : 'cmd —';
    return `${fps}  ${mbps}  ${rtt}  ${cmd}`;
}

export function hudDetailLines() {
    const v = state.liveStats.video || {};
    const c = state.liveStats.cmd;
    const sentHz = state.liveStats.cmdHz ?? 0;
    const cmdLine = c
        ? `lat ${(c.latency_ms ?? 0).toFixed(0)}ms  jit ${(c.jitter_ms ?? 0).toFixed(0)}ms`
        : '—';
    const rateLine = `sent ${sentHz.toFixed(0)}Hz` +
        (c ? ` → recv ${(c.rate_hz ?? 0).toFixed(0)}Hz` : '');
    const ice = iceTypeLabel();
    return [
        `Link   ${transportLabel()}${ice ? `  ·  ${ice}` : ''}`,
        `Video  ${(v.fps ?? 0).toFixed(0)}fps  ${(((v.kbps ?? 0) / 1000)).toFixed(1)}mbps  ${v.width ?? '—'}x${v.height ?? '—'}${v.codec ? '  ' + v.codec : ''}`,
        `       loss ${(v.loss_pct ?? 0).toFixed(1)}%  jbuf ${(v.jitter_buffer_ms ?? 0).toFixed(0)}ms`,
        `       decode ${(v.decode_ms ?? 0).toFixed(0)}ms  e2e ${v.e2e_latency_ms ? v.e2e_latency_ms.toFixed(0) + 'ms' : '—'}  freezes ${v.freezes ?? 0}`,
        `Cmd    ${cmdLine}`,
        `       ${rateLine}`,
        `Clock  RTT ${state.liveStats.rttMs != null ? state.liveStats.rttMs.toFixed(0) : '—'}ms`,
    ];
}

// health ∈ 'good'|'warn'|'bad'|null; null = neutral (no tint).
export function hudDetailRows() {
    const v = state.liveStats.video || {};
    const c = state.liveStats.cmd;
    const rtt = state.liveStats.rttMs;
    const fps = v.fps ?? 0;
    const fmt = (n, d = 0) => (n == null ? '—' : n.toFixed(d));
    // Band thresholds mirror statsHealth axes.
    const band = (x, warn, bad, invert = false) =>
        x == null ? null : invert
            ? (x < bad ? 'bad' : x < warn ? 'warn' : 'good')
            : (x > bad ? 'bad' : x > warn ? 'warn' : 'good');
    return [
        { group: 'Link', rows: [
            { label: 'Transport', value: transportLabel(), health: null },
            { label: 'Path', value: iceTypeLabel() || '—',
              health: state.liveStats.iceType === 'turn' ? 'warn' : null },
            { label: 'RTT', value: `${fmt(rtt)} ms`, health: band(rtt, 100, 200) },
        ]},
        { group: 'Video', rows: [
            { label: 'FPS', value: fmt(fps), health: band(fps, 12, 6, true) },
            { label: 'Bitrate', value: `${fmt((v.kbps ?? 0) / 1000, 1)} mbps`, health: null },
            { label: 'Resolution', value: `${v.width ?? '—'}×${v.height ?? '—'}`, health: null },
            // H264 → HW decode (good); VP8 → usually software (warn).
            { label: 'Codec', value: v.codec || '—',
              health: v.codec ? (v.codec === 'H264' ? 'good' : 'warn') : null },
            { label: 'Loss', value: `${fmt(v.loss_pct, 1)} %`, health: band(v.loss_pct, 1, 3) },
            { label: 'Jitter buf', value: `${fmt(v.jitter_buffer_ms)} ms`, health: null },
            { label: 'Decode', value: `${fmt(v.decode_ms)} ms`, health: null },
            { label: 'E2E', value: v.e2e_latency_ms ? `${fmt(v.e2e_latency_ms)} ms` : '—',
              health: v.e2e_latency_ms ? band(v.e2e_latency_ms, 150, 300) : null },
            // freezes is a monotonic session total, not a rate: warn 8, bad 20.
            { label: 'Freezes', value: `${v.freezes ?? 0}`, health: band(v.freezes, 8, 20) },
        ]},
        { group: 'Command', rows: [
            { label: 'Latency', value: c ? `${fmt(c.latency_ms)} ms` : '—',
              health: c ? band(c.latency_ms, 100, 200) : null },
            { label: 'Jitter', value: c ? `${fmt(c.jitter_ms)} ms` : '—', health: null },
            { label: 'Send rate', value: `${fmt(state.liveStats.cmdHz)} Hz`, health: null },
            { label: 'Recv rate', value: c ? `${fmt(c.rate_hz)} Hz` : '—', health: null },
        ]},
    ];
}

// Hide the robot's 16px benchmark timestamp strip via a display-only clip-path
// sized to the object-contain content rect (stamp decoder still samples source).
export function applyStampCrop() {
    const v = document.getElementById('robot-cam');
    if (!v) return;
    const strip = state.liveStats.stampStripPx || 0;
    // Skip while PiP: clip-path cuts the rounded box and map shows through.
    if (!strip || !v.videoWidth || !v.clientHeight || v.classList.contains('is-pip')) {
        if (v.style.clipPath) v.style.clipPath = '';
        return;
    }
    const scale = Math.min(v.clientWidth / v.videoWidth, v.clientHeight / v.videoHeight);
    const padY = (v.clientHeight - v.videoHeight * scale) / 2;
    const bottom = padY + strip * scale;
    v.style.clipPath = `inset(0 0 ${bottom.toFixed(1)}px 0)`;
}

export function mountHud() {
    if (document.getElementById('live-hud')) return;
    const hud = document.createElement('div');
    hud.id = 'live-hud';
    hud.style.cssText =
        'position:fixed;top:12px;right:12px;z-index:50;font-family:ui-monospace,monospace;' +
        'user-select:none;background:rgba(21,21,21,0.92);border:1px solid #2a2a2a;' +
        'border-radius:10px;padding:10px 12px;color:#e5e7eb;font-size:12px;' +
        'backdrop-filter:blur(4px);min-width:236px;';
    hud.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;
            border-bottom:1px solid #2a2a2a;padding-bottom:7px;margin-bottom:7px;">
            <span id="live-hud-dot" style="width:9px;height:9px;border-radius:9999px;
                background:${HUD_WARN};"></span>
            <span id="live-hud-link" style="text-transform:uppercase;letter-spacing:0.1em;
                font-size:11px;font-weight:600;color:#b0e1f0;">—</span>
            <span id="live-hud-robot" style="margin-left:auto;color:#9ca3af;font-size:11px;"></span>
        </div>
        <pre id="live-hud-panel" style="margin:0;color:#cbd5e1;font-size:11px;
            line-height:1.6;white-space:pre;"></pre>`;
    document.body.appendChild(hud);

    let lastSampleMs = performance.now();
    state.hudTimer = setInterval(() => {
        const now = performance.now();
        sampleCmdHz((now - lastSampleMs) / 1000);
        lastSampleMs = now;
        refreshHud();
    }, 1000);
    refreshHud();
}

function refreshHud() {
    applyStampCrop();
    const dot = document.getElementById('live-hud-dot');
    if (!dot) return;
    dot.style.background = healthColor();
    const link = document.getElementById('live-hud-link');
    if (link) link.textContent = transportLabel();
    const robot = document.getElementById('live-hud-robot');
    if (robot) robot.textContent = state.activeRobot?.robot_name || '';
    const panel = document.getElementById('live-hud-panel');
    if (panel) panel.textContent = hudDetailLines().slice(1).join('\n');
}

export function unmountHud() {
    if (state.hudTimer) { clearInterval(state.hudTimer); state.hudTimer = null; }
    const hud = document.getElementById('live-hud');
    if (hud) hud.remove();
}
