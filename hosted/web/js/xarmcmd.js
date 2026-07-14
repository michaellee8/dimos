// Shared xArm command builders — MUST stay in sync with the robot side
// (ArmHostedConnection) and with the VR cockpit (vrarm.js). Parallel to go2cmd.js.
// cmd_unreliable (state.cmdChannel): LCM PoseStamped + Joy, ABSOLUTE WebXR
// gripSpace poses (robot's webxr_to_robot owns frame conversion + re-bases on
// engage). state_reliable (state.stateChannel): JSON control plane, acked on
// state_reliable_back.

import { geometry_msgs, sensor_msgs, std_msgs } from 'https://esm.sh/jsr/@dimos/msgs@0.1.4';

// nowMs is robot-clock time (Date.now() + state.clockOffsetMs); feeds command
// latency stats only, not IK.
function stamp(nowMs) {
    return new std_msgs.Time({ sec: Math.floor(nowMs / 1000), nsec: (nowMs % 1000) * 1_000_000 });
}

// frame_id carries handedness ("left"/"right") for hand routing + L/R alignment
// — NOT a coordinate frame. position/orientation passed through raw (no conversion).
export function buildPoseStamped(handedness, position, orientation, nowMs) {
    return new geometry_msgs.PoseStamped({
        header: new std_msgs.Header({ stamp: stamp(nowMs), frame_id: handedness }),
        pose: new geometry_msgs.Pose({
            position: new geometry_msgs.Point({ x: position.x, y: position.y, z: position.z }),
            orientation: new geometry_msgs.Quaternion({
                x: orientation.x, y: orientation.y, z: orientation.z, w: orientation.w,
            }),
        }),
    });
}

// Gamepad → Joy. Robot requires axes ≥4 and buttons ≥7 or it drops the frame.
export function buildJoy(handedness, gamepad, nowMs) {
    // xr-standard exposes the thumbstick on axes[2]/[3]; older mappings on [0]/[1].
    const xr = gamepad.mapping === 'xr-standard';
    const stickX = (xr ? gamepad.axes[2] : gamepad.axes[0]) ?? 0.0;
    const stickY = (xr ? gamepad.axes[3] : gamepad.axes[1]) ?? 0.0;
    const axes = [
        stickX,
        stickY,
        gamepad.buttons[0]?.value ?? 0.0,  // trigger analog → gripper
        gamepad.buttons[1]?.value ?? 0.0,  // grip analog
    ];
    // Robot reads button indices 0-6 (trigger, grip, touchpad, thumbstick, X/A, Y/B, menu).
    const buttons = [];
    for (let i = 0; i < gamepad.buttons.length; i++) {
        buttons.push(gamepad.buttons[i]?.pressed ? 1 : 0);
    }
    return new sensor_msgs.Joy({
        header: new std_msgs.Header({ stamp: stamp(nowMs), frame_id: handedness }),
        axes_length: axes.length,
        buttons_length: buttons.length,
        axes,
        buttons,
    });
}

// EE-twist jog (cmd_unreliable). frame_id "eef_twist_arm" routes to the
// coordinator's EEFTwistTask. linear = X/Y/Z m/s, angular = roll/pitch/yaw rad/s.
export function buildEEFTwist(linear, angular, nowMs) {
    return new geometry_msgs.TwistStamped({
        header: new std_msgs.Header({ stamp: stamp(nowMs), frame_id: 'eef_twist_arm' }),
        twist: new geometry_msgs.Twist({
            linear: new geometry_msgs.Vector3({ x: linear.x, y: linear.y, z: linear.z }),
            angular: new geometry_msgs.Vector3({ x: angular.x, y: angular.y, z: angular.z }),
        }),
    });
}

function chanReady(chan) {
    return chan && chan.readyState === 'open';
}

export function sendGripper(chan, closed) {
    if (!chanReady(chan)) return;
    chan.send(JSON.stringify({ type: 'gripper', closed: !!closed }));
}

// E-STOP latch. Unlike the Go2, the arm latches on the estop type alone (no Damp)
// and freezes the coordinator target.
export function sendEstop(chan, nonce) {
    if (!chanReady(chan)) return;
    chan.send(JSON.stringify({ type: 'estop', nonce: nonce() }));
}

// Clear the latch. Does NOT resume motion — hands stay disengaged until the
// operator releases and re-presses engage.
export function sendEstopClear(chan, nonce) {
    if (!chanReady(chan)) return;
    chan.send(JSON.stringify({ type: 'estop_clear', nonce: nonce() }));
}

// Names filtered to known ("cam1"/"cam2") robot-side; empty → first cam.
export function sendCameraSelect(chan, cams) {
    if (!chanReady(chan)) return;
    chan.send(JSON.stringify({ type: 'camera_select', cams }));
}
