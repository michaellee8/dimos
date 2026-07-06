// Immersive WebXR scene, Three.js edition: robot video on a world-anchored
// panel, live-stats quad pinned to its corner, controller poses + Joy
// streamed each frame. Replaces the hand-rolled WebGL version — same
// behavior, but three's WebXRManager owns the session/layers/reference-space
// plumbing (incl. the Quest makeXRCompatible quirk), and the scene graph is
// the foundation for pointclouds / robot models later.

import * as THREE from 'three';

import { geometry_msgs, sensor_msgs, std_msgs } from 'https://esm.sh/jsr/@dimos/msgs@0.1.4';
import { disconnect } from './disconnect.js';
import { renderStatsCanvas } from './hud.js';
import { sendInterval, state } from './state.js';
import { send } from './webrtc.js';

// World-stationary panel in local-floor — the headset moves around it (like a
// TV on a wall). local-floor's origin is where the user started, so these
// absolute coords sit in front of them at eye height.
const PANEL = { w: 1.2, h: 0.675, x: 0.0, y: 1.4, z: -1.5 };
// Stats quad offset from the panel center (its local frame): upper-right,
// slightly forward to avoid depth-fighting.
const STATS = { w: 0.34, h: 0.17, dx: 0.40, dy: 0.22, dz: 0.05 };

// Renderer/scene are module singletons reused across VR sessions — three
// keeps the GL context alive; only the XR session is per-connect.
let renderer = null;
let videoMesh = null;
let videoTex = null;
let statsTex = null;
let scene = null;
let camera = null;

function buildScene() {
    scene = new THREE.Scene();
    // XR overrides the projection per eye; params here only matter pre-entry.
    camera = new THREE.PerspectiveCamera(70, 1, 0.05, 100);

    videoMesh = new THREE.Mesh(
        new THREE.PlaneGeometry(PANEL.w, PANEL.h),
        new THREE.MeshBasicMaterial({ color: 0x0d0e0e }),  // placeholder until frames
    );
    videoMesh.position.set(PANEL.x, PANEL.y, PANEL.z);
    videoMesh.renderOrder = 1;
    scene.add(videoMesh);

    statsTex = new THREE.CanvasTexture(renderStatsCanvas());
    const statsMesh = new THREE.Mesh(
        new THREE.PlaneGeometry(STATS.w, STATS.h),
        new THREE.MeshBasicMaterial({ map: statsTex, transparent: true }),
    );
    statsMesh.position.set(STATS.dx, STATS.dy, STATS.dz);
    statsMesh.renderOrder = 2;
    videoMesh.add(statsMesh);  // child of the panel, moves with it
}

// Bind (or rebind, after reconnect swaps the element) the robot video to the
// panel, and crop the appended benchmark strip via the texture's UV window —
// the DOM views do the same with clip-path.
function updateVideoTexture() {
    const v = document.getElementById('robot-cam');
    if (!v || v.readyState < 2 || !v.videoWidth) return;
    if (!videoTex || videoTex.image !== v) {
        videoTex?.dispose();
        videoMesh.material.map?.dispose?.();
        videoTex = new THREE.VideoTexture(v);
        videoTex.colorSpace = THREE.SRGBColorSpace;
        videoMesh.material.dispose();
        videoMesh.material = new THREE.MeshBasicMaterial({ map: videoTex });
    }
    const strip = state.liveStats.stampStripPx || 0;
    const frac = strip && v.videoHeight ? strip / v.videoHeight : 0;
    videoTex.offset.y = frac;      // flipY texture: v=0 is the bottom row (the strip)
    videoTex.repeat.y = 1 - frac;
}

function processTracking(frame) {
    const now = performance.now();
    if (now - state.lastSendTime < sendInterval) return;
    state.lastSendTime = now;

    const refSpace = renderer.xr.getReferenceSpace();
    if (!refSpace) return;

    // Modality-agnostic: we just stream poses + Joy. The robot blueprint
    // decides what to do with them (arm IK or thumbstick → base velocity).
    for (const inputSource of frame.session.inputSources) {
        const trackingSpace = inputSource.gripSpace || inputSource.targetRaySpace;
        if (!trackingSpace) continue;
        const handedness = inputSource.handedness;
        if (handedness !== 'left' && handedness !== 'right') continue;

        const pose = frame.getPose(trackingSpace, refSpace);
        if (!pose) continue;

        const pos = pose.transform.position;
        const rot = pose.transform.orientation;
        const nowMs = Date.now() + state.clockOffsetMs;
        const stamp = new std_msgs.Time({
            sec: Math.floor(nowMs / 1000),
            nsec: (nowMs % 1000) * 1_000_000,
        });

        const poseStamped = new geometry_msgs.PoseStamped({
            header: new std_msgs.Header({ stamp, frame_id: handedness }),
            pose: new geometry_msgs.Pose({
                position: new geometry_msgs.Point({ x: pos.x, y: pos.y, z: pos.z }),
                orientation: new geometry_msgs.Quaternion({ x: rot.x, y: rot.y, z: rot.z, w: rot.w }),
            }),
        });
        send(poseStamped.encode());

        const gamepad = inputSource.gamepad;
        if (gamepad) {
            // Quest Touch thumbstick lives at axes[2]/[3]; [0]/[1] is the
            // dead legacy touchpad. Packed into Joy axes[0]/[1] for the robot.
            const stickX = gamepad.axes[2] ?? gamepad.axes[0] ?? 0.0;
            const stickY = gamepad.axes[3] ?? gamepad.axes[1] ?? 0.0;
            const axes = [
                stickX,
                stickY,
                gamepad.buttons[0]?.value ?? 0.0,
                gamepad.buttons[1]?.value ?? 0.0,
            ];
            const buttons = [];
            for (let i = 0; i < gamepad.buttons.length; i++) {
                buttons.push(gamepad.buttons[i]?.pressed ? 1 : 0);
            }
            const joyMsg = new sensor_msgs.Joy({
                header: new std_msgs.Header({ stamp, frame_id: handedness }),
                axes_length: axes.length,
                buttons_length: buttons.length,
                axes,
                buttons,
            });
            send(joyMsg.encode());
        }
    }
}

// Roll cmdSendCount → liveStats.cmdHz once per second. The browser HUD's
// hudTimer does this for the DOM views; VR drives it off the frame loop.
let lastCmdSampleMs = 0;
function sampleCmdHz(nowMs) {
    if (!lastCmdSampleMs) { lastCmdSampleMs = nowMs; return; }
    const dt = (nowMs - lastCmdSampleMs) / 1000;
    if (dt < 1.0) return;
    state.liveStats.cmdHz = state.cmdSendCount / dt;
    state.cmdSendCount = 0;
    lastCmdSampleMs = nowMs;
}

function onFrame(timeMs, frame) {
    if (frame) processTracking(frame);
    updateVideoTexture();
    renderStatsCanvas();          // redraw the 2D stats canvas…
    statsTex.needsUpdate = true;  // …and push it to the quad's texture
    sampleCmdHz(timeMs);
    renderer.render(scene, camera);
}

export async function startVR() {
    lastCmdSampleMs = 0;  // fresh session: don't delta against the last one's timestamp
    const canvas = document.getElementById('canvas');
    canvas.style.display = 'block';

    if (!renderer) {
        renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
        renderer.xr.enabled = true;
        renderer.xr.setReferenceSpaceType('local-floor');
        buildScene();
    }

    // AR passthrough when the headset offers it; VR otherwise. Must run
    // inside the Connect click's user gesture.
    let session = null;
    try {
        session = await navigator.xr.requestSession('immersive-ar', {
            requiredFeatures: ['local-floor'],
            optionalFeatures: ['hand-tracking'],
        });
    } catch (e) {
        session = await navigator.xr.requestSession('immersive-vr', {
            requiredFeatures: ['local-floor'],
            optionalFeatures: ['hand-tracking'],
        });
    }

    state.xrSession = session;
    await renderer.xr.setSession(session);  // three handles makeXRCompatible + baseLayer
    state.xrRefSpace = renderer.xr.getReferenceSpace();

    session.addEventListener('end', () => {
        state.xrSession = null;
        renderer.setAnimationLoop(null);
        disconnect();
    });
    renderer.setAnimationLoop(onFrame);
}
