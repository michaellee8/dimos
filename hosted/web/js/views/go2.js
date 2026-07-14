import { disconnect } from '../disconnect.js';
import { CONFIRM_ACTIONS, POSTURE_STATE, SPEEDS, sendEstop, sendEstopClear } from '../go2cmd.js';
import { applyStampCrop, hudDetailRows, hudSummaryLine, sampleCmdHz, socHealth, statsHealth, transportLabel } from '../hud.js';
import { escHtml, state } from '../state.js';
import { startKeyboardLoop } from './keyboard.js';

const POSTURE = [
    { name: 'StandReady', label: 'Stand / Drive' },
    { name: 'StandDown', label: 'Sit' },
];
const ACTIONS = [
    { name: 'Hello', label: 'Shake Hand' },
    { name: 'Stretch', label: 'Stretch' },
    { name: 'FrontPounce', label: 'Pounce' },
    { name: 'FrontJump', label: 'Jump Forward' },
];

const CAMS = [
    { id: 'cam1', label: 'Cam 1' },
    { id: 'cam2', label: 'Cam 2' },
];

const ui = {
    posture: 'StandReady',
    estopped: false,
    speedMode: 'normal',
    selectedCams: ['cam1'],
    obstacleAvoid: true,
    light: 0,
    lightDragging: false,
    robotVideoStalled: false,
    nonce: 0,
    pending: new Map(),
    mainView: 'camera',
    lastMap: null,
    lastOdom: null,
    navGoal: null,
    mapZoom: 1,
    mapPanX: 0, mapPanY: 0,
    pipW: 192, pipH: 120,
};

let tickTimer = null;

function cmdReady() {
    return state.stateChannel && state.stateChannel.readyState === 'open' && !ui.estopped;
}

export function renderGo2(c) {
    const btn = (cmd) =>
        `<button class="cmd-btn relative" data-cmd="${cmd.name}" data-status="idle"><span>${cmd.label}</span></button>`;

    c.innerHTML = `
    <div class="h-screen flex flex-col p-3 lg:p-4 fade-in">
        <header class="flex items-center justify-between mb-3 shrink-0">
            <div class="flex items-center gap-4">
                <span class="crt-glow text-dim-500 font-bold tracking-widest text-lg">DIMENSIONAL</span>
                <span class="term-caps text-gray-600 text-xs">// GO2 TELEOP</span>
                <span class="text-gray-300 text-sm">${escHtml(state.activeRobot?.robot_name || 'go2')}</span>
            </div>
            <div class="flex items-center gap-3">
                <span id="link-pill" class="pill pill-good"><span class="dot"></span><span>LINK OK</span></span>
                <button id="disconnectBtn" class="term-caps px-3 py-1.5 text-xs text-gray-400 hover:text-white border border-[#2a2a2a] rounded">[ disconnect ]</button>
            </div>
        </header>

        <div class="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[1fr_400px] gap-4">
            <section class="bg-bg-950 border border-[#2a2a2a] rounded-xl overflow-hidden flex flex-col min-h-0">
                <div class="flex items-center gap-1.5 px-2 py-1 border-b border-[#2a2a2a] shrink-0">
                    <button id="view-swap" class="strip-btn term-caps tracking-normal" title="Swap camera / map">
                        <span id="view-swap-label">MAP VIEW</span>
                    </button>
                    <button id="mic-toggle" class="strip-btn term-caps tracking-normal" title="Operator mic → robot">
                        <span id="mic-toggle-label">AUDIO OFF</span>
                    </button>
                    <div class="flex items-center gap-1.5 ml-auto" id="cam-tabs"></div>
                </div>
                <div class="relative flex-1 bg-black flex items-center justify-center min-h-0" id="stage">
                    <video id="robot-cam" autoplay muted playsinline
                        class="object-contain is-main" style="display:none;"></video>
                    <canvas id="map-canvas" class="is-pip"></canvas>
                    <div id="pip-resize" title="Drag to resize"></div>
                    <div id="video-placeholder" class="absolute inset-0 flex flex-col items-center justify-center text-center text-gray-500">
                        <div class="text-6xl mb-3">🐕</div>
                        <div id="teleop-status" class="text-lg text-gray-300 px-4 py-2 bg-bg-950/80 border border-[#2a2a2a] rounded-lg">
                            Negotiating WebRTC…
                        </div>
                    </div>
                    <div id="video-lost" class="hidden absolute inset-0 bg-black/70 flex flex-col items-center justify-center">
                        <div class="text-4xl mb-2">⚠</div>
                        <div class="term-caps text-sm text-[#f3b4b4]">video stalled — drive disabled</div>
                    </div>
                    <div class="absolute bottom-3 left-3 text-xs font-mono bg-black/40 rounded px-2 py-1 text-dim-400" id="twist-readout">
                        x 0.00 · y 0.00 · ω 0.00
                    </div>
                    <div class="absolute bottom-3 right-3">
                        <span class="pill pill-good"><span class="dot"></span><span id="posture-chip">STANDING</span></span>
                    </div>
                </div>
                <div class="border-t border-[#2a2a2a] p-3 flex items-center justify-between shrink-0">
                    <div class="flex items-center gap-3 text-xs text-gray-500">
                        <span id="kb-live" class="pill pill-good"><span class="dot"></span>KEYBOARD LIVE</span>
                        <span>Drive: <kbd class="px-1.5 py-0.5 bg-[#1f1f1f] rounded">W</kbd><kbd class="px-1.5 py-0.5 bg-[#1f1f1f] rounded">A</kbd><kbd class="px-1.5 py-0.5 bg-[#1f1f1f] rounded">S</kbd><kbd class="px-1.5 py-0.5 bg-[#1f1f1f] rounded">D</kbd></span>
                    </div>
                </div>
            </section>

            <aside class="flex flex-col gap-2 min-h-0 overflow-y-auto pr-1">
                <div id="blocked" class="hidden blocked-banner rounded-md px-3 py-2 text-xs term-caps shrink-0"></div>

                <section class="bg-bg-950 border border-[#2a2a2a] rounded-md p-3 shrink-0 flex items-center justify-between">
                    <span class="text-sm text-gray-400">🔋 Battery</span>
                    <span id="batt-pct" class="text-sm font-semibold text-dim-400">—%</span>
                </section>

                <section class="bg-bg-950 border border-[#2a2a2a] rounded-md p-3 shrink-0 flex items-center justify-between">
                    <span class="text-sm text-gray-400">Obstacle avoidance</span>
                    <button id="obstacle-toggle" class="px-3 py-1 text-xs term-caps rounded border border-dim-700 text-dim-400">ON</button>
                </section>


                <section class="bg-bg-950 border border-[#2a2a2a] rounded-md p-3 shrink-0 flex items-center gap-3">
                    <span class="text-sm text-gray-400 shrink-0">💡 Light</span>
                    <input id="light-slider" type="range" min="0" max="1" step="0.1" value="0"
                        class="flex-1 accent-[#b0e1f0]">
                    <span id="light-val" class="text-xs font-mono text-dim-400 w-10 text-right">0%</span>
                </section>

                <section class="bg-bg-950 border border-[#2a2a2a] rounded-md p-3 shrink-0">
                    <button id="hud-toggle" class="w-full flex items-center justify-between mb-2">
                        <span class="term-caps text-xs text-gray-500">Telemetry <span id="hud-caret" class="text-gray-600">▸</span></span>
                        <span id="hud-health" class="pill pill-good"><span class="dot"></span><span id="hud-transport">Cloudflare</span></span>
                    </button>
                    <pre id="hud-summary" class="text-xs text-dim-400 leading-relaxed">—</pre>
                    <div id="hud-detail" class="hidden mt-2 pt-2 border-t border-[#2a2a2a] space-y-2.5"></div>
                </section>

                <section class="bg-bg-950 border border-[#2a2a2a] rounded-md p-3 shrink-0">
                    <div class="term-caps text-xs text-gray-500 mb-2">Posture</div>
                    <div class="grid grid-cols-2 gap-2">${POSTURE.map(btn).join('')}</div>
                </section>

                <section class="bg-bg-950 border border-[#2a2a2a] rounded-md p-3 shrink-0">
                    <div class="term-caps text-xs text-gray-500 mb-2">Actions</div>
                    <div class="grid grid-cols-2 gap-2">${ACTIONS.map(btn).join('')}</div>
                </section>

                <section class="bg-bg-950 border border-[#2a2a2a] rounded-md p-3 shrink-0">
                    <div class="term-caps text-xs text-gray-500 mb-2">Speed</div>
                    <div class="grid grid-cols-3 gap-2" id="speed-bar"></div>
                </section>

                <section class="bg-bg-950 border border-[#2a2a2a] rounded-md p-3 shrink-0">
                    <div class="term-caps text-xs text-gray-500 mb-2" id="drive-title">Drive</div>
                    <div class="flex flex-col items-center gap-2">
                        <div class="flex gap-2">
                            <div id="key-q" class="kb-key kb-key-secondary">Q</div>
                            <div id="key-w" class="kb-key">W</div>
                            <div id="key-e" class="kb-key kb-key-secondary">E</div>
                        </div>
                        <div class="flex gap-2">
                            <div id="key-a" class="kb-key">A</div>
                            <div id="key-s" class="kb-key">S</div>
                            <div id="key-d" class="kb-key">D</div>
                        </div>
                    </div>
                    <div class="mt-3 text-[11px] text-gray-500 leading-relaxed" id="drive-hints">
                        <div><span class="text-gray-300">W/S</span> forward · back &nbsp; <span class="text-gray-300">A/D</span> turn left · right</div>
                        <div><span class="text-gray-300">Q/E</span> strafe left · right</div>
                        <div><span class="text-gray-300">Shift</span> 2× fast &nbsp; <span class="text-gray-300">Space</span> ½× slow</div>
                    </div>
                </section>

                <section id="estop-dock" class="sticky bottom-0 z-10 mt-auto bg-bg-950 border border-[#2a2a2a] rounded-md p-3 shrink-0 shadow-lg">
                    <button id="estop" class="estop">■ EMERGENCY STOP</button>
                    <button id="rearm" class="hidden mt-2 w-full py-2 text-xs term-caps text-gray-300 border border-[#2a2a2a] rounded hover:border-dim-700">
                        re-arm →
                    </button>
                </section>
            </aside>
        </div>
    </div>`;

    wireGo2();
    refreshControls();
    startTick();
    startKeyboardLoop();
}

function wireGo2() {
    document.getElementById('disconnectBtn').onclick = disconnect;

    document.getElementById('hud-toggle').addEventListener('click', () => {
        const detail = document.getElementById('hud-detail');
        const collapsed = detail.classList.toggle('hidden');
        document.getElementById('hud-caret').textContent = collapsed ? '▸' : '▾';
        if (!collapsed) renderTelemetryGrid();
    });

    const tabs = document.getElementById('cam-tabs');
    tabs.innerHTML = CAMS.map((c) =>
        `<button data-cam="${c.id}" class="px-4 py-0.5 rounded text-[11px] leading-none border border-[#2a2a2a] text-gray-400">${c.label}</button>`
    ).join('');
    tabs.querySelectorAll('[data-cam]').forEach((b) =>
        b.addEventListener('click', () => toggleCam(b.dataset.cam)));
    renderCamTabs();

    const bar = document.getElementById('speed-bar');
    bar.innerHTML = SPEEDS.map((s) =>
        `<button class="cmd-btn" data-speed="${s.mode}" data-status="idle"><span>${s.label}</span></button>`
    ).join('');
    bar.querySelectorAll('[data-speed]').forEach((b) =>
        b.addEventListener('click', () => selectSpeed(b.dataset.speed)));

    document.getElementById('obstacle-toggle').addEventListener('click', toggleObstacleAvoid);
    renderObstacleToggle();
    wireLightSlider();

    const cam = document.getElementById('robot-cam');
    const placeholder = document.getElementById('video-placeholder');
    const showPlaceholder = (on) => placeholder && placeholder.classList.toggle('hidden', !on);
    cam.addEventListener('playing', () => {
        cam.style.display = 'block';
        showPlaceholder(false);
    });
    cam.addEventListener('emptied', () => showPlaceholder(true));
    cam.addEventListener('resize', applyStampCrop);

    document.querySelectorAll('.cmd-btn[data-cmd]').forEach((b) =>
        b.addEventListener('click', () => sendCommand(b.dataset.cmd, b)));

    document.getElementById('estop').addEventListener('click', () => {
        ui.estopped = true;
        sendEstop(state.stateChannel, () => ++ui.nonce);  // don't gate the latch on an ack
        document.querySelectorAll('.cmd-btn').forEach((b) => (b.dataset.status = 'idle'));
        ui.posture = 'Damp';
        refreshControls();
    });
    document.getElementById('rearm').addEventListener('click', () => {
        ui.estopped = false;  // re-arm; operator must Stand/Drive-ready to resume
        sendEstopClear(state.stateChannel, () => ++ui.nonce);
        refreshControls();
    });

    state.onCmdAck = onCmdAck;
    state.onRobotState = onRobotState;
    state.onMap = onMap;
    state.onOdom = onOdom;
    document.getElementById('view-swap').addEventListener('click', () => setMainView());
    wireMicToggle();
    for (const id of ['robot-cam', 'map-canvas']) {
        document.getElementById(id).addEventListener('click', (e) => {
            if (e.currentTarget.classList.contains('is-pip')) setMainView();
        });
    }
    bindMapPanZoom();
    bindPipResize();
    setMainView('camera');
    window.addEventListener('resize', positionPipHandle);

    selectSpeed(ui.speedMode, /*sendToRobot=*/ false);
}

// Aspect ratio is LOCKED — dragging scales the PiP uniformly.
function bindPipResize() {
    const handle = document.getElementById('pip-resize');
    const stage = document.getElementById('stage');
    if (!handle || !stage) return;
    const MIN_W = 96, MAX_W = 560;
    let resizing = false, startX = 0, startY = 0, startW = 0, ratio = 1;

    handle.addEventListener('pointerdown', (e) => {
        const pip = pipEl();
        if (!pip) return;
        e.preventDefault(); e.stopPropagation();
        resizing = true;
        startX = e.clientX; startY = e.clientY;
        const r = pip.getBoundingClientRect();
        startW = r.width;
        ratio = r.height / r.width;
        handle.setPointerCapture(e.pointerId);
    });
    handle.addEventListener('pointermove', (e) => {
        if (!resizing) return;
        const pip = pipEl();
        if (!pip) return;
        const grow = Math.max(startX - e.clientX, e.clientY - startY);
        ui.pipW = Math.max(MIN_W, Math.min(MAX_W, startW + grow));
        ui.pipH = Math.round(ui.pipW * ratio);
        pip.style.width = ui.pipW + 'px';
        pip.style.height = ui.pipH + 'px';
        positionPipHandle();
        if (pip.id === 'map-canvas') drawMap();
    });
    const end = (e) => {
        if (!resizing) return;
        resizing = false;
        try { handle.releasePointerCapture(e.pointerId); } catch (_) {}
    };
    handle.addEventListener('pointerup', end);
    handle.addEventListener('pointercancel', end);
}

// Track is captured MUTED at connect (webrtc.js); this flips track.enabled.
function wireMicToggle() {
    const btn = document.getElementById('mic-toggle');
    const label = document.getElementById('mic-toggle-label');
    if (!btn || !label) return;
    const sync = () => {
        const t = state.micTrack;
        if (!t) { label.textContent = 'AUDIO N/A'; btn.disabled = true; return; }
        btn.disabled = false;
        label.textContent = t.enabled ? 'AUDIO ON' : 'AUDIO OFF';
        btn.classList.toggle('is-active', t.enabled);
    };
    btn.addEventListener('click', () => {
        const t = state.micTrack;
        if (t) t.enabled = !t.enabled;
        sync();
    });
    state.onMicReady = sync;
    sync();
}

// canvas px → world metres: exact inverse of drawMap's pan/zoom → letterbox → y-flip chain.
function sendNavGoal(e) {
    const m = ui.lastMap;
    const canvas = document.getElementById('map-canvas');
    if (!m || !m.img || !canvas) return;
    if (!state.stateChannel || state.stateChannel.readyState !== 'open') return;
    const rect = canvas.getBoundingClientRect();
    const cw = rect.width, ch = rect.height;
    const cx = e.clientX - rect.left, cy = e.clientY - rect.top;
    const ux = (cx - ui.mapPanX - cw / 2) / ui.mapZoom + cw / 2;
    const uy = (cy - ui.mapPanY - ch / 2) / ui.mapZoom + ch / 2;
    const scale = Math.min(cw / m.w, ch / m.h);
    const dw = m.w * scale, dh = m.h * scale;
    const dx = (cw - dw) / 2, dy = (ch - dh) / 2;
    const col = (ux - dx) / scale;
    const row = ((dy + dh) - uy) / scale;
    if (col < 0 || col > m.w || row < 0 || row > m.h) return;
    const wx = m.origin[0] + col * m.res;
    const wy = m.origin[1] + row * m.res;
    ui.navGoal = { x: wx, y: wy };
    state.stateChannel.send(JSON.stringify(
        { type: 'nav_goal', x: wx, y: wy, nonce: ++ui.nonce }));
    console.info(`[nav] goal → (${wx.toFixed(2)}, ${wy.toFixed(2)})`);
    drawMap();
}

function bindMapPanZoom() {
    const canvas = document.getElementById('map-canvas');
    if (!canvas) return;
    const isMain = () => canvas.classList.contains('is-main');
    const MIN_Z = 1, MAX_Z = 12;

    canvas.addEventListener('wheel', (e) => {
        if (!isMain()) return;
        e.preventDefault();
        const rect = canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left, my = e.clientY - rect.top;
        const prev = ui.mapZoom;
        const next = Math.min(MAX_Z, Math.max(MIN_Z, prev * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
        if (next === prev) return;
        const cx = rect.width / 2, cy = rect.height / 2;
        ui.mapPanX = mx - (mx - ui.mapPanX - cx) * (next / prev) - cx;
        ui.mapPanY = my - (my - ui.mapPanY - cy) * (next / prev) - cy;
        ui.mapZoom = next;
        if (next === MIN_Z) { ui.mapPanX = 0; ui.mapPanY = 0; }
        drawMap();
    }, { passive: false });

    let dragging = false, lastX = 0, lastY = 0, moved = 0;
    canvas.addEventListener('pointerdown', (e) => {
        if (!isMain()) return;
        dragging = true; moved = 0; lastX = e.clientX; lastY = e.clientY;
        canvas.setPointerCapture(e.pointerId);
        canvas.style.cursor = 'grabbing';
    });
    canvas.addEventListener('pointermove', (e) => {
        if (!dragging) return;
        const dxp = e.clientX - lastX, dyp = e.clientY - lastY;
        lastX = e.clientX; lastY = e.clientY; moved += Math.abs(dxp) + Math.abs(dyp);
        ui.mapPanX += dxp; ui.mapPanY += dyp;
        drawMap();
    });
    const endDrag = (e) => {
        if (!dragging) return;
        dragging = false; canvas.style.cursor = '';
        try { canvas.releasePointerCapture(e.pointerId); } catch (_) {}
        if (moved < 5) sendNavGoal(e);
    };
    canvas.addEventListener('pointerup', endDrag);
    canvas.addEventListener('pointercancel', endDrag);
    canvas.addEventListener('dblclick', (e) => {
        if (!isMain()) return;
        e.preventDefault();
        ui.mapZoom = 1; ui.mapPanX = 0; ui.mapPanY = 0;
        drawMap();
    });
}

// Never reparents the <video> (would drop the track) — toggles .is-main / .is-pip.
function setMainView(view) {
    ui.mainView = view || (ui.mainView === 'camera' ? 'map' : 'camera');
    const cam = document.getElementById('robot-cam');
    const map = document.getElementById('map-canvas');
    const camMain = ui.mainView === 'camera';
    cam.classList.toggle('is-main', camMain);
    cam.classList.toggle('is-pip', !camMain);
    map.classList.toggle('is-main', !camMain);
    map.classList.toggle('is-pip', camMain);
    for (const el of [cam, map]) {
        if (el.classList.contains('is-pip')) {
            el.style.width = ui.pipW + 'px';
            el.style.height = ui.pipH + 'px';
        } else {
            el.style.width = ''; el.style.height = '';
        }
    }
    const label = document.getElementById('view-swap-label');
    if (label) label.textContent = camMain ? 'MAP VIEW' : 'CAM VIEW';
    if (camMain) { ui.mapZoom = 1; ui.mapPanX = 0; ui.mapPanY = 0; }
    applyStampCrop();
    positionPipHandle();
    drawMap();
}

function pipEl() { return document.querySelector('#stage .is-pip'); }
function positionPipHandle() {
    const handle = document.getElementById('pip-resize');
    const pip = pipEl();
    const stage = document.getElementById('stage');
    if (!handle || !pip || !stage) return;
    const pr = pip.getBoundingClientRect(), sr = stage.getBoundingClientRect();
    handle.style.display = 'block';
    handle.style.left = (pr.left - sr.left) + 'px';
    handle.style.top = (pr.bottom - sr.top - 11) + 'px';
}

function onMap(msg) {
    if (!msg || !msg.png_b64) return;
    const img = new Image();
    img.onload = () => {
        ui.lastMap = { ...msg, img };
        drawMap();
    };
    img.onerror = () => {};
    img.src = 'data:image/png;base64,' + msg.png_b64;
}

function onOdom(msg) {
    if (!msg) return;
    ui.lastOdom = msg;
    drawMap();
}

// Grid is row-major from origin; world y grows up, canvas down, so the row is flipped.
function drawMap() {
    const canvas = document.getElementById('map-canvas');
    if (!canvas) return;
    const m = ui.lastMap;
    const rect = canvas.getBoundingClientRect();
    const cw = Math.max(1, Math.round(rect.width));
    const ch = Math.max(1, Math.round(rect.height));
    if (canvas.width !== cw) canvas.width = cw;
    if (canvas.height !== ch) canvas.height = ch;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, cw, ch);
    if (!m || !m.img) {
        ctx.fillStyle = '#0b0d0d';
        ctx.fillRect(0, 0, cw, ch);
        ctx.fillStyle = '#3a4a4a';
        ctx.font = '12px monospace';
        ctx.fillText('awaiting map…', 10, 20);
        return;
    }
    const scale = Math.min(cw / m.w, ch / m.h);
    const dw = m.w * scale, dh = m.h * scale;
    const dx = (cw - dw) / 2, dy = (ch - dh) / 2;
    ctx.imageSmoothingEnabled = false;

    ctx.save();
    ctx.translate(ui.mapPanX, ui.mapPanY);
    ctx.translate(cw / 2, ch / 2);
    ctx.scale(ui.mapZoom, ui.mapZoom);
    ctx.translate(-cw / 2, -ch / 2);

    ctx.save();
    ctx.translate(dx, dy + dh);
    ctx.scale(1, -1);
    ctx.drawImage(m.img, 0, 0, dw, dh);

    const o = ui.lastOdom;
    if (o && m.res > 0) {
        const col = (o.x - m.origin[0]) / m.res;
        const row = (o.y - m.origin[1]) / m.res;
        const px = col * scale;
        const py = row * scale;
        if (px >= 0 && px <= dw && py >= 0 && py <= dh) {
            const pxPerM = scale / m.res;
            const MIN_LEN_PX = 14;
            let lenPx = GO2_LEN_M * pxPerM;
            let widPx = GO2_WID_M * pxPerM;
            if (lenPx < MIN_LEN_PX) {
                widPx *= MIN_LEN_PX / lenPx;
                lenPx = MIN_LEN_PX;
            }
            ctx.save();
            ctx.translate(px, py);
            ctx.rotate(o.yaw || 0);
            ctx.fillStyle = 'rgba(176,225,240,0.35)';
            ctx.strokeStyle = '#b0e1f0';
            ctx.lineWidth = 1.5;
            ctx.fillRect(-lenPx / 2, -widPx / 2, lenPx, widPx);
            ctx.strokeRect(-lenPx / 2, -widPx / 2, lenPx, widPx);
            ctx.beginPath();
            ctx.moveTo(0, 0);
            ctx.lineTo(lenPx / 2, 0);
            ctx.strokeStyle = '#0d0e0e';
            ctx.lineWidth = 2;
            ctx.stroke();
            ctx.restore();
        }
    }
    const g = ui.navGoal;
    if (g && m.res > 0) {
        const gx = ((g.x - m.origin[0]) / m.res) * scale;
        const gy = ((g.y - m.origin[1]) / m.res) * scale;
        if (gx >= 0 && gx <= dw && gy >= 0 && gy <= dh) {
            ctx.save();
            ctx.translate(gx, gy);
            ctx.strokeStyle = '#b0e1f0';
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.arc(0, 0, 7, 0, Math.PI * 2);
            ctx.stroke();
            ctx.fillStyle = '#b0e1f0';
            ctx.beginPath();
            ctx.arc(0, 0, 2, 0, Math.PI * 2);
            ctx.fill();
            ctx.restore();
        }
    }
    ctx.restore();
    ctx.restore();
}

const GO2_LEN_M = 0.70;
const GO2_WID_M = 0.31;

function toggleCam(id) {
    const sel = new Set(ui.selectedCams);
    if (sel.has(id)) {
        if (sel.size === 1) return;  // keep at least one camera on
        sel.delete(id);
    } else {
        sel.add(id);
    }
    // Preserve CAMS order so side-by-side order is stable.
    ui.selectedCams = CAMS.map((c) => c.id).filter((id) => sel.has(id));
    renderCamTabs();
    sendCameraSelect();
}

function renderCamTabs() {
    document.querySelectorAll('#cam-tabs [data-cam]').forEach((b) => {
        const on = ui.selectedCams.includes(b.dataset.cam);
        b.className = 'px-4 py-0.5 rounded text-[11px] leading-none border ' +
            (on ? 'bg-dim-500 text-bg-950 border-dim-500' : 'border-[#2a2a2a] text-gray-400');
    });
}

function sendCameraSelect() {
    if (state.stateChannel && state.stateChannel.readyState === 'open') {
        state.stateChannel.send(JSON.stringify({ type: 'camera_select', cams: ui.selectedCams }));
    }
}

function selectSpeed(mode, sendToRobot = true) {
    const spec = SPEEDS.find((s) => s.mode === mode);
    if (!spec) return;
    ui.speedMode = mode;
    state.speedScale = spec.scale;
    document.querySelectorAll('#speed-bar [data-speed]').forEach((b) =>
        b.classList.toggle('is-active', b.dataset.speed === mode));
    if (sendToRobot && state.stateChannel && state.stateChannel.readyState === 'open') {
        state.stateChannel.send(JSON.stringify({ type: 'set_mode', mode, nonce: ++ui.nonce }));
    }
}

function toggleObstacleAvoid() {
    if (!state.stateChannel || state.stateChannel.readyState !== 'open') return;
    ui.obstacleAvoid = !ui.obstacleAvoid;
    renderObstacleToggle();
    state.stateChannel.send(JSON.stringify(
        { type: 'obstacle_avoidance', enabled: ui.obstacleAvoid, nonce: ++ui.nonce }));
}


function renderObstacleToggle() {
    const b = document.getElementById('obstacle-toggle');
    if (!b) return;
    const on = ui.obstacleAvoid;
    b.textContent = on ? 'ON' : 'OFF';
    b.classList.toggle('text-dim-400', on);
    b.classList.toggle('border-dim-700', on);
    b.classList.toggle('text-gray-500', !on);
}

function wireLightSlider() {
    const s = document.getElementById('light-slider');
    if (!s) return;
    const drag = (on) => { ui.lightDragging = on; };
    s.addEventListener('pointerdown', () => drag(true));
    s.addEventListener('pointerup', () => drag(false));
    s.addEventListener('touchstart', () => drag(true), { passive: true });
    s.addEventListener('touchend', () => drag(false));
    s.addEventListener('input', () => renderLightValue(parseFloat(s.value)));
    s.addEventListener('change', () => sendLight(parseFloat(s.value)));
    renderLightSlider();
}

function sendLight(brightness) {
    if (!state.stateChannel || state.stateChannel.readyState !== 'open') return;
    ui.light = brightness;
    const s = document.getElementById('light-slider');
    if (s) { s.classList.remove('cmd-ok', 'cmd-err'); s.classList.add('cmd-sending'); }
    const nonce = ++ui.nonce;
    state.stateChannel.send(JSON.stringify({ type: 'light', brightness, nonce }));
    const timer = setTimeout(() => resolveAck(nonce, false), 3000);
    ui.pending.set(nonce, { el: s, name: 'light', timer });
}

function renderLightValue(v) {
    const val = document.getElementById('light-val');
    if (val) val.textContent = `${Math.round(v * 100)}%`;
}

function renderLightSlider() {
    const s = document.getElementById('light-slider');
    if (s && !ui.lightDragging) s.value = String(ui.light);
    renderLightValue(ui.light);
}

function onCmdAck(msg) {
    resolveAck(msg.nonce, !!msg.ok);
}

// Skipped while a command is pending — robot reports the old state until the ack lands.
function onRobotState(s) {
    if (ui.pending.size > 0) return;
    let dirty = false;
    if (typeof s.posture === 'string' && s.posture !== ui.posture) {
        ui.posture = s.posture;
        dirty = true;
    }
    // E-STOP latch is sticky: telemetry may RAISE it but must NEVER lower it
    // (a pre-estop frame carries estopped:false; clearing it would resume a held-key twist).
    if (s.estopped === true && !ui.estopped) {
        ui.estopped = true;
        dirty = true;
    }
    if (typeof s.video_stalled === 'boolean') {
        ui.robotVideoStalled = s.video_stalled;
    }
    if (typeof s.obstacle_avoidance === 'boolean' && s.obstacle_avoidance !== ui.obstacleAvoid) {
        ui.obstacleAvoid = s.obstacle_avoidance;
        renderObstacleToggle();
    }
    if (typeof s.light === 'number' && !ui.lightDragging && Math.abs(s.light - ui.light) > 0.01) {
        ui.light = s.light;
        renderLightSlider();
    }
    if (Array.isArray(s.cams) && s.cams.join() !== ui.selectedCams.join()) {
        ui.selectedCams = s.cams.filter((c) => CAMS.some((k) => k.id === c));
        if (!ui.selectedCams.length) ui.selectedCams = ['cam1'];
        renderCamTabs();
    }
    // Rage is firmware truth; normal-vs-high is browser-only. Don't send set_mode back.
    if (typeof s.rage === 'boolean') {
        const uiRage = ui.speedMode === 'rage';
        if (s.rage !== uiRage) selectSpeed(s.rage ? 'rage' : 'normal', /*sendToRobot=*/ false);
    }
    if (dirty) refreshControls();
}

function resolveAck(nonce, ok) {
    const p = ui.pending.get(nonce);
    if (!p) return;
    clearTimeout(p.timer);
    ui.pending.delete(nonce);
    const btn = p.el;
    if (ok && POSTURE_STATE[p.name]) ui.posture = POSTURE_STATE[p.name];
    const isRange = btn && btn.tagName === 'INPUT';
    if (isRange) {
        btn.classList.remove('cmd-sending');
        btn.classList.add(ok ? 'cmd-ok' : 'cmd-err');
    } else if (btn) {
        btn.dataset.status = ok ? 'done' : 'error';
    }
    setTimeout(() => {
        if (!document.getElementById('hud-summary')) return;
        if (isRange) btn.classList.remove('cmd-ok', 'cmd-err');
        else if (btn) btn.dataset.status = 'idle';
        refreshControls();
    }, 700);
    refreshControls();
}

function sendCommand(name, btn) {
    if (!cmdReady()) return;
    if (CONFIRM_ACTIONS.has(name) &&
        !confirm(`${name} makes the robot leap — clear the area. Continue?`)) {
        return;
    }
    const nonce = ++ui.nonce;
    btn.dataset.status = 'pending';
    state.stateChannel.send(JSON.stringify({ type: 'sport_cmd', name, nonce }));
    // StandReady is a robot-side combo with ~3.6s of settling sleeps — 3s would mark it failed mid-stand.
    const timeoutMs = name === 'StandReady' ? 9000 : 3000;
    const timer = setTimeout(() => resolveAck(nonce, false), timeoutMs);
    ui.pending.set(nonce, { el: btn, name, timer });
}

function refreshControls() {
    const reason = ui.estopped ? 'E-STOPPED — re-arm to resume' : null;
    const banner = document.getElementById('blocked');
    if (!banner) return;
    banner.textContent = reason || '';
    banner.classList.toggle('hidden', !reason);

    document.querySelectorAll('.cmd-btn').forEach((b) => {
        const active = b.dataset.cmd === ui.posture;
        b.classList.toggle('is-active', active);
        // Don't lock StandReady — may want to re-press it to re-arm drive after sitting.
        const lockActive = active && b.dataset.cmd !== 'StandReady';
        b.disabled = !!reason || (lockActive && b.dataset.status === 'idle');
    });

    document.getElementById('estop').classList.toggle('latched', ui.estopped);
    document.getElementById('rearm').classList.toggle('hidden', !ui.estopped);

    // Gates the keyboard loop's send; poseMode flips buildTwist's key mapping to body-pose axes.
    state.poseMode = ui.posture === 'PoseStand' && !ui.estopped;
    state.driveEnabled = (ui.posture === 'StandReady' || state.poseMode) && !ui.estopped;

    const kb = document.getElementById('kb-live');
    const stalled = state.videoStall.stalled;
    kb.className = 'pill ' + (state.driveEnabled && !stalled ? 'pill-good' : 'pill-bad');
    kb.querySelector('.dot').nextSibling.textContent =
        stalled ? 'DRIVE OFF — video stalled'
        : state.poseMode ? 'POSE LIVE'
        : state.driveEnabled ? 'DRIVE LIVE' : 'DRIVE OFF — press Stand/Drive';

    document.getElementById('posture-chip').textContent =
        ({ StandReady: 'STANDING', PoseStand: 'POSING', StandDown: 'SITTING', RecoveryStand: 'RECOVERY', Damp: 'STOPPED' }[ui.posture]) ||
        ui.posture;
    renderDriveHints();

    renderBattery();
}

function renderDriveHints() {
    const title = document.getElementById('drive-title');
    const hints = document.getElementById('drive-hints');
    if (!title || !hints) return;
    const mode = state.poseMode ? 'pose' : 'drive';
    if (hints.dataset.mode === mode) return;
    hints.dataset.mode = mode;
    title.textContent = state.poseMode ? 'Pose' : 'Drive';
    hints.innerHTML = state.poseMode
        ? `<div><span class="text-gray-300">W/S</span> pitch down · up &nbsp; <span class="text-gray-300">A/D</span> yaw left · right</div>
           <div><span class="text-gray-300">Q/E</span> roll left · right &nbsp; <span class="text-gray-300">R/F</span> body up · down</div>
           <div><span class="text-gray-300">Shift</span> stronger &nbsp; <span class="text-gray-300">Space</span> gentle</div>`
        : `<div><span class="text-gray-300">W/S</span> forward · back &nbsp; <span class="text-gray-300">A/D</span> turn left · right</div>
           <div><span class="text-gray-300">Q/E</span> strafe left · right</div>
           <div><span class="text-gray-300">Shift</span> 2× fast &nbsp; <span class="text-gray-300">Space</span> ½× slow</div>`;
}

function renderBattery() {
    const pct = document.getElementById('batt-pct');
    if (!pct) return;
    const soc = state.liveStats?.soc;
    if (soc == null) {
        pct.textContent = '—%';
        pct.style.color = '#6b7280';
        return;
    }
    const p = Math.max(0, Math.min(100, soc));
    pct.textContent = `${p}%`;
    pct.style.color = { good: '#c4e7f3', warn: '#eab308', bad: '#f3b4b4' }[socHealth(p)];
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

let _lastHudSample = 0;
let _noVideoSinceMs = 0;
function startTick() {
    stopTick();
    _lastHudSample = performance.now();
    _noVideoSinceMs = 0;
    tickTimer = setInterval(() => {
        const now = performance.now();
        sampleCmdHz((now - _lastHudSample) / 1000);
        _lastHudSample = now;

        const summary = document.getElementById('hud-summary');
        if (!summary) return;

        applyStampCrop();

        // Never-got-video escalation: connected but no first frame → after 8s name the likely culprit.
        const chOpen = state.cmdChannel && state.cmdChannel.readyState === 'open';
        const statusEl = document.getElementById('teleop-status');
        if (statusEl && chOpen && !state.videoStall.armed) {
            if (!_noVideoSinceMs) _noVideoSinceMs = now;
            if (ui.robotVideoStalled) {
                statusEl.textContent =
                    'Robot reports its camera is stalled — power-cycle the robot';
            } else if (now - _noVideoSinceMs > 8000) {
                statusEl.textContent =
                    'Connected — no video from robot (power-cycle it if this persists)';
            }
        } else {
            _noVideoSinceMs = 0;
        }

        // Video-freshness lockout: stalled → overlay + drive pill off (loop already blocks sends).
        const lost = document.getElementById('video-lost');
        const stalled = state.videoStall.stalled;
        if (lost && lost.classList.contains('hidden') !== !stalled) {
            lost.classList.toggle('hidden', !stalled);
            refreshControls();
        }
        if (lost && stalled) {
            const label = lost.querySelector('.term-caps');
            if (label) label.textContent = ui.robotVideoStalled
                ? 'robot camera stalled — power-cycle the robot · drive disabled'
                : 'video stalled — drive disabled';
        }

        summary.textContent = hudSummaryLine();
        renderTelemetryGrid();

        const health = statsHealth();
        const pill = document.getElementById('hud-health');
        if (pill) pill.className = 'pill pill-' + health;
        const transport = document.getElementById('hud-transport');
        if (transport) transport.textContent = transportLabel();
        const linkPill = document.getElementById('link-pill');
        if (linkPill) {
            linkPill.className = 'pill pill-' + health;
            linkPill.querySelector('span:last-child').textContent =
                { good: 'LINK OK', warn: 'LINK WEAK', bad: 'LINK BAD' }[health];
        }

        renderBattery();
    }, 1000);
}

export function stopTick() {
    if (tickTimer) {
        clearInterval(tickTimer);
        tickTimer = null;
    }
    if (state.onCmdAck === onCmdAck) state.onCmdAck = null;
    if (state.onRobotState === onRobotState) state.onRobotState = null;
    ui.pending.forEach((p) => clearTimeout(p.timer));
    ui.pending.clear();
}
