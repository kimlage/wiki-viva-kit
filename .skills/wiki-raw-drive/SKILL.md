---
name: wiki-raw-drive
description: Fetch and download RAW sources (statements, invoices, documents) from a single Google Drive folder into the local raw cache, without versioning PII in git. Centralizes raw in Drive and keeps the repo lightweight.
---

# Wiki Raw Drive

## Why

Raw sources (bank statements, invoices, PDFs with PII) must NOT be versioned
in git: they leak sensitive data into history and bloat the repo. They live in a
single Drive folder and are downloaded on demand into the local raw cache
([data/raw/](../../data/raw/), which is gitignored). This separation follows the
kit's architecture: the deterministic code processes; the agent that runs the repo
uses the Drive connector to gather the sources.

## Registry

The filename -> drive_file_id map lives in
[data/raw/_drive_manifest.json](../../data/raw/_drive_manifest.json) (this JSON is
versioned; it contains no PII, only identifiers). The canonical Drive folder is
configured by the repo owner and referenced by `folder id` in the manifest.

## Flow (executed by the agent that runs the repo)

1. To ingest a raw source, find the `drive_file_id` in the manifest (or
   search the folder via the Drive connector: `search_files` with `parentId = '<folder_id>'`).
2. Download the content with the Drive connector (`download_file_content` /
   `read_file_content`) into the raw cache ([data/raw/](../../data/raw/),
   gitignored).
3. Run the deterministic pipeline over the local file (manifest, text, chunks,
   index) and follow with the contextual LLM pass (skill `wiki-llm-context-agent`).
4. If you download a new file, register `filename -> drive_file_id` in the manifest.

## Rules

- Never commit raw files; only the
  [_drive_manifest.json](../../data/raw/_drive_manifest.json) is versioned.
- Never paste PII content (account number, CPF, transactions) into versioned
  pages; private pages may summarize, public pages require redaction and a
  promotion gate.
- If permission is missing on the Drive connector, ask the user to authenticate.
- The auditor blocks secrets in any file and PII in public pages;
  run it before consolidating.
