// Shared Go2 command constants — MUST stay identical between the DOM cockpit
// (views/go2.js) and the VR cockpit (vrui.js) so the two can't drift.

// mode/scale MUST match firmware: normal/high scale velocity browser-side; rage
// also flips the firmware Rage FSM (set_mode). rage lin > 1.0 to exploit the
// ~2.5 m/s envelope (buildTwist's Shift can add ×2 on top).
export const SPEEDS = [
    { mode: 'normal', label: 'Normal', scale: { lin: 0.5, ang: 0.5 } },
    { mode: 'high', label: 'High', scale: { lin: 1.0, ang: 1.0 } },
    { mode: 'rage', label: 'Rage', scale: { lin: 2.0, ang: 1.5 } },
];

// Confirm-gated acrobatics; MUST mirror the robot-side allow-list.
export const CONFIRM_ACTIONS = new Set(['FrontPounce', 'FrontJump']);

// Sport-command name → latched posture reflected on a confirmed ack.
export const POSTURE_STATE = {
    StandReady: 'StandReady', PoseStand: 'PoseStand', StandDown: 'StandDown',
    RecoveryStand: 'RecoveryStand', Sit: 'Sit',
};

// E-STOP send (DOM/VR-panel/VR-button). Latch via dedicated estop type + legacy
// Damp for older robots; fire-and-forget on the reliable channel.
export function sendEstop(chan, nonce) {
    // Channel down: motion still halts (local latch + cmd_vel deadman once twists
    // stop) but the robot-side latch isn't set — warn so it's diagnosable.
    if (!chan || chan.readyState !== 'open') {
        console.warn('[estop] state channel not open — latched locally, robot not notified');
        return;
    }
    chan.send(JSON.stringify({ type: 'estop', nonce: nonce() }));
    chan.send(JSON.stringify({ type: 'sport_cmd', name: 'Damp', nonce: nonce() }));
}
export function sendEstopClear(chan, nonce) {
    if (!chan || chan.readyState !== 'open') return;
    chan.send(JSON.stringify({ type: 'estop_clear', nonce: nonce() }));
}
