export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;

export type UploadProblem = "satellite" | "missing" | "many" | "type" | "empty" | "size";

export const UPLOAD_MESSAGES: Record<UploadProblem, string> = {
  satellite: "Choose a satellite before uploading.",
  missing: "Drop a CSV or JSON telemetry file.",
  many: "Upload one file at a time.",
  type: "Only CSV and JSON files are accepted.",
  empty: "The file is empty.",
  size: "The file is larger than 5 MB.",
};

export function uploadProblem(satelliteId: string, files: File[]): UploadProblem | null {
  if (!satelliteId) {
    return "satellite";
  }
  if (files.length === 0) {
    return "missing";
  }
  if (files.length > 1) {
    return "many";
  }
  const file = files[0];
  const name = file.name.toLowerCase();
  if (!name.endsWith(".csv") && !name.endsWith(".json")) {
    return "type";
  }
  if (file.size <= 0) {
    return "empty";
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return "size";
  }
  return null;
}

export function contentTypeFor(name: string): "text/csv" | "application/json" {
  return name.toLowerCase().endsWith(".json") ? "application/json" : "text/csv";
}

export function passwordIssue(password: string): string | null {
  if (password.length < 12) {
    return "Use at least 12 characters.";
  }
  if (!/[a-z]/.test(password)) {
    return "Include a lowercase letter.";
  }
  if (!/[A-Z]/.test(password)) {
    return "Include an uppercase letter.";
  }
  if (!/[0-9]/.test(password)) {
    return "Include a digit.";
  }
  if (!/[^A-Za-z0-9]/.test(password)) {
    return "Include a symbol.";
  }
  return null;
}

export function emailIssue(email: string): string | null {
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
    return "Enter a valid email address.";
  }
  return null;
}
