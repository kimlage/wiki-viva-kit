// GateDock (?dock=approve): the honest, world-first approval surface that
// replaces the /review 6-panel jargon stack. It shows WHAT changed — content
// pages first (the reason a human gate exists), code collapsed into one crate —
// with real per-file diffs on demand, the honest check status (run them here),
// only genuine privacy concerns, and the request itself: the cockpit prepares,
// GitHub decides. Diffs are text and stay in this 2D dock; the world behind is
// dimmed to the changed set. Everything is t()'d EN+PT.

import { useMemo, useState } from "react";
import { ExternalLink, FileText, GitPullRequest, Package, ShieldAlert, X } from "lucide-react";
import { t } from "../data/i18n";
import { deriveApproval } from "../data/approval";
import { contextLabel } from "../data/presentation";
import { DockTelemetryRail, type DockTelemetryItem, type DockTelemetryTone } from "./DockTelemetryRail";
import { GateChecks } from "./GateChecks";
import { ExpandablePre } from "./ExpandablePre";
import type { BriefSpec, DiffFile, PageRecord, SnapshotBundle } from "../types";
import type { OperatorPort } from "../application/ports";

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
const GATE_TELEMETRY_TONE: Record<string, DockTelemetryTone> = {
  pass: "good",
  fail: "bad",
  partial: "warn",
  not_run: "muted"
};

function approvalTelemetry(view: ReturnType<typeof deriveApproval>): DockTelemetryItem[] {
  const total = Math.max(view.fileCount, 1);
  return [
    {
      key: "content",
      label: t("gate.telemetry.content"),
      value: view.contentFiles.length,
      tone: view.contentFiles.length > 0 ? "info" : "muted",
      ratio: view.contentFiles.length / total,
      detail: t("gate.content", { n: view.contentFiles.length })
    },
    {
      key: "code",
      label: t("gate.telemetry.code"),
      value: view.codeFiles.length,
      tone: view.codeFiles.length > 0 ? "warn" : "muted",
      ratio: view.codeFiles.length / total,
      detail: t("gate.crate", { n: view.codeFiles.length })
    },
    {
      key: "privacy",
      label: t("gate.telemetry.privacy"),
      value: view.privacyFiles.length,
      tone: view.privacyFiles.length > 0 ? "bad" : "good",
      ratio: view.privacyFiles.length / total,
      detail: view.privacyFiles.length > 0 ? t("gate.privacy", { n: view.privacyFiles.length }) : t("gate.telemetry.privacyClear")
    },
    {
      key: "checks",
      label: t("gate.telemetry.checks"),
      value: t(`gate.gate.${view.gateStatus}`),
      tone: GATE_TELEMETRY_TONE[view.gateStatus] ?? "muted",
      ratio: view.gateStatus === "pass" ? 1 : view.gateStatus === "partial" ? 0.55 : view.gateStatus === "fail" ? 1 : 0,
      detail: t("gate.gates.label")
    }
  ];
}

function FileRow({ file, page, loadFileDiff }: { file: DiffFile; page?: PageRecord; loadFileDiff: OperatorPort["loadFileDiff"] }) {
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
      {page && (
        <div className="gateFilePage">
          <strong>{page.title}</strong>
          <small>
            {contextLabel(page.context || "system")} · {t(`scene.trust.${page.freshness_state}`)}
            {page.approved_state === "proposal" ? ` · ${t("scene.trust.proposal")}` : ""}
          </small>
        </div>
      )}
      <div className="gateFileHead">
        <FileText size={13} aria-hidden />
        <code>{file.path}</code>
        <small>
          +{file.additions} −{file.deletions}
        </small>
        {file.risk_hints.length > 0 && <small className="gateFileHints">{file.risk_hints.join(" · ")}</small>}
        <button className="textButton" onClick={toggle} type="button">
          {open ? t("gate.hideDiff") : t("gate.viewDiff")}
        </button>
      </div>
      {open &&
        (busy ? (
          <pre className="gateDiff">…</pre>
        ) : (
          <ExpandablePre
            text={lines && lines.length ? lines.join("\n") : ""}
            title={file.path}
            className="gateDiff"
            emptyLabel={t("gate.diffEmpty")}
          />
        ))}
    </div>
  );
}

export function GateDock({
  bundle,
  busy,
  demo,
  loadFileDiff,
  runGate,
  onWorkflow,
  onComposeBrief,
  onNotice,
  onRefetch,
  onClose
}: {
  bundle: SnapshotBundle;
  busy: boolean;
  demo?: boolean;
  loadFileDiff: OperatorPort["loadFileDiff"];
  runGate: OperatorPort["runGate"];
  onWorkflow: (operation: string, payload?: Record<string, unknown>, dryRun?: boolean) => void;
  onComposeBrief?: (spec: BriefSpec) => void;
  onNotice: (text: string) => void;
  onRefetch: () => void;
  onClose: () => void;
}) {
  const view = deriveApproval(bundle);
  // Diff paths are repo-relative like PageRecord.path — the lookup lets content
  // rows show the page a human recognizes (title/area/state), not just a path.
  const pagesByPath = useMemo(() => {
    const map = new Map<string, PageRecord>();
    for (const page of bundle.pages?.pages ?? []) map.set(page.path, page);
    return map;
  }, [bundle.pages?.pages]);
  const summary = bundle.diff?.summary;
  const branch = bundle.diff?.compare?.current_branch || bundle.git?.current_branch || "";

  return (
    <>
      <div className="dockBackdrop" onClick={onClose} aria-hidden />
      <aside className="gateDock worldDock" role="dialog" aria-label={t("gate.title")}>
        <header className="dockHeader">
          <strong>{t("gate.title")}</strong>
          <span className={`pill pill-${TONE[view.decision]}`}>{t(`gate.decision.${view.decision}`)}</span>
          <button className="readerClose" onClick={onClose} title={t("surface.close")} aria-label={t("surface.close")} type="button">
            <X size={16} />
          </button>
        </header>
        <p className="dockIntro">{t("gate.intro")}</p>
        <DockTelemetryRail label={t("gate.telemetry.approvalAria")} items={approvalTelemetry(view)} />

        {summary && view.fileCount > 0 && (
          <div className="gateSummary" aria-label={t("gate.summary.aria")}>
            <span className="stripChip static">
              {t("gate.summary.files", { n: view.fileCount })}
            </span>
            <span className="stripChip static gateSummaryDelta">
              +{summary.insertions} −{summary.deletions}
            </span>
            {branch && (
              <span className="stripChip static">
                <code>{branch}</code>
              </span>
            )}
            {summary.privacy_review_required && (
              <span className="pill pill-warn">{t("gate.summary.privacy")}</span>
            )}
          </div>
        )}

        {view.privacyFiles.length > 0 && (
          <div className="gateSection gatePrivacy">
            <h4>
              <ShieldAlert size={13} aria-hidden /> {t("gate.privacy", { n: view.privacyFiles.length })}
            </h4>
            <p className="dockIntro">{t("gate.privacy.hint")}</p>
            {view.privacyFiles.map((file) => (
              <FileRow key={file.path} file={file} page={pagesByPath.get(file.path)} loadFileDiff={loadFileDiff} />
            ))}
          </div>
        )}

        <div className="gateSection">
          <h4>{t("gate.content", { n: view.contentFiles.length })}</h4>
          {view.contentFiles.length === 0 && <p className="dockIntro">{t("gate.noContent")}</p>}
          {view.contentFiles.map((file) => (
            <FileRow key={file.path} file={file} page={pagesByPath.get(file.path)} loadFileDiff={loadFileDiff} />
          ))}
        </div>

        {view.codeFiles.length > 0 && (
          <details className="gateSection gateCrate">
            <summary>
              <Package size={14} aria-hidden /> {t("gate.crate", { n: view.codeFiles.length })}
            </summary>
            <p className="dockIntro">{t("gate.crate.hint")}</p>
            {view.codeFiles.map((file) => (
              <FileRow key={file.path} file={file} loadFileDiff={loadFileDiff} />
            ))}
          </details>
        )}

        <div className="gateSection gateChecks">
          <h4>
            {t("gate.gates.label")} <span className={`pill pill-${GATE_TONE[view.gateStatus] ?? "muted"}`}>{t(`gate.gate.${view.gateStatus}`)}</span>
          </h4>
          <GateChecks
            gates={bundle.gates?.gates ?? []}
            busy={busy}
            demo={demo}
            runGate={runGate}
            onComposeBrief={onComposeBrief}
            onNotice={onNotice}
            onRefetch={onRefetch}
          />
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
