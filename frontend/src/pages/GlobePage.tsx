import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getAnomaly } from "../api";
import { mountGlobe, type GlobeHandle } from "../globe/mountGlobe";
import { formatFix, formatUtc, orbitPeriodMs, propagateFix, readSatrec, sampleTrack, sliderStepMs } from "../orbitTrack";
import type { AnomalyDetail } from "../types";
import { useAuth } from "../useAuth";

export function GlobePage() {
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
      <Link className="text-sm text-cyan-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300" to={`/anomalies/${anomalyId}`}>
        Back to anomaly
      </Link>
      <h1 className="mt-3 text-2xl font-medium text-slate-50">Orbit</h1>
      {error && (
        <p className="mt-4 rounded-md border border-rose-800 bg-rose-950 px-3 py-2 text-sm text-rose-100" role="alert">
          {error}
        </p>
      )}
      {!detail && !error && <p className="mt-6 text-sm text-slate-400">Loading…</p>}
      {detail && <OrbitView detail={detail} />}
    </section>
  );
}

export function OrbitView({ detail }: { detail: AnomalyDetail }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const handleRef = useRef<GlobeHandle | null>(null);
  const atMsRef = useRef(0);
  const [globeError, setGlobeError] = useState<string | null>(null);
  const tle = detail.orbit?.tle ?? null;
  const line1 = tle?.line1 ?? "";
  const line2 = tle?.line2 ?? "";
  const satrec = useMemo(() => (line1 && line2 ? readSatrec(line1, line2) : null), [line1, line2]);
  const startMs = Date.parse(detail.anomaly.startTime);
  const endMs = Date.parse(detail.anomaly.endTime);
  const [atMs, setAtMs] = useState(startMs);
  atMsRef.current = atMs;
  const fix = satrec && Number.isFinite(atMs) ? propagateFix(satrec, new Date(atMs)) : null;
  const step = sliderStepMs(startMs, endMs);
  const satelliteId = detail.anomaly.satelliteId;
  const saa = detail.orbit.saa;

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !satrec || !Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs < startMs) {
      return;
    }
    const period = orbitPeriodMs(satrec);
    const anomalyStart = new Date(startMs);
    const anomalyEnd = new Date(endMs);
    let cancelled = false;
    setGlobeError(null);
    mountGlobe({
      container,
      satelliteId,
      saa,
      orbit: sampleTrack(satrec, new Date(startMs - period), anomalyEnd, 360),
      anomaly: sampleTrack(satrec, anomalyStart, anomalyEnd, 180),
      anomalyStart: propagateFix(satrec, anomalyStart),
      initialTime: anomalyStart,
      initialFix: propagateFix(satrec, anomalyStart),
    })
      .then((handle) => {
        if (cancelled) {
          handle.destroy();
          return;
        }
        handleRef.current = handle;
        const current = new Date(atMsRef.current);
        handle.setTime(current, propagateFix(satrec, current));
      })
      .catch(() => {
        if (!cancelled) {
          setGlobeError("The globe could not be started in this browser.");
        }
      });
    return () => {
      cancelled = true;
      handleRef.current?.destroy();
      handleRef.current = null;
    };
  }, [endMs, saa, satrec, satelliteId, startMs]);

  useEffect(() => {
    if (!satrec || !Number.isFinite(atMs)) {
      return;
    }
    handleRef.current?.setTime(new Date(atMs), propagateFix(satrec, new Date(atMs)));
  }, [atMs, satrec]);

  if (!tle || !satrec) {
    return <p className="mt-4 text-sm text-slate-400">No TLE is stored for this satellite at the anomaly time, so the orbit cannot be drawn.</p>;
  }
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs < startMs) {
    return <p className="mt-4 text-sm text-slate-400">This anomaly does not have a usable time window.</p>;
  }

  return (
    <>
      <p className="mt-2 max-w-3xl text-sm text-slate-400">
        Cyan is the orbit leading into the gap. White is the anomaly window. The amber region is the South Atlantic
        Anomaly box used for scoring, {formatBound(saa.latMin)} to {formatBound(saa.latMax)} and {formatBound(saa.lonMin, true)} to {formatBound(saa.lonMax, true)}.
        Day and night follow the slider.
      </p>
      <div className="relative mt-4 h-[min(70vh,720px)] min-h-80 overflow-hidden rounded-md border border-slate-800" ref={containerRef} />
      {globeError && (
        <p className="mt-3 rounded-md border border-rose-800 bg-rose-950 px-3 py-2 text-sm text-rose-100" role="alert">
          {globeError}
        </p>
      )}
      <div className="mt-4">
        <label className="block text-sm text-slate-300" htmlFor="anomaly-time">
          Anomaly time
        </label>
        <input
          className="mt-2 w-full accent-cyan-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300"
          id="anomaly-time"
          max={endMs}
          min={startMs}
          onChange={(event) => setAtMs(Number(event.target.value))}
          step={step}
          type="range"
          value={atMs}
          aria-valuetext={formatUtc(atMs)}
        />
        <p className="mt-2 font-mono text-sm text-slate-200">{formatUtc(atMs)} UTC</p>
        <p className="mt-1 text-sm text-slate-300">{fix ? formatFix(fix) : "No position at this time."}</p>
      </div>
    </>
  );
}

function formatBound(value: number, longitude = false): string {
  if (value === 0) {
    return "0°";
  }
  const hemisphere = longitude ? (value >= 0 ? "E" : "W") : value >= 0 ? "N" : "S";
  return `${Math.abs(value)}°${hemisphere}`;
}
