import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listAnomalies, listSatellites } from "../api";
import { useAuth } from "../useAuth";
import type { Anomaly, Satellite } from "../types";

export function DashboardPage() {
  const { session } = useAuth();
  const [satellites, setSatellites] = useState<Satellite[]>([]);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!session) {
      return;
    }
    let active = true;
    setLoading(true);
    Promise.all([listSatellites(session.idToken), listAnomalies(session.idToken)])
      .then(([nextSatellites, nextAnomalies]) => {
        if (!active) {
          return;
        }
        setSatellites(nextSatellites);
        setAnomalies(nextAnomalies);
        setError(null);
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "Could not load the dashboard.");
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [session]);

  return (
    <section>
      <h1 className="text-2xl font-medium text-slate-50">Dashboard</h1>
      <p className="mt-2 text-sm text-slate-400">Satellites on this account and the newest gap windows.</p>
      {loading && <p className="mt-6 text-sm text-slate-400">Loading…</p>}
      {error && (
        <p className="mt-6 rounded-md border border-rose-800 bg-rose-950 px-3 py-2 text-sm text-rose-100" role="alert">
          {error}
        </p>
      )}
      {!loading && !error && (
        <div className="mt-6 grid gap-6 lg:grid-cols-[16rem_1fr]">
          <aside>
            <h2 className="text-sm uppercase tracking-wide text-slate-400">Satellites</h2>
            {satellites.length === 0 ? (
              <p className="mt-3 text-sm text-slate-400">No satellites are registered for this account yet.</p>
            ) : (
              <ul className="mt-3 space-y-2">
                {satellites.map((satellite) => (
                  <li className="rounded-md border border-slate-800 bg-[#0c1824] px-3 py-2" key={satellite.satelliteId}>
                    <p className="font-medium text-slate-100">{satellite.name || satellite.satelliteId}</p>
                    <p className="font-mono text-xs text-slate-400">{satellite.satelliteId}</p>
                    {satellite.noradId && <p className="text-xs text-slate-500">NORAD {satellite.noradId}</p>}
                  </li>
                ))}
              </ul>
            )}
          </aside>
          <div>
            <h2 className="text-sm uppercase tracking-wide text-slate-400">Recent anomalies</h2>
            {anomalies.length === 0 ? (
              <p className="mt-3 text-sm text-slate-400">No gaps have been recorded yet. Upload a telemetry file to look for them.</p>
            ) : (
              <ul className="mt-3 divide-y divide-slate-800 rounded-md border border-slate-800">
                {anomalies.map((anomaly) => (
                  <li key={anomaly.anomalyId}>
                    <Link className="block px-4 py-3 hover:bg-slate-900" to={`/anomalies/${anomaly.anomalyId}`}>
                      <span className="font-mono text-sm text-cyan-100">{anomaly.satelliteId}</span>
                      <span className="ml-3 text-sm text-slate-300">{formatGap(anomaly.gapSeconds)} gap</span>
                      <span className="mt-1 block font-mono text-xs text-slate-500">
                        {anomaly.startTime} UTC to {anomaly.endTime} UTC
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function formatGap(seconds: number): string {
  if (seconds >= 120) {
    return `${Math.round(seconds / 60)} min`;
  }
  return `${Math.round(seconds)} s`;
}
