// Coordinate mapping between the simulation world frame and the Three.js scene.
//
// Backend world frame: ENU (X = East, Y = North, Z = Up), metres.
// Three.js default: right-handed, Y up.
//
// Mapping: worldToThree([x, y, z]) = [x, z, -y]
//   world X (East)  -> three X
//   world Z (Up)    -> three Y
//   world Y (North) -> three -Z   (chosen so handedness is preserved: no mirror)
//
// All values shown to the user (hover, click, export preview) MUST be converted
// back via threeToWorld so the displayed numbers are ENU world coordinates and
// stay consistent with exported data.

export type Vec3 = [number, number, number];

export function worldToThree(p: Vec3): Vec3 {
  return [p[0], p[2], -p[1]];
}

export function threeToWorld(p: Vec3): Vec3 {
  return [p[0], -p[2], p[1]];
}

export function worldDist(a: Vec3, b: Vec3): number {
  const dx = a[0] - b[0];
  const dy = a[1] - b[1];
  const dz = a[2] - b[2];
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

// Distance between two points already expressed in the Three.js frame.
export function threeDist(a: Vec3, b: Vec3): number {
  const dx = a[0] - b[0];
  const dy = a[1] - b[1];
  const dz = a[2] - b[2];
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

// 2D (horizontal) world distance, ignoring altitude — matches backend
// layout_geometry.horizontal_distance semantics.
export function worldHorizontalDist(a: Vec3, b: Vec3): number {
  const dx = a[0] - b[0];
  const dy = a[1] - b[1];
  return Math.sqrt(dx * dx + dy * dy);
}
