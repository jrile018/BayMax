import fs from 'node:fs/promises';import path from 'node:path';import {createHash} from 'node:crypto';import {fileURLToPath} from 'node:url';
const mappings=[['Build/Workers','cesium/Workers'],['Source/Assets','cesium/Assets'],['Source/ThirdParty','cesium/ThirdParty']];
async function filesAt(root,current=root){
 const result=[];
 for(const entry of await fs.readdir(current,{withFileTypes:true})){
  const full=path.join(current,entry.name);
  if(entry.isSymbolicLink())throw Error('asset symlink rejected');
  if(entry.isDirectory())result.push(...await filesAt(root,full));
  else if(entry.isFile())result.push(full);
 }
 return result;
}
export async function buildAssets(packageRoot,outDir){
 const lists=[];
 for(const [from,to] of mappings){
  const source=path.join(packageRoot,from);const stat=await fs.lstat(source);
  if(!stat.isDirectory()||stat.isSymbolicLink())throw Error('required asset directory missing or symlink');
  lists.push([source,to,await filesAt(source)]);
 }
 const license=await fs.readFile(path.join(packageRoot,'LICENSE.md'));
 await fs.mkdir(outDir,{recursive:true});
 for(const [source,to,files] of lists)for(const file of files){
  const destination=path.join(outDir,to,path.relative(source,file));await fs.mkdir(path.dirname(destination),{recursive:true});await fs.copyFile(file,destination);
 }
 await fs.writeFile(path.join(outDir,'LICENSE.cesium.md'),license);
 const files=[];
 for(const file of await filesAt(outDir)){
  const relative=path.relative(outDir,file).split(path.sep).join('/');if(relative==='asset-manifest.json')continue;
  const bytes=await fs.readFile(file);files.push({path:relative,bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex')});
 }
 files.sort((a,b)=>a.path.localeCompare(b.path));
 const manifest={schema:'maps-world-assets-v1',engine:'22.3.0',files};
 await fs.writeFile(path.join(outDir,'asset-manifest.json'),JSON.stringify(manifest,null,2)+'\n');return manifest;
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 const manifest=await buildAssets(new URL('node_modules/@cesium/engine/',import.meta.url).pathname,new URL('dist/',import.meta.url).pathname);console.log('Assets verified:',manifest.files.length);
}
