// Single shared WebXR renderer for all VR cockpits (vr.js, vrarm.js). A canvas has
// exactly ONE WebGL context; a second renderer would fight for it and setSession()
// would build an XRWebGLBinding against a stale session. So both cockpits share this.

import * as THREE from 'three';

let renderer = null;

export function getVRRenderer() {
    if (!renderer) {
        const canvas = document.getElementById('canvas');
        // xrCompatible at context creation — on Quest, without it the immersive session
        // can't use the GL context and video panels come up black.
        renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, xrCompatible: true });
        renderer.autoClear = true;
        renderer.xr.enabled = true;
        renderer.xr.setReferenceSpaceType('local-floor');
    }
    return renderer;
}
