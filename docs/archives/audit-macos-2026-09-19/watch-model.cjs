// Execute the actual polling function in an isolated VM, no browser or network.
const fs = require('fs'), vm = require('vm');
const source = fs.readFileSync('src/aparte/assets/app.js', 'utf8');
const start = source.indexOf('async function watchModel()');
const end = source.indexOf('/* ---------- Init', start);
const scheduled = [];
const state = { calls: 0, downloadBlocked: false };
const context = {
  setTimeout(fn) { scheduled.push(fn); },
  renderModelState(data) { state.downloadBlocked = data.state === 'downloading'; },
  async fetch() {
    state.calls++;
    if (state.calls === 1) return { ok: true, json: async () => ({ state: 'downloading' }) };
    throw new Error('transient request failure');
  }
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);
(async () => {
  await context.watchModel();
  await scheduled.shift()();
  console.log(JSON.stringify({ ...state, pendingTimers: scheduled.length }));
})();
