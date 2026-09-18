import fs from 'node:fs';
import path from 'node:path';
const root=process.cwd();
const lock=JSON.parse(fs.readFileSync(path.join(root,'package-lock.json'),'utf8'));
const notices=['THIRD-PARTY SOFTWARE NOTICES','Markdown Reader bundles these free open-source packages.','Packages may be partially included or eliminated by the production bundler.',''];
for(const [directory,entry]of Object.entries(lock.packages).sort()){
  if(!directory||entry.dev)continue;
  const location=path.join(root,directory);if(!fs.existsSync(location))continue;
  let info;try{info=JSON.parse(fs.readFileSync(path.join(location,'package.json'),'utf8'));}catch{continue;}
  notices.push('='.repeat(72),`${info.name} ${info.version}`,`License: ${typeof info.license==='string'?info.license:JSON.stringify(info.license??entry.license??'See upstream package')}`,`Source: ${typeof info.repository==='string'?info.repository:info.repository?.url??info.homepage??''}`,'');
  const licenses=fs.readdirSync(location).filter(file=>/^(licen[sc]e|copying|notice)(?:[.-]|$)/i.test(file));
  for(const file of licenses){const full=path.join(location,file);if(fs.statSync(full).isFile())notices.push(fs.readFileSync(full,'utf8'),'');}
}
fs.writeFileSync(path.join(root,'dist','THIRD_PARTY_NOTICES.txt'),notices.join('\n'));
console.log('Bundled third-party notices written.');
