import { useEffect, useState, type DragEvent, type FormEvent } from "react";
import { listSatellites, uploadTelemetry } from "../api";
import { useAuth } from "../useAuth";
import type { Satellite } from "../types";
import { UPLOAD_MESSAGES, uploadProblem } from "../uploadRules";

export function UploadPage() {
  const { session } = useAuth();
  const [satellites, setSatellites] = useState<Satellite[]>([]);
  const [satelliteId, setSatelliteId] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    if (!session) {
      return;
    }
    let active = true;
    listSatellites(session.idToken)
      .then((rows) => {
        if (active) {
          setSatellites(rows);
        }
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "Could not load satellites.");
        }
      });
    return () => {
      active = false;
    };
  }, [session]);

  function takeFiles(next: File[]) {
    setFiles(next);
    setUploadId(null);
    const problem = uploadProblem(satelliteId, next);
    setError(problem ? UPLOAD_MESSAGES[problem] : null);
  }

  function onDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    takeFiles(Array.from(event.dataTransfer.files));
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const problem = uploadProblem(satelliteId, files);
    if (problem) {
      setError(UPLOAD_MESSAGES[problem]);
      return;
    }
    if (!session) {
      return;
    }
    setPending(true);
    setError(null);
    try {
      const id = await uploadTelemetry(session.idToken, satelliteId, files[0]);
      setUploadId(id);
      setFiles([]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Upload failed.");
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="mx-auto max-w-xl">
      <h1 className="text-2xl font-medium text-slate-50">Upload telemetry</h1>
      <p className="mt-2 text-sm text-slate-400">CSV or JSON, up to 5 MB. The file is checked here before a URL is requested.</p>
      <form className="mt-6 space-y-4" onSubmit={onSubmit}>
        <label className="block text-sm text-slate-300">
          Satellite
          <select
            className="mt-1 w-full rounded-md border border-slate-700 bg-[#0c1824] px-3 py-2 text-slate-100"
            onChange={(event) => {
              setSatelliteId(event.target.value);
              if (files.length > 0) {
                const problem = uploadProblem(event.target.value, files);
                setError(problem ? UPLOAD_MESSAGES[problem] : null);
              }
            }}
            value={satelliteId}
          >
            <option value="">Select a satellite</option>
            {satellites.map((satellite) => (
              <option key={satellite.satelliteId} value={satellite.satelliteId}>
                {satellite.name || satellite.satelliteId}
              </option>
            ))}
          </select>
        </label>
        <label
          className={`block rounded-lg border border-dashed px-4 py-10 text-center text-sm ${
            dragging ? "border-cyan-400 bg-cyan-950/40" : "border-slate-600 bg-[#0c1824]"
          }`}
          onDragLeave={() => setDragging(false)}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDrop={onDrop}
        >
          <span className="text-slate-200">Drag a file here, or choose one.</span>
          <input
            aria-label="Telemetry file"
            className="mt-3 block w-full text-sm text-slate-300"
            multiple
            onChange={(event) => takeFiles(Array.from(event.target.files ?? []))}
            type="file"
          />
        </label>
        {files.length === 1 && (
          <p className="text-sm text-slate-300">
            {files[0].name} · {files[0].size.toLocaleString()} bytes
          </p>
        )}
        {error && (
          <p className="rounded-md border border-rose-800 bg-rose-950 px-3 py-2 text-sm text-rose-100" role="alert">
            {error}
          </p>
        )}
        {uploadId && (
          <p className="rounded-md border border-emerald-800 bg-emerald-950 px-3 py-2 text-sm text-emerald-100" role="status">
            Upload {uploadId} is in the bucket. Gaps appear on the dashboard after parsing.
          </p>
        )}
        <button className="rounded-md bg-cyan-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-60" disabled={pending} type="submit">
          {pending ? "Uploading…" : "Upload"}
        </button>
      </form>
    </section>
  );
}
