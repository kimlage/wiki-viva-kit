import type { PageEntityIndex, RuntimeEvent, WorldState } from "../contracts";
import type { RegistryKernel } from "../registries/RegistryKernel";

export function createWorldReducer(index: PageEntityIndex, kernel: RegistryKernel) {
  return (state: WorldState, event: RuntimeEvent): WorldState => {
    switch (event.type) {
      case "hydrateRoute":
        return kernel.validateState(event.state).length === 0 ? event.state : state;
      case "inspectHover":
      case "inspectEntity":
        return { ...state, hoveredId: event.entityId && index.has(event.entityId) ? event.entityId : undefined };
      case "selectEntity":
        return index.has(event.entityId) ? { ...state, selectedId: event.entityId } : state;
      case "readEntity": {
        const entityId = event.entityId ?? state.selectedId;
        return entityId && index.has(entityId) ? { ...state, readerId: entityId, dock: undefined } : state;
      }
      case "openReader": {
        const entityId = event.entityId ?? state.selectedId;
        return entityId && index.has(entityId) ? { ...state, readerId: entityId, dock: undefined } : state;
      }
      case "selectCenter":
        return index.has(event.entityId)
          ? { ...state, centerId: event.entityId, selectedId: undefined, hoveredId: undefined, readerId: undefined, group: undefined }
          : state;
      case "setView": {
        const view = kernel.views.get(event.view);
        if (!view) return state;
        const overlay = view.allowedOverlays.includes(state.overlay) ? state.overlay : view.defaultOverlay;
        return { ...state, view: event.view, overlay };
      }
      case "setLens":
        return { ...state, lens: event.lens };
      case "setOverlay": {
        const view = kernel.views.require(state.view);
        return view.allowedOverlays.includes(event.overlay) ? { ...state, overlay: event.overlay } : state;
      }
      case "selectGroup":
        return { ...state, group: event.group, selectedId: undefined };
      case "openSurface":
      case "openDock":
        return event.dock && kernel.surfaces.has(event.dock) ? { ...state, dock: event.dock, readerId: undefined } : state;
      case "openSource":
        return index.get(event.entityId)?.pageType.startsWith("source") ? { ...state, selectedId: event.entityId, dock: "source", readerId: undefined } : state;
      case "openPerson":
        return index.get(event.entityId)?.pageType === "person" || index.get(event.entityId)?.pageType === "root_entity"
          ? { ...state, selectedId: event.entityId, readerId: event.entityId, dock: undefined }
          : state;
      case "openAction":
        return index.get(event.entityId)?.pageType === "action" ? { ...state, selectedId: event.entityId, readerId: event.entityId, dock: undefined } : state;
      case "focusRegion":
        return { ...state, focusedRegion: event.regionId };
      case "seedPage":
        return { ...state, dock: "create", readerId: undefined };
      case "executeOperatorCommand":
      case "refreshSnapshot":
        return state;
      case "closeSurface":
        return { ...state, dock: undefined, readerId: undefined };
      case "setFallback":
        return { ...state, fallback: event.fallback };
      case "setCameraIntent":
        return { ...state, cameraIntent: event.intent };
      case "setSafeArea":
        return { ...state, safeArea: event.safeArea };
    }
  };
}
