// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { configureLanguage } from "../data/i18n";
import { InformationNotice } from "./InformationNotice";

afterEach(() => { cleanup(); configureLanguage("en"); vi.unstubAllGlobals(); });
it("keeps the original observation date and describes the current-use condition without refreshing", () => {
  configureLanguage("pt");
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  render(<InformationNotice frontmatter={{ verified_at: "2026-01-01", information_requirements: [
    {target:"claim-balance",fields:["amount"],temporal:"current",max_age_days:1}
  ] }} />);
  expect(screen.getByText("Verificação registrada: 2026-01-01")).toBeTruthy();
  expect(screen.getByText("A informação atual precisa estar verificada antes da execução.")).toBeTruthy();
  expect(screen.getByText("claim-balance")).toBeTruthy();
  expect(fetch).not.toHaveBeenCalled();
});
it("presents historical use with its observation limit", () => {
  render(<InformationNotice frontmatter={{ information_requirements: [
    {target:"historical-claim",fields:["body"],temporal:"historical",max_age_days:0}
  ] }} />);
  expect(screen.getByText("Historical reading preserves the original observation date.")).toBeTruthy();
  expect(screen.getByText("No factual verification is recorded here.")).toBeTruthy();
});
