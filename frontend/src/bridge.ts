export type LoadPayload={documentId:string;revision:number;markdown:string;savedMarkdown?:string;editable:boolean;theme:'light'|'dark';zoom:number;width?:'comfortable'|'wide';state?:ScrollState;scrollState?:ScrollState;debug?:boolean};
export type ScrollState={scrollY:number;anchor?:string;offset?:number};
export const context={documentId:'',revision:0};
let requestCounter=0;
const assetRequests=new Map<string,(url:string|null)=>void>();
const imageRequests=new Map<string,(url:string|null)=>void>();
declare global {interface Window {reader:any;webkit?:{messageHandlers:{reader:{postMessage:(message:string)=>void}}};readerMessages?:unknown[];find?:(text:string,...args:boolean[])=>boolean}}
export function send(message:Record<string,unknown>):void {
  const value={documentId:context.documentId,revision:context.revision,...message};
  if(window.webkit?.messageHandlers?.reader)window.webkit.messageHandlers.reader.postMessage(JSON.stringify(value));
  else {window.readerMessages??=[];window.readerMessages.push(value);window.dispatchEvent(new CustomEvent('reader-message',{detail:value}));}
}
export function resolveAsset(src:string):Promise<string|null>{
  if(/^(https?:|data:image\/(?:png|jpeg|gif|webp|avif|svg\+xml);)/i.test(src))return Promise.resolve(src);
  if(/^[a-z][a-z0-9+.-]*:/i.test(src)&&!src.startsWith('file:'))return Promise.resolve(null);
  if(!window.webkit?.messageHandlers?.reader)return Promise.resolve(src);
  return new Promise(resolve=>{const requestId=`asset-${++requestCounter}`;assetRequests.set(requestId,resolve);send({type:'resolveAsset',requestId,src});setTimeout(()=>{if(assetRequests.delete(requestId))resolve(null)},10000)});
}
export function assetResolved(requestId:string,url:string|null){assetRequests.get(requestId)?.(url);assetRequests.delete(requestId)}
export function chooseImage():Promise<string|null>{return new Promise(resolve=>{const requestId=`image-${++requestCounter}`;imageRequests.set(requestId,resolve);send({type:'chooseImage',requestId})})}
export function imageChosen(requestId:string,src:string|null){imageRequests.get(requestId)?.(src);imageRequests.delete(requestId)}
