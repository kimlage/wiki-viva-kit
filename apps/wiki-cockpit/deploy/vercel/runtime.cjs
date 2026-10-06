'use strict';

// Authentication belongs to Vercel's ingress, configured for ALL deployments.
// This demo handler never treats request headers, cookies or runtime flags as
// identity. It has no repository access, operator mutation API or credentials.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const sha256 = (bytes) => crypto.createHash('sha256').update(bytes).digest('hex');
const DEFAULT_ROUTE = '/w?projection=2d&page=source-banco-export&map_focus=source-banco-export&reader=1&tour=0';
const HEADERS = Object.freeze({
  'Cache-Control': 'private, no-store, max-age=0',
  Vary: 'Cookie, Authorization',
  Pragma: 'no-cache',
  Expires: '0',
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data: blob:; font-src 'self'; worker-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
});
const TYPES = Object.freeze({
  '.html': 'text/html; charset=utf-8', '.json': 'application/json; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml', '.txt': 'text/plain; charset=utf-8',
});

function regularFile(filename) {
  for (let current = filename; ; current = path.dirname(current)) {
    if (fs.lstatSync(current).isSymbolicLink()) throw new Error('symlink');
    if (path.dirname(current) === current) break;
  }
  if (!fs.lstatSync(filename).isFile()) throw new Error('not a regular file');
  return fs.readFileSync(filename);
}

function allowedPayload(uri) {
  return uri === '/index.html' || uri === '/favicon.svg' || uri === '/wiki-cockpit.config.json'
    || uri === '/files/synthetic-note.txt'
    || /^\/assets\/[A-Za-z0-9_.~-]+\.(js|css)$/.test(uri)
    || /^\/snapshot\/(content\/)?[A-Za-z0-9_.-]+\.json$/.test(uri);
}

function loadRelease(bundleRoot, expectedManifestSha256) {
  if (!/^[a-f0-9]{64}$/.test(expectedManifestSha256 || '')) throw new Error('manifest pin required');
  const raw = regularFile(path.join(bundleRoot, 'release-manifest.json'));
  if (raw.length > 256 * 1024 || sha256(raw) !== expectedManifestSha256) throw new Error('manifest integrity');
  const manifest = JSON.parse(raw.toString('utf8'));
  if (manifest.schema_version !== 'wiki_vercel_preview.v1' || manifest.synthetic_fixture !== 'walking_skeleton'
    || !/^[a-f0-9]{40}(?:[a-f0-9]{24})?$/.test(manifest.source_head || '')
    || typeof manifest.snapshot_id !== 'string' || !manifest.snapshot_id
    || manifest.default_route !== DEFAULT_ROUTE || !manifest.files || Array.isArray(manifest.files)) throw new Error('manifest contract');
  const entries = Object.entries(manifest.files);
  if (!entries.length || entries.length > 256) throw new Error('payload count');
  const files = new Map();
  let total = 0;
  for (const [uri, info] of entries) {
    if (!allowedPayload(uri) || !info || !/^[a-f0-9]{64}$/.test(info.sha256 || '')
      || !Number.isSafeInteger(info.bytes) || info.bytes < 0 || info.bytes > 20 * 1024 * 1024
      || info.content_type !== TYPES[path.extname(uri)]) throw new Error('payload catalog');
    total += info.bytes;
    if (total > 50 * 1024 * 1024) throw new Error('payload size');
    const bytes = regularFile(path.join(bundleRoot, uri.slice(1)));
    if (bytes.length !== info.bytes || sha256(bytes) !== info.sha256) throw new Error('payload integrity');
    files.set(uri, { bytes, type: info.content_type });
  }
  for (const required of ['/index.html', '/favicon.svg', '/wiki-cockpit.config.json', '/snapshot/manifest.json', '/snapshot/pages.json']) {
    if (!files.has(required)) throw new Error('missing payload');
  }
  const snapshot = JSON.parse(files.get('/snapshot/manifest.json').bytes.toString('utf8'));
  if (snapshot.snapshot_id !== manifest.snapshot_id || snapshot.fixture?.scenario_id !== 'walking_skeleton') throw new Error('snapshot revision');
  const pages = JSON.parse(files.get('/snapshot/pages.json').bytes.toString('utf8')).pages;
  if (!Array.isArray(pages) || !pages.length) throw new Error('page catalog');
  const ids = new Set(pages.map(page => page.id));
  if (ids.size !== pages.length || [...ids].some(id => typeof id !== 'string' || !id)) throw new Error('page identifiers');
  if (!manifest.reader || Array.isArray(manifest.reader) || Object.keys(manifest.reader).length !== ids.size) throw new Error('reader coverage');
  const reader = new Map();
  const sidecars = new Set();
  for (const [id, uri] of Object.entries(manifest.reader)) {
    if (!ids.has(id) || !/^\/snapshot\/content\/[A-Za-z0-9_.-]+\.json$/.test(uri) || !files.has(uri) || sidecars.has(uri)) throw new Error('reader catalog');
    const content = JSON.parse(files.get(uri).bytes.toString('utf8'));
    if (content.ok !== true || content.schema_version !== 'wiki_web_page_content.v1'
      || content.page?.page_id !== id || content.frontmatter?.page_id !== id
      || typeof content.body !== 'string' || content.snapshot_id !== manifest.snapshot_id) throw new Error('reader revision');
    sidecars.add(uri);
    reader.set(id, uri);
  }
  if (entries.filter(([uri]) => uri.startsWith('/snapshot/content/')).length !== sidecars.size) throw new Error('unmapped sidecar');
  const download = manifest.downloads?.['synthetic-note'];
  if (Object.keys(manifest.downloads || {}).length !== 1 || download?.uri !== '/files/synthetic-note.txt'
    || download.filename !== 'synthetic-note.txt' || !files.has(download.uri)) throw new Error('download catalog');
  return { files, reader, snapshotId: manifest.snapshot_id };
}

function requestTarget(raw) {
  if (typeof raw !== 'string' || !raw.startsWith('/') || raw.startsWith('//') || /[\u0000-\u0020\u007f\\#]/.test(raw)) return { error: 400 };
  if (Buffer.byteLength(raw) > 8192) return { error: 414 };
  const separator = raw.indexOf('?');
  const pathname = separator < 0 ? raw : raw.slice(0, separator);
  const query = separator < 0 ? '' : raw.slice(separator + 1);
  try {
    // Do not let URL() silently normalize traversal before catalog lookup.
    const decoded = decodeURIComponent(pathname);
    decodeURIComponent(query.replace(/\+/g, ' '));
    if (/[\u0000-\u001f\u007f\\]/.test(decoded) || /(?:^|\/)\.{1,2}(?:\/|$)/.test(decoded)) return { error: 400 };
  } catch {
    return { error: 400 };
  }
  return { pathname, query: new URLSearchParams(query) };
}

function createHandler(bundleRoot, expectedManifestSha256) {
  let release;
  try { release = loadRelease(bundleRoot, expectedManifestSha256); } catch { release = null; }
  return function handler(req, res) {
    const head = req.method === 'HEAD';
    const send = (status, bytes, type, extra = {}) => {
      res.statusCode = status;
      for (const [name, value] of Object.entries({ ...HEADERS, 'Content-Type': type, 'Content-Length': String(bytes.length), ...extra })) res.setHeader(name, value);
      res.end(head ? undefined : bytes);
    };
    const fail = (status, error, code, extra) => send(status, Buffer.from(JSON.stringify({ ok: false, error, error_code: code }) + '\n'), TYPES['.json'], extra);
    if (req.method !== 'GET' && req.method !== 'HEAD') return fail(405, 'method not allowed', 'method_not_allowed', { Allow: 'GET, HEAD' });
    const target = requestTarget(req.url);
    if (target.error) return fail(target.error, 'invalid request target', 'invalid_request_target');
    if (!release) return fail(503, 'preview release unavailable', 'release_unavailable');
    const { pathname, query } = target;
    if (pathname === '/') return send(307, Buffer.alloc(0), TYPES['.json'], { Location: DEFAULT_ROUTE });
    let uri = pathname;
    let attachment = false;
    if (pathname === '/w') uri = '/index.html';
    else if (pathname.startsWith('/pages/')) {
      const match = /^\/pages\/([^/]+)\/content$/.exec(pathname);
      if (!match) return fail(404, 'not found', 'not_found');
      const id = decodeURIComponent(match[1]);
      const revisions = query.getAll('snapshot_id');
      if (revisions.length !== 1 || revisions[0] !== release.snapshotId) return fail(409, 'snapshot revision mismatch', 'snapshot_revision_mismatch');
      uri = release.reader.get(id);
      if (!uri) return fail(404, 'not found', 'not_found');
    } else if (pathname === '/files/synthetic-note') {
      uri = '/files/synthetic-note.txt';
      attachment = true;
    } else if (pathname === '/index.html' || pathname.startsWith('/files/')) {
      return fail(404, 'not found', 'not_found');
    }
    const file = release.files.get(uri);
    if (!file) return fail(404, 'not found', 'not_found');
    return send(200, file.bytes, file.type, attachment ? { 'Content-Disposition': 'attachment; filename="synthetic-note.txt"' } : {});
  };
}

module.exports = { createHandler };
