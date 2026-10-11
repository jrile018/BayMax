export function assetUrl(base,path) {
 const root=new URL(base);
 if(!root.pathname.endsWith('/'))throw new Error('asset base needs slash');
 if(!/^[\w./-]+$/.test(path)||path.startsWith('/')||path.split('/').some(p=>p==='..'))throw new Error('invalid asset path');
 const url=new URL(path,root);
 if(url.origin!==root.origin||!url.pathname.startsWith(root.pathname))throw new Error('asset outside base');
 return url.href;
}
