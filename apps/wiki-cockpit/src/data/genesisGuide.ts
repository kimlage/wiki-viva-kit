// The genesis tutorial as DATA: per-stage title/body/CTA/anchor, consumed by
// the in-world GuideBeacon (and by the 2D fallback card). The guide is
// anchored to the SUBJECT of each step and never disappears during the action
// — `during` is the specific "do it there" instruction that replaces the CTA
// while the action surface is open. Behavior (navigation, stage advance) stays
// in the shell; this module only says WHAT each stage is.

import { genesisActionDock, GENESIS_FINAL_STAGE } from "./genesis";
import { t } from "./i18n";

// Where the beacon anchors per stage — the page the step is ABOUT.
export const GENESIS_STAGE_ANCHOR: Record<number, string> = {
  1: "root-alex-rivera",
  2: "root-alex-rivera",
  3: "hub-financeiro",
  4: "person-marina-costa",
  5: "root-alex-rivera",
  6: "source-banco-export",
  7: "hub-sistema",
  8: "root-alex-rivera"
};

export type GenesisGuideData = {
  stage: number;
  final: boolean;
  progress: { k: number; n: number };
  title: string;
  body: string;
  // null on stage 0 (the founding cards ARE the action) and on the finale.
  ctaLabel: string | null;
  // Specific in-action instruction; null when the stage has no action surface.
  during: string | null;
  anchorId: string | null;
  dock: { dock: "create" | "blocks"; src?: string } | null;
};

export function genesisGuide(stage: number): GenesisGuideData {
  const k = Math.min(Math.max(stage, 0), GENESIS_FINAL_STAGE);
  const final = k >= GENESIS_FINAL_STAGE;
  const dock = final || k === 0 ? null : genesisActionDock(k);
  return {
    stage: k,
    final,
    progress: { k: Math.max(k, 1), n: GENESIS_FINAL_STAGE },
    title: t(`genesis.stage${k}.title`),
    body: t(`genesis.stage${k}.body`),
    ctaLabel: final || k === 0 ? null : t(`genesis.stage${k}.cta`),
    during: dock ? t(`genesis.stage${k}.during`) : null,
    anchorId: GENESIS_STAGE_ANCHOR[k] ?? null,
    dock
  };
}
