export type TreeEntry={path:string;description:string;depth:number};

/** Recognize a plain-text file tree with aligned annotations, not arbitrary code. */
export function parseAnnotatedTree(source:string,language:string):TreeEntry[]|null {
  if(language&&!['text','plain','plaintext'].includes(language.toLowerCase()))return null;
  const rows=source.replace(/\r\n?/g,'\n').split('\n').filter(line=>line.trim());
  if(rows.length<4||rows.length>500)return null;
  const parsed:{indent:number;path:string;description:string}[]=[];
  for(const row of rows){
    const match=/^([ \t]*)(\S+)(?:[ \t]{2,}(\S.*))?[ \t]*$/.exec(row);
    if(!match||!/[./]/.test(match[2]))return null;
    parsed.push({indent:[...match[1]].reduce((n,c)=>n+(c==='\t'?4:1),0),path:match[2],description:match[3]??''});
  }
  if(parsed.filter(row=>row.description).length<2||
     !parsed.some(row=>row.path.endsWith('/'))||
     !parsed.some(row=>row.indent>parsed[0].indent))return null;
  const indents=[...new Set(parsed.map(row=>row.indent))].sort((a,b)=>a-b);
  return parsed.map(row=>({path:row.path,description:row.description,depth:indents.indexOf(row.indent)}));
}
