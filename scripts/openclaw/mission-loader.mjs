/** Opt-in, version-bound runtime overlay. Installed packages remain unchanged. */
import {registerHooks,createRequire} from 'node:module';
import fs from 'node:fs';
import crypto from 'node:crypto';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {configureRuntime} from './mission-guard.mjs';
import {NativeCaptureRegistry,configureNativeRegistry,qualifyNativeModule} from './mission-runtime.mjs';
const manifest=JSON.parse(fs.readFileSync(new URL('./mission-overlay.json',import.meta.url),'utf8'));
const guard=new URL('./mission-guard.mjs',import.meta.url).href;
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
export function treeHash(root) {
  const records=[];
  function visit(dir) {
    for(const item of fs.readdirSync(dir,{withFileTypes:true})) {
      if(item.name==='node_modules') continue;
      const file=path.join(dir,item.name), rel=path.relative(root,file);
      if(item.isDirectory()) visit(file);
      else if(/\.(mjs|js|json)$/.test(item.name)) {
        if(!item.isFile()) throw new Error('wiki_mission_package_symlink');
        records.push([rel,sha(fs.readFileSync(file))]);
      }
    }
  }
  visit(root);records.sort((a,b)=>a[0]<b[0]?-1:a[0]>b[0]?1:0);
  return sha(records.map(([name,hash])=>name+'\0'+hash+'\n').join(''));
}
export function validatePackage(root,spec) {
  if(!root || !path.isAbsolute(root) || fs.realpathSync(root)!==root) throw new Error('wiki_mission_package_root');
  const pkg=JSON.parse(fs.readFileSync(path.join(root,'package.json'),'utf8'));
  if(pkg.name!==spec.name || pkg.version!==spec.version || treeHash(root)!==spec.tree_sha256) throw new Error('wiki_mission_unsupported_package');
}
export function transform(name,source) {
  const spec=manifest.files.find(f=>f.name===name);
  if(!spec) throw new Error('wiki_mission_unknown_hook');
  if(sha(source)!==spec.sha256) throw new Error('wiki_mission_unsupported_runtime_bytes');
  for(const [before,after] of spec.edits) {
    if(source.split(before).length!==2) throw new Error('wiki_mission_overlay_shape_changed');
    source=source.replace(before,after);
  }
  return `import * as wikiMissionGuard from ${JSON.stringify(guard)};\n`+source+`\nwikiMissionGuard.loadedHook(${JSON.stringify(name)},import.meta.url);\n`;
}
export async function install() {
  const roots={core:process.env.WIKI_OPENCLAW_CORE_ROOT,plugin:process.env.WIKI_OPENCLAW_PLUGIN_ROOT};
  for(const [name,spec] of Object.entries(manifest.packages)) validatePackage(roots[name],spec);
  const sdk=createRequire(path.join(roots.plugin,'package.json')).resolve('openclaw/plugin-sdk/process-runtime');
  if(!fs.realpathSync(sdk).startsWith(roots.core+path.sep)) throw new Error('wiki_mission_sdk_root_changed');
  configureNativeRegistry(new NativeCaptureRegistry({pluginRoot:roots.plugin,coreRoot:roots.core,files:manifest.files.filter(f=>f.package==='plugin'),validatePackage:root=>validatePackage(root,manifest.packages.plugin)}));
  configureRuntime(manifest.files.map(f=>f.name));
  const expected=new Map(manifest.files.map(f=>[path.join(roots[f.package],f.relative),f]));
  registerHooks({load(url,context,nextLoad){
    const out=nextLoad(url,context);
    if(!url.startsWith('file:')) return out;
    const file=fileURLToPath(url), name=path.basename(file);
    if(!manifest.files.some(f=>f.name===name)) return out;
    const qualified=expected.has(file) || qualifyNativeModule(file);
    if(!qualified || fs.realpathSync(file)!==file || new URL(url).search || new URL(url).hash) throw new Error('wiki_mission_hook_root_changed');
    return {...out,source:transform(name,typeof out.source==='string'?out.source:Buffer.from(out.source).toString('utf8'))};
  }});
  // Load the guarded plugin modules before the gateway admits a chat. The
  // native loader qualifies its captured copies separately before execution.
  for(const f of manifest.files.filter(f=>f.package==='plugin')) await import(pathToFileURL(path.join(roots.plugin,f.relative)).href);
}
// Importing helpers in a test does not activate a gateway or plugin.
if(process.env.WIKI_OPENCLAW_GUARD_BOOTSTRAP==='1') await install();
