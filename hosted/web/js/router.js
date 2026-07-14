// Views register themselves at import time (main.js) so router.js need not import views/* — avoids import cycles.

const routes = {};

export function register(view, renderer) {
    routes[view] = renderer;
}

export function navigate(view) {
    const app = document.getElementById('app');
    const fn = routes[view];
    if (fn) fn(app);
    else console.warn('[router] unknown view:', view);
}
