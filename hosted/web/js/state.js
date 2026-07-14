// SECURITY: ?broker= is dev-only — in prod it would let a phishing link redirect every api() call (and the bearer token) to an attacker origin.
const isLocalDev = ['localhost', '127.0.0.1', '0.0.0.0'].includes(window.location.hostname);
const brokerParam = new URLSearchParams(window.location.search).get('broker') || '';

export const state = {
    token: localStorage.getItem('teleop_token') || '',
    refreshToken: localStorage.getItem('teleop_refresh') || '',
    userEmail: localStorage.getItem('teleop_email') || '',
    brokerOverride: isLocalDev ? brokerParam : '',

    setupInProgress: false,  // setupWebRTC re-entry guard
    pc: null,
    room: null,          // LiveKit Room (livekit transport only; null for cloudflare)
    cmdChannel: null,
    stateChannel: null,
    stateBackChannel: null,
    mapChannel: null,       // robot → operator map (occupancy grid + odom), unreliable
    micTrack: null,         // operator mic MediaStreamTrack (starts muted; cockpit toggles)
    xrSession: null,
    xrRefSpace: null,
    activeRobot: null,

    clockOffsetMs: 0,
    bestRttMs: Infinity,
    clockSyncBurstTimer: null,
    clockSyncDriftTimer: null,

    videoStatsTimer: null,
    videoStatsPrev: null,

    opHeartbeatTimer: null,

    kbInterval: null,
    kbKeys: new Set(),

    speedScale: { lin: 0.5, ang: 0.5 },

    liveStats: {
        video: null,
        rttMs: null,
        offsetMs: 0,
        cmdHz: 0,
        cmd: null,          // robot-measured: {latency_ms, jitter_ms, rate_hz, throughput_bps}
        soc: null,          // robot battery state-of-charge (%)
        iceType: null,      // 'direct' | 'stun' | 'turn' | null
        stampStripPx: 0,    // benchmark strip rows below the frame (0 = not stamping)
    },
    onCmdAck: null,         // view hook: (msg) => void for {type:cmd_ack,nonce,ok}
    onRobotState: null,     // view hook: (state) => void for robot_telemetry.state
    onMap: null,            // view hook: (msg) => void for {type:map,...} occupancy grid
    onOdom: null,           // view hook: (msg) => void for {type:odom,x,y,yaw,ts}
    onMicReady: null,       // view hook: () => void once mic track captured
    driveEnabled: true,     // gates WASD; go2 cockpit sets false until Stand/Drive
    poseMode: false,        // PoseStand: buildTwist maps keys to body-pose axes
    // stall.js: stalled drives overlay/HUD; blocked suppresses twist sends.
    videoStall: { stalled: false, blocked: false, armed: false },
    cmdSendCount: 0,        // rolling counter; sampled into cmdHz once/sec
    hudTimer: null,
    armHudTimer: null,

    xrSupported: false,
};

if (isLocalDev && !state.token) {
    state.token = 'dev-token';
    state.userEmail = 'dev@local';
}

export const sendInterval = 1000 / 80;
export const CLOCK_SYNC_BURST_COUNT = 5;
export const CLOCK_SYNC_BURST_INTERVAL_MS = 400;
export const CLOCK_SYNC_DRIFT_INTERVAL_MS = 30000;
export const VIDEO_STATS_INTERVAL_MS = 1000;
export const OP_HEARTBEAT_INTERVAL_MS = 5000;  // MUST stay under broker's ~20s reap window

// immersive-vr only: headsets (Quest) support it, phones don't.
export const xrDetection = (async () => {
    if (!navigator.xr) return false;
    state.xrSupported = await navigator.xr.isSessionSupported('immersive-vr').catch(() => false);
    return state.xrSupported;
})();

export function escHtml(s) {
    return s ? String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])) : '';
}

export function timeAgo(iso) {
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs/24)}d ago`;
}
