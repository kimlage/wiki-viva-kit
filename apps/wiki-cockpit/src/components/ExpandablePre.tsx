// ExpandablePre + OutputModal: one reusable primitive for the long monospace
// text that shows up everywhere (command/gate output, per-file diffs). Inline
// it stays clamped so it never breaks the layout; the Expand button opens a
// full-screen modal with the complete, scrollable, copyable content. Used by
// CommandOutput, GateChecks and the Gate dock's file rows — no bespoke <pre>
// overflow handling per call site.

import { useState } from "react";
import { Copy, Maximize2, X } from "lucide-react";
import { t } from "../data/i18n";
import { copyText } from "../lib/clipboard";

export function OutputModal({ title, text, onClose }: { title: string; text: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    // Copy failed and fallback failed too — the text is selectable in the <pre> anyway.
    if (!(await copyText(text))) return;
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };
  return (
    <>
      <div className="outputModalBackdrop" onClick={onClose} aria-hidden />
      <div className="outputModal" role="dialog" aria-label={title} aria-modal="true">
        <header className="outputModalHead">
          <strong title={title}>{title}</strong>
          <button className="textButton" onClick={copy} type="button">
            <Copy size={13} />
            <span>{copied ? t("output.copied") : t("output.copy")}</span>
          </button>
          <button className="readerClose" onClick={onClose} title={t("help.close")} type="button">
            <X size={16} />
          </button>
        </header>
        <pre className="outputModalBody">{text}</pre>
      </div>
    </>
  );
}

export function ExpandablePre({
  text,
  title,
  className,
  emptyLabel
}: {
  text: string;
  title: string;
  className?: string;
  emptyLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const body = text && text.trim() ? text : emptyLabel ?? t("output.empty");
  // Only offer Expand when there is enough content that the clamp actually
  // hides something — a two-line result needs no modal.
  const worthExpanding = Boolean(text) && (text.length > 220 || text.split("\n").length > 6);
  return (
    <div className="expandablePre">
      <pre className={`expandablePreBody${className ? ` ${className}` : ""}`}>{body}</pre>
      {worthExpanding && (
        <button className="expandPreButton textButton" onClick={() => setOpen(true)} type="button">
          <Maximize2 size={12} />
          <span>{t("output.expand")}</span>
        </button>
      )}
      {open && <OutputModal title={title} text={text} onClose={() => setOpen(false)} />}
    </div>
  );
}
