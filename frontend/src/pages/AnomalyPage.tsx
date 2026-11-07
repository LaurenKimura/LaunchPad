import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getAnomaly } from "../api";
import { useAuth } from "../useAuth";
import { CAUSE_LABELS, type AnomalyDetail } from "../types";

export function AnomalyPage() {
  const { anomalyId = "" } = useParams();
  const { session } = useAuth();
  const [detail, setDetail] = useState<AnomalyDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!session || !anomalyId) {
      return;
    }
    let active = true;
    getAnomaly(session.idToken, anomalyId)
      .then((next) => {
        if (active) {
          setDetail(next);
          setError(null);
        }
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "Could not load this anomaly.");
        }
      });
    return () => {
      active = false;
    };
  }, [anomalyId, session]);

  return (
    <section>
      <Link className="text-sm text-cyan-200" to="/">
        Back to dashboard
      </Link>
      <h1 className="mt-3 text-2xl font-medium text-slate-50">Anomaly {anomalyId}</h1>
      {error && (
        <p className="mt-4 rounded-md border border-rose-800 bg-rose-950 px-3 py-2 text-sm text-rose-100" role="alert">
          {error}
        </p>
      )}
      {!detail && !error && <p className="mt-6 text-sm text-slate-400">Loading…</p>}
      {detail && (
        <>
          <p className="mt-2 font-mono text-sm text-slate-400">
            {detail.anomaly.satelliteId} · {detail.anomaly.startTime} UTC to {detail.anomaly.endTime} UTC
          </p>
          <p className="mt-4 text-sm text-slate-300">Each score is an independent 0–100 estimate. The numbers are not shares of one total.</p>
          {detail.scores.length === 0 ? (
            <p className="mt-4 text-sm text-slate-400">Scores are not ready yet. Correlation runs after the file is parsed.</p>
          ) : (
            <ul className="mt-4 grid gap-4 md:grid-cols-2">
              {detail.scores.map((score) => (
                <li className="rounded-md border border-slate-800 bg-[#0c1824] p-4" key={score.causeId}>
                  <p className="text-sm text-slate-400">{CAUSE_LABELS[score.causeId] ?? score.causeId}</p>
                  <p className="mt-1 font-mono text-3xl text-slate-50">{score.score}</p>
                  <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-300">
                    {score.evidence.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
