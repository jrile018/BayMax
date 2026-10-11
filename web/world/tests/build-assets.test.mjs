import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs/promises';import os from 'node:os';import path from 'node:path';
const {buildAssets}=await import('../build-assets.mjs').catch(()=>({}));
test('asset build requires workers, copies exact bytes and rejects escaping symlinks',async()=>{
 assert.equal(typeof buildAssets,'function','buildAssets missing');
 const dir=await fs.mkdtemp(path.join(os.tmpdir(),'maps-assets-'));
 try{
  const pkg=path.join(dir,'pkg'),out=path.join(dir,'out');
  await fs.mkdir(pkg);await fs.writeFile(path.join(pkg,'LICENSE.md'),'Apache notice');
  await assert.rejects(buildAssets(pkg,out),/required|missing|ENOENT/i);
  for(const name of ['Build/Workers','Source/Assets','Source/ThirdParty'])await fs.mkdir(path.join(pkg,name),{recursive:true});
  await fs.writeFile(path.join(pkg,'Build/Workers/a.js'),'worker');
  const manifest=await buildAssets(pkg,out);
  assert.equal(await fs.readFile(path.join(out,'cesium/Workers/a.js'),'utf8'),'worker');
  assert.match(manifest.files.find(f=>f.path==='cesium/Workers/a.js').sha256,/^[a-f0-9]{64}$/);
  await fs.symlink(path.join(dir,'outside'),path.join(pkg,'Source/Assets/escape'));
  await assert.rejects(buildAssets(pkg,out),/symlink/i);
 }finally{await fs.rm(dir,{recursive:true,force:true});}
});
