// CodexDock: the honest Codex diagnostics facility (?dock=codex). It renders the
// six-rung ladder straight from the live capability record — one rung per gate,
// the first failing one highlighted with the RAW server reason and exactly ONE
// copyable fix (including rung 0: "restart the operator"). A Re-verify button
// re-probes on demand, so the moment the owner fixes it (reinstall, login,
// restart) the dock flips green with no page reload. No fake capability ever.

import { useState } from "react";
import { Check, Copy, RefreshCw, X } from "lucide-react";
import { t } from "../data/i18n";
import { copyText } from "../lib/clipboard";
import { codexLadder } from "../data/codexLadder";
import type { CodexRungId, RungState } from "../data/codexLadder";
import type { CodexCapability } from "../types";

// Which rungs carry a copyable fix command/action when they block.
const FIX: Record<CodexRungId, boolean> = {
  operator: true,
  enabled: true,
  installed: true,
  runnable: true,
  authed: true,
  ready: false
};

function stateGlyph(state: RungState) {
  if (state === "ok") return <Check size={14} className="rungOk" aria-hidden />;
  if (state === "blocked") return <span className="rungDot rungBlocked" aria-hidden />;
  return <span className="rungDot rungPending" aria-hidden />;
}

export function CodexDock({
  capability,
  busy,
  onReverify,
  onClose
}: {
  capability: CodexCapability;
  busy: boolean;
  onReverify: () => void;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState<string | null>(null);
  const rungs = codexLadder(capability);

  const copy = async (text: string, id: string) => {
    // Result ignored on purpose: the fix text stays visible to copy by hand.
    await copyText(text);
    setCopied(id);
    window.setTimeout(() => setCopied((current) => (current === id ? null : current)), 1500);
  };

  return (
    <>
      <div className="dockBackdrop" onClick={onClose} aria-hidden />
      <aside className="codexDock worldDock" role="dialog" aria-label={t("codex.dock.title")}>
        <header className="dockHeader">
          <strong>{t("codex.dock.title")}</strong>
          {capability.version && <span className="pill pill-muted">{capability.version}</span>}
          <button className="readerClose" onClick={onClose} title={t("surface.close")} aria-label={t("surface.close")} type="button">
            <X size={16} />
          </button>
        </header>
        <p className="dockIntro">{t("codex.dock.intro")}</p>

        <ol className="codexLadder">
          {rungs.map((rung) => {
            const fixText = FIX[rung.id] ? t(`codex.rung.${rung.id}.fix`) : "";
            return (
              <li key={rung.id} className={`codexRung rung-${rung.state}`}>
                <div className="rungHead">
                  {stateGlyph(rung.state)}
                  <span>{t(`codex.rung.${rung.id}`)}</span>
                </div>
                {rung.state === "blocked" && (
                  <div className="rungBody">
                    {fixText && (
                      <div className="rungFix">
                        <code>{fixText}</code>
                        <button className="textButton" onClick={() => copy(fixText, rung.id)} type="button">
                          <Copy size={12} />
                          <span>{copied === rung.id ? t("codex.dock.copied") : t("codex.dock.copy")}</span>
                        </button>
                      </div>
                    )}
                    {capability.reason && (
                      <p className="rungReason">
                        <span>{t("codex.dock.reason")}:</span> <code>{capability.reason}</code>
                      </p>
                    )}
                  </div>
                )}
                {rung.id === "ready" && rung.state === "ok" && <p className="rungReason">{t("codex.rung.ready.ok")}</p>}
              </li>
            );
          })}
        </ol>

        <div className="dockActions">
          <button className="secondaryButton" onClick={onReverify} disabled={busy} type="button">
            <RefreshCw size={14} />
            <span>{t("codex.dock.reverify")}</span>
          </button>
        </div>
      </aside>
    </>
  );
}
