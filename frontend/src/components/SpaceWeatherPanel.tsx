import { kpBand, EVENT_LABELS } from "../timelineLayout";
import type { AnomalyDetail } from "../types";

export function SpaceWeatherPanel({ weather }: { weather: AnomalyDetail["spaceWeather"] }) {
  const kp = weather.kp;
  return (
    <aside aria-labelledby="weather-title" className="rounded-md border border-slate-800 bg-[#0c1824] p-4">
      <h2 id="weather-title" className="text-lg font-medium text-slate-50">
        Space weather
      </h2>
      {kp ? (
        <>
          <p className="mt-4 text-sm text-slate-400">Latest Kp</p>
          <p className="font-mono text-4xl text-slate-50">{formatKp(kp.value)}</p>
          <p className="mt-1 text-sm text-slate-300">{kpBand(kp.value)} on the NOAA Kp scale.</p>
          <p className="mt-1 font-mono text-xs text-slate-500">Observed {kp.observedAt} UTC</p>
        </>
      ) : (
        <p className="mt-4 text-sm text-slate-400">No Kp sample is stored yet.</p>
      )}
      <h3 className="mt-6 text-sm font-medium text-slate-200">Recent events</h3>
      {weather.events.length === 0 ? (
        <p className="mt-2 text-sm text-slate-400">No recent DONKI events are stored.</p>
      ) : (
        <ul className="mt-2 space-y-3">
          {weather.events.map((event) => (
            <li key={`${event.kind}-${event.label}-${event.start}`}>
              <p className="text-sm text-slate-100">
                {EVENT_LABELS[event.kind] ?? event.kind} {event.label}
              </p>
              <p className="font-mono text-xs text-slate-500">
                {event.start} to {event.end} UTC
              </p>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}

function formatKp(value: number): string {
  if (Number.isInteger(value)) {
    return String(value);
  }
  return value.toFixed(1);
}
