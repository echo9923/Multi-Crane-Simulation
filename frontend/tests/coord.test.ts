import { describe, it, expect } from "vitest";
import {
  worldToThree,
  threeToWorld,
  worldDist,
  worldHorizontalDist,
} from "@/coord";

describe("coord worldToThree / threeToWorld", () => {
  it("maps ENU to Three.js Y-up", () => {
    expect(worldToThree([1, 2, 3])).toEqual([1, 3, -2]);
  });

  it("is the inverse of threeToWorld", () => {
    const samples: ([number, number, number])[] = [
      [0, 0, 0],
      [1, 2, 3],
      [-10, 40, 55],
      [78.3, 4.1, 46],
    ];
    for (const p of samples) {
      expect(threeToWorld(worldToThree(p))).toEqual(p);
      expect(worldToThree(threeToWorld(p))).toEqual(p);
    }
  });

  it("preserves right-handedness (no mirror): cross product sign unchanged", () => {
    // ENU basis vectors: e=(1,0,0) n=(0,1,0) u=(0,0,1); e x n = u.
    // After mapping, the Z component of (e' x n') must match u' on the mapped axis.
    const e = worldToThree([1, 0, 0]); // [1,0,0]
    const n = worldToThree([0, 1, 0]); // [0,0,-1]
    const cross = [
      e[1] * n[2] - e[2] * n[1],
      e[2] * n[0] - e[0] * n[2],
      e[0] * n[1] - e[1] * n[0],
    ];
    // u = worldToThree([0,0,1]) = [0,1,0]; cross must equal u (not its negation).
    expect(cross).toEqual([0, 1, 0]);
  });

  it("computes Euclidean distance in world metres", () => {
    expect(worldDist([0, 0, 0], [3, 4, 0])).toBeCloseTo(5, 10);
    expect(worldDist([0, 0, 0], [1, 2, 2])).toBeCloseTo(3, 10);
  });

  it("horizontal distance ignores altitude", () => {
    expect(worldHorizontalDist([0, 0, 0], [3, 4, 99])).toBeCloseTo(5, 10);
    expect(worldHorizontalDist([0, 0, 5], [0, 0, 9])).toBeCloseTo(0, 10);
  });

  it("handles zero / negative coordinates identically to positives", () => {
    expect(worldToThree([-1, -2, -3])).toEqual([-1, -3, 2]);
  });
});
