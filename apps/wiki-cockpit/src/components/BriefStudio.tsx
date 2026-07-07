// BriefStudio: the surface where a composed work brief becomes the operator's.
// It shows the COMPLETE prompt — conventions, the deterministic evidence, the
// targets, the intent and the pinned output contract — as editable markdown.
// The operator reads it, edits anything (including their own intent), and picks
// an exit: copy it into any agent, save the edits, or (Phase 2) execute it
// locally with Codex. What you see here is exactly what runs.

import { useEffect, useRef, useState } from "react";
import { Copy, Play, RotateCcw, Save, Trash2, X } from "lucide-react";
import { codexUnavailableReason, t } from "../data/i18n";
import { copyText } from "../lib/clipboard";
import type { BriefRecord, CodexCapability, GitState } from "../types";

export function BriefStudio({
  brief,
  capability,
  busy,
  git,
  onSaveText,
  onDiscard,
  onExecute,
  onDiagnose,
  onNotice,
  onClose
}: {
  brief: BriefRecord;
  capability: CodexCapability;
  busy: boolean;
  git?: GitState;
  onSaveText: (briefId: string, text: string) => void;
  onDiscard: (briefId: string) => void;
  onExecute?: (brief: BriefRecord, text: string) => void;
  onDiagnose?: () => void;
  onNotice: (text: string) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState(brief.text);
  const composedRef = useRef(brief.text);

  // A new brief resets the editor; the composed text is the reset baseline.
  useEffect(() => {
    setText(brief.text);
    composedRef.current = brief.text;
  }, [brief.brief_id, brief.text]);

  const dirty = text !== composedRef.current;
  const executeEnabled = Boolean(onExecute) && capability.usable && !busy;
  const executeTitle = capability.usable
    ? t("brief.exit.execute")
    : capability.reason || codexUnavailableReason(capability);

  const copy = async () => {
    await copyText(text);
    onNotice(t("brief.exit.copied"));
  };

  return (
    <>
      <div className="briefStudioBackdrop" onClick={onClose} aria-hidden />
      <aside className="briefStudio" role="dialog" aria-labelledby="briefStudioTitle">
        <header className="briefStudioHeader">
          <div>
            <strong id="briefStudioTitle">{t("brief.studio.title")}</strong>
            <span className={`pill pill-${brief.status === "draft" ? "info" : "muted"}`}>{brief.status}</span>
          </div>
          <div className="briefStudioMeta">
            <small>{t("brief.studio.snapshot", { when: brief.snapshot_generated_at || "—" })}</small>
            <small>{t("brief.studio.size", { n: text.length })}</small>
          </div>
          <button className="readerClose" onClick={onClose} title={t("brief.studio.close")} type="button">
            <X size={16} />
          </button>
        </header>

        <p className="briefStudioHint">{t("brief.studio.editHint")}</p>

        <textarea
          className="briefTextArea"
          value={text}
          spellCheck={false}
          onChange={(event) => setText(event.target.value)}
          aria-label={t("brief.studio.title")}
        />

        <p className="briefStudioPinned">{t("brief.studio.pinnedNote")}</p>

        {/* Pre-flight: WHERE the job will run, before Execute is pressed — the
            late "worktree must be clean" dead end becomes an upfront fact. */}
        {git && git.proposal.is_proposal_branch && (
          <p className="briefStudioGitNote">
            {t("brief.exec.continueCurrent", {
              branch: git.current_branch,
              n: git.worktree.changed_files.length
            })}
          </p>
        )}
        {git && !git.proposal.is_proposal_branch && !git.worktree.clean && (
          <p className="briefStudioGitNote briefStudioGitWarn">
            {t("brief.exec.dirtyDefault", { branch: git.current_branch, n: git.worktree.changed_files.length })}
          </p>
        )}

        <div className="briefStudioActions">
          <button className="secondaryButton" onClick={copy} type="button">
            <Copy size={14} />
            <span>{t("brief.exit.copy")}</span>
          </button>
          <button
            className="secondaryButton"
            onClick={() => onSaveText(brief.brief_id, text)}
            disabled={!dirty || busy || brief.status !== "draft"}
            type="button"
          >
            <Save size={14} />
            <span>{t("brief.exit.save")}</span>
          </button>
          <button
            className="secondaryButton"
            onClick={() => setText(composedRef.current)}
            disabled={!dirty}
            type="button"
            title={t("brief.studio.reset")}
          >
            <RotateCcw size={14} />
            <span>{t("brief.studio.reset")}</span>
          </button>
          <button
            className="primaryButton"
            onClick={() => onExecute && onExecute(brief, text)}
            disabled={!executeEnabled}
            title={executeTitle}
            type="button"
          >
            <Play size={14} />
            <span>{t("brief.exit.execute")}</span>
          </button>
          <button className="dangerButton" onClick={() => onDiscard(brief.brief_id)} disabled={busy} type="button">
            <Trash2 size={14} />
            <span>{t("brief.exit.discard")}</span>
          </button>
        </div>
        {!capability.usable && (
          // Honest, VISIBLE reason (not a disabled-button tooltip) + a door to
          // the diagnostics dock — the owner always has a next step.
          <p className="briefStudioCodexNote">
            <span>{codexUnavailableReason(capability)}</span>
            {onDiagnose && (
              <button className="textButton" onClick={onDiagnose} type="button">
                {t("codex.dock.open")}
              </button>
            )}
          </p>
        )}
      </aside>
    </>
  );
}
