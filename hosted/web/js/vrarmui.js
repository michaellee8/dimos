import * as THREE from 'three';

import { hudDetailRows, healthColor, transportLabel } from './hud.js';
import { state } from './state.js';
import { sendEstop, sendEstopClear } from './xarmcmd.js';

const C = {
    bg: 'rgba(18,19,19,0.92)', bgSolid: '#121313', panel: '#0d0e0e',
    line: '#2a2a2a', text: '#d1d5db', dim: '#6b7280', cyan: '#b0e1f0',
    good: '#34d399', warn: '#ffcc00', bad: '#ff5252',
    estopBorder: '#d97777',
};

const HEALTH = { good: C.cyan, warn: C.warn, bad: C.bad };

// Reconciled from robot_telemetry (authoritative on connect).
export const aui = {
    engaged: { left: false, right: false },
    estopped: false,
    nonce: 0,
    pending: new Map(),   // nonce → { id, expiry } for cmd_ack feedback
};

function nextNonce() { return ++aui.nonce; }

class Panel {
    constructor({ wM, hM, cw, ch, opacity = 1 }) {
        this.cw = cw; this.ch = ch;
        this.canvas = document.createElement('canvas');
        this.canvas.width = cw; this.canvas.height = ch;
        this.ctx = this.canvas.getContext('2d');
        this.tex = new THREE.CanvasTexture(this.canvas);
        this.tex.colorSpace = THREE.SRGBColorSpace;
        this.mesh = new THREE.Mesh(
            new THREE.PlaneGeometry(wM, hM),
            new THREE.MeshBasicMaterial({ map: this.tex, transparent: true, opacity }),
        );
        this.mesh.userData.panel = this;
        this.regions = [];
        this.hoverId = null;
        this.dirty = true;
    }
    placeFlat(pos, rotX) { this.mesh.position.copy(pos); this.mesh.rotation.set(rotX, 0, 0); }
    markDirty() { this.dirty = true; }
    // UV (three, flipY) → canvas px; row = (1-v)*ch.
    hitTest(uv) {
        const px = uv.x * this.cw, py = (1 - uv.y) * this.ch;
        for (const r of this.regions) {
            if (px >= r.x && px <= r.x + r.w && py >= r.y && py <= r.y + r.h) return r.id;
        }
        return null;
    }
    setHover(id) { if (id !== this.hoverId) { this.hoverId = id; this.dirty = true; } }
    bg() {
        const x = this.ctx;
        x.clearRect(0, 0, this.cw, this.ch);
        x.fillStyle = C.bg;
        roundRect(x, 2, 2, this.cw - 4, this.ch - 4, 18); x.fill();
        x.strokeStyle = C.line; x.lineWidth = 2; x.stroke();
        this.regions = [];
    }
    header(text) {
        const x = this.ctx;
        x.fillStyle = C.dim;
        x.font = '600 22px ui-monospace, monospace';
        x.fillText(text.toUpperCase(), 24, 40);
    }
    // st ∈ idle|active|pending|error.
    chip(id, bx, by, bw, bh, label, st = 'idle') {
        const x = this.ctx, hot = this.hoverId === id;
        let fill = C.bgSolid, border = C.line, txt = C.text;
        if (st === 'active') { fill = C.cyan; border = C.cyan; txt = C.panel; }
        else if (st === 'error') { fill = '#4a1d1d'; border = C.estopBorder; txt = '#f3b4b4'; }
        else if (st === 'pending') { border = C.cyan; txt = C.dim; }
        if (hot && st === 'idle') border = C.cyan;
        x.fillStyle = fill; roundRect(x, bx, by, bw, bh, 10); x.fill();
        x.lineWidth = hot ? 2.5 : 1.5; x.strokeStyle = border; x.stroke();
        x.fillStyle = txt;
        x.font = '600 22px ui-monospace, monospace';
        x.textAlign = 'center'; x.textBaseline = 'middle';
        x.fillText(label, bx + bw / 2, by + bh / 2 + 1);
        x.textAlign = 'left'; x.textBaseline = 'alphabetic';
        this.regions.push({ id, x: bx, y: by, w: bw, h: bh });
    }
    // Read-only status pill (engaged L/R) — no hit region.
    pill(bx, by, bw, bh, label, on) {
        const x = this.ctx;
        x.fillStyle = on ? C.cyan : C.bgSolid;
        roundRect(x, bx, by, bw, bh, 10); x.fill();
        x.lineWidth = 1.5; x.strokeStyle = on ? C.cyan : C.line; x.stroke();
        x.fillStyle = on ? C.panel : C.dim;
        x.font = '600 22px ui-monospace, monospace';
        x.textAlign = 'center'; x.textBaseline = 'middle';
        x.fillText(label, bx + bw / 2, by + bh / 2 + 1);
        x.textAlign = 'left'; x.textBaseline = 'alphabetic';
    }
    dispose() { this.tex.dispose(); this.mesh.geometry.dispose(); this.mesh.material.dispose(); }
}

function roundRect(x, bx, by, bw, bh, r) {
    x.beginPath();
    x.moveTo(bx + r, by);
    x.arcTo(bx + bw, by, bx + bw, by + bh, r);
    x.arcTo(bx + bw, by + bh, bx, by + bh, r);
    x.arcTo(bx, by + bh, bx, by, r);
    x.arcTo(bx, by, bx + bw, by, r);
    x.closePath();
}

function renderConsole(p) {
    p.bg();
    p.header('xArm cockpit');

    // Engage status is read-only; the robot decides engage from the held button.
    const x = p.ctx;
    x.fillStyle = C.dim; x.font = '600 20px ui-monospace, monospace';
    x.fillText('ENGAGE', 24, 96);
    p.pill(150, 74, 130, 44, `L ${aui.engaged.left ? 'ON' : '—'}`, aui.engaged.left);
    p.pill(292, 74, 130, 44, `R ${aui.engaged.right ? 'ON' : '—'}`, aui.engaged.right);

    if (aui.estopped) {
        p.chip('estop_clear', 24, 168, 540, 130, 'E-STOP LATCHED — CLEAR', 'error');
    } else {
        const pend = [...aui.pending.values()].some((v) => v.id === 'estop');
        p.chip('estop', 24, 168, 540, 130, 'E-STOP', pend ? 'pending' : 'idle');
    }
}

function renderStats(p) {
    p.bg();
    const x = p.ctx;
    x.fillStyle = healthColor();
    x.beginPath(); x.arc(30, 34, 9, 0, Math.PI * 2); x.fill();
    x.fillStyle = C.text; x.font = '600 20px ui-monospace,monospace';
    x.fillText(transportLabel(), 48, 40);

    let y = 78;
    for (const g of hudDetailRows()) {
        x.fillStyle = C.dim; x.font = '600 15px ui-monospace,monospace';
        x.fillText(g.group.toUpperCase(), 24, y); y += 24;
        for (const r of g.rows) {
            x.fillStyle = C.dim; x.font = '15px ui-monospace,monospace';
            x.textAlign = 'left'; x.fillText(r.label, 30, y);
            x.fillStyle = HEALTH[r.health] || C.text;
            x.textAlign = 'right'; x.font = '600 15px ui-monospace,monospace';
            x.fillText(String(r.value), p.cw - 24, y);
            x.textAlign = 'left';
            y += 24;
        }
        y += 10;
    }
}

function handleClick(id) {
    if (id === 'estop') {
        aui.estopped = true;  // optimistic; robot_telemetry reconciles
        markPending('estop');
        sendEstop(state.stateChannel, nextNonce);
    } else if (id === 'estop_clear') {
        aui.estopped = false;
        markPending('estop_clear');
        sendEstopClear(state.stateChannel, nextNonce);
    }
}

function markPending(id) {
    aui.pending.set(aui.nonce + 1, { id, expiry: 0 });  // nonce bumps on send
}

export function onCmdAck(msg) {
    aui.pending.delete(msg.nonce);
    _dirty();
}

// robot_telemetry.state — authoritative.
export function onRobotState(s) {
    if (s.engaged) aui.engaged = { left: !!s.engaged.left, right: !!s.engaged.right };
    // Sticky E-STOP latch: telemetry may raise it, never lower it. Only re-arm clears.
    if (s.estopped === true) aui.estopped = true;
    _dirty();
}

let _panel = null;
function _dirty() { if (_panel) _panel.markDirty(); }

export function buildArmCockpit(scene, _headPos) {
    // Console shelf below the camera panel (CAM in vrarm.js sits at y≈1.52, z≈-1.6).
    const console_ = new Panel({ wM: 1.5, hM: 0.52, cw: 1180, ch: 410, opacity: 0.97 });
    console_.placeFlat(new THREE.Vector3(0, 0.86, -1.3), -0.6);
    console_.mesh.renderOrder = 3;
    scene.add(console_.mesh);
    _panel = console_;

    // Stats panel: continues the camera-screen arc one panel further right, pulled
    // forward and yawed harder to face the operator. renderOrder above the screens
    // so it never z-fights into them at the seam.
    const stats = new Panel({ wM: 0.5, hM: 0.70, cw: 440, ch: 620, opacity: 0.97 });
    stats.mesh.position.set(1.42, 1.52, -1.28);
    stats.mesh.rotation.y = -0.7;
    stats.mesh.renderOrder = 4;
    scene.add(stats.mesh);

    let lastStatsMs = 0;  // repaint the 1Hz panels, not per frame

    return {
        panels: [console_, stats],
        meshes: [console_.mesh, stats.mesh],
        onClick(panel, uv) {
            const id = panel.hitTest(uv);
            if (id) handleClick(id);
        },
        tick(nowMs) {
            if (nowMs - lastStatsMs >= 1000) {
                console_.markDirty(); stats.markDirty(); lastStatsMs = nowMs;
            }
            if (console_.dirty) {
                renderConsole(console_); console_.tex.needsUpdate = true; console_.dirty = false;
            }
            if (stats.dirty) {
                renderStats(stats); stats.tex.needsUpdate = true; stats.dirty = false;
            }
        },
        dispose() {
            for (const p of [console_, stats]) { scene.remove(p.mesh); p.dispose(); }
            _panel = null;
        },
    };
}
