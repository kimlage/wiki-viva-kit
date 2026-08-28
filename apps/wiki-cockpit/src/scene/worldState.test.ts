import { describe, expect, it } from "vitest";
import { isLegacyRegionGroup, parseRealFamilyGroupId, realFamilyGroupId, worldNavigationState } from "./worldState";

describe("world navigation state", () => {
  it("accepts real family groups and rejects legacy region groups", () => {
    expect(parseRealFamilyGroupId("family:source")).toEqual({ family: "source", key: "family:source" });
    expect(realFamilyGroupId("source")).toBe("family:source");
    expect(parseRealFamilyGroupId("region:pratica:family:source")).toBeNull();
    expect(isLegacyRegionGroup("region:pratica")).toBe(true);
  });

  it("keeps center, lens and real group in separate state slots", () => {
    expect(
      worldNavigationState({
        centerId: "root-alex-rivera",
        lens: "pratica",
        group: "family:source",
        pageId: "source-drive-export",
        reader: true
      })
    ).toEqual({
      centerId: "root-alex-rivera",
      lens: "pratica",
      group: "family:source",
      pageId: "source-drive-export",
      reader: true,
      legacyRegion: false
    });
  });

  it("does not promote a region namespace to a navigable group", () => {
    expect(worldNavigationState({ centerId: "root", lens: "pratica", group: "region:pratica" })).toMatchObject({
      centerId: "root",
      lens: "pratica",
      group: undefined,
      legacyRegion: true
    });
  });
});
