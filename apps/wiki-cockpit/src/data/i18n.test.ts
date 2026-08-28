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

  it("explains the sustained-performance fallback in both languages", () => {
    configureLanguage("en");
    expect(t("scene.fallback.performance.title")).toBe("Performance-safe map");
    expect(t("scene.fallback.performance.body")).toContain("same pages, groups and navigation");
    configureLanguage("pt-BR");
    expect(t("scene.fallback.performance.title")).toBe("Mapa seguro para este dispositivo");
    expect(t("scene.fallback.performance.body")).toContain("mesmas páginas, grupos e navegação");
    expect(t("scene.fallback.aria")).toBe("Mapa de conteúdo");
    expect(t("scene.workspace.approved")).toBe("Espaço aprovado");
  });

  it("localizes every hidden visual-lab surface instead of leaking mixed UI copy", () => {
    configureLanguage("en");
    expect(t("visualControl.aria")).toBe("God mode visual controls");
    expect(t("visualControl.slider.motion")).toBe("Motion");
    expect(t("visualControl.json.invalid")).toBe("Invalid JSON");
    configureLanguage("pt-BR");
    expect(t("visualControl.aria")).toBe("Controles visuais do modo mestre");
    expect(t("visualControl.slider.motion")).toBe("Movimento");
    expect(t("visualControl.json.invalid")).toBe("JSON inválido");
  });

  it("keeps the shared tour wording valid outside demo routes", () => {
    configureLanguage("en");
    expect(t("tour.welcome.body")).toContain("This guide presents");
    expect(t("tour.welcome.body").toLowerCase()).not.toContain("demo");
    configureLanguage("pt");
    expect(t("tour.welcome.body")).toContain("Este guia apresenta");
    expect(t("tour.welcome.body").toLowerCase()).not.toContain("demo");
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

  it("explains compatibility views in both cockpit languages", () => {
    configureLanguage("en");
    expect(t("world.experience.compatibility.badge")).toBe("Compatibility view");
    expect(t("world.experience.compatibility.switchHint")).toContain("native view");

    configureLanguage("pt");
    expect(t("world.experience.compatibility.badge")).toBe("Visão de compatibilidade");
    expect(t("world.experience.compatibility.switchHint")).toContain("visão nativa");
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
