// GateDock (?dock=approve): the honest, world-first approval surface that
// replaces the /review 6-panel jargon stack. It shows WHAT changed — content
// pages first (the reason a human gate exists), code collapsed into one crate —
// with real per-file diffs on demand, the honest check status (run them here),
// only genuine privacy concerns, and the request itself: the cockpit prepares,
// GitHub decides. Diffs are text and stay in this 2D dock; the world behind is
// dimmed to the changed set. Everything is t()'d EN+PT.

import { useState } from "react";
import { ExternalLink, FileText, GitPullRequest, Package, RefreshCw, ShieldAlert, X } from "lucide-react";
import { t } from "../data/i18n";
import { deriveApproval } from "../data/approval";
import { loadFileDiff, runGate } from "../data/snapshot";
import type { DiffFile, SnapshotBundle } from "../types";

const TONE: Record<string, "good" | "warn" | "bad" | "info" | "muted"> = {
  clean: "good",
  ready: "info",
  review: "warn",
  checks: "bad"
};
const GATE_TONE: Record<string, "good" | "warn" | "bad" | "muted"> = {
  pass: "good",
  fail: "bad",
  partial: "warn",
  not_run: "muted"
};

function FileRow({ file }: { file: DiffFile }) {
  const [open, setOpen] = useState(false);
  const [lines, setLines] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const toggle = async () => {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (lines === null) {
      setBusy(true);
      const result = await loadFileDiff(file.path);
      setLines(result.ok && result.diff ? result.diff : []);
      setBusy(false);
    }
  };
  return (
    <div className="gateFile">
      <div className="gateFileHead">
        <FileText size={13} aria-hidden />
        <code>{file.path}</code>
        <small>
          +{file.additions} −{file.deletions}
        </small>
        <button className="textButton" onClick={toggle} type="button">
          {open ? t("gate.hideDiff") : t("gate.viewDiff")}
        </button>
      </div>
      {open && <pre className="gateDiff">{busy ? "…" : lines && lines.length ? lines.join("\n") : t("gate.diffEmpty")}</pre>}
    </div>
  );
}

export function GateDock({
  bundle,
  busy,
  onWorkflow,
  onNotice,
  onRefetch,
  onClose
}: {
  bundle: SnapshotBundle;
  busy: boolean;
  onWorkflow: (operation: string, payload?: Record<string, unknown>, dryRun?: boolean) => void;
  onNotice: (text: string) => void;
  onRefetch: () => void;
  onClose: () => void;
}) {
  const view = deriveApproval(bundle);
  const [runningGates, setRunningGates] = useState(false);

  const runAllGates = async () => {
    setRunningGates(true);
    try {
      for (const gate of bundle.gates?.gates ?? []) {
        await runGate(gate.id);
      }
      onNotice(t("gate.gates.label"));
      onRefetch();
    } finally {
      setRunningGates(false);
    }
  };

  return (
    <>
      <div className="dockBackdrop" onClick={onClose} aria-hidden />
      <aside className="gateDock worldDock" role="dialog" aria-label={t("gate.title")}>
        <header className="dockHeader">
          <strong>{t("gate.title")}</strong>
          <span className={`pill pill-${TONE[view.decision]}`}>{t(`gate.decision.${view.decision}`)}</span>
          <button className="readerClose" onClick={onClose} title={t("help.close")} type="button">
            <X size={16} />
          </button>
        </header>
        <p className="dockIntro">{t("gate.intro")}</p>

        {view.privacyFiles.length > 0 && (
          <div className="gateSection gatePrivacy">
            <h4>
              <ShieldAlert size={13} aria-hidden /> {t("gate.privacy", { n: view.privacyFiles.length })}
            </h4>
            <p className="dockIntro">{t("gate.privacy.hint")}</p>
            {view.privacyFiles.map((file) => (
              <FileRow key={file.path} file={file} />
            ))}
          </div>
        )}

        <div className="gateSection">
          <h4>{t("gate.content", { n: view.contentFiles.length })}</h4>
          {view.contentFiles.length === 0 && <p className="dockIntro">{t("gate.noContent")}</p>}
          {view.contentFiles.map((file) => (
            <FileRow key={file.path} file={file} />
          ))}
        </div>

        {view.codeFiles.length > 0 && (
          <details className="gateSection gateCrate">
            <summary>
              <Package size={14} aria-hidden /> {t("gate.crate", { n: view.codeFiles.length })}
            </summary>
            <p className="dockIntro">{t("gate.crate.hint")}</p>
            {view.codeFiles.map((file) => (
              <FileRow key={file.path} file={file} />
            ))}
          </details>
        )}

        <div className="gateSection gateChecks">
          <h4>
            {t("gate.gates.label")} <span className={`pill pill-${GATE_TONE[view.gateStatus] ?? "muted"}`}>{t(`gate.gate.${view.gateStatus}`)}</span>
          </h4>
          <button className="secondaryButton" onClick={runAllGates} disabled={runningGates || busy} type="button">
            <RefreshCw size={14} />
            <span>{runningGates ? t("gate.running") : t("gate.runGates")}</span>
          </button>
        </div>

        <div className="dockActions gateRequest">
          {view.prUrl ? (
            <a className="primaryButton" href={view.prUrl} target="_blank" rel="noreferrer">
              <ExternalLink size={14} />
              <span>{t("gate.pr.open")}</span>
            </a>
          ) : view.fileCount > 0 ? (
            <button
              className="primaryButton"
              onClick={() => onWorkflow("open_draft_pr", {}, false)}
              disabled={busy || !view.isProposalBranch}
              type="button"
            >
              <GitPullRequest size={14} />
              <span>{t("gate.pr.prepare")}</span>
            </button>
          ) : (
            <span className="dockIntro">{t("gate.pr.none")}</span>
          )}
        </div>
        <p className="gateContract">{t("gate.pr.contract")}</p>
      </aside>
    </>
  );
}
