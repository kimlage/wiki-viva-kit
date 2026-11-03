import type { ContextPacket } from "./contextPackets";

// Match the packet producer's UTF-8 JSON: sorted Unicode keys, no whitespace
// or trailing newline. Build object text directly so numeric-looking keys
// cannot be reordered by JavaScript's object enumeration rules.
export function canonicalPacketJson(value: unknown): string {
  if (value === null || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "string") {
    if (Array.from(value).some(c => { const n = c.codePointAt(0)!; return n >= 0xd800 && n <= 0xdfff; })) throw new Error("context_packet_export_encoding");
    return JSON.stringify(value);
  }
  if (typeof value === "number" && Number.isSafeInteger(value) && !Object.is(value, -0)) return String(value);
  if (Array.isArray(value)) return `[${value.map(canonicalPacketJson).join(",")}]`;
  if (value && typeof value === "object" && Object.getPrototypeOf(value) === Object.prototype) {
    const keys = Object.keys(value).sort((a, b) => {
      const x = Array.from(a, c => c.codePointAt(0)!), y = Array.from(b, c => c.codePointAt(0)!);
      for (let i = 0; i < Math.min(x.length, y.length); i++) if (x[i] !== y[i]) return x[i] - y[i];
      return x.length - y.length;
    });
    return `{${keys.map(key => `${canonicalPacketJson(key)}:${canonicalPacketJson((value as Record<string, unknown>)[key])}`).join(",")}}`;
  }
  throw new Error("context_packet_export_encoding");
}
export async function contextPacketExportBytes(packet: ContextPacket): Promise<Uint8Array<ArrayBuffer>> {
  const bytes = new TextEncoder().encode(canonicalPacketJson(packet));
  if (!Number.isSafeInteger(packet.bytes_used) || !Number.isSafeInteger(packet.max_bytes) || bytes.length !== packet.bytes_used || bytes.length > packet.max_bytes) throw new Error("context_packet_export_bytes_mismatch");
  const payload = Object.fromEntries(Object.entries(packet).filter(([key]) => key !== "packet_digest"));
  const digest = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonicalPacketJson(payload)));
  const hex = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
  if (hex !== packet.packet_digest) throw new Error("context_packet_export_digest_mismatch");
  return bytes;
}
