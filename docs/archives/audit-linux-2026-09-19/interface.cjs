const fs = require('fs'); const vm = require('vm');
function setup(source){
 const elements=new Map(); const active=[]; const pending=[];
 function element(sel){ if(!elements.has(sel)) elements.set(sel,{value:'',checked:false,disabled:false,hidden:true,textContent:'',innerHTML:'',style:{},dataset:{},listeners:{},classList:{add(){},remove(){},toggle(){}},addEventListener(k,f){this.listeners[k]=f},querySelector(s){return element(sel+' '+s)},querySelectorAll(){return []},setAttribute(){},focus(){},appendChild(){}});return elements.get(sel)}
 const context=vm.createContext({console,Blob,ArrayBuffer,DataView,Int16Array,Float32Array,URLSearchParams,Intl,Date,window:{},localStorage:{getItem(){return'fr'}},navigator:{language:'fr',mediaDevices:{getUserMedia(){return new Promise(resolve=>pending.push(()=>{const stream={live:true,getTracks(){return[{stop(){stream.live=false}}]}};active.push(stream);resolve(stream)}))}}},document:{querySelector:element,querySelectorAll(){return[]},addEventListener(){},contains(){return true}},AudioContext:class{sampleRate=16000;createMediaStreamSource(){return{connect(){},disconnect(){}}}createScriptProcessor(){return{connect(){},disconnect(){}}}async close(){}},setTimeout(){return 1},clearTimeout(){},fetch:async(path)=>({ok:true,json:async()=>path==='/api/polish'?{text:'Polished'}:path==='/api/history'?{entries:[]}:{text:'Transcript'},text:async()=>''})});
 vm.runInContext(source.split('/* ---------- Init ---------- */')[0],context);vm.runInContext('livePreview=false',context);
 return{context,element,active,pending,run(s){return vm.runInContext(s,context)}};
}
const versions=[['working',fs.readFileSync('src/aparte/assets/app.js','utf8')]];
if(process.argv[2]) versions.push(['reference',fs.readFileSync(process.argv[2],'utf8')]);
(async()=>{for(const [version,source] of versions){
 const c=setup(source);const click=c.element('#record').listeners.click;
 const a=click(),b=click(); const requests=c.pending.length;c.pending.shift()();await a;c.pending.shift()();await b;await click();
 console.log(version,JSON.stringify({case:'double click starts',getUserMediaRequests:requests,liveStreamsAfterStop:c.active.filter(x=>x.live).length,recordState:c.run('recordState'),sessionIsNull:c.run('recordingSession===null')}));
 const d=setup(source);const start=d.element('#record').listeners.click();d.pending.shift()();await start; const importEnabled=!d.element('#pick-file').disabled;await d.run('transcribeBlob(new Blob(["audio"]))');
 console.log(version,JSON.stringify({case:'import while recording',importEnabled,liveStreamsAfterImport:d.active.filter(x=>x.live).length,recordState:d.run('recordState'),sessionIsNull:d.run('recordingSession===null')}));
 const e=setup(source);e.run('livePreview=true');e.element('#set-live-preview').checked=false;await e.element('#save-settings').listeners.click();
 console.log(version,JSON.stringify({case:'save disable preview',checkbox:e.element('#set-live-preview').checked,livePreview:e.run('livePreview')}));
}}
)();
