// CoachMarks: the first-run guided tour of the knowledge world. Anchors each
// step to a real HUD element, explains the concept in plain language, and gets
// out of the way. Shows once (localStorage), reopens with "?" or the guide
// button. No fake progress — it is a map legend in narrative form.

import { useCallback, useEffect, useMemo, useState } from "react";
import { t } from "../data/i18n";

const TOUR_DONE_KEY = "wikiCockpitTourDone.v1";

type TourStep = { key: string; anchor: string | null };

const STEPS: TourStep[] = [
  { key: "welcome", anchor: null },
  { key: "perspectives", anchor: ".perspectiveGlyphs" },
  { key: "drill", anchor: ".worldBreadcrumbs" },
  { key: "mission", anchor: ".worldMissionCard" },
  { key: "search", anchor: ".commandSearch" },
  { key: "packet", anchor: ".trayButton" },
  { key: "missions", anchor: ".missionsButton" }
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

export function CoachMarks({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [step, setStep] = useState(0);
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);

  useEffect(() => {
    if (open) setStep(0);
  }, [open]);

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
      if (event.key === "ArrowRight" || event.key === "Enter") {
        setStep((value) => (value + 1 >= STEPS.length ? (finish(), value) : value + 1));
      }
      if (event.key === "ArrowLeft") setStep((value) => Math.max(0, value - 1));
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
      <div className={anchorRect ? "coachCard anchored" : "coachCard"} style={cardStyle}>
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
