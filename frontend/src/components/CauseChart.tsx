import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { CAUSE_LABELS, type CauseScore } from "../types";
import { CAUSE_COLORS } from "../timelineLayout";

const AXIS_LABELS: Record<string, string> = {
  radiation: "Radiation",
  eclipse_power: "Eclipse",
  geomagnetic: "Geomagnetic",
  software_system: "Software",
};

export function CauseChart({ scores }: { scores: CauseScore[] }) {
  const data = scores.map((score) => ({
    causeId: score.causeId,
    label: AXIS_LABELS[score.causeId] ?? score.causeId,
    score: score.score,
  }));
  return (
    <section aria-labelledby="cause-chart-title" className="min-w-0">
      <h2 id="cause-chart-title" className="text-lg font-medium text-slate-50">
        Cause likelihoods
      </h2>
      <p className="mt-1 text-sm text-slate-400">
        Each bar is an independent estimate from 0 to 100. The bars do not add up to 100.
      </p>
      {scores.length === 0 ? (
        <p className="mt-4 text-sm text-slate-400">Scores are not ready yet. Correlation runs after the file is parsed.</p>
      ) : (
        <>
          <div className="mt-4 h-72 w-full" aria-hidden="true">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data} margin={{ top: 28, right: 8, left: 0, bottom: 4 }}>
                <CartesianGrid vertical={false} stroke="#1e293b" />
                <XAxis
                  dataKey="label"
                  height={64}
                  interval={0}
                  stroke="#475569"
                  tick={{ fill: "#cbd5e1", fontSize: 12 }}
                />
                <YAxis
                  domain={[0, 100]}
                  stroke="#475569"
                  tick={{ fill: "#94a3b8", fontSize: 12 }}
                  ticks={[0, 25, 50, 75, 100]}
                  width={40}
                />
                <Bar
                  dataKey="score"
                  label={{ position: "top", fill: "#e2e8f0", fontSize: 12 }}
                  maxBarSize={64}
                  radius={[4, 4, 0, 0]}
                >
                  {data.map((entry) => (
                    <Cell key={entry.causeId} fill={CAUSE_COLORS[entry.causeId] ?? "#94a3b8"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <table className="sr-only">
            <caption>Cause likelihoods, each an independent value from 0 to 100</caption>
            <thead>
              <tr>
                <th scope="col">Cause</th>
                <th scope="col">Likelihood</th>
              </tr>
            </thead>
            <tbody>
              {scores.map((score) => (
                <tr key={score.causeId}>
                  <th scope="row">{CAUSE_LABELS[score.causeId] ?? score.causeId}</th>
                  <td>{score.score}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
