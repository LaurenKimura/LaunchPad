import { describe, expect, it } from "vitest";
import { formatFix, orbitPeriodMs, propagateFix, readSatrec, sampleTrack, sliderStepMs } from "./orbitTrack";

const LINE1 = "1 25544U 98067A   24279.50000000  .00016717  00000-0  10270-3 0  9993";
const LINE2 = "2 25544  51.6400 123.4567 0006789  12.3456 347.6543 15.50000000123456";

describe("satellite.js orbit track", () => {
  it("propagates a low Earth orbit inside the inclination", () => {
    const satrec = readSatrec(LINE1, LINE2);
    expect(satrec).not.toBeNull();
    const fix = propagateFix(satrec!, new Date("2024-10-05T12:00:00Z"));
    expect(fix).not.toBeNull();
    expect(Math.abs(fix!.latitudeDeg)).toBeLessThanOrEqual(52);
    expect(fix!.heightKm).toBeGreaterThan(200);
    expect(fix!.heightKm).toBeLessThan(800);
    expect(orbitPeriodMs(satrec!)).toBeGreaterThan(90 * 60 * 1000);
    expect(orbitPeriodMs(satrec!)).toBeLessThan(96 * 60 * 1000);
  });

  it("samples a track that moves in longitude", () => {
    const satrec = readSatrec(LINE1, LINE2)!;
    const start = new Date("2024-10-05T12:00:00Z");
    const end = new Date(start.getTime() + orbitPeriodMs(satrec));
    const track = sampleTrack(satrec, start, end, 24);
    expect(track.length).toBeGreaterThan(10);
    const longitudes = new Set(track.map((fix) => Math.round(fix.longitudeDeg)));
    expect(longitudes.size).toBeGreaterThan(3);
  });

  it("formats a fix and picks a slider step across the window", () => {
    expect(formatFix({ latitudeDeg: -12.5, longitudeDeg: -30, heightKm: 410.26 })).toBe("12.50°S, 30.00°W, 410.3 km");
    expect(sliderStepMs(0, 60_000)).toBe(1000);
    expect(sliderStepMs(0, 2_000_000)).toBe(10_000);
  });
});
