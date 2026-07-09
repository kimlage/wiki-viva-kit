import { useEffect, useMemo, useSyncExternalStore } from "react";
import type { WorldRoute } from "../router";
import type { OperatorCommandCard, BriefSpec, SnapshotBundle } from "../types";
import type { RuntimeConfig } from "../data/runtimeConfig";
import type { PageEntityIndex } from "../world/contracts";
import type { NavigationPort, OperatorPort } from "../application/ports";
import { WorldRuntime } from "../world/WorldRuntime";
import { createDefaultKernel } from "../world/registries/RegistryKernel";
import { hydrateWorldRoute } from "../world/state/routeHydration";
import { installVisualPrimitiveRegistry } from "../data/visualPrimitives";
import { WorldView } from "./WorldView";
import "../styles.css";

export function RuntimeWorldView(props: {
  bundle: SnapshotBundle;
  runtime: RuntimeConfig;
  route: WorldRoute;
  bornPageIds?: string[];
  onRun: (action: OperatorCommandCard) => void;
  onNotice?: (text: string) => void;
  onComposeBrief?: (spec: BriefSpec) => void;
  navigation: NavigationPort;
  loadPageContent: OperatorPort["loadPageContent"];
}) {
  const { bundle, route } = props;
  const pages = useMemo<PageEntityIndex>(
    () => new Map(bundle.pages.pages.map((page) => [page.id, { id: page.id, pageType: page.page_type, title: page.title }])),
    [bundle]
  );
  const rootId = bundle.manifest.root_page_id || bundle.pages.pages.find((page) => page.page_type === "root_entity")?.id || bundle.pages.pages[0]?.id || "";
  const kernel = useMemo(() => {
    const next = createDefaultKernel();
    installVisualPrimitiveRegistry(next);
    return next;
  }, []);
  const hydrated = useMemo(() => hydrateWorldRoute({ route, pages, rootId, kernel }), [kernel, pages, rootId, route]);
  const worldRuntime = useMemo(() => new WorldRuntime({ state: hydrated, pages, kernel }), [kernel, pages]);

  useEffect(() => {
    worldRuntime.dispatch({ type: "hydrateRoute", state: hydrated });
  }, [hydrated, worldRuntime]);

  const worldState = useSyncExternalStore(
    (notify) => worldRuntime.subscribe(() => notify()),
    () => worldRuntime.getState(),
    () => worldRuntime.getState()
  );

  return <WorldView {...props} worldRuntime={worldRuntime} worldState={worldState} />;
}
