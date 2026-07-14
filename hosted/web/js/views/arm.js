import { disconnect } from '../disconnect.js';
import { applyStampCrop, hudDetailRows, hudSummaryLine, sampleCmdHz, statsHealth, transportLabel } from '../hud.js';
import { createStallGate, videoMediaTime } from '../stall.js';
import { escHtml, sendInterval, state } from '../state.js';
import {
    buildEEFTwist, sendCameraSelect, sendEstop, sendEstopClear, sendGripper,
} from '../xarmcmd.js';

const LINEAR_SPEED = 0.12;   // m/s
const ANGULAR_SPEED = 0.8;   // rad/s

// key → [axis, sign] for LINEAR jog (no Shift)
const AXIS_KEYS = {
    w: ['x', +1], s: ['x', -1],
    a: ['y', +1], d: ['y', -1],
    q: ['z', +1], e: ['z', -1],
};

// key → [axis, sign] for ANGULAR jog (Shift): W/S pitch(Y), A/D roll(X), Q/E yaw(Z)
const ROT_AXIS_KEYS = {
    w: ['y', +1], s: ['y', -1],
    a: ['x', +1], d: ['x', -1],
    q: ['z', +1], e: ['z', -1],
};

const CAMS = [
    { id: 'cam1', label: 'Cam 1' },
    { id: 'cam2', label: 'Cam 2' },
];

const _held = new Set();
let _estopped = false;
let _gripperClosed = false;
let _estopNonce = 0;
// Single cam by default: selecting both makes the robot hstack into an unreadable side-by-side strip.
let _cams = ['cam1'];
let _camsRequested = false;
let _wasSending = false;

function trackedKey(e) {
    const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
    if (k in AXIS_KEYS || k === 'Shift' || k === ' ') return k === ' ' ? 'Space' : k;
    return null;
}

function onKeyDown(e) {
    const k = trackedKey(e);
    if (k === null) return;
    e.preventDefault();
    if (k === 'Space') {
        // Edge-triggered gripper toggle (once per press, not per repeat).
        if (!e.repeat) {
            _gripperClosed = !_gripperClosed;
            sendGripper(state.stateChannel, _gripperClosed);
            paintStatus();
        }
        return;
    }
    _held.add(k);
}
function onKeyUp(e) {
    const k = trackedKey(e);
    if (k === null) return;
    e.preventDefault();
    _held.delete(k);
}
function clearHeld() { _held.clear(); }

function buildTwist() {
    const linear = { x: 0, y: 0, z: 0 };
    const angular = { x: 0, y: 0, z: 0 };
    const rot = _held.has('Shift');
    const vec = rot ? angular : linear;
    const speed = rot ? ANGULAR_SPEED : LINEAR_SPEED;
    const map = rot ? ROT_AXIS_KEYS : AXIS_KEYS;
    for (const key of _held) {
        const b = map[key];
        if (b) vec[b[0]] += b[1] * speed;
    }
    return { linear, angular };
}

function triggerEstop() {
    if (_estopped) { _estopped = false; sendEstopClear(state.stateChannel, () => ++_estopNonce); }
    else { _estopped = true; sendEstop(state.stateChannel, () => ++_estopNonce); }
    paintStatus();
}

function paintStatus() {
    const grip = document.getElementById('arm-grip');
    if (grip) {
        grip.textContent = _gripperClosed ? 'CLOSED' : 'OPEN';
        grip.className = _gripperClosed ? 'text-amber-400 font-bold' : 'text-green-400 font-bold';
    }
    const chip = document.getElementById('arm-grip-chip');
    if (chip) chip.textContent = _gripperClosed ? 'GRIP CLOSED' : 'OPEN';
    const es = document.getElementById('arm-estop-btn');
    if (es) {
        es.textContent = _estopped ? 'E-STOP LATCHED — CLEAR' : 'E-STOP';
        es.className = _estopped
            ? 'w-full px-4 py-4 bg-red-900 border border-red-500 text-red-100 font-bold rounded-lg'
            : 'w-full px-4 py-4 bg-red-600 hover:bg-red-500 text-white font-bold rounded-lg';
    }
    renderCamTabs();
}

function paintKeys() {
    for (const key of ['w', 'a', 's', 'd', 'q', 'e']) {
        const el = document.getElementById(`arm-key-${key}`);
        if (el) el.classList.toggle('pressed', _held.has(key));
    }
    const shift = document.getElementById('arm-key-shift');
    if (shift) shift.classList.toggle('pressed', _held.has('Shift'));
    const title = document.getElementById('arm-key-title');
    if (title) title.textContent = _held.has('Shift') ? 'Rotate (Shift)' : 'Translate';
}

function renderCamTabs() {
    document.querySelectorAll('#arm-cam-tabs [data-cam]').forEach((b) => {
        const on = _cams.includes(b.dataset.cam);
        b.className = 'px-4 py-0.5 rounded text-[11px] leading-none border '
            + (on ? 'bg-dim-500 text-bg-950 border-dim-500' : 'border-[#2a2a2a] text-gray-400');
    });
}

function toggleCam(id) {
    const sel = new Set(_cams);
    if (sel.has(id)) {
        if (sel.size === 1) return;  // keep at least one camera on
        sel.delete(id);
    } else {
        sel.add(id);
    }
    _cams = CAMS.map((c) => c.id).filter((cid) => sel.has(cid));
    sendCameraSelect(state.stateChannel, _cams);
    renderCamTabs();
}

export function renderArm(c) {
    // Drop any stale #robot-cam left on <body> by a prior session: it precedes #app in
    // document order, so getElementById would return it and the WebRTC track would attach off-screen.
    document.querySelectorAll('#robot-cam').forEach((el) => {
        if (!el.closest('#app')) el.remove();
    });
    c.innerHTML = `
    <div class="min-h-screen flex flex-col md:flex-row gap-4 p-4 fade-in">
        <div class="flex-1 flex flex-col">
            <div class="flex items-center justify-between mb-2">
                <h1 class="text-2xl font-bold text-white">${escHtml(state.activeRobot?.robot_name || 'xArm teleop')}</h1>
                <button id="disconnectBtn" class="term-caps px-3 py-1.5 text-xs text-gray-400 hover:text-white border border-[#2a2a2a] rounded">[ disconnect ]</button>
            </div>
            <div id="teleop-status" class="text-sm text-gray-300 px-3 py-2 bg-bg-950 border border-[#2a2a2a] rounded-lg mb-3">Negotiating…</div>
            <div class="flex items-center gap-1.5 px-2 py-1 bg-bg-950 border border-[#2a2a2a] border-b-0 rounded-t-lg">
                <span class="term-caps text-[10px] text-gray-600 mr-1">Camera</span>
                <div class="flex items-center gap-1.5" id="arm-cam-tabs"></div>
            </div>
            <div class="relative w-full bg-black border-x border-[#2a2a2a] overflow-hidden" style="aspect-ratio:16/9;">
                <video id="robot-cam" autoplay muted playsinline
                    class="absolute inset-0 w-full h-full object-contain"
                    style="display:none;"></video>
                <div id="arm-twist-readout" class="absolute bottom-3 left-3 text-xs font-mono bg-black/40 rounded px-2 py-1 text-dim-400">
                    idle
                </div>
                <div class="absolute bottom-3 right-3">
                    <span class="pill pill-good"><span class="dot"></span><span id="arm-grip-chip">OPEN</span></span>
                </div>
            </div>
            <div class="border border-[#2a2a2a] rounded-b-lg p-3 flex items-center justify-between shrink-0 bg-bg-950">
                <div class="flex items-center gap-3 text-xs text-gray-500">
                    <span id="arm-live" class="pill pill-good"><span class="dot"></span>KEYBOARD LIVE</span>
                    <span>Jog:
                        <kbd class="px-1.5 py-0.5 bg-[#1f1f1f] rounded">W</kbd><kbd class="px-1.5 py-0.5 bg-[#1f1f1f] rounded">A</kbd><kbd class="px-1.5 py-0.5 bg-[#1f1f1f] rounded">S</kbd><kbd class="px-1.5 py-0.5 bg-[#1f1f1f] rounded">D</kbd><kbd class="px-1.5 py-0.5 bg-[#1f1f1f] rounded">Q</kbd><kbd class="px-1.5 py-0.5 bg-[#1f1f1f] rounded">E</kbd>
                        &nbsp;<span class="text-gray-600">Shift</span> rot &nbsp;<span class="text-gray-600">Space</span> grip
                    </span>
                </div>
            </div>
        </div>
        <div class="w-full md:w-72 flex flex-col gap-3">
            <section class="bg-bg-950 border border-[#2a2a2a] rounded-lg p-3">
                <button id="hud-toggle" class="w-full flex items-center justify-between mb-2">
                    <span class="term-caps text-xs text-gray-500">Telemetry <span id="hud-caret" class="text-gray-600">▸</span></span>
                    <span id="hud-health" class="pill pill-good"><span class="dot"></span><span id="hud-transport">—</span></span>
                </button>
                <pre id="hud-summary" class="text-xs text-dim-400 leading-relaxed">—</pre>
                <div id="hud-detail" class="hidden mt-2 pt-2 border-t border-[#2a2a2a] space-y-2.5"></div>
            </section>
            <div class="bg-bg-950 border border-[#2a2a2a] rounded-lg p-3 flex items-center justify-between">
                <span class="text-gray-400 text-xs term-caps">Gripper</span>
                <div class="flex items-center gap-2">
                    <span id="arm-grip" class="text-green-400 font-bold">OPEN</span>
                    <span class="text-gray-600 text-[10px]">Space</span>
                </div>
            </div>

            <section class="bg-bg-950 border border-[#2a2a2a] rounded-lg p-3">
                <div class="term-caps text-xs text-gray-500 mb-2" id="arm-key-title">Translate</div>
                <div class="flex flex-col items-center gap-2">
                    <div class="flex gap-2">
                        <div id="arm-key-q" class="kb-key kb-key-secondary">Q</div>
                        <div id="arm-key-w" class="kb-key">W</div>
                        <div id="arm-key-e" class="kb-key kb-key-secondary">E</div>
                    </div>
                    <div class="flex gap-2">
                        <div id="arm-key-a" class="kb-key">A</div>
                        <div id="arm-key-s" class="kb-key">S</div>
                        <div id="arm-key-d" class="kb-key">D</div>
                    </div>
                    <div class="flex gap-2">
                        <div id="arm-key-shift" class="kb-key wide">Shift</div>
                    </div>
                </div>
                <div class="mt-3 text-[11px] text-gray-500 leading-relaxed">
                    <div><span class="text-gray-300">W/S</span> ±X &nbsp; <span class="text-gray-300">A/D</span> ±Y &nbsp; <span class="text-gray-300">Q/E</span> ±Z</div>
                    <div><span class="text-gray-300">Shift</span>: W/S pitch · A/D roll · Q/E yaw</div>
                    <div><span class="text-gray-300">Space</span> gripper</div>
                </div>
            </section>

            <button id="arm-estop-btn"
                class="w-full px-4 py-4 bg-red-600 hover:bg-red-500 text-white font-bold rounded-lg">E-STOP</button>
        </div>
    </div>`;

    document.getElementById('disconnectBtn').onclick = disconnect;
    document.getElementById('arm-estop-btn').onclick = triggerEstop;
    document.getElementById('robot-cam').addEventListener('resize', applyStampCrop);
    const tabs = document.getElementById('arm-cam-tabs');
    tabs.innerHTML = CAMS.map((c) =>
        `<button data-cam="${c.id}" class="px-4 py-0.5 rounded text-[11px] leading-none border border-[#2a2a2a] text-gray-400">${c.label}</button>`
    ).join('');
    tabs.querySelectorAll('[data-cam]').forEach((b) =>
        b.addEventListener('click', () => toggleCam(b.dataset.cam)));
    document.getElementById('hud-toggle').addEventListener('click', () => {
        const detail = document.getElementById('hud-detail');
        const collapsed = detail.classList.toggle('hidden');
        document.getElementById('hud-caret').textContent = collapsed ? '▸' : '▾';
        if (!collapsed) renderTelemetryGrid();
    });
    paintStatus();
}

const HEALTH_TINT = { good: 'text-[#b0e1f0]', warn: 'text-[#eab308]', bad: 'text-[#f3b4b4]' };

function renderTelemetryGrid() {
    const el = document.getElementById('hud-detail');
    if (!el || el.classList.contains('hidden')) return;
    el.innerHTML = hudDetailRows().map((g) => `
        <div>
            <div class="term-caps text-[10px] text-gray-600 mb-1">${g.group}</div>
            <div class="grid grid-cols-2 gap-x-3 gap-y-1">
                ${g.rows.map((r) => `
                    <span class="text-xs text-gray-500">${r.label}</span>
                    <span class="text-xs text-right font-mono ${HEALTH_TINT[r.health] || 'text-gray-300'}">${r.value}</span>
                `).join('')}
            </div>
        </div>`).join('');
}

function startHudTick() {
    stopHudTick();
    let last = performance.now();
    state.armHudTimer = setInterval(() => {
        const now = performance.now();
        sampleCmdHz((now - last) / 1000);
        last = now;
        const summary = document.getElementById('hud-summary');
        if (!summary) return;
        summary.textContent = hudSummaryLine();
        const health = statsHealth();
        const pill = document.getElementById('hud-health');
        if (pill) pill.className = `pill pill-${health}`;
        const tl = document.getElementById('hud-transport');
        if (tl) tl.textContent = transportLabel();
        renderTelemetryGrid();
        applyStampCrop();
    }, 1000);
}

function stopHudTick() {
    if (state.armHudTimer) { clearInterval(state.armHudTimer); state.armHudTimer = null; }
}

export function startArmLoop() {
    stopArmLoop();
    _held.clear();
    _estopped = false;
    _gripperClosed = false;
    _cams = ['cam1'];
    _camsRequested = false;
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    window.addEventListener('blur', clearHeld);
    startHudTick();

    const stallGate = createStallGate();
    state.videoStall = { stalled: false, blocked: false, armed: false };

    state.kbInterval = setInterval(() => {
        // One-shot: sync robot to default cam selection once the reliable channel opens.
        if (!_camsRequested && state.stateChannel && state.stateChannel.readyState === 'open') {
            sendCameraSelect(state.stateChannel, _cams);
            _camsRequested = true;
            paintStatus();
        }

        paintKeys();

        const chan = state.cmdChannel;
        const chanOk = !!chan && chan.readyState === 'open';

        const held = _held.size > 0;
        const gate = stallGate.sample(
            videoMediaTime(document.getElementById('robot-cam')), performance.now(), held,
        );
        state.videoStall = gate;

        const live = document.getElementById('arm-live');
        if (live) {
            const ok = chanOk && !gate.blocked && !_estopped;
            live.className = 'pill ' + (ok ? 'pill-good' : 'pill-bad');
            live.querySelector('.dot').nextSibling.textContent =
                _estopped ? 'E-STOP LATCHED'
                : gate.blocked ? 'JOG OFF — video stalled'
                : !chanOk ? 'CONNECTING…'
                : 'KEYBOARD LIVE';
        }

        if (!chanOk) return;

        // Send only while jogging (plus one zero-twist on release/block/estop): idle zero-twists
        // flood the datachannel and add latency. The robot's eef_twist holds when idle.
        const readout = document.getElementById('arm-twist-readout');
        const shouldStop = gate.blocked || _estopped || !held;
        if (shouldStop) {
            if (_wasSending) {
                const nowMs = Date.now() + state.clockOffsetMs;
                chan.send(buildEEFTwist({ x: 0, y: 0, z: 0 }, { x: 0, y: 0, z: 0 }, nowMs).encode());
                _wasSending = false;
            }
            if (readout) readout.textContent = _estopped ? 'E-STOP' : 'idle';
            return;
        }

        const { linear, angular } = buildTwist();
        const nowMs = Date.now() + state.clockOffsetMs;
        chan.send(buildEEFTwist(linear, angular, nowMs).encode());
        state.cmdSendCount++;
        _wasSending = true;

        if (readout) {
            readout.textContent = _held.has('Shift')
                ? `ω  r ${angular.x.toFixed(2)} · p ${angular.y.toFixed(2)} · y ${angular.z.toFixed(2)}`
                : `v  x ${linear.x.toFixed(2)} · y ${linear.y.toFixed(2)} · z ${linear.z.toFixed(2)}`;
        }
    }, sendInterval);
}

export function stopArmLoop() {
    window.removeEventListener('keydown', onKeyDown);
    window.removeEventListener('keyup', onKeyUp);
    window.removeEventListener('blur', clearHeld);
    if (state.kbInterval) { clearInterval(state.kbInterval); state.kbInterval = null; }
    stopHudTick();
    _held.clear();
}
