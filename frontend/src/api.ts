import { appConfig } from "./config";
import type { Anomaly, AnomalyDetail, Explanation, Presign, Satellite } from "./types";
import { contentTypeFor } from "./uploadRules";

const ERROR_TEXT: Record<string, string> = {
  unauthorized: "Sign in again.",
  not_found: "That record is not on your account.",
  satellite_not_found: "That satellite is not on your account.",
  invalid_content_type: "Only CSV and JSON files are accepted.",
  invalid_satellite: "Choose a satellite.",
  invalid_anomaly: "That anomaly id is not valid.",
  invalid_limit: "Choose a smaller page size.",
  invalid_body: "The explanation request was not valid.",
  invalid_question: "Enter a question.",
  question_too_long: "Shorten the question to 500 characters.",
  no_scores: "This anomaly has no stored scores to explain.",
  daily_limit: "The daily explanation limit for this account has been reached.",
  explanation_unavailable: "The explanation service is unavailable. Try again shortly.",
  store_unavailable: "The service is unavailable. Try again shortly.",
  sign_failed: "The upload URL could not be signed. Try again.",
};

export class ApiError extends Error {
  code: string;

  constructor(code: string) {
    super(ERROR_TEXT[code] ?? "The request failed.");
    this.code = code;
  }
}

export async function listSatellites(idToken: string): Promise<Satellite[]> {
  const payload = await request<{ satellites: Satellite[] }>("/satellites", idToken);
  return payload.satellites;
}

export async function listAnomalies(idToken: string): Promise<Anomaly[]> {
  const payload = await request<{ anomalies: Anomaly[] }>("/anomalies", idToken);
  return payload.anomalies;
}

export async function getAnomaly(idToken: string, anomalyId: string): Promise<AnomalyDetail> {
  return request<AnomalyDetail>(`/anomalies/${encodeURIComponent(anomalyId)}`, idToken);
}

export async function explainAnomaly(idToken: string, anomalyId: string): Promise<Explanation> {
  return request<Explanation>(`/anomalies/${encodeURIComponent(anomalyId)}/explain`, idToken, {
    method: "POST",
    body: "{}",
  });
}

export async function askAnomaly(idToken: string, anomalyId: string, question: string): Promise<Explanation> {
  return request<Explanation>(`/anomalies/${encodeURIComponent(anomalyId)}/explain`, idToken, {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

export async function uploadTelemetry(idToken: string, satelliteId: string, file: File): Promise<string> {
  const presign = await request<Presign>("/uploads", idToken, {
    method: "POST",
    body: JSON.stringify({
      satelliteId,
      contentType: contentTypeFor(file.name),
    }),
  });
  const form = new FormData();
  for (const [key, value] of Object.entries(presign.fields)) {
    form.append(key, value);
  }
  form.append("file", file);
  const uploaded = await fetch(presign.url, { method: "POST", body: form });
  if (!uploaded.ok && uploaded.status !== 204) {
    throw new ApiError("sign_failed");
  }
  return presign.uploadId;
}

async function request<T>(path: string, idToken: string, init: RequestInit = {}): Promise<T> {
  const { apiUrl } = appConfig();
  if (!apiUrl) {
    throw new Error("Set VITE_API_URL to the API base URL.");
  }
  const response = await fetch(`${apiUrl}${path}`, {
    ...init,
    headers: {
      Authorization: idToken,
      ...(init.body ? { "Content-Type": "application/json" } : {}),
    },
  });
  const text = await response.text();
  const payload = text ? (JSON.parse(text) as { error?: string }) : {};
  if (!response.ok) {
    throw new ApiError(payload.error ?? "request_failed");
  }
  return payload as T;
}
