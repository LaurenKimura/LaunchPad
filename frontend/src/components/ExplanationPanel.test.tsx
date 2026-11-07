import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api";
import { ExplanationPanel, type ExplainClient } from "./ExplanationPanel";

function client(overrides: Partial<ExplainClient> = {}): ExplainClient {
  return {
    explain: vi.fn(async () => ({
      summary: "Radiation is 85. The evidence is weak for software faults.",
      fixes: ["safe mode", "EDAC scrubbing"],
      disclaimer: "These scores are estimates, not confirmed root causes.",
      remaining: 19,
    })),
    ask: vi.fn(async (question: string) => ({
      answer: `The stored radiation score is 85. Asked: ${question}`,
      disclaimer: "These scores are estimates, not confirmed root causes.",
      remaining: 18,
    })),
    ...overrides,
  };
}

describe("explanation panel", () => {
  it("shows the summary, the allowed fixes, and a follow-up answer", async () => {
    const api = client();
    render(<ExplanationPanel client={api} />);
    await userEvent.click(screen.getByRole("button", { name: "Explain scores" }));
    expect(await screen.findByText(/Radiation is 85/)).toBeInTheDocument();
    expect(screen.getByText("safe mode")).toBeInTheDocument();
    expect(screen.getByText("EDAC scrubbing")).toBeInTheDocument();
    expect(screen.getByText("These scores are estimates, not confirmed root causes.")).toBeInTheDocument();
    expect(screen.getByText("19 explanations left today.")).toBeInTheDocument();

    const box = screen.getByRole("textbox", { name: "Follow-up question" });
    await userEvent.type(box, "What was the radiation score?{Enter}");
    expect(await screen.findByText(/Asked: What was the radiation score\?/)).toBeInTheDocument();
    expect(api.ask).toHaveBeenCalledWith("What was the radiation score?");
    expect(screen.getByText("18 explanations left today.")).toBeInTheDocument();
  });

  it("shows the daily limit and keeps the question", async () => {
    const api = client({
      ask: vi.fn(async () => {
        throw new ApiError("daily_limit");
      }),
    });
    render(<ExplanationPanel client={api} />);
    const box = screen.getByRole("textbox", { name: "Follow-up question" });
    await userEvent.type(box, "Was it in eclipse?");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/daily explanation limit/);
    expect(box).toHaveValue("Was it in eclipse?");
  });
});
