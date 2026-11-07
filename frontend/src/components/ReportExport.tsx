import { reportJson, reportPdf, buildReport } from "../report";
import type { AnomalyDetail } from "../types";

export function ReportExport({ detail }: { detail: AnomalyDetail }) {
  return (
    <div className="flex flex-wrap gap-2">
      <button
        className="min-h-11 rounded-md border border-slate-600 px-3 text-sm text-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300"
        onClick={() => save(`${fileBase(detail)}.json`, new Blob([reportJson(buildReport(detail, new Date().toISOString()))], { type: "application/json" }))}
        type="button"
      >
        Download JSON
      </button>
      <button
        className="min-h-11 rounded-md border border-slate-600 px-3 text-sm text-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300"
        onClick={() => save(`${fileBase(detail)}.pdf`, new Blob([reportPdf(buildReport(detail, new Date().toISOString()))], { type: "application/pdf" }))}
        type="button"
      >
        Download PDF
      </button>
    </div>
  );
}

function fileBase(detail: AnomalyDetail): string {
  return `anomaly-${detail.anomaly.anomalyId}`;
}

function save(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
