/** Offline test: exact core edits in the host; no plugin or Gateway is started. */
import fs from 'node:fs';
import path from 'node:path';
import {registerHooks} from 'node:module';
import {fileURLToPath} from 'node:url';
import {transform,validatePackage} from '../../scripts/openclaw/mission-loader.mjs';
import {configureRuntime} from '../../scripts/openclaw/mission-guard.mjs';
const m=JSON.parse(fs.readFileSync(new URL('../../scripts/openclaw/mission-overlay.json',import.meta.url)));
const core=process.env.WIKI_TEST_OPENCLAW_CORE_ROOT;process.env.WIKI_OPENCLAW_CORE_ROOT=core;
validatePackage(core,m.packages.core);configureRuntime(m.files.map(f=>f.name));
const files=new Map(m.files.filter(f=>f.package==='core'&&!(process.env.WIKI_TEST_RETIREMENT_SKIP_WRITER_HOOK==='1'&&f.name==='sqlite-worker-store-C0QRqven.mjs')).map(f=>[path.join(core,f.relative),f]));
registerHooks({load(url,context,nextLoad){const out=nextLoad(url,context);if(!url.startsWith('file:'))return out;const f=files.get(fileURLToPath(url));return f?{...out,source:transform(f.name,typeof out.source==='string'?out.source:Buffer.from(out.source).toString())}:out;}});
