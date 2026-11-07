import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AnomalyDetail } from "../types";
import { GlobePage } from "./GlobePage";

const setTime = vi.fn();
const destroy = vi.fn();

vi.mock("../useAuth", () => ({
  useAuth: () => ({ session: { email: "ops@example.com", idToken: "token" } }),
}));

vi.mock("../globe/mountGlobe", () => ({
  mountGlobe: vi.fn(async () => ({ setTime, destroy })),
}));

const LINE1 = "1 25544U 98067A   24279.50000000  .00016717  00000-0  10270-3 0  9993";
const LINE2 = "2 25544  51.6400 123.4567 0006789  12.3456 347.6543 15.50000000123456";

const detail: AnomalyDetail = {
  anomaly: {
    anomalyId: "gap-0002",
    satelliteId: "iss",
    uploadId: "upload-1",
    startTime: "2024-10-05T12:00:00Z",
    endTime: "2024-10-05T12:10:00Z",
    gapSeconds: 600,
  },
  scores: [],
  disclaimer: "These scores are estimates, not confirmed root causes.",
  orbit: {
    tle: { line1: LINE1, line2: LINE2, epoch: "2024-10-05T12:00:00Z" },
    saa: { latMin: -50, latMax: 0, lonMin: -90, lonMax: 40 },
  },
  timeline: {
    viewStart: "2024-10-05T09:00:00Z",
    viewEnd: "2024-10-05T15:10:00Z",
    events: [],
    eclipses: [],
    eclipseStatus: "unavailable",
  },
  spaceWeather: { kp: null, events: [] },
};

vi.mock("../api", () => ({
  getAnomaly: vi.fn(async () => detail),
}));

import { getAnomaly } from "../api";
import { mountGlobe } from "../globe/mountGlobe";

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/anomalies/gap-0002/globe"]}>
      <Routes>
        <Route path="/anomalies/:anomalyId/globe" element={<GlobePage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("globe page", () => {
  beforeEach(() => {
    setTime.mockClear();
    destroy.mockClear();
    vi.mocked(mountGlobe).mockClear();
    vi.mocked(getAnomaly).mockResolvedValue(detail);
  });

  it("shows the anomaly position, the SAA box, and moves with the slider", async () => {
    renderPage();
    const slider = await screen.findByRole("slider", { name: "Anomaly time" });
    expect(screen.getByText(/50°S to 0° and 90°W to 40°E/)).toBeInTheDocument();
    expect(screen.getByText("2024-10-05T12:00:00Z UTC")).toBeInTheDocument();
    expect(screen.getByText(/km/)).toBeInTheDocument();
    const next = Number(slider.getAttribute("min")) + Number(slider.getAttribute("step"));
    fireEvent.change(slider, { target: { value: String(next) } });
    expect(screen.getByText("2024-10-05T12:00:03Z UTC")).toBeInTheDocument();
    expect(setTime).toHaveBeenCalled();
    const last = setTime.mock.calls[setTime.mock.calls.length - 1][0] as Date;
    expect(last.toISOString()).toBe("2024-10-05T12:00:03.000Z");
  });

  it("explains a missing TLE and does not start the globe", async () => {
    vi.mocked(getAnomaly).mockResolvedValue({
      ...detail,
      orbit: { ...detail.orbit, tle: null },
    });
    renderPage();
    expect(await screen.findByText(/No TLE is stored/)).toBeInTheDocument();
    expect(mountGlobe).not.toHaveBeenCalled();
  });
});