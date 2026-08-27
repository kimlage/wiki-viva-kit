import {
  applySourceOperation,
  buildIngestionPlan,
  cancelCodexJob,
  composeBrief,
  composeSourceBrief,
  discardBrief,
  getBrief,
  intakeCopy,
  listSourceOperationReceipts,
  listBriefs,
  listCodexJobs,
  loadCodexCapability,
  loadAgentCapabilities,
  loadFileDiff,
  loadPageContent,
  loadSnapshotBundle,
  loadTemporalGraphForBundle,
  previewSourceOperation,
  previewSourceRefresh,
  returnCodexJob,
  runOperatorCommand,
  runGate,
  runGitWorkflow,
  runIngestionStep,
  runSourceRefresh,
  saveBriefText,
  spawnCodexJob,
  streamCodexLog
} from "../data/snapshot";
import {
  buildUrl,
  getRouteUrlSnapshot,
  installLinkInterceptor,
  navigate,
  parseRoute,
  patchWorld,
  retreat,
  subscribeRouteUrl,
  worldFromRoute
} from "../router";
import type { ApplicationPorts, NavigationPort, OperatorPort } from "../application/ports";

const operator: OperatorPort = {
  loadSnapshotBundle,
  loadPageContent,
  loadTemporalGraph: (bundle, options) => loadTemporalGraphForBundle(bundle, options?.signal),
  loadCodexCapability,
  loadAgentCapabilities,
  composeBrief,
  listBriefs,
  getBrief,
  saveBriefText,
  discardBrief,
  spawnCodexJob,
  listCodexJobs,
  streamCodexLog,
  returnCodexJob,
  cancelCodexJob,
  loadFileDiff,
  intakeCopy,
  runGate,
  runOperatorCommand,
  runGitWorkflow,
  composeSourceBrief,
  previewSourceOperation,
  applySourceOperation,
  listSourceOperationReceipts,
  previewSourceRefresh,
  runSourceRefresh,
  buildIngestionPlan,
  runIngestionStep
};

const navigation: NavigationPort = {
  subscribe: subscribeRouteUrl,
  getSnapshot: getRouteUrlSnapshot,
  getServerSnapshot: () => "/",
  attachLinkInterceptor: installLinkInterceptor,
  parseUrl(url) {
    const [pathname, search = ""] = url.split("?");
    return parseRoute(pathname, search ? `?${search}` : "");
  },
  toWorld: worldFromRoute,
  href: buildUrl,
  patch: patchWorld,
  hrefForPatch(route, patch) {
    return buildUrl(patchWorld(route, patch));
  },
  dispatch(intent) {
    if (intent.type === "navigate") {
      navigate(intent.target, { replace: intent.replace });
      return;
    }
    if (intent.type === "patch-world") {
      navigate(patchWorld(intent.route, intent.patch), { replace: intent.replace });
      return;
    }
    if (intent.type === "retreat-world") {
      navigate(retreat(intent.route), { replace: intent.replace });
      return;
    }
    window.history.back();
  }
};

export const browserApplication: ApplicationPorts = { navigation, operator };
