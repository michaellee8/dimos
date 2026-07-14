export function setStatus(msg) {
    const el = document.getElementById('teleop-status');
    if (el) el.textContent = msg;
}

// #robot-cam <video> is the WebRTC sink + GL-quad texture source; create it hidden if the view didn't render one (VR).
export function ensureRobotCam() {
    let v = document.getElementById('robot-cam');
    if (!v) {
        v = document.createElement('video');
        v.id = 'robot-cam';
        v.autoplay = true;
        v.muted = true;
        v.playsInline = true;
        v.style.display = 'none';
        document.body.appendChild(v);
    }
    return v;
}
