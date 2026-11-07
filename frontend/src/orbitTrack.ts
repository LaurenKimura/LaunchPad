import { degreesLat, degreesLong, eciToGeodetic, gstime, propagate, twoline2satrec, type SatRec } from "satellite.js";

export type GeodeticFix = {
  at: string;
  latitudeDeg: number;
  longitudeDeg: number;
  heightKm: number;
};

export type TrackPoint = {
  latitudeDeg: number;
  longitudeDeg: number;
  heightKm: number;
};

export function readSatrec(line1: string, line2: string): SatRec | null {
  try {
    const satrec = twoline2satrec(line1.trim(), line2.trim());
    if (satrec.error) {
      return null;
    }
    return satrec;
  } catch {
    return null;
  }
}

export function propagateFix(satrec: SatRec, at: Date): GeodeticFix | null {
  const propagated = propagate(satrec, at);
  if (!propagated?.position || typeof propagated.position === "boolean") {
    return null;
  }
  const geo = eciToGeodetic(propagated.position, gstime(at));
  const latitudeDeg = degreesLat(geo.latitude);
  const longitudeDeg = degreesLong(geo.longitude);
  if (!Number.isFinite(latitudeDeg) || !Number.isFinite(longitudeDeg) || !Number.isFinite(geo.height)) {
    return null;
  }
  return {
    at: at.toISOString().replace(".000Z", "Z"),
    latitudeDeg,
    longitudeDeg,
    heightKm: geo.height,
  };
}

export function orbitPeriodMs(satrec: SatRec): number {
  if (!satrec.no || satrec.no <= 0) {
    return 90 * 60 * 1000;
  }
  return ((2 * Math.PI) / satrec.no) * 60 * 1000;
}

export function sampleTrack(satrec: SatRec, start: Date, end: Date, maxSamples: number): GeodeticFix[] {
  const span = end.getTime() - start.getTime();
  if (span <= 0) {
    const fix = propagateFix(satrec, start);
    return fix ? [fix] : [];
  }
  const count = Math.min(Math.max(2, maxSamples), Math.max(2, Math.ceil(span / 1000)));
  const fixes: GeodeticFix[] = [];
  for (let index = 0; index <= count; index += 1) {
    const at = new Date(start.getTime() + (span * index) / count);
    const fix = propagateFix(satrec, at);
    if (fix) {
      fixes.push(fix);
    }
  }
  return fixes;
}

export function sliderStepMs(startMs: number, endMs: number): number {
  const span = Math.max(0, endMs - startMs);
  if (span === 0) {
    return 1000;
  }
  return Math.max(1000, Math.round(span / 200));
}

export function formatUtc(ms: number): string {
  return new Date(ms).toISOString().replace(".000Z", "Z");
}

export function formatFix(fix: TrackPoint): string {
  const lat = `${Math.abs(fix.latitudeDeg).toFixed(2)}°${fix.latitudeDeg >= 0 ? "N" : "S"}`;
  const lon = `${Math.abs(fix.longitudeDeg).toFixed(2)}°${fix.longitudeDeg >= 0 ? "E" : "W"}`;
  return `${lat}, ${lon}, ${fix.heightKm.toFixed(1)} km`;
}
