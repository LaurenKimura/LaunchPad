import { describe, expect, it } from "vitest";
import { kpBand, placeInterval } from "./timelineLayout";

describe("timeline placement", () => {
  it("places an hour inside a six-hour view", () => {
    const placed = placeInterval(
      "2026-03-01T01:00:00Z",
      "2026-03-01T02:00:00Z",
      "2026-03-01T00:00:00Z",
      "2026-03-01T06:00:00Z",
    );
    expect(placed.left).toBeCloseTo(100 / 6);
    expect(placed.width).toBeCloseTo(100 / 6);
  });

  it("clips an event that starts before the view and keeps a sliver visible", () => {
    const placed = placeInterval(
      "2026-02-28T20:00:00Z",
      "2026-03-02T08:00:00Z",
      "2026-02-28T23:00:00Z",
      "2026-03-01T05:00:00Z",
    );
    expect(placed.left).toBe(0);
    expect(placed.width).toBe(100);
  });

  it("gives a one-minute gap a visible width", () => {
    const placed = placeInterval(
      "2026-03-01T02:00:00Z",
      "2026-03-01T02:01:00Z",
      "2026-02-28T23:00:00Z",
      "2026-03-01T05:01:00Z",
    );
    expect(placed.width).toBeGreaterThanOrEqual(1.25);
    expect(placed.left).toBeGreaterThan(0);
    expect(placed.left + placed.width).toBeLessThanOrEqual(100);
  });
});

describe("Kp bands", () => {
  it("uses the NOAA descriptions", () => {
    expect(kpBand(4.7)).toBe("Quiet to unsettled");
    expect(kpBand(5)).toBe("Minor storm");
    expect(kpBand(9)).toBe("Extreme storm");
  });
});
