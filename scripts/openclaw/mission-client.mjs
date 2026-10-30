/** Pin the native managed app-server without reclassifying external commands. */
import fs from 'node:fs';import path from 'node:path';import crypto from 'node:crypto';import {createRequire} from 'node:module';
const require=(ok,code)=>{if(!ok)throw new Error(`wiki_mission_${code}`);};
const hash=file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
export function pinnedClientAdmission(pluginRoot,spec) {
  require(spec?.platform===process.platform && spec?.arch===process.arch,'client_platform_unsupported');
  const resolve=createRequire(path.join(pluginRoot,'package.json'));
  const describe=(item)=>{
    const manifest=fs.realpathSync(resolve.resolve(item.name+'/package.json'));
    const root=path.dirname(manifest),file=path.join(root,item.file);
    return {item,manifest,root,file};
  };
  const launcher=describe(spec.launcher),native=describe(spec.native);
  const verify=()=>{
    for(const entry of [launcher,native]) {
      const {item,manifest,file}=entry;
      const pkg=JSON.parse(fs.readFileSync(manifest));
      require(pkg.name===(item.manifest_name??item.name) && pkg.version===item.version,'client_package_changed');
      require(fs.realpathSync(resolve.resolve(item.name+'/package.json'))===manifest && fs.realpathSync(file)===file && fs.statSync(file).isFile() && hash(file)===item.sha256,'client_bytes_changed');
    }
    require(fs.realpathSync(createRequire(launcher.manifest).resolve(spec.native.name+'/package.json'))===native.manifest,'client_dependency_changed');
  };
  verify();
  const args=['app-server','--listen','stdio://'];
  const admittedArgs=[args,['-c','cli_auth_credentials_store="ephemeral"',...args]].map(value=>JSON.stringify(value));
  return options=>{
    require(options?.commandSource==='resolved-managed' && options.transport==='stdio' && options.command===launcher.file && admittedArgs.includes(JSON.stringify(options.args)),'client_selection_changed');
    verify();
  };
}
