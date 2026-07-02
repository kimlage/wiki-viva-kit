// HelpTip: the learning layer's smallest unit. A "?" button that explains a
// system concept in plain language — what it is, what to look at, what happens
// — either from the glossary (term) or from explicit text. Keyboard and
// screen-reader friendly: it is a real button with an expanded region.

import { useEffect, useRef, useState } from "react";
import { glossary, t } from "../data/i18n";

export function HelpTip({ term, title, body }: { term?: string; title?: string; body?: string }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement>(null);
  const entry = term ? glossary(term) : null;
  const helpTitle = title ?? entry?.title ?? "";
  const helpBody = body ?? entry?.body ?? "";

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    rootRef.current?.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      rootRef.current?.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!helpBody) return null;
  return (
    <span className="helpTip" ref={rootRef}>
      <button
        className="helpTipButton"
        type="button"
        aria-expanded={open}
        title={t("help.whatIs")}
        onClick={(event) => {
          event.stopPropagation();
          setOpen((value) => !value);
        }}
      >
        ?
      </button>
      {open && (
        <span className="helpTipPopover" role="note">
          {helpTitle && <strong>{helpTitle}</strong>}
          <span>{helpBody}</span>
        </span>
      )}
    </span>
  );
}
