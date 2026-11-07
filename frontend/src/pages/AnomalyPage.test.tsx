import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { AnomalyDetail } from "../types";
import { AnomalyPage } from "./AnomalyPage";

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
    { causeId: "radiation", score: 85, evidence: ["SEP 2026-SEP-1 covers the entire gap."] },
    { causeId: "eclipse_power", score: 40, evidence: ["The satellite was in Earth shadow for 40% of the propagated samples."] },
    { causeId: "geomagnetic", score: 10, evidence: ["Highest Kp overlapping this gap was 1.3."] },
    { causeId: "software_system", score: 0, evidence: ["No repeating pattern."] },
  ],
  disclaimer: "These scores are estimates, not confirmed root causes.",
  timeline: {
    viewStart: "2026-02-28T23:00:00Z",
    viewEnd: "2026-03-01T05:01:00Z",
    events: [
      {
        kind: "sep",
        label: "2026-SEP-1",
        start: "2026-02-28T20:00:00Z",
        end: "2026-03-02T08:00:00Z",
      },
    ],
    eclipses: [{ start: "2026-03-01T02:00:20Z", end: "2026-03-01T02:00:40Z" }],
    eclipseStatus: "computed",
  },
  spaceWeather: {
    kp: { value: 5, observedAt: "2026-03-01T12:00:00Z" },
    events: [
      {
        kind: "sep",
        label: "2026-SEP-1",
        start: "2026-02-28T20:00:00Z",
        end: "2026-03-02T08:00:00Z",
      },
    ],
  },
};

vi.mock("../useAuth", () => ({
  useAuth: () => ({ session: { email: "ops@example.com", idToken: "token" } }),
}));

vi.mock("../api", () => ({
  getAnomaly: vi.fn(async () => detail),
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/anomalies/gap-0002"]}>
      <Routes>
        <Route path="/anomalies/:anomalyId" element={<AnomalyPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("anomaly detail", () => {
  it("shows independent scores, the timeline, evidence, and the latest Kp", async () => {
    renderPage();
    expect(await screen.findByRole("table", { name: /independent value from 0 to 100/i })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /radiation 85/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Radiation" })).toBeInTheDocument();
    expect(screen.getByText("SEP 2026-SEP-1 covers the entire gap.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /anomaly/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /eclipse/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sep 2026-sep-1/i })).toBeInTheDocument();
    expect(screen.getByText("Minor storm on the NOAA Kp scale.")).toBeInTheDocument();
    expect(screen.getByText("Observed 2026-03-01T12:00:00Z UTC")).toBeInTheDocument();
  });

  it("moves through timeline rows with the keyboard", async () => {
    renderPage();
    const anomaly = await screen.findByRole("button", { name: /anomaly/i });
    const eclipse = screen.getByRole("button", { name: /eclipse/i });
    const sep = screen.getByRole("button", { name: /sep 2026-sep-1/i });
    await userEvent.tab();
    expect(screen.getByRole("link", { name: /back to dashboard/i })).toHaveFocus();
    await userEvent.tab();
    expect(anomaly).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(anomaly).toHaveAttribute("aria-pressed", "true");
    await userEvent.tab();
    expect(eclipse).toHaveFocus();
    await userEvent.tab();
    expect(sep).toHaveFocus();
  });
});
