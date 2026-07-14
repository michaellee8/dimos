import { setStatus } from './dom.js';
import { mountHud } from './hud.js';
import { setupLiveKit } from './livekit.js';
import { navigate } from './router.js';
import { state } from './state.js';
import { startArmLoop, stopArmLoop } from './views/arm.js';
import { stopTick } from './views/go2.js';
import { startKeyboardLoop, stopKeyboardLoop } from './views/keyboard.js';
import { startVR } from './vr.js';
import { startArmVR } from './vrarm.js';
import { setupWebRTC } from './webrtc.js';

function setupTransport(sessionId, transport) {
    return transport === 'livekit' ? setupLiveKit(sessionId) : setupWebRTC(sessionId);
}

export async function connectToRobot(sessionId, robotName, transport) {
    state.activeRobot = { session_id: sessionId, robot_name: robotName, transport: transport || 'cloudflare' };
    try {
        if (!navigator.xr) throw new Error('WebXR not supported. Use Quest 3 browser.');

        navigate('teleop');
        // VR FIRST — gesture activation must be alive when requestSession() runs.
        await startVR();

        try {
            await setupTransport(sessionId, transport);
        } catch (rtcError) {
            if (state.xrSession) { await state.xrSession.end().catch(() => {}); state.xrSession = null; }
            throw rtcError;
        }
        setStatus(`Connected — ${robotName}`);
    } catch (e) {
        console.error(e);
        setStatus(`Connection failed: ${e.message}`);
        setTimeout(() => navigate('dashboard'), 3000);
    }
}

export async function connectXArm(sessionId, robotName, transport) {
    state.activeRobot = { session_id: sessionId, robot_name: robotName, transport: transport || 'cloudflare' };
    try {
        if (!navigator.xr) throw new Error('WebXR not supported. Use Quest 3 browser.');

        navigate('teleop');
        // VR FIRST — gesture activation must be alive when requestSession() runs.
        await startArmVR();

        try {
            await setupTransport(sessionId, transport);
        } catch (rtcError) {
            if (state.xrSession) { await state.xrSession.end().catch(() => {}); state.xrSession = null; }
            throw rtcError;
        }
        setStatus(`Connected — ${robotName}`);
    } catch (e) {
        console.error(e);
        setStatus(`Connection failed: ${e.message}`);
        setTimeout(() => navigate('dashboard'), 3000);
    }
}

export async function connectArmBrowser(sessionId, robotName, transport) {
    state.activeRobot = { session_id: sessionId, robot_name: robotName, transport: transport || 'cloudflare' };
    try {
        navigate('arm');
        await setupTransport(sessionId, transport);
        startArmLoop();
        setStatus(`Connected — ${robotName}`);
    } catch (e) {
        console.error(e);
        stopArmLoop();
        setStatus(`Connection failed: ${e.message}`);
        setTimeout(() => navigate('dashboard'), 3000);
    }
}

export async function connectKeyboard(sessionId, robotName, transport) {
    state.activeRobot = { session_id: sessionId, robot_name: robotName, transport: transport || 'cloudflare' };
    try {
        navigate('keyboard');
        await setupTransport(sessionId, transport);
        setStatus(`Connected — ${robotName}`);
        startKeyboardLoop();
        mountHud();
    } catch (e) {
        console.error(e);
        setStatus(`Connection failed: ${e.message}`);
        setTimeout(() => navigate('dashboard'), 3000);
    }
}

export async function connectGo2(sessionId, robotName, transport) {
    state.activeRobot = { session_id: sessionId, robot_name: robotName, transport: transport || 'cloudflare' };
    try {
        navigate('go2');  // renderGo2() starts the drive loop + telemetry tick itself
        await setupTransport(sessionId, transport);
        setStatus(`Connected — ${robotName}`);
    } catch (e) {
        console.error(e);
        // renderGo2 already started the drive loop + tick; stop them or they stack across retries.
        stopKeyboardLoop();
        stopTick();
        setStatus(`Connection failed: ${e.message}`);
        setTimeout(() => navigate('dashboard'), 3000);
    }
}
