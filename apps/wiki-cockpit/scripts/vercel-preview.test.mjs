import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const { createHandler } = createRequire(import.meta.url)('../deploy/vercel/runtime.cjs');
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const json = value => Buffer.from(JSON.stringify(value) + '\n');
const defaultRoute = '/w?projection=2d&page=source-banco-export&map_focus=source-banco-export&reader=1&tour=0';
const snapshotId = 'wiki-viva-demo-synthetic-runtime-test';
const sidecarUri = '/snapshot/content/source-synthetic.12345678.json';

function fixture(t) {
  const root = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), 'wiki-vercel-runtime-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const payloads = {
    '/index.html': [Buffer.from('<!doctype html><title>Synthetic Preview</title>'), 'text/html; charset=utf-8'],
    '/favicon.svg': [Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"/>'), 'image/svg+xml'],
    '/assets/app~one.js': [Buffer.from('export const synthetic = true;'), 'text/javascript; charset=utf-8'],
    '/assets/app.css': [Buffer.from('body{color:#111}'), 'text/css; charset=utf-8'],
    '/wiki-cockpit.config.json': [json({ mode: 'static', snapshot_base: '/snapshot', api_base: '', codex: { enabled: false } }), 'application/json; charset=utf-8'],
    '/snapshot/manifest.json': [json({ snapshot_id: snapshotId, fixture: { scenario_id: 'walking_skeleton' } }), 'application/json; charset=utf-8'],
    '/snapshot/pages.json': [json({ pages: [{ id: 'source-synthetic' }] }), 'application/json; charset=utf-8'],
    [sidecarUri]: [json({ ok: true, schema_version: 'wiki_web_page_content.v1', snapshot_id: snapshotId, page: { page_id: 'source-synthetic' }, frontmatter: { page_id: 'source-synthetic' }, body: 'Synthetic source.' }), 'application/json; charset=utf-8'],
    '/files/synthetic-note.txt': [Buffer.from('Synthetic attachment.\n'), 'text/plain; charset=utf-8'],
  };
  const files = {};
  for (const [uri, [bytes, type]] of Object.entries(payloads)) {
    const filename = path.join(root, uri.slice(1));
    fs.mkdirSync(path.dirname(filename), { recursive: true });
    fs.writeFileSync(filename, bytes);
    files[uri] = { bytes: bytes.length, sha256: sha(bytes), content_type: type };
  }
  const manifest = { schema_version: 'wiki_vercel_preview.v1', synthetic_fixture: 'walking_skeleton', source_head: 'a'.repeat(40), snapshot_id: snapshotId, default_route: defaultRoute, files, reader: { 'source-synthetic': sidecarUri }, downloads: { 'synthetic-note': { uri: '/files/synthetic-note.txt', filename: 'synthetic-note.txt' } } };
  const seal = () => {
    const bytes = json(manifest);
    fs.writeFileSync(path.join(root, 'release-manifest.json'), bytes);
    return sha(bytes);
  };
  const pin = seal();
  return { root, payloads, manifest, seal, pin, handler: createHandler(root, pin) };
}

function request(handler, url, method = 'GET', headers = {}) {
  const response = { statusCode: 0, headers: {}, body: Buffer.alloc(0), setHeader(name, value) { this.headers[name.toLowerCase()] = value; }, end(body) { this.body = body === undefined ? Buffer.alloc(0) : Buffer.from(body); } };
  handler({ url, method, headers }, response);
  assert.equal(response.headers['cache-control'], 'private, no-store, max-age=0');
  assert.equal(response.headers.vary, 'Cookie, Authorization');
  assert.equal(response.headers.pragma, 'no-cache');
  assert.equal(response.headers.expires, '0');
  assert.equal(response.headers['x-content-type-options'], 'nosniff');
  assert.match(response.headers['content-security-policy'], /frame-ancestors 'none'/);
  assert.equal(response.headers['referrer-policy'], 'no-referrer');
  return response;
}

test('all catalogued resource classes use one read-only handler with exact HEAD semantics', t => {
  const f = fixture(t);
  const routes = ['/w', '/assets/app~one.js', '/assets/app.css', '/favicon.svg', '/wiki-cockpit.config.json', '/snapshot/manifest.json', '/snapshot/pages.json', sidecarUri, `/pages/source-synthetic/content?snapshot_id=${snapshotId}`, '/files/synthetic-note'];
  for (const url of routes) {
    const get = request(f.handler, url);
    assert.equal(get.statusCode, 200, url);
    assert.equal(Number(get.headers['content-length']), get.body.length);
    const head = request(f.handler, url, 'HEAD');
    assert.equal(head.statusCode, 200, url);
    assert.deepEqual(head.headers, get.headers);
    assert.equal(head.body.length, 0);
  }
  assert.equal(request(f.handler, '/files/synthetic-note').headers['content-disposition'], 'attachment; filename="synthetic-note.txt"');
  const root = request(f.handler, '/');
  assert.equal(root.statusCode, 307);
  assert.equal(root.headers.location, defaultRoute);
});

test('only /w serves HTML; absent boot, APIs, internals and raw download paths return JSON 404', t => {
  const { handler } = fixture(t);
  for (const url of ['/index.html', '/snapshot/boot', '/snapshot/missing.json', '/health', '/api/ingest', '/wiki', '/index.cjs', '/runtime.cjs', '/release-manifest.json', '/.vc-config.json', '/.vercel/output/config.json', '/files/synthetic-note.txt', '/anything']) {
    const response = request(handler, url);
    assert.equal(response.statusCode, 404, url);
    assert.match(response.headers['content-type'], /^application\/json/);
    assert.equal(JSON.parse(response.body).error_code, 'not_found');
    const head = request(handler, url, 'HEAD');
    assert.equal(head.statusCode, 404);
    assert.equal(head.body.length, 0);
    assert.equal(head.headers['content-length'], response.headers['content-length']);
  }
});

test('reader pins a single snapshot revision and never resolves an identifier as a filesystem path', t => {
  const { handler } = fixture(t);
  for (const query of ['', '?snapshot_id=old', `?snapshot_id=${snapshotId}&snapshot_id=${snapshotId}`]) {
    const response = request(handler, `/pages/source-synthetic/content${query}`);
    assert.equal(response.statusCode, 409);
    assert.equal(JSON.parse(response.body).error_code, 'snapshot_revision_mismatch');
  }
  assert.equal(request(handler, `/pages/unknown/content?snapshot_id=${snapshotId}`).statusCode, 404);
  assert.equal(request(handler, `/pages/source%2Dsynthetic/content?snapshot_id=${snapshotId}`).statusCode, 200);
  assert.equal(request(handler, `/pages/source%252Dsynthetic/content?snapshot_id=${snapshotId}`).statusCode, 404);
});

test('request validation rejects traversal, malformed encodings, absolute URLs and controls without reflecting input', t => {
  const { handler } = fixture(t);
  for (const url of ['/../index.html', '/snapshot/%2e%2e/index.html', '/snapshot/%2f../index.html', '/w\\index.html', '/w#fragment', '/w\nInjected: private-sentinel', '/w?bad=%GG', '/w?bad=%E9', '//foreign.invalid/w', 'https://foreign.invalid/w', '/pages/%/content', '/snapshot/%00manifest.json']) {
    const response = request(handler, url);
    assert.equal(response.statusCode, 400, JSON.stringify(url));
    assert.ok(!response.body.includes(Buffer.from('private-sentinel')));
  }
  assert.equal(request(handler, '/w?' + 'x'.repeat(8192)).statusCode, 414);
});

test('all writes and OPTIONS fail with JSON, no-store and an explicit method allowance', t => {
  const { handler } = fixture(t);
  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'TRACE', 'CONNECT']) {
    for (const url of ['/w', '/snapshot/manifest.json', '/pages/source-synthetic/content', '/api/ingest']) {
      const response = request(handler, url, method);
      assert.equal(response.statusCode, 405);
      assert.equal(response.headers.allow, 'GET, HEAD');
      assert.equal(JSON.parse(response.body).error_code, 'method_not_allowed');
    }
  }
});

test('headers, cookies and query flags cannot enable operator routes or bypass missing resources', t => {
  const { handler } = fixture(t);
  const spoofed = { cookie: 'sso=private-sentinel', authorization: 'Bearer private-sentinel', 'x-vercel-protection-bypass': 'private-sentinel', 'x-forwarded-user': 'owner', 'x-matched-path': '/w' };
  for (const url of ['/api/codex/run?authenticated=1', '/health?role=owner', '/wiki?path=/w']) {
    const response = request(handler, url, 'GET', spoofed);
    assert.equal(response.statusCode, 404);
    assert.ok(!response.body.includes(Buffer.from('private-sentinel')));
  }
  // Native ingress authentication must be tested on the actual host. The
  // synthetic handler is intentionally not an authentication implementation.
  assert.equal(request(handler, '/w', 'GET', {}).statusCode, 200);
});

test('cold start refuses corrupted payloads and changed manifests with generic cache-safe 503', t => {
  const f = fixture(t);
  fs.writeFileSync(path.join(f.root, 'assets/app~one.js'), 'corrupted private-sentinel');
  let response = request(createHandler(f.root, f.pin), '/w');
  assert.equal(response.statusCode, 503);
  assert.equal(JSON.parse(response.body).error_code, 'release_unavailable');
  assert.ok(!response.body.includes(Buffer.from(f.root)));
  // Updating a payload's catalog hash cannot defeat the manifest pin in index.cjs.
  f.manifest.files['/assets/app~one.js'].sha256 = sha(Buffer.from('corrupted private-sentinel'));
  f.manifest.files['/assets/app~one.js'].bytes = Buffer.byteLength('corrupted private-sentinel');
  f.seal();
  assert.equal(request(createHandler(f.root, f.pin), '/w').statusCode, 503);
  // A warm function serves its frozen release, without re-reading mutable files.
  assert.equal(request(f.handler, '/assets/app~one.js').body.toString(), 'export const synthetic = true;');
});

test('symlink payloads and catalog escape, MIME, coverage and download contract failures fail closed', t => {
  const cases = [
    f => { const p = path.join(f.root, 'assets/app~one.js'); fs.renameSync(p, p + '.real'); fs.symlinkSync(p + '.real', p); },
    f => { f.manifest.files['/../index.html'] = f.manifest.files['/index.html']; },
    f => { f.manifest.files['/assets/app~one.js'].content_type = 'text/html; charset=utf-8'; },
    f => { f.manifest.files['/assets/app~one.js'].bytes += 1; },
    f => { f.manifest.reader = {}; },
    f => { f.manifest.reader['source-synthetic'] = '/index.html'; },
    f => { f.manifest.downloads['synthetic-note'].filename = 'bad\r\nX-Leak: private-sentinel'; },
    f => { f.manifest.default_route = '//foreign.invalid'; },
    f => { delete f.manifest.files['/snapshot/pages.json']; },
  ];
  for (const mutate of cases) {
    const f = fixture(t);
    mutate(f);
    const response = request(createHandler(f.root, f.seal()), '/w');
    assert.equal(response.statusCode, 503);
    assert.ok(!response.body.includes(Buffer.from('private-sentinel')));
  }
});
