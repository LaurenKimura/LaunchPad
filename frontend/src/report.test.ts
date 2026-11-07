import { describe, expect, it } from "vitest";
import { buildReport, reportJson, reportPdf } from "./report";
import type { AnomalyDetail } from "./types";

const detail: AnomalyDetail = {
  anomaly: {
    anomalyId: "gap-0002",
    satelliteId: "iss",
    uploadId: "upload-1",
    startTime: "2026-03-01T02:00:00Z",
    endTime: "2026-03-01T02:01:00Z",
    gapSeconds: 60,
  },
  scores: [
    { causeId: "radiation", score: 85, evidence: ["SEP covers the gap (full overlap)."] },
    { causeId: "eclipse_power", score: 40, evidence: ["Earth shadow for 40% of samples."] },
  ],
  disclaimer: "These scores are estimates, not confirmed root causes.",
  orbit: {
    tle: { line1: "SECRET-TLE-LINE", line2: "2 secret", epoch: "2026-03-01T00:00:00Z" },
    saa: { latMin: -50, latMax: 0, lonMin: -90, lonMax: 40 },
  },
  timeline: {
    viewStart: "2026-02-28T23:00:00Z",
    viewEnd: "2026-03-01T05:01:00Z",
    events: [{ kind: "sep", label: "2026-SEP-1", start: "2026-02-28T20:00:00Z", end: "2026-03-02T08:00:00Z" }],
    eclipses: [{ start: "2026-03-01T02:00:20Z", end: "2026-03-01T02:00:40Z" }],
    eclipseStatus: "computed",
  },
  spaceWeather: {
    kp: { value: 5, observedAt: "2026-03-01T12:00:00Z" },
    events: [],
  },
};

describe("anomaly report", () => {
  it("exports the scores and leaves the TLE lines out", () => {
    const report = buildReport(detail, "2026-03-02T00:00:00Z");
    const json = reportJson(report);
    expect(json).toContain("These scores are estimates, not confirmed root causes.");
    expect(json).toContain('"score": 85');
    expect(json).toContain("Radiation");
    expect(json).toContain("2026-SEP-1");
    expect(json).not.toContain("SECRET-TLE-LINE");
  });

  it("writes a PDF that contains the same disclaimer and escapes parentheses", () => {
    const pdf = new TextDecoder().decode(reportPdf(buildReport(detail, "2026-03-02T00:00:00Z")));
    expect(pdf.startsWith("%PDF-1.4")).toBe(true);
    expect(pdf).toContain("These scores are estimates, not confirmed root causes.");
    expect(pdf).toContain("SEP covers the gap \\(full overlap\\).");
    expect(pdf).not.toContain("SECRET-TLE-LINE");
    const start = pdf.match(/startxref\n(\d+)/);
    expect(start).not.toBeNull();
    expect(pdf.indexOf("xref\n")).toBe(Number(start?.[1]));
  });
});
