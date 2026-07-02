// WorkDock (?dock=work): the monitoring surface for delegated work. It lists
// CODEX JOBS (queued → running → delivered/failed/cancelled) with honest
// wall-clock times, a step timeline, a redacted live log tail and the branch /
// draft-PR handoff — plus SAVED BRIEFS (drafts you can reopen or discard).
// Deep-linkable like every other dock; polls while open so a job finishing is
// never missed. The same honest lifecycle you'd track when delegating to a
// person.

import { useCallback, useEffect, useRef, useState } from "react";
import { RefreshCw, X } from "lucide-react";
import { codexUnavailableReason, t } from "../data/i18n";
import type { BriefRecord, CodexCapability, CodexJobRecord } from "../types";
import {
  cancelCodexJob,
  discardBrief,
  listBriefs,
  listCodexJobs,
  streamCodexLog
} from "../data/snapshot";

type PillTone = "good" | "warn" | "bad" | "info" | "muted";

function jobTone(status: string): PillTone {
  if (status === "delivered") return "warn"; // delivered = waiting on the human
  if (status === "failed" || status === "cancelled") return "bad";
  if (status === "running") return "info";
  return "muted"; // queued
}

function stepTone(status: string): PillTone {
  if (status === "complete") return "good";
  if (status === "running") return "info";
  if (status === "failed") return "bad";
  return "muted"; // pending | skipped
}

const ACTIVE = new Set(["queued", "running", "committing"]);
const LOG_TAIL_LINES = 200;

// Compact human duration from two ISO timestamps (end defaults to now).
// Exported for tests: the monitoring surface must not lie about elapsed time.
export function formatElapsed(startIso?: string | null, endIso?: string | null): string {
  if (!startIso) return "";
  const start = Date.parse(startIso);
  const end = endIso ? Date.parse(endIso) : Date.now();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return "";
  const seconds = Math.round((end - start) / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}min ${seconds % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}min`;
}

function jobClock(job: CodexJobRecord): string {
  if (job.status === "running") return t("work.job.elapsed", { t: formatElapsed(job.started_at, null) || "…" });
  if (job.finished_at && job.started_at) return t("work.job.finishedIn", { t: formatElapsed(job.started_at, job.finished_at) });
  if (job.status === "queued") return t("work.job.queued");
  return "";
}

export function WorkDock({
  capability,
  demo,
  onResumeBrief,
  onReturn,
  onDiagnose,
  onNotice,
  onClose
}: {
  capability: CodexCapability;
  demo: boolean;
  onResumeBrief: (briefId: string) => void;
  onReturn?: (jobId: string, feedback: string) => void;
  onDiagnose?: () => void;
  onNotice: (text: string) => void;
  onClose: () => void;
}) {
  const [jobs, setJobs] = useState<CodexJobRecord[]>([]);
  const [drafts, setDrafts] = useState<BriefRecord[]>([]);
  const [openLog, setOpenLog] = useState<string | null>(null);
  const [logText, setLogText] = useState("");
  const [fullLog, setFullLog] = useState(false);
  const [returnFor, setReturnFor] = useState<string | null>(null);
  const [feedback, setFeedback] = useState("");

  const load = useCallback(async () => {
    if (demo) return;
    const [jobList, briefList] = await Promise.all([listCodexJobs(), listBriefs()]);
    setJobs(jobList);
    setDrafts(briefList.filter((b) => b.status === "draft"));
  }, [demo]);

  // Poll while the dock is open — a monitoring surface must not go quiet the
  // moment the last job leaves the ACTIVE set (that is exactly when the human
  // wants to see the outcome). The interval also refreshes running clocks.
  useEffect(() => {
    load();
    if (demo) return undefined;
    const id = window.setInterval(load, 2500);
    return () => window.clearInterval(id);
  }, [demo, load]);

  // Live log for the expanded job.
  useEffect(() => {
    if (!openLog) return undefined;
    let stop = false;
    const pull = async () => {
      const text = await streamCodexLog(openLog);
      if (!stop) setLogText(text);
    };
    pull();
    const id = window.setInterval(pull, 2000);
    return () => {
      stop = true;
      window.clearInterval(id);
    };
  }, [openLog]);

  const doDiscard = async (briefId: string) => {
    try {
      await discardBrief(briefId);
      onNotice(t("brief.exit.discarded"));
      load();
    } catch {
      /* non-fatal */
    }
  };
  const doCancel = async (jobId: string) => {
    const result = await cancelCodexJob(jobId);
    if (!result || result.ok === false) {
      onNotice(t("work.job.cancelFailed", { error: result?.error || "404" }));
    }
    load();
  };

  const visibleLog = (() => {
    if (fullLog) return logText;
    const lines = logText.split("\n");
    return lines.length > LOG_TAIL_LINES ? lines.slice(-LOG_TAIL_LINES).join("\n") : logText;
  })();
  const logTruncated = !fullLog && logText.split("\n").length > LOG_TAIL_LINES;

  const empty = jobs.length === 0 && drafts.length === 0;

  return (
    <>
      <div className="dockBackdrop" onClick={onClose} aria-hidden />
      <aside className="workDockPanel worldDock" role="dialog" aria-label={t("work.aria")}>
        <header className="dockHeader">
          <strong>{t("work.title")}</strong>
          {!capability.usable && !demo &&
            (onDiagnose ? (
              <button className="pill pill-warn workCodexChip" onClick={onDiagnose} type="button">
                {codexUnavailableReason(capability)} · {t("codex.dock.open")}
              </button>
            ) : (
              <span className="pill pill-muted">{t("work.unavailable")}</span>
            ))}
          <button className="textButton" onClick={load} title={t("work.refresh")} type="button">
            <RefreshCw size={13} />
          </button>
          <button className="readerClose" onClick={onClose} title={t("help.close")} type="button">
            <X size={16} />
          </button>
        </header>

        {demo ? (
          <p className="workEmpty">{t("work.demoOff")}</p>
        ) : (
          <div className="workBody">
            <section className="workSection">
              <h4>{t("work.tab.jobs")}</h4>
              {jobs.map((job) => (
                <article className="workJob" key={job.job_id}>
                  <div className="workJobHead">
                    <span className={`pill pill-${jobTone(job.status)}`}>{job.status}</span>
                    <strong>{job.theme || job.job_id}</strong>
                    <small className="workJobClock">{jobClock(job)}</small>
                    {ACTIVE.has(job.status) && (
                      <button className="textButton" onClick={() => doCancel(job.job_id)} type="button">
                        {t("work.job.cancel")}
                      </button>
                    )}
                  </div>
                  {job.reason && <small className="workJobReason">{job.reason}</small>}
                  <div className="workSteps" aria-hidden>
                    {job.steps?.map((step) => (
                      <span className={`workStep workStep-${stepTone(step.status)}`} key={step.id} title={`${step.label}: ${step.status}`}>
                        {step.label}
                      </span>
                    ))}
                  </div>
                  <div className="workJobLinks">
                    {job.draft_pr_url ? (
                      <a className="textButton" href={job.draft_pr_url} target="_blank" rel="noreferrer">
                        {t("work.job.openPr")}
                      </a>
                    ) : job.branch ? (
                      <small>
                        {t("work.job.branch", { branch: job.branch })}
                        {job.dry_run ? ` · ${t("work.job.localOnly")}` : ""}
                      </small>
                    ) : null}
                    <button
                      className="textButton"
                      onClick={() => {
                        setOpenLog(openLog === job.job_id ? null : job.job_id);
                        setFullLog(false);
                        setLogText("");
                      }}
                      type="button"
                    >
                      {openLog === job.job_id ? t("work.job.hideLog") : t("work.job.showLog")}
                    </button>
                    {onReturn && job.status === "delivered" && (
                      <button
                        className="textButton"
                        onClick={() => {
                          setReturnFor(returnFor === job.job_id ? null : job.job_id);
                          setFeedback("");
                        }}
                        type="button"
                      >
                        {t("work.job.return")}
                      </button>
                    )}
                  </div>
                  {openLog === job.job_id && (
                    <>
                      {logTruncated && (
                        <button className="textButton workLogMore" onClick={() => setFullLog(true)} type="button">
                          {t("work.job.logTail", { n: LOG_TAIL_LINES })}
                        </button>
                      )}
                      <pre className="workLog">{visibleLog || "…"}</pre>
                    </>
                  )}
                  {returnFor === job.job_id && onReturn && (
                    <div className="workReturn">
                      <textarea
                        value={feedback}
                        onChange={(event) => setFeedback(event.target.value)}
                        placeholder={t("work.job.returnPlaceholder")}
                        aria-label={t("work.job.return")}
                      />
                      <button
                        className="secondaryButton"
                        disabled={!feedback.trim()}
                        onClick={() => {
                          onReturn(job.job_id, feedback.trim());
                          setReturnFor(null);
                          setFeedback("");
                        }}
                        type="button"
                      >
                        {t("work.job.returnSend")}
                      </button>
                    </div>
                  )}
                </article>
              ))}
              {jobs.length === 0 && <p className="workEmpty">{t("work.jobs.empty")}</p>}
            </section>

            {drafts.length > 0 && (
              <section className="workSection">
                <h4>{t("work.tab.drafts")}</h4>
                {drafts.map((brief) => (
                  <div className="workRow" key={brief.brief_id}>
                    <div className="workRowMain">
                      <strong>{brief.spec?.theme || brief.brief_id}</strong>
                      <small>{brief.spec?.intent || brief.spec?.mission_kind || ""}</small>
                    </div>
                    <button className="textButton" onClick={() => onResumeBrief(brief.brief_id)} type="button">
                      {t("work.draft.resume")}
                    </button>
                    <button className="textButton" onClick={() => doDiscard(brief.brief_id)} type="button">
                      {t("work.draft.discard")}
                    </button>
                  </div>
                ))}
              </section>
            )}

            {empty && <p className="workEmpty">{t("work.empty")}</p>}
          </div>
        )}
      </aside>
    </>
  );
}
