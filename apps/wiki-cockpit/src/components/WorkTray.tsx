// WorkTray: the human delegation surface. It lists SAVED BRIEFS (drafts you can
// reopen or discard) and CODEX JOBS (queued → running → delivered), each with a
// status pill, a step timeline, a redacted live log, and the branch / draft-PR
// link. It polls while any job is active so the operator watches work happen —
// the same honest lifecycle you'd track when delegating to a person.

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
  if (status === "done") return "good";
  if (status === "delivered" || status === "returned") return "warn";
  if (status === "failed" || status === "cancelled") return "bad";
  if (status === "running" || status === "committing") return "info";
  return "muted";
}

function stepTone(status: string): PillTone {
  if (status === "complete") return "good";
  if (status === "running") return "info";
  if (status === "failed") return "bad";
  if (status === "skipped") return "muted";
  return "muted";
}

const ACTIVE = new Set(["queued", "running", "committing"]);

export function WorkTray({
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
  const [returnFor, setReturnFor] = useState<string | null>(null);
  const [feedback, setFeedback] = useState("");
  const timer = useRef<number | null>(null);

  const load = useCallback(async () => {
    if (demo) return;
    const [jobList, briefList] = await Promise.all([listCodexJobs(), listBriefs()]);
    setJobs(jobList);
    setDrafts(briefList.filter((b) => b.status === "draft"));
  }, [demo]);

  // Load on open; poll while any job is active.
  useEffect(() => {
    load();
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [load]);

  useEffect(() => {
    const active = jobs.some((j) => ACTIVE.has(j.status));
    if (timer.current) window.clearInterval(timer.current);
    if (active && !demo) {
      timer.current = window.setInterval(load, 2500);
    }
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [jobs, demo, load]);

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
    await cancelCodexJob(jobId);
    load();
  };

  const empty = jobs.length === 0 && drafts.length === 0;

  return (
    <div className="workTray" role="region" aria-label={t("work.aria")}>
      <header>
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

          <section className="workSection">
            <h4>{t("work.tab.jobs")}</h4>
            {jobs.map((job) => (
              <article className="workJob" key={job.job_id}>
                <div className="workJobHead">
                  <span className={`pill pill-${jobTone(job.status)}`}>{job.status}</span>
                  <strong>{job.theme || job.job_id}</strong>
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
                    onClick={() => setOpenLog(openLog === job.job_id ? null : job.job_id)}
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
                {openLog === job.job_id && <pre className="workLog">{logText || "…"}</pre>}
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
          </section>

          {empty && <p className="workEmpty">{t("work.empty")}</p>}
        </div>
      )}
    </div>
  );
}
