"""Recovery interactions without a microphone, browser, or personal state.

Node is optional, as with the project's other optional tools. The actual recovery
controller runs in a small DOM stub; browser layout is checked separately.
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
const block = source.split('/* ---------- Récupération après un échec ---------- */')[1]
  .split('/* ---------- Mise à jour ---------- */')[0];
const elements = new Map();
class Element {
  constructor() { this.children = []; this.dataset = {}; this.value = ''; this.handlers = {}; }
  appendChild(el) { this.children.push(el); }
  replaceChildren() { this.children = []; }
  setAttribute() {}
  addEventListener(name, fn) { this.handlers[name] = fn; }
  contains(el) { return this.children.includes(el) || this.children.some(c => c.contains(el)); }
  querySelectorAll() { return this.children.flatMap(c => [c, ...c.querySelectorAll()]); }
  focus() { ctx.document.activeElement = this; }
}
const get = selector => {
  if (!elements.has(selector)) elements.set(selector, new Element());
  return elements.get(selector);
};
let confirms = [];
let approve = true;
let calls = [];
let respond = async () => ({ok: true, json: async () => ({entries: []})});
const ctx = {
  console, Date, setInterval() {},
  $: get, editor: get('#editor'), lang: 'fr', previewing: false, recordState: 'idle',
  t: (key, vars) => key + (vars ? JSON.stringify(vars) : ''),
  loadRecent() {}, syncActionState() {}, status() {},
  window: { addEventListener() {}, confirm(message) { confirms.push(message); return approve; } },
  document: { body: {}, hidden: false, addEventListener() {}, createElement: () => new Element() },
  fetch: (url, opts) => { calls.push({url, opts}); return respond(url, opts); },
};
ctx.document.activeElement = ctx.editor;
vm.createContext(ctx);
vm.runInContext(block, ctx);
const run = code => vm.runInContext(code, ctx);
const entry = {id: 'capture-1', created_at: Date.now()/1000, expires_at: Date.now()/1000+3600, has_text: true};
ctx.entry = entry;
run('recoveryEntries = [entry]');
'''


@unittest.skipUnless(NODE, "Node is required for the JavaScript controller tests")
class RecoveryUiTest(unittest.TestCase):
    def check_js(self, body):
        result = subprocess.run(
            [NODE, "-e", HARNESS + "\n(async () => {\n" + body +
             "\n})().catch(err => { console.error(err); process.exitCode = 1; });", str(ASSETS / "app.js")],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_delayed_retry_preserves_edits_and_requires_explicit_replacement(self):
        self.check_js(r'''
let finish;
respond = (url) => url.endsWith('/retry') ? new Promise(resolve => { finish = resolve; })
  : Promise.resolve({ok: true, json: async () => ({entries: [entry]})});
ctx.editor.value = 'original';
const pending = ctx.actOnRecovery('retry', entry.id);
ctx.editor.value = 'edited while waiting';
await ctx.actOnRecovery('retry', entry.id);
assert.equal(calls.filter(c => c.url.endsWith('/retry')).length, 1);
finish({ok: true, json: async () => ({text: 'recovered text'})});
await pending;
assert.equal(ctx.editor.value, 'edited while waiting');
assert.equal(get('#recovery-text').value, 'recovered text');
approve = false;
get('#open-recovery').handlers.click();
assert.equal(ctx.editor.value, 'edited while waiting');
approve = true;
get('#open-recovery').handlers.click();
assert.equal(ctx.editor.value, 'recovered text');
assert.equal(confirms.length, 2);
assert.ok(calls.every(c => !/copy|paste/.test(c.url)));
''')

    def test_raw_text_skips_polishing_without_touching_editor(self):
        self.check_js(r'''
respond = async url => ({ok: true, json: async () => url.endsWith('/retry')
  ? {text: 'raw dictation'} : {entries: [entry]}});
ctx.editor.value = 'keep';
await ctx.actOnRecovery('raw', entry.id);
const request = calls.find(c => c.url.endsWith('/retry'));
assert.deepEqual(JSON.parse(request.opts.body), {id: entry.id, raw: true});
assert.equal(ctx.editor.value, 'keep');
assert.equal(get('#recovery-text').value, 'raw dictation');
''')

    def test_http_errors_are_local_and_do_not_expose_response(self):
        self.check_js(r'''
for (const [status, key] of [[409, 'busy'], [410, 'expired'], [400, 'invalid'], [500, 'failed']]) {
  respond = async url => url.endsWith('/retry') ? {ok: false, status,
    text: async () => { throw new Error('private response must not be read'); }}
    : {ok: true, json: async () => ({entries: [entry]})};
  await ctx.actOnRecovery('retry', entry.id);
  assert.equal(get('#recovery-status').textContent, 'recovery.' + key);
  assert.equal(get('#recovery').hidden, false);
}
''')

    def test_stale_read_cannot_restore_deleted_entry(self):
        self.check_js(r'''
let finish;
respond = url => url === '/api/recovery' ? new Promise(resolve => { finish = resolve; })
  : Promise.resolve({ok: true});
const reading = ctx.loadRecovery();
await ctx.actOnRecovery('delete', entry.id);
finish({ok: true, json: async () => ({entries: [entry]})});
await reading;
assert.equal(run('recoveryEntries.length'), 0);
assert.equal(get('#recovery-list').children.length, 0);
''')

    def test_declining_delete_or_result_replacement_keeps_data(self):
        self.check_js(r'''
run("recoveryResult = {id: 'old', text: 'unopened recovery'}");
approve = false;
await ctx.actOnRecovery('delete', entry.id);
await ctx.actOnRecovery('retry', entry.id);
get('#dismiss-recovery').handlers.click();
assert.equal(calls.length, 0);
assert.equal(run('recoveryResult.text'), 'unopened recovery');
assert.equal(run('recoveryEntries.length'), 1);
''')

    def test_active_recording_blocks_opening_recovered_result(self):
        self.check_js(r'''
run("recoveryResult = {id: 'old', text: 'recovered'}");
ctx.recordState = 'recording';
ctx.editor.value = 'live preview';
get('#open-recovery').handlers.click();
assert.equal(ctx.editor.value, 'live preview');
assert.equal(confirms.length, 0);
assert.equal(get('#recovery-status').textContent, 'recovery.editor_busy');
''')


if __name__ == "__main__":
    unittest.main()
