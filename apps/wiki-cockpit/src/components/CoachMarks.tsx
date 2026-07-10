// CoachMarks: the first-run guided tour of the knowledge world. Anchors each
// step to a real HUD element, explains the concept in plain language, and gets
// out of the way. Shows once (localStorage), reopens with "?" or the guide
// button. No fake progress — it is a map legend in narrative form.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { t } from "../data/i18n";

const TOUR_DONE_KEY = "wikiCockpitTourDone.v1";

type TourStep = { key: string; anchor: string | null };

const STEPS: TourStep[] = [
  { key: "welcome", anchor: null },
  { key: "views", anchor: ".worldNavigatorViewControls" },
  { key: "overlay", anchor: ".worldNavigatorOverlaySelect" },
  { key: "lens", anchor: ".quadrantCompass" },
  { key: "drill", anchor: ".worldBreadcrumbs" },
  { key: "mission", anchor: ".worldMissionCard, .worldMissionSlim" },
  { key: "search", anchor: ".commandSearch" }
];

export function tourSeen(): boolean {
  try {
    return window.localStorage.getItem(TOUR_DONE_KEY) === "1";
  } catch {
    return true;
  }
}

function markTourSeen(): void {
  try {
    window.localStorage.setItem(TOUR_DONE_KEY, "1");
  } catch {
    /* private mode — the tour just shows again next time */
  }
}

export function CoachMarks({
  open,
  onClose,
  returnFocusTo
}: {
  open: boolean;
  onClose: () => void;
  returnFocusTo?: HTMLElement | null;
}) {
  const [step, setStep] = useState(0);
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (open) {
      // React commits `autoFocus` before passive effects. Reading only
      // document.activeElement here would therefore remember the tour's own
      // Next button instead of the control that opened it. The caller captures
      // the opener at the interaction boundary and hands it in explicitly.
      previousFocusRef.current = returnFocusTo ?? null;
      setStep(0);
      return undefined;
    }
    previousFocusRef.current?.focus();
    previousFocusRef.current = null;
    return undefined;
  }, [open, returnFocusTo]);

  const current = STEPS[Math.min(step, STEPS.length - 1)];

  useEffect(() => {
    if (!open) return undefined;
    const measure = () => {
      const element = current.anchor ? document.querySelector(current.anchor) : null;
      setAnchorRect(element ? element.getBoundingClientRect() : null);
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [current.anchor, open]);

  const finish = useCallback(() => {
    markTourSeen();
    onClose();
  }, [onClose]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event: KeyboardEvent) => {
      event.stopPropagation();
      if (event.key === "Escape") finish();
      const target = event.target instanceof HTMLElement ? event.target : null;
      const enterHandledByControl =
        event.key === "Enter" &&
        Boolean(target?.closest("button, a, input, select, textarea, [role='button'], [role='link']"));
      if (event.key === "ArrowRight" || (event.key === "Enter" && !enterHandledByControl)) {
        setStep((value) => (value + 1 >= STEPS.length ? (finish(), value) : value + 1));
      }
      if (event.key === "ArrowLeft") setStep((value) => Math.max(0, value - 1));
      if (event.key === "Tab") {
        const focusable = [...(cardRef.current?.querySelectorAll<HTMLElement>("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])") ?? [])]
          .filter((element) => !element.hasAttribute("disabled"));
        if (focusable.length === 0) return;
        const first = focusable[0]!;
        const last = focusable[focusable.length - 1]!;
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey, { capture: true });
    return () => window.removeEventListener("keydown", onKey, { capture: true });
  }, [finish, open]);

  const cardStyle = useMemo(() => {
    if (!anchorRect) return undefined;
    const top = Math.min(Math.max(anchorRect.bottom + 12, 70), window.innerHeight - 240);
    const left = Math.min(Math.max(anchorRect.left, 16), Math.max(window.innerWidth - 396, 16));
    return { top, left } as const;
  }, [anchorRect]);

  if (!open) return null;
  const last = step === STEPS.length - 1;
  return (
    <div className="coachOverlay" role="dialog" aria-modal="true" aria-label={t(`tour.${current.key}.title`)}>
      {anchorRect && (
        <div
          className="coachSpotlight"
          style={{
            top: anchorRect.top - 6,
            left: anchorRect.left - 6,
            width: anchorRect.width + 12,
            height: anchorRect.height + 12
          }}
          aria-hidden
        />
      )}
      <div ref={cardRef} className={anchorRect ? "coachCard anchored" : "coachCard"} style={cardStyle}>
        <span className="coachProgress">{t("tour.progress", { step: step + 1, total: STEPS.length })}</span>
        <h2>{t(`tour.${current.key}.title`)}</h2>
        <p>{t(`tour.${current.key}.body`)}</p>
        <div className="coachButtons">
          <button className="textButton" onClick={finish} type="button">
            {t("tour.skip")}
          </button>
          {step > 0 && (
            <button className="secondaryButton" onClick={() => setStep((value) => Math.max(0, value - 1))} type="button">
              {t("tour.back")}
            </button>
          )}
          <button
            className="actionButton"
            onClick={() => (last ? finish() : setStep((value) => value + 1))}
            type="button"
            autoFocus
          >
            <span>{last ? t("tour.done") : t("tour.next")}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
