import { useState } from "react";
import { EVENT_COLORS, EVENT_LABELS, placeInterval } from "../timelineLayout";
import type { AnomalyDetail } from "../types";

type Row = {
  id: string;
  title: string;
  start: string;
  end: string;
  color: string;
};

export function AnomalyTimeline({ detail }: { detail: AnomalyDetail }) {
  const [selected, setSelected] = useState("");
  const rows = timelineRows(detail);
  const { viewStart, viewEnd, eclipseStatus, eclipses } = detail.timeline;
  return (
    <section aria-labelledby="timeline-title" className="mt-8">
      <h2 id="timeline-title" className="text-lg font-medium text-slate-50">
        Timeline
      </h2>
      <p className="mt-1 text-sm text-slate-400">
        The track runs from three hours before the gap to three hours after it. A bar that reaches either edge
        continues outside this view. Times are UTC. Use Tab to move through the rows.
      </p>
      <p className="mt-2 font-mono text-xs text-slate-500">
        {viewStart} to {viewEnd}
      </p>
      <ol className="mt-4 space-y-2">
        {rows.map((row) => {
          const placed = placeInterval(row.start, row.end, viewStart, viewEnd);
          return (
            <li key={row.id}>
              <button
                aria-pressed={selected === row.id}
                className="grid w-full min-h-11 gap-2 rounded-md border border-transparent px-2 py-2 text-left hover:border-slate-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 aria-pressed:border-cyan-800 sm:grid-cols-[14rem_minmax(0,1fr)] sm:items-center"
                onClick={() => setSelected(selected === row.id ? "" : row.id)}
                type="button"
              >
                <span>
                  <span className="block text-sm text-slate-100">{row.title}</span>
                  <span className="block font-mono text-xs text-slate-400">
                    {row.start} to {row.end} UTC
                  </span>
                </span>
                <span aria-hidden="true" className="relative h-3 rounded-full bg-slate-800">
                  <span
                    className="absolute inset-y-0 rounded-full"
                    style={{ left: `${placed.left}%`, width: `${placed.width}%`, background: row.color }}
                  />
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      {eclipseStatus === "unavailable" && (
        <p className="mt-3 text-sm text-slate-400">No TLE was available, so Earth-shadow time was not drawn.</p>
      )}
      {eclipseStatus === "computed" && eclipses.length === 0 && (
        <p className="mt-3 text-sm text-slate-400">The satellite was in sunlight for every propagated sample in this gap.</p>
      )}
      {detail.timeline.events.length === 0 && (
        <p className="mt-3 text-sm text-slate-400">No SEP, flare, CME, or geomagnetic storm overlaps this view.</p>
      )}
    </section>
  );
}

function timelineRows(detail: AnomalyDetail): Row[] {
  const rows: Row[] = [
    {
      id: "anomaly",
      title: "Anomaly",
      start: detail.anomaly.startTime,
      end: detail.anomaly.endTime,
      color: EVENT_COLORS.anomaly,
    },
  ];
  detail.timeline.eclipses.forEach((interval, index) => {
    rows.push({
      id: `eclipse-${index}`,
      title: "Eclipse",
      start: interval.start,
      end: interval.end,
      color: EVENT_COLORS.eclipse,
    });
  });
  detail.timeline.events.forEach((event, index) => {
    const kind = EVENT_LABELS[event.kind] ?? event.kind;
    rows.push({
      id: `event-${index}`,
      title: `${kind} ${event.label}`,
      start: event.start,
      end: event.end,
      color: EVENT_COLORS[event.kind] ?? "#94a3b8",
    });
  });
  return rows;
}
