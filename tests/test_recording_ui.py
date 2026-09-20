"""Exercise browser capture handlers with deferred permissions and fake audio.

Only resources are mocked: the controller and WAV encoder come from app.js.
No microphone, clipboard, model or personal configuration is accessed.
"""
import shutil
import subprocess
import unittest
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "src/aparte/assets"
NODE = shutil.which("node")
HARNESS = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
const controller = source.split('/* ---------- Drawers ---------- */')[0];
const updates = source.split('/* ---------- Mise à jour ---------- */')[1].split('let lastHealth')[0];
const elements = new Map();
class Element {
  constructor() {
    this.value = ''; this.checked = false; this.handlers = {}; this.files = [];
    this.classes = new Set(); this.attributes = {};
    this.classList = {
      add: (...v) => v.forEach(k => this.classes.add(k)),
      remove: (...v) => v.forEach(k => this.classes.delete(k)),
      toggle: (k, on) => on ? this.classes.add(k) : this.classes.delete(k),
    };
  }
  querySelector(selector) { return get(selector); }
  setAttribute(k, v) { this.attributes[k] = v; }
  addEventListener(name, fn) { this.handlers[name] = fn; }
  click() { return this.handlers.click?.(); }
}
const get = selector => {
  if (!elements.has(selector)) elements.set(selector, new Element());
  return elements.get(selector);
};
const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => { resolve=a; reject=b; }); return {promise,resolve,reject}; };
const events = {};
const timers = new Map(); let timerId = 0;
let permissionCalls = 0, trackStops = 0, contexts = 0, closes = 0, disconnects = 0;
let failAt = '', closing = () => Promise.resolve(), lastProcessor;
const stream = {getTracks: () => [{stop: () => {trackStops++;}}]};
let permission = () => Promise.resolve(stream);
const node = () => ({connect() {if (failAt === 'connect') throw Error('connect');}, disconnect() {disconnects++;}});
class FakeAudioContext {
  constructor() {contexts++; if (failAt === 'constructor') throw Error('constructor'); this.sampleRate = 16000; this.destination = {};}
  createMediaStreamSource() {if (failAt === 'source') throw Error('source'); return node();}
  createScriptProcessor() {if (failAt === 'processor') throw Error('processor'); lastProcessor=node(); return lastProcessor;}
  close() {closes++; return closing();}
}
let requests = [];
let respond = async () => ({ok:true, json:async () => ({text:'final transcript'})});
const ctx = {
  console, Blob, ArrayBuffer, DataView, Int16Array, Float32Array, TextDecoder,
  AudioContext: FakeAudioContext,
  document: {querySelector:get, querySelectorAll:() => [], documentElement:{}},
  navigator: {language:'fr', mediaDevices:{getUserMedia() {permissionCalls++;return permission();}}},
  window: {addEventListener: (name, fn) => {events[name]=fn;}},
  localStorage: {getItem:() => 'fr'},
  setTimeout(fn) {const id=++timerId;timers.set(id,fn);return id;},
  clearTimeout(id) {timers.delete(id);},
  fetch: (url, opts) => {requests.push({url,opts});return respond(url,opts);},
  loadRecovery() {}, recordRecent() {}, escapeHtml:s => s,
};
vm.createContext(ctx);
vm.runInContext(controller + updates, ctx);
const run = code => vm.runInContext(code, ctx);
const click = () => get('#record').handlers.click();
const file = () => {get('#file').files=[new Blob(['audio'])];return get('#file').handlers.change();};
const flush = async () => {for(let i=0;i<8;i++) await Promise.resolve();};
'''


@unittest.skipUnless(NODE, "Node is required for the JavaScript controller tests")
class RecordingUiTest(unittest.TestCase):
    def check_js(self, body):
        result = subprocess.run(
            [NODE, "-e", HARNESS + "\n(async () => {\n" + body +
             "\n})().catch(err => { console.error(err); process.exitCode = 1; });", str(ASSETS / "app.js")],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_delayed_permission_excludes_second_start_and_import(self):
        self.check_js(r'''
const grant=deferred(); permission=()=>grant.promise;
const first=click(); await click(); await file();
assert.equal(permissionCalls,1); assert.equal(run('recordState'),'opening');
assert.equal(get('#record').disabled,true); assert.equal(get('#record').classes.has('recording'),false);
assert.equal(get('#pick-file').disabled,true); assert.equal(requests.length,0);
grant.resolve(stream);await first;
assert.equal(run('recordState'),'recording'); assert.equal(get('#record').disabled,false);
await file(); assert.equal(requests.length,0);assert.equal(get('#file').value,'');
events.pagehide(); await flush();assert.equal(trackStops,1);
''')

    def test_stopping_excludes_start_import_and_releases_tracks_before_close(self):
        self.check_js(r'''
await click();const close=deferred(); closing=()=>close.promise;
const stop=click();await click();await file();
assert.equal(run('recordState'),'stopping');assert.equal(trackStops,1);
assert.equal(permissionCalls,1);assert.equal(requests.length,0);
close.resolve();await stop;
assert.equal(run('recordState'),'idle');assert.equal(requests.length,1);
assert.equal(get('#editor').value,'final transcript');
assert.equal(closes,1);assert.equal(disconnects,2);
''')

    def test_partial_initialization_failure_releases_every_acquired_resource(self):
        self.check_js(r'''
for (const stage of ['constructor','source','processor','connect']) {
  failAt=stage;const stopsBefore=trackStops, closesBefore=closes;
  await click();assert.equal(run('recordState'),'idle');
  assert.equal(trackStops,stopsBefore+1);
  assert.equal(closes,closesBefore+(stage==='constructor'?0:1));
  assert.equal(get('#record').disabled,false);
}
''')

    def test_stop_is_idempotent(self):
        self.check_js(r'''
const session=await ctx.startWavRecording();
const a=session.stop(),b=session.stop(); assert.equal(a,b); await a;
await session.cancel();assert.equal(trackStops,1);assert.equal(closes,1);

''')

    def test_captured_samples_are_transcribed_when_context_close_rejects_or_throws(self):
        self.check_js(r'''
for (const failsAsync of [true,false]) {
  await click();
  lastProcessor.onaudioprocess({inputBuffer:{getChannelData:()=>new Float32Array([0.5,-0.5,1])}});
  const stopsBefore=trackStops;
  closing=()=> {if(failsAsync) return Promise.reject(Error('already closed')); throw Error('already closed');};
  const finished=click();
  assert.equal(trackStops,stopsBefore+1); // Libération avant toute attente.
  await finished;
  assert.equal(run('recordState'),'idle');
  assert.equal(get('#editor').value,'final transcript');
  const blob=requests.at(-1).opts.body;
  assert.equal(blob.type,'audio/wav');
  const wav=new DataView(await blob.arrayBuffer());
  assert.equal(wav.getUint32(40,true),6);
  assert.equal(wav.getInt16(44,true),16383);
  assert.equal(wav.getInt16(46,true),-16384);
  assert.equal(wav.getInt16(48,true),32767);
}
assert.equal(requests.length,2);
''')

    def test_permission_denied_allows_new_attempt(self):
        self.check_js(r'''
permission=()=>Promise.reject(Error('denied'));await click();
assert.equal(run('recordState'),'idle');assert.equal(contexts,0);
permission=()=>Promise.resolve(stream);await click();
assert.equal(run('recordState'),'recording');assert.equal(permissionCalls,2);
events.pagehide();
''')

    def test_permission_granted_after_pagehide_never_constructs_audio_context(self):
        self.check_js(r'''
const grant=deferred();permission=()=>grant.promise;
const first=click();events.pagehide();grant.resolve(stream);await first;
assert.equal(trackStops,1);assert.equal(contexts,0);assert.equal(run('recordState'),'idle');
assert.equal(run('recordingSession'),null);assert.equal(timers.size,0);
''')

    def test_pagehide_stops_recording_and_ignores_pending_final_response(self):
        self.check_js(r'''
await click();events.pagehide();await flush();
assert.equal(trackStops,1);assert.equal(closes,1);assert.equal(timers.size,0);
await click();const response=deferred();respond=()=>response.promise;
const final=click();await flush();assert.equal(run('recordState'),'processing');
events.pagehide();get('#editor').value='restored after navigation';
response.resolve({ok:true,json:async()=>({text:'stale final'})});await final;
assert.equal(get('#editor').value,'restored after navigation');assert.equal(run('recordState'),'idle');
''')

    def test_preview_json_resolved_after_stop_cannot_overwrite_final(self):
        self.check_js(r'''
await click();const json=deferred();
respond=async url=>({ok:true,json:()=>url.includes('preview=1')?json.promise:Promise.resolve({text:'final'})});
const tick=[...timers.values()][0]();await flush();
await click();assert.equal(get('#editor').value,'final');
json.resolve({text:'obsolete preview'});await tick;
assert.equal(get('#editor').value,'final');assert.equal(run('previewing'),false);
''')

    def test_update_and_capture_are_mutually_exclusive(self):
        self.check_js(r'''
await click();await ctx.runUpdate();
assert.equal(requests.length,0);assert.equal(get('#update-note').textContent,'update.capture_busy');
events.pagehide();await flush();
const response=deferred();respond=()=>response.promise;
const updating=ctx.runUpdate();await click();await file();
assert.equal(permissionCalls,1);assert.equal(requests.length,1);
assert.equal(get('#record').disabled,true);assert.equal(get('#pick-file').disabled,true);
response.reject(Error('update failed'));await updating;
assert.equal(get('#record').disabled,false);assert.equal(get('#pick-file').disabled,false);
''')

    def test_two_import_events_only_submit_once_and_input_can_be_reused(self):
        self.check_js(r'''
const response=deferred();respond=()=>response.promise;
const first=file();await file();await click();
assert.equal(requests.length,1);assert.equal(permissionCalls,0);assert.equal(get('#file').value,'');
response.resolve({ok:true,json:async()=>({text:'imported'})});await first;
assert.equal(get('#editor').value,'imported');assert.equal(run('recordState'),'idle');
''')


if __name__ == "__main__":
    unittest.main()
