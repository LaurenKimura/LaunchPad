import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";

const auth = vi.hoisted(() => ({
  ready: true,
  configured: true,
  session: null as { email: string; idToken: string } | null,
  signIn: vi.fn(),
  signUp: vi.fn(),
  confirm: vi.fn(),
  signOut: vi.fn(),
}));

vi.mock("../useAuth", () => ({
  useAuth: () => auth,
}));

vi.mock("../api", () => ({
  listSatellites: vi.fn(),
  listAnomalies: vi.fn(),
  uploadTelemetry: vi.fn(),
}));

import { listAnomalies, listSatellites, uploadTelemetry } from "../api";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("operator pages", () => {
  beforeEach(() => {
    auth.session = null;
    auth.signIn.mockReset();
    vi.mocked(listSatellites).mockReset();
    vi.mocked(listAnomalies).mockReset();
  });

  it("shows the estimate disclaimer and rejects an empty sign-in", async () => {
    renderAt("/login");
    expect(screen.getByRole("note")).toHaveTextContent("These scores are estimates, not confirmed root causes.");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a valid email address.");
    expect(auth.signIn).not.toHaveBeenCalled();
  });

  it("shows password rules on sign-up before calling Cognito", async () => {
    renderAt("/signup");
    await userEvent.type(screen.getByLabelText("Email"), "ops@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "short");
    await userEvent.type(screen.getByLabelText("Repeat password"), "short");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Use at least 12 characters.");
    expect(auth.signUp).not.toHaveBeenCalled();
  });

  it("lists satellites and recent anomalies", async () => {
    auth.session = { email: "ops@example.com", idToken: "token" };
    vi.mocked(listSatellites).mockResolvedValue([{ satelliteId: "iss", name: "ISS", noradId: "25544" }]);
    vi.mocked(listAnomalies).mockResolvedValue([
      {
        anomalyId: "gap-0001",
        satelliteId: "iss",
        uploadId: "upload-1",
        startTime: "2026-03-01T00:00:30Z",
        endTime: "2026-03-01T00:01:30Z",
        gapSeconds: 60,
      },
    ]);
    renderAt("/");
    expect(await screen.findByText("ISS")).toBeInTheDocument();
    expect(screen.getByText("60 s gap")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /iss/i })).toHaveAttribute("href", "/anomalies/gap-0001");
  });

  it("shows validation errors for a bad drop and does not upload", async () => {
    auth.session = { email: "ops@example.com", idToken: "token" };
    vi.mocked(listSatellites).mockResolvedValue([{ satelliteId: "iss", name: "ISS" }]);
    renderAt("/upload");
    await screen.findByRole("option", { name: "ISS" });
    await userEvent.selectOptions(screen.getByLabelText("Satellite"), "iss");
    const input = screen.getByLabelText("Telemetry file");
    await userEvent.upload(input, new File(["hello"], "notes.txt", { type: "text/plain" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Only CSV and JSON files are accepted.");

    await userEvent.upload(input, new File([], "empty.csv", { type: "text/csv" }));
    expect(screen.getByRole("alert")).toHaveTextContent("The file is empty.");

    await userEvent.click(screen.getByRole("button", { name: "Upload" }));
    expect(screen.getByRole("alert")).toHaveTextContent("The file is empty.");
    expect(uploadTelemetry).not.toHaveBeenCalled();
  });
});
