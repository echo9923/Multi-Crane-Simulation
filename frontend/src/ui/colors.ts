// CSS crane swatch colors. Mirrors DEFAULT_CRANE_PALETTE in
// three/geometry/crane.ts so the swatches in the sidebar / status panels match
// the colors of the cranes rendered in the 3D scene. Kept as plain hex strings
// so UI components don't pull the Three.js geometry module into their bundle.
export const CRANE_PALETTE_CSS = [
  "#2563eb",
  "#d97706",
  "#7c3aed",
  "#0d9488",
  "#db2777",
  "#4f46e5",
];

export function craneColorCss(index: number): string {
  return CRANE_PALETTE_CSS[index % CRANE_PALETTE_CSS.length];
}
