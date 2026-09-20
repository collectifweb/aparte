"""Real JS functions, fake network and clipboard; no personal device used."""
import shutil
import subprocess
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / 'src/aparte/assets/app.js'
NODE = shutil.which('node')

@unittest.skipUnless(NODE, 'Node required')
class MacUiTest(unittest.TestCase):
    def check(self, script):
        prefix = "const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');const source=fs.readFileSync(process.argv[1],'utf8');\n"
        result = subprocess.run([NODE, '-e', prefix + script, str(APP)], text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_polling_recovers_from_transient_error_and_observes_native_retry(self):
        self.check(r'''
const timers=new Map();let next=0,calls=0;const rendered=[];
const ctx={modelDownloading:true, t:x=>x, $:()=>({}),
clearTimeout:id=>timers.delete(id),setTimeout:fn=>{timers.set(++next,fn);return next;},
renderModelState:data=>{rendered.push(data.state);ctx.modelDownloading=data.state==='downloading';},
fetch:async()=>{calls++;if(calls===2)throw Error('temporary');return {ok:true,status:200,json:async()=>({state:calls===1?'downloading':'ready'})};}};
vm.createContext(ctx);vm.runInContext(source.slice(source.indexOf('let modelWatchTimer'),source.indexOf('/* ---------- Init')),ctx);
(async()=>{await ctx.watchModel();assert.equal(timers.size,1);
await [...timers.values()][0]();assert.equal(timers.size,1);
await [...timers.values()][0]();assert.deepEqual(rendered,['downloading','ready']);assert.equal(ctx.modelDownloading,false);
assert.equal(timers.size,1);})().catch(e=>{console.error(e);process.exitCode=1;});
''')

    def test_mac_copy_uses_browser_clipboard_without_waiting_for_http(self):
        self.check(r'''
let handler,copied=[],http=0;
const ctx={systemClipboard:false,editor:{value:'Texte français'},status(){},t:x=>x,
$:()=>({addEventListener:(_n,fn)=>{handler=fn;}}),
navigator:{clipboard:{writeText:text=>{copied.push(text);return Promise.resolve();}}},
postJson:()=>{http++;throw Error('must not call native route');}};
vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('$("#copy").addEventListener'),source.indexOf('$("#paste").addEventListener')),ctx);
(async()=>{const done=handler();assert.deepEqual(copied,['Texte français']);await done;assert.equal(http,0);})().catch(e=>{console.error(e);process.exitCode=1;});
''')

    def test_model_banner_recovers_and_success_stays_dismissed(self):
        self.check(r'''
const timers=new Map(),elements=new Map();let next=0;
function $(key){if(!elements.has(key))elements.set(key,{hidden:false,textContent:'',style:{},
classList:{toggle(){}},setAttribute(){},removeAttribute(){}});return elements.get(key);}
const ctx={$,t:x=>x,lang:'fr',syncActionState(){},modelDownloading:false,
clearTimeout:id=>timers.delete(id),setTimeout:fn=>{timers.set(++next,fn);return next;}};
vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('const modelNotice'),source.indexOf('let modelWatchTimer')),ctx);
ctx.renderModelState({state:'downloading'});
vm.runInContext('modelReconnecting=true',ctx);$('#model-line').textContent='reconnecting';
ctx.renderModelState({state:'downloading'});assert.equal($('#model-line').textContent,'model.downloading');
ctx.renderModelState({state:'ready'});const completion=[...timers.keys()][0];
ctx.renderModelState({state:'ready'});assert.equal([...timers.keys()][0],completion);
timers.get(completion)();timers.delete(completion);assert.equal($('#model-notice').hidden,true);
ctx.renderModelState({state:'ready'});assert.equal($('#model-notice').hidden,true);
ctx.renderModelState({state:'downloading'});assert.equal($('#model-notice').hidden,false);
ctx.renderModelState({state:'ready'});assert.equal(timers.size,1);
ctx.renderModelState({state:'downloading'});assert.equal(timers.size,0);
''')
