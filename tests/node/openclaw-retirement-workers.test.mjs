import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
import {retirementWorkerArguments} from '../../scripts/openclaw/mission-retirement.mjs';
test('SQLite worker preload refuses unknown generations, roots and URL decorations',()=>{
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'wiki-worker-source-')));
 const previous=process.env.WIKI_OPENCLAW_CORE_ROOT;
 try{
  process.env.WIKI_OPENCLAW_CORE_ROOT=root;fs.mkdirSync(path.join(root,'dist'));
  const file=path.join(root,'dist','synthetic-worker.mjs');fs.writeFileSync(file,'');
  const url=pathToFileURL(file);
  const result=retirementWorkerArguments([],url,{moduleUrl:url.href});
  assert.equal(result[0],'--import');assert.match(result[1],/mission-worker-loader\.mjs$/);
  for(const [carrier,source,generation]of [[url,undefined,{}],[new URL(url.href+'?unknown'),undefined],
   [new URL(url.href+'#unknown'),undefined],[pathToFileURL(import.meta.filename),undefined],
   [url,{sourceLoaderUrl:'https://example.test/source'}],[url,{moduleUrl:pathToFileURL(import.meta.filename)}]])
   assert.throws(()=>retirementWorkerArguments([],carrier,source,generation));
 }finally{if(previous===undefined)delete process.env.WIKI_OPENCLAW_CORE_ROOT;else process.env.WIKI_OPENCLAW_CORE_ROOT=previous;fs.rmSync(root,{recursive:true});}
});
test('actual worker loader refuses replacement native matcher bytes before evaluation',()=>{
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'wiki-worker-integrity-')));
 try{
  const manifest=JSON.parse(fs.readFileSync(new URL('../../scripts/openclaw/mission-overlay.json',import.meta.url)));
  fs.mkdirSync(path.join(root,'dist'));fs.writeFileSync(path.join(root,'package.json'),JSON.stringify(manifest.packages.core));
  const file=path.join(root,'dist','session-transcript-turn-state-Bqkxfhzx.mjs');
  fs.writeFileSync(file,'console.log("UNGUARDED_EVALUATION")');
  const result=spawnSync(process.execPath,['--import',new URL('../../scripts/openclaw/mission-worker-loader.mjs',import.meta.url).href,file],{env:{...process.env,WIKI_OPENCLAW_CORE_ROOT:root},encoding:'utf8'});
  assert.notEqual(result.status,0);assert.match(result.stderr,/wiki_mission_worker_integrity/);
  assert.equal(result.stdout.includes('UNGUARDED_EVALUATION'),false);
 }finally{fs.rmSync(root,{recursive:true});}
});
