export function placeInterval(
  startIso: string,
  endIso: string,
  viewStartIso: string,
  viewEndIso: string,
): { left: number; width: number } {
  const viewStart = Date.parse(viewStartIso);
  const viewEnd = Date.parse(viewEndIso);
  const span = viewEnd - viewStart;
  if (!Number.isFinite(span) || span <= 0) {
    return { left: 0, width: 100 };
  }
  const start = clamp(Date.parse(startIso), viewStart, viewEnd);
  const end = clamp(Date.parse(endIso), viewStart, viewEnd);
  const left = ((start - viewStart) / span) * 100;
  const natural = ((Math.max(end, start) - start) / span) * 100;
  const width = Math.min(Math.max(natural, end > start ? 1.25 : 0), 100 - left);
  return { left, width };
}

function clamp(value: number, low: number, high: number): number {
  if (!Number.isFinite(value)) {
    return low;
  }
  return Math.min(high, Math.max(low, value));
}

export function kpBand(value: number): string {
  if (value >= 9) {
    return "Extreme storm";
  }
  if (value >= 8) {
    return "Severe storm";
  }
  if (value >= 7) {
    return "Strong storm";
  }
  if (value >= 6) {
    return "Moderate storm";
  }
  if (value >= 5) {
    return "Minor storm";
  }
  return "Quiet to unsettled";
}

export const EVENT_LABELS: Record<string, string> = {
  sep: "SEP",
  flare: "Flare",
  cme: "CME",
  gst: "Geomagnetic storm",
  eclipse: "Eclipse",
  anomaly: "Anomaly",
};

export const EVENT_COLORS: Record<string, string> = {
  sep: "#f59e0b",
  flare: "#fb7185",
  cme: "#f97316",
  gst: "#c084fc",
  eclipse: "#818cf8",
  anomaly: "#22d3ee",
};

export const CAUSE_COLORS: Record<string, string> = {
  radiation: "#f59e0b",
  eclipse_power: "#38bdf8",
  geomagnetic: "#c084fc",
  software_system: "#34d399",
};
