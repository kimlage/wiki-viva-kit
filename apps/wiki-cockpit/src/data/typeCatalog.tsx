// The human catalog: every page type and every block gets a FACE — an icon and
// a one-line "what it is / when to use it". No naked chips, no raw ids: an
// option you cannot explain is an option that should not be on screen. Icons
// are geometry (CVD-safe by construction); descriptions live in i18n (EN+PT).

import type { ReactNode } from "react";
import {
  BadgeCheck,
  BookOpen,
  Boxes,
  CalendarClock,
  CircleDot,
  Compass,
  Database,
  Eye,
  FileText,
  FolderKanban,
  Gauge,
  GitPullRequest,
  Glasses,
  HeartHandshake,
  Home,
  Inbox,
  Landmark,
  Lightbulb,
  ListTree,
  Lock,
  NotebookPen,
  Package,
  Quote,
  Repeat,
  Scale,
  ScrollText,
  Sprout,
  Trophy,
  User,
  Users,
  Wand2,
  Wrench,
  Zap
} from "lucide-react";
import { pageTypeStyle } from "./presentation";
import { t } from "./i18n";

const TYPE_ICONS: Record<string, ReactNode> = {
  root_entity: <Home size={16} />,
  root_index: <Home size={16} />,
  context_hub: <Landmark size={16} />,
  ontology_index: <ListTree size={16} />,
  source_catalog: <ListTree size={16} />,
  source_registry: <ListTree size={16} />,
  relationship_map: <HeartHandshake size={16} />,
  source: <Database size={16} />,
  source_config: <BookOpen size={16} />,
  input_channel: <Inbox size={16} />,
  input_stage: <Inbox size={16} />,
  ingestion_event: <CalendarClock size={16} />,
  decision: <Scale size={16} />,
  claim: <Quote size={16} />,
  insight: <Lightbulb size={16} />,
  journal_entry: <NotebookPen size={16} />,
  perspective: <Glasses size={16} />,
  action: <Zap size={16} />,
  process: <Repeat size={16} />,
  artifact: <Package size={16} />,
  dashboard: <Gauge size={16} />,
  operational_rule: <ScrollText size={16} />,
  system_log: <ScrollText size={16} />,
  meeting: <Users size={16} />,
  person: <User size={16} />,
  role: <BadgeCheck size={16} />,
  responsibility: <BadgeCheck size={16} />,
  holon: <CircleDot size={16} />,
  project: <FolderKanban size={16} />,
  initiative: <FolderKanban size={16} />,
  context_note: <FileText size={16} />,
  template_block: <Boxes size={16} />,
  skill: <Wand2 size={16} />,
  tool: <Wrench size={16} />
};

export function typeIcon(pageType: string): ReactNode {
  return TYPE_ICONS[pageType] ?? <FileText size={16} />;
}

// One-line description: a per-type key, falling back to the family's line so
// custom downstream types still explain themselves.
export function typeDescription(pageType: string): string {
  const specific = t(`type.desc.${pageType}`);
  if (specific !== `type.desc.${pageType}`) return specific;
  const family = pageTypeStyle(pageType).family;
  const generic = t(`type.desc.family.${family}`);
  return generic !== `type.desc.family.${family}` ? generic : "";
}

// The NAME question is the type's own question — "Title / e.g. Authorize the
// Q3 budget" asked of a root entity was nonsense. Per-type prompt + example,
// falling back to the generic pair.
export function typeNamePrompt(pageType: string): string {
  const specific = t(`type.namePrompt.${pageType}`);
  return specific !== `type.namePrompt.${pageType}` ? specific : t("create.name");
}

export function typeNameExample(pageType: string): string {
  const specific = t(`type.nameExample.${pageType}`);
  return specific !== `type.nameExample.${pageType}` ? specific : t("create.namePlaceholder");
}

// --- Blocks -----------------------------------------------------------------

const BLOCK_ICONS: Record<string, ReactNode> = {
  quadrants: <Compass size={15} />,
  perspective_bundle: <Glasses size={15} />,
  relations: <HeartHandshake size={15} />,
  privacy_boundary: <Lock size={15} />,
  git_human_gate: <GitPullRequest size={15} />,
  source_recipe: <BookOpen size={15} />,
  ui_views: <Eye size={15} />,
  ui_missions: <Trophy size={15} />,
  ui_create: <Sprout size={15} />,
  ui_intake: <Inbox size={15} />,
  gamification: <Gauge size={15} />
};

// Accepts a block id (wiki.block.<family>.vN), a family, or a package name.
export function blockIcon(idOrFamily: string): ReactNode {
  const family = idOrFamily.replace(/^wiki\.block\./, "").replace(/\.v\d+$/, "");
  return BLOCK_ICONS[family] ?? <Boxes size={15} />;
}

export function blockDescription(idOrFamily: string, fallback = ""): string {
  const family = idOrFamily.replace(/^wiki\.block\./, "").replace(/\.v\d+$/, "");
  const key = `block.desc.${family}`;
  const text = t(key);
  return text !== key ? text : fallback;
}
