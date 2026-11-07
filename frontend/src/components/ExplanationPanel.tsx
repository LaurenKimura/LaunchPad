import { useState, type FormEvent } from "react";
import { DISCLAIMER } from "../disclaimer";
import type { Explanation } from "../types";

export type ExplainClient = {
  explain: () => Promise<Explanation>;
  ask: (question: string) => Promise<Explanation>;
};

type Message = {
  question: string;
  answer: string;
};

export function ExplanationPanel({ client }: { client: ExplainClient }) {
  const [summary, setSummary] = useState<string | null>(null);
  const [fixes, setFixes] = useState<string[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [remaining, setRemaining] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<"" | "explain" | "ask">("");

  async function explain() {
    setPending("explain");
    setError(null);
    try {
      const result = await client.explain();
      setSummary(result.summary ?? "");
      setFixes(result.fixes ?? []);
      setRemaining(result.remaining);
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "Could not explain this anomaly.");
    } finally {
      setPending("");
    }
  }

  async function send(event: FormEvent) {
    event.preventDefault();
    const next = question.trim();
    if (!next || pending) {
      return;
    }
    setPending("ask");
    setError(null);
    try {
      const result = await client.ask(next);
      setMessages((current) => [...current, { question: next, answer: result.answer ?? "" }]);
      setQuestion("");
      setRemaining(result.remaining);
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "Could not answer that question.");
    } finally {
      setPending("");
    }
  }

  return (
    <section aria-labelledby="explanation-title" className="mt-8">
      <h2 id="explanation-title" className="text-lg font-medium text-slate-50">
        Explanation
      </h2>
      <p className="mt-1 max-w-3xl text-sm text-slate-400">
        A summary and follow-up answers use this anomaly&apos;s stored scores, evidence, and timeline. Each request counts toward the daily limit.
      </p>
      <button
        className="mt-4 min-h-11 rounded-md bg-cyan-300 px-4 text-sm font-medium text-slate-950 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 disabled:opacity-60"
        disabled={pending !== ""}
        onClick={() => void explain()}
        type="button"
      >
        {pending === "explain" ? "Explaining…" : "Explain scores"}
      </button>
      {summary !== null && (
        <div className="mt-4 rounded-md border border-slate-800 bg-[#0c1824] p-4">
          <p className="text-sm text-slate-100">{summary}</p>
          <h3 className="mt-4 text-sm text-slate-400">Recommended fixes</h3>
          {fixes.length === 0 ? (
            <p className="mt-2 text-sm text-slate-300">None of the allowed fixes were supported by the stored scores.</p>
          ) : (
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-100">
              {fixes.map((fix) => (
                <li key={fix}>{fix}</li>
              ))}
            </ul>
          )}
          <p className="mt-4 text-sm text-slate-400">{DISCLAIMER}</p>
        </div>
      )}
      <form className="mt-4" onSubmit={(event) => void send(event)}>
        <label className="block text-sm text-slate-300" htmlFor="follow-up">
          Follow-up question
        </label>
        <div className="mt-2 flex flex-col gap-2 sm:flex-row">
          <input
            className="min-h-11 w-full rounded-md border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300"
            id="follow-up"
            maxLength={500}
            onChange={(event) => setQuestion(event.target.value)}
            value={question}
          />
          <button
            className="min-h-11 rounded-md border border-slate-600 px-4 text-sm text-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 disabled:opacity-60"
            disabled={pending !== "" || question.trim() === ""}
            type="submit"
          >
            Send
          </button>
        </div>
      </form>
      {messages.length > 0 && (
        <ol aria-live="polite" className="mt-4 space-y-3">
          {messages.map((message) => (
            <li className="rounded-md border border-slate-800 p-3" key={`${message.question}-${message.answer}`}>
              <p className="text-sm text-slate-400">{message.question}</p>
              <p className="mt-2 text-sm text-slate-100">{message.answer}</p>
            </li>
          ))}
        </ol>
      )}
      {remaining !== null && (
        <p className="mt-3 text-sm text-slate-400">{remaining} explanations left today.</p>
      )}
      {error && (
        <p className="mt-3 rounded-md border border-rose-800 bg-rose-950 px-3 py-2 text-sm text-rose-100" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
