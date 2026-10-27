// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EvidenceMarkdown } from "./EvidenceMarkdown";
import type { ResolvedLink } from "../types";

afterEach(cleanup);

describe("verified card evidence", () => {
  it("opens canonical pages and pinned artifacts without dispatching work", () => {
    const open = vi.fn();
    const url = "https://github.com/example/wiki/blob/" + "a".repeat(40) + "/docs/receipt.json";
    const links = [{kind:"page",href:"../source.md",page_id:"source"}, {kind:"artifact",href:"../receipt.json",url}] as ResolvedLink[];
    render(<EvidenceMarkdown text="Read [source](../source.md) and [receipt](../receipt.json)." links={links} open={open}/>);
    fireEvent.click(screen.getByRole("link", {name:"source"}));
    expect(open).toHaveBeenCalledExactlyOnceWith("source");
    const receipt = screen.getByRole("link", {name:"receipt"});
    expect(receipt.getAttribute("href")).toBe(url);
    expect(receipt.getAttribute("rel")).toBe("noopener noreferrer");
    expect(receipt.getAttribute("target")).toBe("_blank");
  });

  it("keeps unsupported paths and schemes inert even for keyboard or context-menu navigation", () => {
    const links = [{kind:"external",href:"file:///private/secret"}, {kind:"external",href:"https://token@example.test"}] as ResolvedLink[];
    render(<EvidenceMarkdown text={'[local](file:///private/secret) [auth](https://token@example.test) [unknown](../unknown.md)\n\n<style>body{display:none}</style>\n\n![tracker](https://example.test/image)'} links={links} open={vi.fn()} />);
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(document.querySelector("img,style,script,iframe")).toBeNull();
    expect(document.querySelectorAll('a[aria-disabled="true"]')).toHaveLength(3);
  });

  it("replaces display titles only as text, preserving URLs and immutable source text", () => {
    const text = '`project-id` and [project-id](https://example.test/project-id)';
    render(<EvidenceMarkdown text={text} links={[{kind:"external",text:"project-id",href:"https://example.test/project-id",domain:"example.test"}]} pages={[{id:"project-id",title:"<img src=x onerror=alert(1)>"} as never]} open={vi.fn()}/>);
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByRole("link").getAttribute("href")).toBe("https://example.test/project-id");
    expect(screen.getAllByText("<img src=x onerror=alert(1)>")).toHaveLength(2);
    expect(text).toBe('`project-id` and [project-id](https://example.test/project-id)');
  });
});
