export const CORE_DEMO_SCENARIO_IDS = [
  "walking_skeleton",
  "normal_operations",
  "dense_stress",
  "source_lifecycle",
  "failures",
  "compatibility",
  "accessibility"
] as const;

export const PACK_SHOWCASE_SCENARIO_IDS = [
  "study_research_showcase",
  "personal_finance_showcase"
] as const;

export const DEMO_SCENARIO_IDS = [
  ...CORE_DEMO_SCENARIO_IDS,
  ...PACK_SHOWCASE_SCENARIO_IDS
] as const;

export type DemoScenarioId = (typeof DEMO_SCENARIO_IDS)[number];

const scenarioIds = new Set<string>(DEMO_SCENARIO_IDS);

export function isDemoScenarioId(value: string | null | undefined): value is DemoScenarioId {
  return Boolean(value && scenarioIds.has(value));
}
