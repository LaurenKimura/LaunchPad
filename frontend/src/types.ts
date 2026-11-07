export type Satellite = {
  satelliteId: string;
  name?: string;
  noradId?: string;
};

export type Anomaly = {
  anomalyId: string;
  satelliteId: string;
  uploadId: string;
  startTime: string;
  endTime: string;
  gapSeconds: number;
};

export type CauseScore = {
  causeId: string;
  score: number;
  evidence: string[];
};

export type TimelineEvent = {
  kind: string;
  label: string;
  start: string;
  end: string;
};

export type TimeSpan = {
  start: string;
  end: string;
};

export type AnomalyDetail = {
  anomaly: Anomaly;
  scores: CauseScore[];
  disclaimer: string;
  timeline: {
    viewStart: string;
    viewEnd: string;
    events: TimelineEvent[];
    eclipses: TimeSpan[];
    eclipseStatus: "unavailable" | "computed";
  };
  spaceWeather: {
    kp: { value: number; observedAt: string } | null;
    events: TimelineEvent[];
  };
};

export type Presign = {
  uploadId: string;
  url: string;
  fields: Record<string, string>;
  maxBytes: number;
};

export const CAUSE_LABELS: Record<string, string> = {
  radiation: "Radiation",
  eclipse_power: "Eclipse / power",
  geomagnetic: "Geomagnetic",
  software_system: "Software / system",
};
