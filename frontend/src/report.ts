import { CAUSE_LABELS, type AnomalyDetail, type AnomalyReport } from "./types";

const LINE_WIDTH = 90;
const LINES_PER_PAGE = 46;

export function buildReport(detail: AnomalyDetail, exportedAt: string): AnomalyReport {
  return {
    title: "LaunchPad anomaly report",
    exportedAt,
    disclaimer: detail.disclaimer,
    anomaly: {
      anomalyId: detail.anomaly.anomalyId,
      satelliteId: detail.anomaly.satelliteId,
      uploadId: detail.anomaly.uploadId,
      startTime: detail.anomaly.startTime,
      endTime: detail.anomaly.endTime,
      gapSeconds: detail.anomaly.gapSeconds,
    },
    scores: detail.scores.map((score) => ({
      causeId: score.causeId,
      label: CAUSE_LABELS[score.causeId] ?? score.causeId,
      score: score.score,
      evidence: score.evidence,
    })),
    timeline: {
      eclipseStatus: detail.timeline.eclipseStatus,
      events: detail.timeline.events,
      eclipses: detail.timeline.eclipses,
    },
    spaceWeather: detail.spaceWeather,
    southAtlanticAnomaly: detail.orbit.saa,
  };
}

export function reportJson(report: AnomalyReport): string {
  return `${JSON.stringify(report, null, 2)}\n`;
}

export function reportLines(report: AnomalyReport): string[] {
  const lines = [
    report.title,
    `Exported ${report.exportedAt}`,
    report.disclaimer,
    "",
    `Anomaly ${report.anomaly.anomalyId}`,
    `Satellite ${report.anomaly.satelliteId}`,
    `Upload ${report.anomaly.uploadId}`,
    `Window ${report.anomaly.startTime} to ${report.anomaly.endTime} UTC`,
    `Gap ${report.anomaly.gapSeconds} seconds`,
    "",
    "Cause likelihoods. Each score is an independent estimate from 0 to 100.",
  ];
  if (report.scores.length === 0) {
    lines.push("No scores are stored.");
  }
  for (const score of report.scores) {
    lines.push(`${score.label}: ${score.score}`);
    if (score.evidence.length === 0) {
      lines.push("  No evidence lines.");
    }
    for (const line of score.evidence) {
      lines.push(`  ${line}`);
    }
  }
  lines.push("", `Eclipse status: ${report.timeline.eclipseStatus}`);
  if (report.timeline.eclipses.length === 0) {
    lines.push("No eclipse intervals in this window.");
  }
  for (const eclipse of report.timeline.eclipses) {
    lines.push(`Eclipse ${eclipse.start} to ${eclipse.end} UTC`);
  }
  lines.push("", "Space-weather events overlapping the gap");
  if (report.timeline.events.length === 0) {
    lines.push("No overlapping events are stored.");
  }
  for (const event of report.timeline.events) {
    lines.push(`${event.kind} ${event.label}: ${event.start} to ${event.end} UTC`);
  }
  const kp = report.spaceWeather.kp;
  lines.push("", kp ? `Latest Kp ${kp.value} observed ${kp.observedAt} UTC` : "No Kp observation is stored.");
  const saa = report.southAtlanticAnomaly;
  lines.push(
    `South Atlantic Anomaly box used for scoring: latitude ${saa.latMin} to ${saa.latMax}, longitude ${saa.lonMin} to ${saa.lonMax}.`,
  );
  lines.push("", report.disclaimer);
  return lines.flatMap((line) => wrap(line, LINE_WIDTH));
}

export function reportPdf(report: AnomalyReport): Uint8Array {
  return asciiBytes(renderPdf(reportLines(report)));
}

function wrap(text: string, width: number): string[] {
  if (text.length <= width) {
    return [text];
  }
  const words = text.split(" ");
  const lines: string[] = [];
  let current = "";
  for (const word of words) {
    const next = current ? `${current} ${word}` : word;
    if (next.length > width && current) {
      lines.push(current);
      current = word;
    } else {
      current = next;
    }
  }
  if (current) {
    lines.push(current);
  }
  return lines.length > 0 ? lines : [""];
}

function renderPdf(lines: string[]): string {
  const pages: string[][] = [];
  for (let index = 0; index < lines.length; index += LINES_PER_PAGE) {
    pages.push(lines.slice(index, index + LINES_PER_PAGE));
  }
  if (pages.length === 0) {
    pages.push([""]);
  }
  const objects: string[] = ["<< /Type /Catalog /Pages 2 0 R >>", ""];
  const pageIds: number[] = [];
  pages.forEach((pageLines, index) => {
    const pageId = 3 + index * 2;
    const contentId = pageId + 1;
    pageIds.push(pageId);
    const stream = pageStream(pageLines);
    objects.push(
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents ${contentId} 0 R /Resources << /Font << /F1 ${3 + pages.length * 2} 0 R >> >> >>`,
    );
    objects.push(`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`);
  });
  objects[1] = `<< /Type /Pages /Count ${pages.length} /Kids [${pageIds.map((id) => `${id} 0 R`).join(" ")}] >>`;
  objects.push("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>");

  const chunks = ["%PDF-1.4\n"];
  let cursor = chunks[0].length;
  const offsets: number[] = [];
  objects.forEach((body, index) => {
    const object = `${index + 1} 0 obj\n${body}\nendobj\n`;
    offsets.push(cursor);
    chunks.push(object);
    cursor += object.length;
  });
  const xrefAt = cursor;
  const xref = ["xref\n", `0 ${objects.length + 1}\n`, "0000000000 65535 f \n"];
  for (const offset of offsets) {
    xref.push(`${offset.toString().padStart(10, "0")} 00000 n \n`);
  }
  const trailer = `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefAt}\n%%EOF\n`;
  return chunks.join("") + xref.join("") + trailer;
}

function pageStream(lines: string[]): string {
  const commands = ["BT", "/F1 11 Tf", "54 740 Td", "14 TL"];
  for (const line of lines) {
    commands.push(`(${escapePdf(line)}) Tj`, "T*");
  }
  commands.push("ET");
  return commands.join("\n");
}

function escapePdf(text: string): string {
  return text
    .replace(/[^\x20-\x7e]/g, "?")
    .replace(/\\/g, "\\\\")
    .replace(/\(/g, "\\(")
    .replace(/\)/g, "\\)");
}

function asciiBytes(text: string): Uint8Array {
  const bytes = new Uint8Array(text.length);
  for (let index = 0; index < text.length; index += 1) {
    bytes[index] = text.charCodeAt(index);
  }
  return bytes;
}
