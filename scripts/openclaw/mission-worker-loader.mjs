/** The native SQLite writer has its own loader realm. No SDK or mission starts. */
import {registerHooks} from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
const manifest=JSON.parse(fs.readFileSync(new URL('./mission-overlay.json',import.meta.url)));
const name='session-transcript-turn-state-Bqkxfhzx.mjs';
const spec=manifest.files.find(f=>f.name===name);
const root=process.env.WIKI_OPENCLAW_CORE_ROOT;
if(!root||!path.isAbsolute(root)||fs.realpathSync(root)!==root)throw Error('wiki_mission_worker_root');
const pkg=JSON.parse(fs.readFileSync(path.join(root,'package.json')));
if(pkg.name!==manifest.packages.core.name||pkg.version!==manifest.packages.core.version)throw Error('wiki_mission_worker_version');
const expected=path.join(root,spec.relative);
registerHooks({load(url,context,nextLoad){
 const out=nextLoad(url,context);
 if(!url.startsWith('file:')||path.basename(fileURLToPath(url))!==name)return out;
 if(fileURLToPath(url)!==expected||fs.realpathSync(expected)!==expected||new URL(url).search||new URL(url).hash)throw Error('wiki_mission_worker_module');
 let source=typeof out.source==='string'?out.source:Buffer.from(out.source).toString();
 if(crypto.createHash('sha256').update(source).digest('hex')!==spec.sha256)throw Error('wiki_mission_worker_integrity');
 for(const [before,after]of spec.edits){if(source.split(before).length!==2)throw Error('wiki_mission_worker_shape');source=source.replace(before,after);}
 return {...out,source};
}});
