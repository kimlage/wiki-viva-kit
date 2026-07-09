#!/usr/bin/env node

const url = process.env.WIKI_COCKPIT_SNAPSHOT_URL || "http://127.0.0.1:5174/api/snapshot/pages.json";
const expectedRepo = process.env.WIKI_COCKPIT_EXPECT_REPO_ID || "";
const minPages = Number(process.env.WIKI_COCKPIT_MIN_PAGES || "1");

function fail(message) {
  console.error(`snapshot-api check failed: ${message}`);
  process.exit(1);
}

const response = await fetch(url, { headers: { accept: "application/json" } }).catch((error) => {
  fail(`${url} is unreachable: ${error instanceof Error ? error.message : String(error)}`);
});

const contentType = response.headers.get("content-type") || "";
if (!contentType.toLowerCase().includes("application/json")) {
  fail(`${url} returned ${contentType || "unknown content type"} instead of application/json`);
}
if (!response.ok) fail(`${url} returned HTTP ${response.status}`);

const payload = await response.json().catch((error) => {
  fail(`${url} did not parse as JSON: ${error instanceof Error ? error.message : String(error)}`);
});

const repoId = String(payload.repo_id || payload.repo?.repo_id || "");
const pageCount = Array.isArray(payload.pages) ? payload.pages.length : 0;

if (expectedRepo && repoId !== expectedRepo) {
  fail(`repo_id ${repoId || "(missing)"} !== expected ${expectedRepo}`);
}
if (pageCount < minPages) {
  fail(`page count ${pageCount} < expected minimum ${minPages}`);
}

console.log(`snapshot-api ok: ${repoId || "(unknown repo)"} ${pageCount} pages from ${url}`);
