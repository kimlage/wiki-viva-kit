import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw, Square, TerminalSquare } from "lucide-react";
import { t } from "../data/i18n";
import type { CodexJobRecord } from "../types";

const ACTIVE_STATUSES = new Set(["queued", "running", "committing"]);

function jobTone(status: string): "good" | "warn" | "bad" | "info" | "muted" {
  if (status === "done") return "good";
  if (status === "delivered" || status === "returned") return "warn";
  if (status === "failed" || status === "cancelled") return "bad";
  if (status === "running" || status === "committing") return "info";
  return "muted";
}

export function SourceRunMonitor({
  sourceId,
  demo,
  onListJobs,
  onStreamJobLog,
  onCancelJob
}: {
  sourceId: string;
  demo: boolean;
  onListJobs?: (options?: { signal?: AbortSignal }) => Promise<CodexJobRecord[]>;
  onStreamJobLog?: (jobId: string, options?: { signal?: AbortSignal }) => Promise<string>;
  onCancelJob?: (jobId: string) => Promise<CodexJobRecord | null>;
}) {
  const [jobs, setJobs] = useState<CodexJobRecord[]>([]);
  const [offline, setOffline] = useState(false);
  const [openLog, setOpenLog] = useState("");
  const [logText, setLogText] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    if (demo || !onListJobs) return;
    try {
      const listed = await onListJobs({ signal });
      if (signal?.aborted) return;
      const theme = `ingest-${sourceId}`;
      setJobs(
        listed
          .filter((job) => job.theme === theme)
          .sort((a, b) => String(b.updated_at || b.created_at || "").localeCompare(String(a.updated_at || a.created_at || "")))
          .slice(0, 3)
      );
      setOffline(false);
    } catch {
      if (!signal?.aborted) setOffline(true);
    }
  }, [demo, onListJobs, sourceId]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    if (demo || !onListJobs) return () => controller.abort();
    const interval = window.setInterval(() => void load(controller.signal), 2500);
    return () => {
      controller.abort();
      window.clearInterval(interval);
    };
  }, [demo, load, onListJobs]);

  useEffect(() => {
    if (!openLog || !onStreamJobLog || demo) {
      setLogText("");
      return undefined;
    }
    const controller = new AbortController();
    const pull = async () => {
      try {
        const text = await onStreamJobLog(openLog, { signal: controller.signal });
        if (!controller.signal.aborted) setLogText(text);
      } catch {
        // Keep the last safe tail. The monitor's offline state is refreshed by load().
      }
    };
    void pull();
    const interval = window.setInterval(() => void pull(), 2000);
    return () => {
      controller.abort();
      window.clearInterval(interval);
    };
  }, [demo, onStreamJobLog, openLog]);

  const active = useMemo(() => jobs.filter((job) => ACTIVE_STATUSES.has(job.status)).length, [jobs]);

  const cancel = async (jobId: string) => {
    if (!onCancelJob || busy) return;
    setBusy(true);
    try {
      await onCancelJob(jobId);
      await load();
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="sourceRunMonitor" aria-label={t("source.runs.title")}>
      <header>
        <span><TerminalSquare size={15} aria-hidden /><strong>{t("source.runs.title")}</strong></span>
        <span className={`pill pill-${offline ? "warn" : active > 0 ? "info" : "muted"}`}>
          {offline ? t("source.runs.offline") : active > 0 ? t("source.runs.active", { n: active }) : t("source.runs.quiet")}
        </span>
        <button className="textButton" type="button" onClick={() => void load()} disabled={demo || !onListJobs} aria-label={t("source.runs.refresh")}>
          <RefreshCw size={13} aria-hidden />
        </button>
      </header>
      {jobs.length === 0 ? (
        <p>{t("source.runs.empty")}</p>
      ) : (
        <div className="sourceRunList">
          {jobs.map((job) => (
            <article key={job.job_id}>
              <header>
                <span className={`pill pill-${jobTone(job.status)}`}>{job.status}</span>
                <strong>{job.agent || "agent"}</strong>
                <code>{job.job_id}</code>
                {ACTIVE_STATUSES.has(job.status) && onCancelJob && (
                  <button className="textButton" type="button" disabled={busy} onClick={() => void cancel(job.job_id)}>
                    <Square size={11} aria-hidden /> {t("source.runs.cancel")}
                  </button>
                )}
              </header>
              <div className="sourceRunSteps" aria-label={t("source.runs.steps")}>
                {(job.steps ?? []).map((step) => (
                  <span key={step.id} data-status={step.status} title={step.label}>{step.label}</span>
                ))}
              </div>
              {onStreamJobLog && (
                <button className="textButton" type="button" onClick={() => setOpenLog(openLog === job.job_id ? "" : job.job_id)}>
                  {openLog === job.job_id ? t("source.runs.hideLog") : t("source.runs.showLog")}
                </button>
              )}
              {openLog === job.job_id && <pre>{logText || "…"}</pre>}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
