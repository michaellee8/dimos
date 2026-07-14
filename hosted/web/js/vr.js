import * as THREE from 'three';

import { geometry_msgs, std_msgs } from 'https://esm.sh/jsr/@dimos/msgs@0.1.4';
import { disconnect } from './disconnect.js';
import { sendEstop } from './go2cmd.js';
import { sampleCmdHz } from './hud.js';
import { createStallGate, videoMediaTime } from './stall.js';
import { sendInterval, state } from './state.js';
import { getVRRenderer } from './vrrenderer.js';
import { buildCockpit, onCmdAck, onMap, onOdom, onRobotState, vui } from './vrui.js';

const HEAD = new THREE.Vector3(0, 1.55, 0);
// MUST agree with buildCockpit's CAM_HALF_W / PANEL_Y / PANEL_Z (map + stats sit flush).
const CAM = { w: 1.4, h: 0.7875, x: 0, y: 1.52, z: -1.6 };
const STICK_DEADZONE = 0.12;

let renderer = null, scene = null, camera = null;
let cockpit = null, controllers = [];
let videoMesh = null, videoTex = null;
let stallGate = null;
let camEl = null;
const raycaster = new THREE.Raycaster();
const _rayOrigin = new THREE.Vector3();
const _rayDir = new THREE.Vector3();

function buildScene() {
    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(70, 1, 0.05, 100);

    videoMesh = new THREE.Mesh(
        new THREE.PlaneGeometry(CAM.w, CAM.h),
        new THREE.MeshBasicMaterial({ color: 0x0d0e0e }),
    );
    videoMesh.position.set(CAM.x, CAM.y, CAM.z);
    // Flat (+Z toward user), NOT lookAt: map/stats sit coplanar flush against this panel's edges.
    videoMesh.renderOrder = 1;
    scene.add(videoMesh);

    cockpit = buildCockpit(scene, HEAD);
}

function initControllers() {
    const lineGeo = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, 0, -5),
    ]);
    for (let i = 0; i < 2; i++) {
        const ctrl = renderer.xr.getController(i);
        const laser = new THREE.Line(lineGeo, new THREE.LineBasicMaterial({ color: 0xb0e1f0, transparent: true, opacity: 0.5 }));
        laser.scale.z = 1;
        ctrl.add(laser);
        const dot = new THREE.Mesh(
            new THREE.SphereGeometry(0.012, 12, 12),
            new THREE.MeshBasicMaterial({ color: 0xb0e1f0 }),
        );
        dot.visible = false;
        ctrl.userData.dot = dot;
        scene.add(dot);
        ctrl.addEventListener('selectstart', () => onSelect(ctrl));
        scene.add(ctrl);
        controllers.push(ctrl);
    }
}

function onSelect(ctrl) {
    const hit = raycastPanels(ctrl);
    if (hit) cockpit.onClick(hit.object.userData.panel, hit.uv);
}

function raycastPanels(ctrl) {
    _rayOrigin.setFromMatrixPosition(ctrl.matrixWorld);
    _rayDir.set(0, 0, -1).applyQuaternion(ctrl.quaternion).normalize();
    raycaster.set(_rayOrigin, _rayDir);
    const hits = raycaster.intersectObjects(cockpit.meshes, false);
    return hits.length ? hits[0] : null;
}

function updateVideoTexture() {
    const v = camEl;
    if (!v || v.readyState < 2 || !v.videoWidth) return;
    if (!videoTex || videoTex.image !== v) {
        videoTex?.dispose();
        videoTex = new THREE.VideoTexture(v);
        videoTex.colorSpace = THREE.SRGBColorSpace;
        videoMesh.material.dispose();
        videoMesh.material = new THREE.MeshBasicMaterial({ map: videoTex });
    }
    const strip = state.liveStats.stampStripPx || 0;
    const frac = strip && v.videoHeight ? strip / v.videoHeight : 0;
    videoTex.offset.y = frac;
    videoTex.repeat.y = 1 - frac;
}

// Thumbstick → TwistStamped, identical shape/scale to keyboard.js buildTwist.
let lastDriveSend = 0;
let twistSeq = 0;
let wasDriving = false;

function driveFromSticks(frame) {
    const now = performance.now();
    if (now - lastDriveSend < sendInterval) return;
    lastDriveSend = now;

    // Read sticks FIRST: the stall gate needs the held-state to keep drive
    // blocked after a freeze clears until the operator releases the stick.
    let lx = 0, ly = 0, rx = 0, boost = 1;
    for (const src of frame.session.inputSources) {
        const gp = src.gamepad;
        if (!gp) continue;
        const ax = gp.axes;
        const sx = ax[2] ?? ax[0] ?? 0, sy = ax[3] ?? ax[1] ?? 0;
        if (src.handedness === 'left') { lx += sx; ly += sy; }
        else if (src.handedness === 'right') { rx += sx; }
        if (gp.buttons[1]?.pressed) boost = src.handedness === 'right' ? 2.0 : 0.5;  // grip
        if (gp.buttons[5]?.pressed) triggerEstop();  // B/Y — hardware E-STOP
    }
    const dz = (n) => (Math.abs(n) < STICK_DEADZONE ? 0 : n);
    const fwd = -dz(ly), strafe = -dz(lx), turn = -dz(rx);
    const held = fwd !== 0 || strafe !== 0 || turn !== 0;

    const gate = stallGate.sample(videoMediaTime(camEl), now, held);
    state.videoStall = gate;

    const canDrive = state.driveEnabled && !vui.estopped && !gate.blocked
        && state.cmdChannel && state.cmdChannel.readyState === 'open';
    if (!canDrive) {
        if (wasDriving) { sendTwist(0, 0, 0); wasDriving = false; }  // one stop then quiet
        return;
    }
    if (fwd === 0 && strafe === 0 && turn === 0) {
        if (wasDriving) { sendTwist(0, 0, 0); wasDriving = false; }
        return;
    }
    const sp = state.speedScale || { lin: 0.5, ang: 0.5 };
    sendTwist(fwd * boost * sp.lin, strafe * boost * sp.lin, turn * boost * sp.ang);
    wasDriving = true;
}

function sendTwist(lx, ly, az) {
    if (!state.cmdChannel || state.cmdChannel.readyState !== 'open') return;
    const nowMs = Date.now() + state.clockOffsetMs;
    const ts = new std_msgs.Time({ sec: Math.floor(nowMs / 1000), nsec: (nowMs % 1000) * 1_000_000 });
    twistSeq = (twistSeq + 1) & 0x7fffffff;
    const twist = new geometry_msgs.TwistStamped({
        header: new std_msgs.Header({ stamp: ts, frame_id: 'vr', seq: twistSeq }),
        twist: new geometry_msgs.Twist({
            linear: new geometry_msgs.Vector3({ x: lx, y: ly, z: 0 }),
            angular: new geometry_msgs.Vector3({ x: 0, y: 0, z: az }),
        }),
    });
    state.cmdChannel.send(twist.encode());
    state.cmdSendCount++;
}

let _estopCooldown = 0;
function triggerEstop() {
    const now = performance.now();
    if (now < _estopCooldown || vui.estopped) return;
    _estopCooldown = now + 1500;  // debounce the physical button
    vui.estopped = true;
    sendEstop(state.stateChannel, () => ++vui.nonce);
    cockpit.panels.forEach((p) => p.markDirty());
}

let lastCmdSampleMs = 0;
function tickCmdHz(nowMs) {
    if (!lastCmdSampleMs) { lastCmdSampleMs = nowMs; return; }
    if (nowMs - lastCmdSampleMs < 1000) return;
    sampleCmdHz((nowMs - lastCmdSampleMs) / 1000);
    lastCmdSampleMs = nowMs;
}

function updateHover() {
    for (const p of cockpit.panels) p.setHover(null);
    for (const ctrl of controllers) {
        const dot = ctrl.userData.dot;
        const hit = raycastPanels(ctrl);
        if (!hit) { dot.visible = false; continue; }
        dot.visible = true;
        dot.position.copy(hit.point);
        const panel = hit.object.userData.panel;
        panel.setHover(panel.hitTest(hit.uv));
    }
}

function onFrame(timeMs, frame) {
    // #robot-cam is created by webrtc.js ontrack (after startVR); resolve once, then reuse.
    if (!camEl) camEl = document.getElementById('robot-cam');
    if (frame) { driveFromSticks(frame); }
    updateHover();
    updateVideoTexture();
    if (videoMesh.material.map) {
        const stalled = vui.robotVideoStalled || state.videoStall?.stalled;
        videoMesh.material.color.setHex(stalled ? 0x552222 : 0xffffff);
    }
    cockpit.tick(timeMs);
    tickCmdHz(timeMs);
    renderer.render(scene, camera);
}

export async function startVR() {
    lastCmdSampleMs = 0; lastDriveSend = 0; wasDriving = false;
    stallGate = createStallGate();
    state.videoStall = { stalled: false, blocked: false, armed: false };
    document.getElementById('canvas').style.display = 'block';
    renderer = getVRRenderer();
    buildScene();
    controllers = [];

    // Passthrough (AR) when available; opaque VR otherwise. MUST run inside the Connect click gesture.
    let session = null, ar = false;
    try {
        session = await navigator.xr.requestSession('immersive-ar', {
            requiredFeatures: ['local-floor'], optionalFeatures: ['hand-tracking'],
        });
        ar = true;
    } catch (e) {
        session = await navigator.xr.requestSession('immersive-vr', {
            requiredFeatures: ['local-floor'], optionalFeatures: ['hand-tracking'],
        });
    }
    scene.background = ar ? null : new THREE.Color(0x0a0b0b);
    renderer.setClearAlpha(ar ? 0 : 1);

    state.xrSession = session;
    await renderer.xr.setSession(session);
    state.xrRefSpace = renderer.xr.getReferenceSpace();
    initControllers();

    state.onCmdAck = onCmdAck;
    state.onRobotState = onRobotState;
    state.onMap = onMap;
    state.onOdom = onOdom;

    session.addEventListener('end', () => {
        state.xrSession = null;
        state.onCmdAck = state.onRobotState = state.onMap = state.onOdom = null;
        renderer.setAnimationLoop(null);
        cockpit?.dispose();
        cockpit = null;
        videoTex?.dispose(); videoTex = null;
        videoMesh?.geometry.dispose(); videoMesh?.material.dispose(); videoMesh = null;
        camEl = null;
        disconnect();
    });
    renderer.setAnimationLoop(onFrame);
}
