// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TakezoRitualFallback, takezoRuntimeKind } from "./TakezoRitualFallback";
import { configureLanguage, t } from "../data/i18n";

afterEach(() => {
  cleanup();
  configureLanguage("en");
});

describe("takezoRuntimeKind — §5.3 voice per runtime", () => {
  it("maps the runtimes the copy distinguishes", () => {
    expect(takezoRuntimeKind(true, "local_operator")).toBe("demo");
    expect(takezoRuntimeKind(false, "sample_fallback")).toBe("sample");
    expect(takezoRuntimeKind(false, "local_operator")).toBe("local");
  });

  it("treats unreachable/static runtimes as sealed contemplation", () => {
    expect(takezoRuntimeKind(false, "static_demo")).toBe("demo");
    expect(takezoRuntimeKind(false, "")).toBe("demo");
  });
});

describe("TakezoRitualFallback — the 2D twin (plan §15.6, §22.3)", () => {
  it("shows the mandated alt text for the local illustration", () => {
    render(<TakezoRitualFallback runtime="demo" onClose={() => {}} />);
    expect(
      screen.getByRole("img", { name: "Takezo, a wizard cat with a blue robe, a blue hat and red ribbons" })
    ).toBeTruthy();
  });

  it("speaks the sealed demo copy with a single exit — zero admin affordances", () => {
    render(<TakezoRitualFallback runtime="demo" onClose={() => {}} />);
    expect(screen.getByText(t("takezo.speech.demo"))).toBeTruthy();
    expect(screen.getByText(t("takezo.note.demo"))).toBeTruthy();
    expect(screen.getByRole("button", { name: t("takezo.action.leave") })).toBeTruthy();
    expect(screen.queryByRole("button", { name: t("takezo.action.unlock") })).toBeNull();
  });

  it("is honest about sample data when the operator was unreachable", () => {
    render(<TakezoRitualFallback runtime="sample" onClose={() => {}} />);
    expect(screen.getByText(t("takezo.speech.sample"))).toBeTruthy();
    expect(screen.queryByRole("button", { name: t("takezo.action.unlock") })).toBeNull();
  });

  it("offers unlock / explore / cancel to a local operator", () => {
    const onUnlock = vi.fn();
    render(<TakezoRitualFallback runtime="local" onUnlock={onUnlock} onClose={() => {}} />);
    expect(screen.getByText(t("takezo.speech.locked"))).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: t("takezo.action.unlock") }));
    expect(onUnlock).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: t("takezo.action.explore") })).toBeTruthy();
    expect(screen.getByRole("button", { name: t("takezo.action.cancel") })).toBeTruthy();
  });

  it("moves keyboard focus onto the speech dialog and closes on Escape", () => {
    const onClose = vi.fn();
    render(<TakezoRitualFallback runtime="demo" onClose={onClose} />);
    const dialog = screen.getByRole("dialog", { name: t("takezo.plateAria") });
    expect(document.activeElement).toBe(dialog);
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes through the explore and cancel paths without any other side effect", () => {
    const onClose = vi.fn();
    render(<TakezoRitualFallback runtime="local" onUnlock={() => {}} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: t("takezo.action.explore") }));
    fireEvent.click(screen.getByRole("button", { name: t("takezo.action.cancel") }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});

describe("takezo copy — i18n parity (plan §15.7, §22.3)", () => {
  const keys = [
    "takezo.name",
    "takezo.plateAria",
    "takezo.alt",
    "takezo.speech.locked",
    "takezo.speech.demo",
    "takezo.speech.sample",
    "takezo.speech.dryRun",
    "takezo.speech.stalePlan",
    "takezo.speech.proposal",
    "takezo.speech.lock",
    "takezo.note.demo",
    "takezo.note.sample",
    "takezo.note.local",
    "takezo.action.unlock",
    "takezo.action.explore",
    "takezo.action.cancel",
    "takezo.action.leave"
  ];

  it("resolves every ritual line in both languages", () => {
    for (const lang of ["en", "pt"] as const) {
      configureLanguage(lang);
      for (const key of keys) {
        expect(t(key), `${lang}:${key}`).not.toBe(key);
      }
    }
  });

  it("keeps the §15.7 quotes verbatim in Portuguese", () => {
    configureLanguage("pt");
    expect(t("takezo.speech.locked")).toBe(
      "A corrente se abriu. Eu posso mostrar o caminho; a chave ainda pertence ao operador."
    );
    expect(t("takezo.speech.lock")).toBe("A corrente está fechada.");
    expect(t("takezo.alt")).toBe("Takezo, gato mago com robe azul, chapéu azul e fitas vermelhas");
  });
});
