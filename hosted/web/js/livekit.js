// LiveKit transport (operator). Drop-in for setupWebRTC when robot's transport="livekit".
// Produces the same state.* surface (cmdChannel/stateChannel shims, robot-cam video) so keyboard/vr/hud/send/clock-sync work unchanged.

import { api } from './api.js';
import { ensureRobotCam, setStatus } from './dom.js';
import { state } from './state.js';
import {
    handleStateMessage, startClockSync, startOpHeartbeat,
    startVideoStats, stopVideoStats, timeout,
} from './webrtc.js';

const CMD_TOPIC = 'cmd_unreliable';
const STATE_TOPIC = 'state_reliable';
const STATE_BACK_TOPIC = 'state_reliable_back';
const CONNECT_TIMEOUT_MS = 20000;

// Reused per packet on the hot data path — don't allocate per message.
const DEC = new TextDecoder();
const ENC = new TextEncoder();

function toU8(bytes) {
    if (bytes instanceof Uint8Array) return bytes;
    if (bytes instanceof ArrayBuffer) return new Uint8Array(bytes);
    if (ArrayBuffer.isView(bytes)) return new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    return new Uint8Array(bytes);
}

export async function setupLiveKit(sessionId) {
    // Re-entry guard: a double-click Connect would spin up two Rooms fighting over state.*.
    if (state.setupInProgress) {
        throw new Error('Connect already in progress — disconnect first to retry');
    }
    state.setupInProgress = true;
    try {
        return await _setupLiveKitInner(sessionId);
    } finally {
        state.setupInProgress = false;
    }
}

async function _setupLiveKitInner(sessionId) {
    const LK = window.LivekitClient;
    if (!LK) throw new Error('LiveKit client SDK not loaded');
    setStatus('Connecting (LiveKit)...');

    // Broker mints a room-scoped token; LiveKit handles ICE/TURN, so no SDP exchange here.
    const data = await api('POST', `/sessions/${sessionId}/join`, { role: 'operator' });
    if (!data.url || !data.token) throw new Error('Broker did not return LiveKit url/token');

    // adaptiveStream would downgrade the hidden VR GL-texture <video>; teleop wants full rate — keep off.
    const room = new LK.Room({ adaptiveStream: false });
    state.room = room;

    let videoTrack = null;
    const maybeStartStats = () => {
        const receiver = videoTrack?.receiver;
        if (!receiver || !state.stateChannel) return;
        stopVideoStats();
        startVideoStats(state.stateChannel, () => receiver.getStats());
    };
    room.on(LK.RoomEvent.TrackSubscribed, (track) => {
        if (track.kind !== 'video') return;
        const existed = !!document.getElementById('robot-cam');
        const v = ensureRobotCam();
        // Detach prior track before rebinding — on a robot republish the old track + its receiver (held by stats sampler) would leak.
        if (videoTrack && videoTrack !== track) {
            try { videoTrack.detach(v); } catch (_) {}
        }
        track.attach(v);
        if (existed) v.style.display = 'block';
        v.play?.().catch(() => {});
        videoTrack = track;
        maybeStartStats();
    });

    // Robot replies on the back channel by protocol; LiveKit never echoes our own published data.
    room.on(LK.RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
        if (topic === STATE_BACK_TOPIC) {
            handleStateMessage(DEC.decode(payload));
        }
    });

    // Drop refs on terminal disconnect so send() doesn't fire into a dead Room and a fresh setup doesn't skip teardown.
    room.on(LK.RoomEvent.Disconnected, () => {
        console.info('[livekit] room disconnected');
        if (state.room === room) {
            stopVideoStats();
            state.room = null;
            state.cmdChannel = null;
            state.stateChannel = null;
        }
    });

    // On failure/timeout tear down the half-open Room — else it keeps reconnecting and a retry spins up a second Room.
    try {
        await Promise.race([
            room.connect(data.url, data.token),
            timeout(CONNECT_TIMEOUT_MS, 'Timed out connecting to LiveKit'),
        ]);
    } catch (err) {
        await room.disconnect().catch(() => {});
        if (state.room === room) state.room = null;
        throw err;
    }

    // DataChannel shims onto LiveKit topics: readyState tracks room.state so callers stop sending mid-reconnect; close() is a no-op; publishData rejections swallowed.
    const lp = room.localParticipant;
    const publish = (bytes, opts) => lp.publishData(bytes, opts).catch(() => {});
    const isOpen = () => (room.state === 'connected' ? 'open' : 'closed');
    state.cmdChannel = {
        get readyState() { return isOpen(); },
        send: (bytes) => publish(toU8(bytes), { reliable: false, topic: CMD_TOPIC }),
        close: () => {},
    };
    state.stateChannel = {
        get readyState() { return isOpen(); },
        send: (txt) => publish(ENC.encode(txt), { reliable: true, topic: STATE_TOPIC }),
        close: () => {},
    };

    startClockSync(state.stateChannel);
    startOpHeartbeat(sessionId);
    // maybeStartStats also runs from TrackSubscribed; whichever side runs second actually starts the sampler.
    maybeStartStats();
}
