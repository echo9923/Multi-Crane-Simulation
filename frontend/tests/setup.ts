// Vitest global setup. Three.js Scene/Mesh/Object3D work without a WebGL
// context, but constructing THREE.WebGLRenderer in jsdom throws. Tests that
// touch the renderer always inject a stub via the controller's factory hook,
// so no WebGL shim is required here.

// jsdom lacks matchMedia; stub the globals the app may read at import time so
// component imports never throw. (@testing-library/react auto-cleans up the DOM
// between tests by default, which is what we want.)
if (!("matchMedia" in window)) {
  // @ts-expect-error minimal stub
  window.matchMedia = () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
  });
}
