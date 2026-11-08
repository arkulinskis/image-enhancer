// Drive headless Chrome over the DevTools protocol: load a URL, run steps, log console + exceptions.
// node tools/live/drive.mjs <url> <steps.json> <outdir>   (outdir gets log.txt, screenshots and a fresh Chrome profile)
// steps: [{wait: ms} | {eval: "js"} | {shot: "name", full: true} | {waitFor: "js expr", timeout: ms}]
// env WINDOW="390,844" sets the window size (default 1280,1000); SCALE=2 takes full-page shots at 2x pixels.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const [url, stepsFile, outDir] = process.argv.slice(2);
// "$TEST_PASSWORD" in a steps file is replaced by the test account's password (tools/live/.test-account-password.txt).
const pwFile = new URL('./.test-account-password.txt', import.meta.url);
const testPw = fs.existsSync(pwFile) ? fs.readFileSync(pwFile, 'utf8').trim() : '';
// (the generated password only uses letters, digits, "-" and "_", so it is safe inside a JSON string)
const steps = JSON.parse(fs.readFileSync(stepsFile, 'utf8').split('$TEST_PASSWORD').join(testPw));
fs.mkdirSync(outDir, { recursive: true });
const port = process.env.CDP_PORT ? +process.env.CDP_PORT : 9300 + Math.floor(Math.random() * 500);
const chrome = process.env.CDP_PORT ? { kill() {} } : spawn('C:/Program Files/Google/Chrome/Application/chrome.exe', [
  '--headless=new', '--disable-gpu', `--remote-debugging-port=${port}`, `--user-data-dir=${path.resolve(outDir, 'profile')}`,
  `--window-size=${process.env.WINDOW || '1280,1000'}`, '--no-first-run', '--disable-extensions', 'about:blank'], { stdio: 'ignore' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const log = [];
const say = s => { log.push(s); console.log(s); };

let ws, id = 0; const pending = new Map();
function send(method, params = {}) {
  return new Promise((res, rej) => { const i = ++id; pending.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })); });
}
async function evaluate(expr) {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) return 'EVAL ERROR: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text);
  return r.result.value;
}
try {
  let target;
  for (let i = 0; i < 150 && !target; i++) {
    try { const list = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); target = list.find(t => t.type === 'page'); if (!target && i > 10) target = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: 'PUT' })).json(); } catch (e) { if (i % 25 === 24) say('[wait] ' + e.message + ' ' + (e.cause && e.cause.code)); }
    if (!target) await sleep(200);
  }
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener('open', r));
  ws.addEventListener('message', ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(m.error.message)) : p.res(m.result); return; }
    if (m.method === 'Runtime.consoleAPICalled') {
      const text = m.params.args.map(a => a.value ?? a.description ?? a.type).join(' ');
      if (!/JQMIGRATE|Message not recognised|Service Worker/.test(text)) say(`[console.${m.params.type}] ${text}`);
    } else if (m.method === 'Runtime.exceptionThrown') {
      const d = m.params.exceptionDetails; say(`[EXCEPTION] ${d.exception?.description || d.text}`);
    } else if (m.method === 'Log.entryAdded') {
      const e = m.params.entry; if (e.level === 'error') say(`[log.${e.level}] ${e.text} ${e.url || ''}`);
    }
  });
  await send('Runtime.enable'); await send('Log.enable'); await send('Page.enable');
  try { await send('Network.enable'); await send('Network.setBypassServiceWorker', { bypass: true }); } catch (e) {}  // Anvil's service worker breaks reused headless profiles
  if (process.env.MOBILE) {  // true phone size (headless windows can't be narrower than ~500 px)
    const [mw, mh] = process.env.MOBILE.split(',').map(Number);
    await send('Emulation.setDeviceMetricsOverride', { width: mw, height: mh, deviceScaleFactor: 2, mobile: true });
    await send('Emulation.setTouchEmulationEnabled', { enabled: true });
  }
  await send('Page.navigate', { url });
  for (const st of steps) {
    if (st.wait) await sleep(st.wait);
    if (st.waitFor) {
      const end = Date.now() + (st.timeout || 15000); let ok = false;
      while (Date.now() < end) { if (await evaluate(`!!(${st.waitFor})`) === true) { ok = true; break; } await sleep(300); }
      say(`[waitFor] ${st.waitFor} -> ${ok ? 'ok' : 'TIMEOUT'}`);
    }
    if (st.eval) say(`[eval] ${JSON.stringify(await evaluate(st.eval))}`.slice(0, 60000));
    if (st.shot) {
      let opts = { format: 'png' };
      if (st.full) {
        const m = await send('Page.getLayoutMetrics');
        const [w] = (process.env.MOBILE || process.env.WINDOW || '1280,1000').split(',').map(Number);
        const h = Math.min(6000, Math.ceil(m.cssContentSize.height));
        await send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: Number(process.env.SCALE || 1), mobile: !!process.env.MOBILE || w < 600 });
        await sleep(300);
        opts = { format: 'png', captureBeyondViewport: true, clip: { x: 0, y: 0, width: w, height: h, scale: 1 } };
      }
      const r = await send('Page.captureScreenshot', opts);
      if (st.full && process.env.MOBILE) { const [mw, mh] = process.env.MOBILE.split(',').map(Number); await send('Emulation.setDeviceMetricsOverride', { width: mw, height: mh, deviceScaleFactor: 2, mobile: true }); }
      else if (st.full) await send('Emulation.clearDeviceMetricsOverride');
      fs.writeFileSync(path.join(outDir, st.shot + '.png'), Buffer.from(r.data, 'base64')); say(`[shot] ${st.shot}`);
    }
  }
} catch (e) { say('[driver error] ' + e.stack); }
fs.writeFileSync(path.join(outDir, 'log.txt'), log.join('\n'));
chrome.kill(); process.exit(0);
