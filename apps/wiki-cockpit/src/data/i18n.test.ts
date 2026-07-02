import { afterEach, describe, expect, it } from "vitest";
import { __dictKeysForTest, codexUnavailableReason, configureLanguage, glossary, t, uiLanguage } from "./i18n";

afterEach(() => configureLanguage("en"));

describe("i18n", () => {
  it("ships English as the base system language", () => {
    configureLanguage(undefined);
    expect(uiLanguage()).toBe("en");
    expect(t("world.galaxy")).toBe("Galaxy");
    expect(t("mission.checks.label")).toBe("Run the checks");
  });

  it("flips the whole UI to Portuguese when the wiki language is pt*", () => {
    configureLanguage("pt-BR");
    expect(uiLanguage()).toBe("pt");
    expect(t("world.galaxy")).toBe("Galáxia");
    expect(t("mission.approve.label")).toBe("Aprovar uma mudança");
    // Jargon explanations exist in both languages.
    expect(t("mission.approve.help")).toContain("humano revisar");
    configureLanguage("en");
    expect(t("mission.approve.help")).toContain("human reviews");
  });

  it("interpolates params and falls back key → EN → key", () => {
    configureLanguage("pt");
    expect(t("world.pages", { n: 42 })).toBe("42 páginas");
    expect(t("chave.inexistente")).toBe("chave.inexistente");
  });

  it("lets implementations override individual strings via config", () => {
    configureLanguage("pt", { "world.galaxy": "Universo" });
    expect(t("world.galaxy")).toBe("Universo");
    expect(t("world.missions")).toBe("Missões");
  });

  it("exposes a bilingual glossary for system jargon", () => {
    configureLanguage("pt");
    expect(glossary("freshness")?.title).toBe("Frescor");
    configureLanguage("en");
    expect(glossary("freshness")?.title).toBe("Freshness");
    expect(glossary("nope")).toBeNull();
  });

  it("keeps EN and PT dictionaries in full parity (no silent English leaks)", () => {
    const en = new Set(__dictKeysForTest.en);
    const pt = new Set(__dictKeysForTest.pt);
    const missingInPt = [...en].filter((key) => !pt.has(key));
    const missingInEn = [...pt].filter((key) => !en.has(key));
    expect(missingInPt, `keys missing in PT: ${missingInPt.join(", ")}`).toEqual([]);
    expect(missingInEn, `keys missing in EN: ${missingInEn.join(", ")}`).toEqual([]);
  });

  it("derives a localized Codex-unavailable headline from capability booleans", () => {
    const base = { enabled: true, installed: true, runnable: true, authed: true };
    configureLanguage("pt");
    expect(codexUnavailableReason({ ...base, enabled: false })).toBe("Codex está desligado nesta wiki");
    expect(codexUnavailableReason({ ...base, installed: false })).toBe("Codex não está instalado");
    expect(codexUnavailableReason({ ...base, runnable: false })).toBe("Codex está instalado mas não executa");
    expect(codexUnavailableReason({ ...base, authed: false })).toContain("codex login");
    configureLanguage("en");
    expect(codexUnavailableReason({ ...base, installed: false })).toBe("Codex is not installed");
  });
});
