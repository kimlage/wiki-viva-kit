// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import type { SourceEntity } from "../types";
import { SourceAuthorizationCard } from "./SourceAuthorizationCard";
afterEach(cleanup);
const source = { auth: { method: "mcp", ref: "approved-controller", scopes: ["read"], note: "Use the existing client." } } as unknown as SourceEntity;
it("retains source method and pointer without account or executor setup", () => {
 render(<SourceAuthorizationCard source={source} agentName="Example agent" agentCapabilitiesKnown={false} agentReady={false} connectorReady={false} liveAccessVerified={false}/>);
 expect(screen.getByText("approved-controller")).toBeTruthy();
 expect(screen.queryByRole("button")).toBeNull();
 expect(screen.queryByRole("combobox")).toBeNull();
});
it("does not present a connector catalogue or preview as verified access", () => {
 render(<SourceAuthorizationCard source={source} agentName="Example agent" agentCapabilitiesKnown agentReady connectorReady liveAccessVerified={false} route={{mode:"deterministic_connector",argv:[],mcp_hint:"",how_to_export:"",runnable:true}}/>);
 expect(screen.queryByText("Access verified")).toBeNull();
});
