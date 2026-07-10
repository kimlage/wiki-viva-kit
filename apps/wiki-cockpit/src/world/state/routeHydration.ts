import type { WorldRoute } from "../../router";
import { createDefaultKernel, type RegistryKernel } from "../registries/RegistryKernel";
import { LENS_IDS, OVERLAY_IDS, type FamilyGroupId, type LensId, type OverlayId, type PageEntityIndex, type RouteWarning, type ViewId, type WorldState } from "../contracts";

const SHORT_LENSES: Record<string, LensId> = {
  intencao: "q1_intencao",
  pratica: "q2_pratica",
  relacoes: "q3_relacoes",
  sistemas: "q4_sistemas"
};

const LEGACY_VIEW: Record<string, { view: ViewId; lens?: LensId; overlay: OverlayId }> = {
  quadrants: { view: "quadrants", overlay: "actions" },
  radar: { view: "radar", overlay: "freshness" },
  districts: { view: "districts", lens: "type", overlay: "actions" },
  trails: { view: "trails", lens: "relations", overlay: "evidence" },
  atlas: { view: "atlas", lens: "type", overlay: "actions" },
  focus: { view: "focus", lens: "relations", overlay: "evidence" }
};

function familyGroup(value: string): FamilyGroupId | undefined {
  return value.startsWith("family:") ? (value as FamilyGroupId) : undefined;
}

export function hydrateWorldRoute(input: {
  route: WorldRoute;
  pages: PageEntityIndex;
  rootId: string;
  kernel?: RegistryKernel;
  mode?: WorldState["mode"];
}): WorldState {
  const { route, pages, rootId } = input;
  const kernel = input.kernel ?? createDefaultKernel();
  const warnings: RouteWarning[] = [];
  const requestedRuntime = route.query.runtime;
  const inferredMode: WorldState["mode"] = !route.query.view && route.perspectiveExplicit ? "compat" : "v8";
  const mode = input.mode ?? (requestedRuntime || inferredMode);
  const requestedCenter = route.query.center || rootId;
  const centerId = pages.has(requestedCenter) ? requestedCenter : rootId;
  if (requestedCenter !== centerId) warnings.push({ code: "invalid_center", value: requestedCenter, normalizedTo: rootId });

  const requestedView = (route.query.view || route.perspective) as ViewId;
  const mapped = LEGACY_VIEW[requestedView] ?? LEGACY_VIEW.quadrants;
  const view = kernel.views.has(requestedView) ? requestedView : mapped.view;
  if (!kernel.views.has(requestedView)) warnings.push({ code: "invalid_view", value: requestedView, normalizedTo: view });
  if (!route.query.view && route.perspectiveExplicit) warnings.push({ code: "legacy_route", value: route.perspective, normalizedTo: view });

  const viewDefinition = kernel.views.require(view);
  const nativeQueryView = Boolean(route.query.view && kernel.views.has(route.query.view));
  const rawLens = route.query.lens || route.query.quadrant || (nativeQueryView ? viewDefinition.defaultLens : mapped.lens) || viewDefinition.defaultLens;
  const normalizedLens = SHORT_LENSES[rawLens] ?? rawLens;
  if (route.query.quadrant) warnings.push({ code: "legacy_quadrant", value: route.query.quadrant, normalizedTo: normalizedLens });
  const lens = (LENS_IDS as readonly string[]).includes(normalizedLens)
    ? normalizedLens as LensId
    : (mapped.lens || kernel.views.require(view).defaultLens);
  if (lens !== normalizedLens) warnings.push({ code: "invalid_lens", value: normalizedLens, normalizedTo: lens });

  const requestedOverlay = (route.query.overlay || (nativeQueryView ? viewDefinition.defaultOverlay : mapped.overlay)) as OverlayId;
  const overlay = viewDefinition.allowedOverlays.includes(requestedOverlay) ? requestedOverlay : viewDefinition.defaultOverlay;
  if (requestedOverlay !== overlay) warnings.push({
    code: (OVERLAY_IDS as readonly string[]).includes(requestedOverlay) ? "unsupported_overlay" : "invalid_overlay",
    value: requestedOverlay,
    normalizedTo: overlay
  });

  const rawGroup = route.query.worldGroup || route.group || "";
  const group = familyGroup(rawGroup);
  if (rawGroup.startsWith("region:")) warnings.push({ code: "legacy_region_group", value: rawGroup });
  const rawPage = route.query.page || route.pageId;
  const selectedId = rawPage && pages.has(rawPage) ? rawPage : undefined;
  if (rawPage && !selectedId) warnings.push({ code: "invalid_page", value: rawPage });

  return {
    mode,
    centerId,
    view,
    lens,
    overlay,
    group,
    selectedId,
    readerId: route.query.reader ? selectedId : undefined,
    dock: route.query.dock || undefined,
    fallback: route.query.visual,
    cameraIntent: { kind: "preserve" },
    safeArea: { top: 0, right: 0, bottom: 0, left: 0, width: 0, height: 0 },
    warnings
  };
}

export function canonicalWorldUrl(
  state: WorldState,
  demo = false,
  carry?: WorldRoute["query"]
): string {
  const params = new URLSearchParams();
  params.set("center", state.centerId);
  params.set("view", state.view);
  params.set("lens", state.lens);
  params.set("overlay", state.overlay);
  if (state.group) params.set("group", state.group);
  if (state.selectedId) params.set("page", state.selectedId);
  if (state.dock) params.set("dock", state.dock);
  if (state.readerId) params.set("reader", "1");
  if (state.fallback) params.set("visual", "1");
  if (state.mode !== "v8") params.set("runtime", state.mode);
  // Runtime state owns semantic world fields. The router still owns bounded
  // workflow/demo context; carry it forward so a view/lens/overlay event never
  // drops search, packets, Genesis stage or the selected demo universe.
  if (carry?.q) params.set("q", carry.q);
  if (carry?.filter) params.set("filter", carry.filter);
  if (carry?.packet.length) params.set("packet", carry.packet.join(","));
  if (!state.dock && !state.readerId && carry?.tray) params.set("tray", carry.tray);
  if (state.dock && carry?.src) params.set("src", carry.src);
  if (state.readerId && carry?.diff) params.set("diff", "1");
  if (state.dock === "approve" && carry?.station) params.set("station", String(carry.station));
  if (carry?.ack.length) params.set("ack", carry.ack.join(","));
  if (carry?.genesis) {
    params.set("genesis", "1");
    if (carry.stage > 0) params.set("stage", String(carry.stage));
  }
  if (demo && carry?.demoScenario) params.set("demo_scenario", carry.demoScenario);
  if (demo && carry?.tour) params.set("tour", carry.tour);
  return `${demo ? "/demo" : ""}/w?${params.toString()}`;
}
