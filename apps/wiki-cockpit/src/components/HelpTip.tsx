// HelpTip: the learning layer's smallest unit. A "?" button that explains a
// system concept in plain language — what it is, what to look at, what happens
// — either from the glossary (term) or from explicit text. Keyboard and
// screen-reader friendly: it is a real button with an expanded region.
//
// The popover is portaled to <body> and fixed-positioned from the button's
// rect, so it never gets clipped by an overflow:auto ancestor (missions panel,
// packet tray, search list) and always opens toward the roomier side.

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { glossary, t } from "../data/i18n";

export function HelpTip({ term, title, body }: { term?: string; title?: string; body?: string }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ left: number; top: number; placement: "up" | "down" } | null>(null);
  const rootRef = useRef<HTMLSpanElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const entry = term ? glossary(term) : null;
  const helpTitle = title ?? entry?.title ?? "";
  const helpBody = body ?? entry?.body ?? "";

  useLayoutEffect(() => {
    if (!open) return;
    const button = rootRef.current?.querySelector("button");
    if (!button) return;
    const rect = button.getBoundingClientRect();
    const width = Math.min(320, window.innerWidth - 24);
    const openUp = rect.top > window.innerHeight / 2;
    const left = Math.min(Math.max(rect.left + rect.width / 2 - width / 2, 12), window.innerWidth - width - 12);
    setPos({ left, top: openUp ? rect.top : rect.bottom, placement: openUp ? "up" : "down" });
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!rootRef.current?.contains(target) && !popoverRef.current?.contains(target)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        setOpen(false);
      }
    };
    const dismiss = () => setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    // Any scroll invalidates the anchored position — just close.
    window.addEventListener("scroll", dismiss, true);
    window.addEventListener("resize", dismiss);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", dismiss, true);
      window.removeEventListener("resize", dismiss);
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
      {open &&
        pos &&
        createPortal(
          <div
            ref={popoverRef}
            className={pos.placement === "up" ? "helpTipPopover fixed placeUp" : "helpTipPopover fixed"}
            role="note"
            style={{ left: pos.left, top: pos.top }}
          >
            {helpTitle && <strong>{helpTitle}</strong>}
            <span>{helpBody}</span>
          </div>,
          document.body
        )}
    </span>
  );
}
