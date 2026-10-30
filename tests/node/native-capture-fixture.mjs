import fs from 'node:fs';import path from 'node:path';import os from 'node:os';import {pathToFileURL} from 'node:url';
import {NativeCaptureRegistry,configureNativeRegistry} from '../../scripts/openclaw/mission-runtime.mjs';
import {treeHash,validatePackage} from '../../scripts/openclaw/mission-loader.mjs';
export function createFixtureRegistry(names=['run.mjs','inference.mjs']) {
 const base=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'wiki-capture-'))),pluginRoot=path.join(base,'plugin'),coreRoot=path.join(base,'core');
 fs.mkdirSync(path.join(pluginRoot,'dist'),{recursive:true});fs.mkdirSync(coreRoot);
 fs.writeFileSync(path.join(coreRoot,'package.json'),JSON.stringify({name:'openclaw',version:'1',exports:{'./plugin-sdk/process-runtime':'./runtime.js'}}));fs.writeFileSync(path.join(coreRoot,'runtime.js'),'');
 fs.writeFileSync(path.join(pluginRoot,'package.json'),JSON.stringify({name:'@openclaw/codex',version:'1'}));
 const files=names.map(name=>({name,relative:'dist/'+name}));
 for(const f of files)fs.writeFileSync(path.join(pluginRoot,f.relative),'export const synthetic=true;');
 fs.writeFileSync(path.join(pluginRoot,'dist/index.js'),'');fs.mkdirSync(path.join(pluginRoot,'node_modules'));fs.symlinkSync(coreRoot,path.join(pluginRoot,'node_modules/openclaw'),'dir');
 const spec={name:'@openclaw/codex',version:'1',tree_sha256:treeHash(pluginRoot)};
 const registry=new NativeCaptureRegistry({pluginRoot,coreRoot,files,validatePackage:root=>validatePackage(root,spec)});
 let n=0;
 function candidate({runtime=true,shared,load=true}={}) {
  const root=shared?.root ?? path.join(base,'capture-'+(++n));if(!shared)fs.cpSync(pluginRoot,root,{recursive:true,dereference:false});
  let current;
  const control=new AbortController();
  const instance={pluginId:'codex',accepting:true,replacementReserved:false,forcedRetirement:false,lifecycle:{signal:control.signal},runtimeScope:{pluginTrustedOfficialInstall:true},onModuleDispose:()=>{}};
  if(runtime)instance.owner={instance,record:{id:'codex',source:path.join(pluginRoot,'dist/index.js')}};
  current=instance;
  const artifact={resolve:source=>path.join(root,path.relative(pluginRoot,source)),sourceForCaptured:file=>path.join(pluginRoot,path.relative(root,file)),moduleRoot:()=>root,assertModuleAvailable:file=>{if(!fs.existsSync(file))throw Error('native unavailable');}};
  const params={rootDir:pluginRoot,instance};const read=()=>current;
  const url=pathToFileURL(path.join(root,files[0].relative)).href, inferUrl=pathToFileURL(path.join(root,files[1].relative)).href;
  const register=()=>registry.register(params,artifact,read);
  return {root,instance,control,artifact,params,read,url,inferUrl,register,setCurrent:value=>{current=value;},load:()=>files.forEach(f=>registry.loaded(f.name,pathToFileURL(path.join(root,f.relative)).href))};
 }
 return {base,pluginRoot,coreRoot,files,registry,candidate,clean:()=>fs.rmSync(base,{recursive:true,force:true})};
}
let shared;
export function guardTestOwner() {
 if(!shared){shared=createFixtureRegistry(['run-attempt-CGHsrfPB.mjs','inference-dispatch-CO6tTs4q.mjs','shared-client-C0gEybHs.mjs']);configureNativeRegistry(shared.registry);}
 const c=shared.candidate();c.dispose=c.register();c.load();return {...c,owner:shared.registry.capture(c.url),inferenceOwner:shared.registry.capture(c.inferUrl),routeOwner:shared.registry.capture(pathToFileURL(path.join(c.root,shared.files[2].relative)).href)};
}
