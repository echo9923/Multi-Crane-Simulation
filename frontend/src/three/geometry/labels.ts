// Canvas-texture text sprites for in-scene labels (floor numbers, zone names).
//
// Sprites stay inside the single WebGLRenderer path the controller already
// owns — no second CSS2DRenderer, no DOM overlay. They always face the camera.
//
// jsdom (the vitest environment) has no 2D canvas backend, so getContext("2d")
// returns null there; makeTextSprite returns null in that case and every caller
// simply skips the label. Labels are therefore purely decorative and never
// affect the named scene-graph objects the geometry tests assert on.

import * as THREE from "three";

export interface TextSpriteOptions {
  /** Text fill color (CSS string). */
  color?: string;
  /** Pill background color (CSS string); omit for transparent. */
  background?: string;
  /** World-space height of the rendered sprite, in metres. */
  worldHeight?: number;
  /** Font size in canvas pixels (drives texture resolution). */
  fontPx?: number;
  /** Keep the label visible through geometry (default true). */
  alwaysOnTop?: boolean;
}

const DPR = 2; // crisp text on hi-dpi displays

// Probe once whether a real 2D canvas backend exists. jsdom (vitest) has none
// and logs a noisy "getContext not implemented" on every call, so we cache the
// result and short-circuit — keeping test output clean while staying fully
// functional in a real browser.
let canvas2dSupported: boolean | null = null;
function supports2dCanvas(): boolean {
  if (canvas2dSupported !== null) return canvas2dSupported;
  if (typeof document === "undefined") {
    canvas2dSupported = false;
    return false;
  }
  try {
    canvas2dSupported = Boolean(document.createElement("canvas").getContext("2d"));
  } catch {
    canvas2dSupported = false;
  }
  return canvas2dSupported;
}

/**
 * Build a billboarded text sprite, or null when no 2D canvas backend exists
 * (jsdom / headless tests). Caller positions the returned sprite.
 */
export function makeTextSprite(
  text: string,
  opts: TextSpriteOptions = {},
): THREE.Sprite | null {
  if (!supports2dCanvas()) return null;
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  if (!ctx) return null; // defensive: backend vanished after the probe

  const color = opts.color ?? "#1e293b";
  const fontPx = (opts.fontPx ?? 64) * DPR;
  const padX = fontPx * 0.4;
  const padY = fontPx * 0.28;
  const font = `600 ${fontPx}px system-ui, "PingFang SC", "Microsoft YaHei", sans-serif`;

  ctx.font = font;
  const metrics = ctx.measureText(text);
  const textW = Math.max(1, metrics.width);
  canvas.width = Math.ceil(textW + padX * 2);
  canvas.height = Math.ceil(fontPx + padY * 2);

  // measureText resets after the canvas resize, so re-set the font.
  ctx.font = font;
  ctx.textBaseline = "middle";
  ctx.textAlign = "center";

  if (opts.background) {
    ctx.fillStyle = opts.background;
    const r = canvas.height * 0.28;
    roundRect(ctx, 0, 0, canvas.width, canvas.height, r);
    ctx.fill();
  }

  ctx.fillStyle = color;
  ctx.fillText(text, canvas.width / 2, canvas.height / 2 + fontPx * 0.04);

  const texture = new THREE.CanvasTexture(canvas);
  texture.minFilter = THREE.LinearFilter;
  texture.needsUpdate = true;

  const material = new THREE.SpriteMaterial({
    map: texture,
    transparent: true,
    depthTest: !(opts.alwaysOnTop ?? true),
    depthWrite: false,
  });
  const sprite = new THREE.Sprite(material);

  const worldHeight = opts.worldHeight ?? 3;
  const aspect = canvas.width / canvas.height;
  sprite.scale.set(worldHeight * aspect, worldHeight, 1);
  return sprite;
}

function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
): void {
  const radius = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.arcTo(x + w, y, x + w, y + h, radius);
  ctx.arcTo(x + w, y + h, x, y + h, radius);
  ctx.arcTo(x, y + h, x, y, radius);
  ctx.arcTo(x, y, x + w, y, radius);
  ctx.closePath();
}
