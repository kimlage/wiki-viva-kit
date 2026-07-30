import type { Dispatch } from "react";
import type {
  AnattaPrototypeSession,
  PrototypeAction,
  RendererMode
} from "./model";

export type AnattaVariantProps = {
  session: AnattaPrototypeSession;
  dispatch: Dispatch<PrototypeAction>;
  rendererMode: RendererMode;
  reducedMotion: boolean;
};
