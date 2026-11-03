import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import packetFixture from "./fixtures/context-packet-export.json";
import { canonicalPacketJson, contextPacketExportBytes } from "./contextPacketExport";
import type { ContextPacket } from "./contextPackets";
const packet = packetFixture as ContextPacket;
const expected = readFileSync(new URL("./fixtures/context-packet-export.json", import.meta.url));
it("matches the Python-produced canonical fixture, including UTF-8, numeric-looking and astral keys", async () => {
  const before = JSON.stringify(packet);
  const bytes = await contextPacketExportBytes(packet);
  expect(new TextDecoder().decode(bytes)).toBe(expected.toString("utf8"));
  expect(bytes.length).toBe(packet.bytes_used);
  expect(canonicalPacketJson(packet)).toContain('"10":"ten","2":"two"');
  expect(canonicalPacketJson(packet)).toContain('"é":"accent","":"private-use test key","🌱":"astral test key"');
  expect(JSON.parse(new TextDecoder().decode(bytes))).toEqual(packetFixture);
  expect(JSON.stringify(packet)).toBe(before);
  expect(packet.packet_digest).toBe("3930581a0135fe891028fe51b57a6f9d6fee89528e10a3e3e7ee252d032dea02");
});
it("refuses an incorrect byte count instead of rewriting the signed packet", async () => {
  await expect(contextPacketExportBytes({ ...packet, bytes_used: packet.bytes_used + 1 })).rejects.toThrow("context_packet_export_bytes_mismatch");
  await expect(contextPacketExportBytes({ ...packet, max_bytes: packet.bytes_used - 1 })).rejects.toThrow("context_packet_export_bytes_mismatch");
});
it("refuses a digest mismatch even when the encoded size is unchanged", async () => {
  await expect(contextPacketExportBytes({ ...packet, packet_digest: "0".repeat(64) })).rejects.toThrow("context_packet_export_digest_mismatch");
});
it("fails closed for values the canonical packet producer cannot encode", () => {
  expect(() => canonicalPacketJson({ text: "\ud800" })).toThrow("context_packet_export_encoding");
  expect(() => canonicalPacketJson({ count: Infinity })).toThrow("context_packet_export_encoding");
});
