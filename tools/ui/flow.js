/* The main journeys, run inside the real app (Anvil App Server) by tools/ui_test.py through tools/live/drive.mjs.
   Resolves to {ok, log}. Keep log lines ASCII (the Windows console).
   1. a visitor: About page, members-only redirect, sign-up -> the "private console" note, sign out
   2. the owner (ADMIN_EMAILS account): Queue, a new API key, the HTTP API called with it (styles, a picture sent as
      JSON, its status + ETA), the PC away -> "asking again" state, the job page + cancel, the test bench (style chips,
      fidelity, a real file upload, send), Styles edit + reset, Connect (API address, code samples, settings),
      key edit / switch off / replace / delete, the theme switch, sign out. */
(async function () {
  const log = [], t0 = Date.now();
  const say = (m) => log.push(((Date.now() - t0) / 1000).toFixed(1) + 's ' + m);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function until(fn, what, ms) {
    const end = Date.now() + (ms || 20000);
    while (Date.now() < end) { try { const v = fn(); if (v) return v; } catch (e) {} await sleep(150); }
    throw new Error('timed out waiting for: ' + what);
  }
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const vis = (e) => e && e.getBoundingClientRect().width > 0;
  const norm = (s) => String(s || '').trim().replace(/\s+/g, ' ');
  const byText = (sel, text) => $$(sel).find((e) => vis(e) && norm(e.textContent) === text);
  async function click(sel, text) {
    const el = await until(() => (text ? byText(sel, text) : $$(sel).find(vis)), sel + (text ? ' "' + text + '"' : ''));
    el.scrollIntoView({ block: 'center' });
    el.click();
    return el;
  }
  function type(input, value) {
    input.focus();
    input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }
  async function page(hash, ready, what) {
    if (location.hash !== hash) window.UI_READY = false;  // the old page stays until the router runs
    location.hash = hash;
    await until(() => window.UI_READY && location.hash === hash && ready(), what || hash, 30000);
    await sleep(300);
  }
  const ok = (cond, msg) => { if (!cond) throw new Error('FAILED: ' + msg); say('ok   ' + msg); };
  const fields = () => $$('.au-card input[type=text], .au-card input[type=email], .au-card input[type=password]').filter((i) => i.offsetParent);
  async function signOut() {
    await click('.anvil-role-avatar button');
    await click('.ui-menu button', 'Sign out');
    await until(() => location.hash === '#landing' && window.UI_READY && $('.ui-header .ui-btn.primary'), 'signed out');
  }
  async function adminIn() {
    const pw = 'Hb-local-admin-Kq7-2026';
    await page('#auth', () => fields().length >= 2);
    type(fields()[0], 'arkulinskis@gmail.com'); type(fields()[1], pw);
    $$('.anvil-role-btn-block button').find((b) => vis(b) && /Sign in/.test(b.textContent)).click();
    const end = Date.now() + 8000;
    while (Date.now() < end && location.hash !== '#home') await sleep(200);
    if (location.hash !== '#home') {  // no owner account in this local database yet: make it
      $$('.au-card .ui-seg button').find((b) => /Create account/.test(b.textContent)).click();
      await sleep(500);
      const i = fields(); type(i[0], 'Local Admin'); type(i[1], 'arkulinskis@gmail.com'); type(i[2], pw);
      const tick = $('.au-card input[type=checkbox]'); if (tick && !tick.checked) tick.click();
      $$('.anvil-role-btn-block button').find((b) => vis(b) && /Create account/.test(b.textContent)).click();
    }
    await until(() => location.hash === '#home' && window.UI_READY && vis($('.ie-pc')), 'signed in as the owner', 60000);
  }
  function pngDataUrl(w, h, hue) {
    const c = document.createElement('canvas'); c.width = w; c.height = h;
    const g = c.getContext('2d');
    g.fillStyle = 'hsl(' + hue + ',60%,70%)'; g.fillRect(0, 0, w, h);
    g.fillStyle = '#e2533a'; g.beginPath(); g.moveTo(w * .2, h * .6); g.lineTo(w * .5, h * .25); g.lineTo(w * .8, h * .6); g.fill();
    g.fillStyle = '#3a704a'; g.fillRect(0, h * .7, w, h * .3);
    return c.toDataURL('image/png');
  }
  async function api(method, path, key, body) {
    const r = await fetch(location.origin + '/_/api/v1' + path, {
      method, headers: Object.assign({ Authorization: 'Bearer ' + key }, body ? { 'Content-Type': 'application/json' } : {}),
      body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, data: await r.json() };
  }

  try {
    // ---------------------------------------------------------------- 1. a visitor
    await page('#landing', () => $('.lp-hero'), 'landing');
    ok($('.lp-hero a[href="#auth/signup"]'), 'landing: hero with the owner sign-up link');
    ok($('.ie-tray svg.dev-flat') && $('.ie-tray svg.dev-paint'), 'landing: the developing-print hero');
    ok($('.ui-header .ui-btn.primary') && /Sign in/.test($('.ui-header .ui-btn.primary').textContent), 'landing: Sign in in the header');
    ok($$('.lp-styles > div').length === 10, 'landing: the ten styles');
    await page('#profile', () => true);
    await until(() => window.UI_READY && $$('.au-card input').length >= 2, 'redirected to sign in');
    ok(true, 'a members-only page asks visitors to sign in');
    await click('.au-card .ui-seg button', 'Create account');
    await until(() => fields().length >= 3, 'sign-up form');
    type(fields()[0], 'Curious Visitor'); type(fields()[1], 'visitor' + Date.now() + '@example.com'); type(fields()[2], 'Hb-' + Math.random().toString(36).slice(2) + '-Kq7');
    const tick = $('.au-card input[type=checkbox]'); if (tick && !tick.checked) tick.click();
    await click('.anvil-role-btn-block button', 'Create account');
    await until(() => location.hash === '#profile' && window.UI_READY && $('.pf-grid'), 'back on the page they wanted', 40000);
    await page('#home', () => $('.ie-private'));
    ok(vis($('.ie-private')) && !vis($('.ie-pc')), 'a non-owner account sees "this console is private", nothing else');
    ok(!$$('.ui-nav .nav-link').length, 'a non-owner has no console menu');
    location.hash = '#keys';
    await until(() => location.hash === '#home' && window.UI_READY && vis($('.ie-private')), 'sent back from an owner-only page');
    ok(true, 'owner-only pages send others back');
    await signOut();

    // ---------------------------------------------------------------- 2. the owner
    await adminIn();
    ok($$('.ui-nav .nav-link').length === 5, 'owner: the console menu (Queue, Test bench, Apps & keys, Styles, Connect)');
    ok(/PC|queue/.test($('.anvil-role-ie-pc-state').textContent), 'queue: the PC panel');
    await until(() => $$('.ie-job.recent').length >= 1, 'demo history');
    ok($$('.ie-job.recent img').length >= 2, 'queue: recent jobs show before and after thumbnails');

    // a new API key
    await page('#keys', () => $('.anvil-role-ic-plus'));
    const appName = 'Flow App ' + Date.now().toString(36);
    await click('.anvil-role-ic-plus button');
    const nameBox = await until(() => $('.ie-keyedit input'), 'new key dialog');
    type(nameBox, appName);
    await click('.ie-keyedit .anvil-role-btn-primary button');
    const keyLabel = await until(() => $$('.ie-keymade .anvil-role-ie-code').find((e) => /^ie_/.test(norm(e.textContent))), 'the key, shown once');
    const KEY = norm(keyLabel.textContent);
    ok(KEY.length === 43 && /whsec_/.test($('.ie-keymade').textContent), 'keys: a new key + webhook secret, shown once');
    await click('.ie-keymade .anvil-role-btn-primary button');
    await until(() => !vis($('.ie-keymade')) && $$('.ie-key').some((r) => r.textContent.includes(appName)), 'the key in the list');
    ok(true, 'keys: the new app is listed');

    // the HTTP API with that key
    let r = await api('GET', '/styles', KEY);
    ok(r.status === 200 && r.data.styles.length === 10 && r.data.styles[0].key === 'kids_book', 'API: GET /styles with the key');
    r = await api('GET', '/styles', 'ie_wrongwrongwrongwrongwrong');
    ok(r.status === 401 && /Unknown API key/.test(r.data.error), 'API: a wrong key is refused');
    r = await api('POST', '/jobs', KEY, { image: pngDataUrl(400, 300, 200), style: 'scifi', ref: 'flow-1', fidelity: 'strict', prompt: 'add two moons' });
    ok(r.status === 202 && /^job_/.test(r.data.job.id) && r.data.job.status === 'queued', 'API: POST /jobs queues a picture (202)');
    const JOB = r.data.job.id;
    r = await api('POST', '/jobs', KEY, { image: pngDataUrl(30, 30, 10), style: 'scifi' });
    ok(r.status === 400 && /64 px/.test(r.data.error), 'API: a tiny picture is refused with a reason');
    r = await api('GET', '/jobs/' + JOB, KEY);
    ok(r.status === 200 && r.data.job.ref === 'flow-1' && r.data.job.position >= 1 && r.data.job.source_url, 'API: GET /jobs/<id> has the position and links');
    // no PC is connected locally: the dispatcher finds nobody and schedules the next try
    let away = null;
    for (let i = 0; i < 40 && !away; i++) { const q = await api('GET', '/jobs/' + JOB, KEY); if (q.data.job.next_try_at) away = q.data.job; else await sleep(1500); }
    ok(away && away.status === 'queued' && away.eta_seconds > 600, 'no PC: the job waits, next try about 15 minutes away, ETA counts it');
    r = await api('GET', '/queue', KEY);
    ok(r.status === 200 && r.data.pc_online === false && r.data.pc_next_try_at && r.data.yours_waiting >= 1, 'API: GET /queue says the PC is away and when it is asked again');

    // the queue page shows it
    await page('#home', () => $$('.ie-job:not(.recent)').length >= 1);
    ok($$('.ie-job:not(.recent)').some((e) => e.textContent.includes(JOB)), 'queue: the API job is waiting');
    ok($('.ie-lamp').getAttribute('data-state') === 'away' && /answering/.test($('.anvil-role-ie-pc-state').textContent), 'queue: lamp + "The PC is not answering"');
    ok(/Asking again at/.test($('.anvil-role-ie-pc-detail').textContent), 'queue: says when it asks again');
    await click('.anvil-role-btn-primary button', 'Ask the PC now');
    await until(() => /Asking the PC now|Nothing is waiting/.test(document.body.textContent), 'kick toast');
    ok(true, 'queue: Ask the PC now');

    // the job page: cancel it
    await page('#job/' + JOB, () => vis($('.ie-ba')));
    ok(/Sci-fi/.test($('.page-job .anvil-role-page-title').textContent) && /add two moons/.test($('.anvil-role-ie-instr').textContent), 'job page: style + the instruction the model gets');
    ok(/exact composition/.test($('.anvil-role-ie-instr').textContent), 'job page: strict fidelity is in the instruction');
    await click('.page-job button', 'Cancel');
    await click('.anvil-modal-content button', 'Cancel it');
    await until(() => /Cancelled/.test($('.page-job .anvil-role-st').textContent), 'cancelled');
    ok(vis(byText('.page-job button', 'Try again')), 'job page: cancel, then Try again is offered');
    r = await api('GET', '/jobs/' + JOB, KEY);
    ok(r.data.job.status === 'cancelled', 'API: the app sees it cancelled');

    // the test bench: a real upload through the FileLoader
    await page('#try', () => $$('.anvil-role-ie-chip').length === 10);
    ok(true, 'test bench: ten style chips');
    await click('.anvil-role-ie-chip button', 'Sci-fi');
    await until(() => byText('.anvil-role-ie-chip button', 'Sci-fi').getAttribute('aria-pressed') === 'true', 'chip pressed');
    ok(true, 'test bench: picking a style marks it (aria-pressed)');
    await click('.page-try .ui-seg button', 'Strict');
    ok(byText('.page-try .ui-seg button', 'Strict').getAttribute('aria-pressed') === 'true', 'test bench: fidelity toggle');
    const blob = await (await fetch(pngDataUrl(512, 384, 120))).blob();
    const dt = new DataTransfer(); dt.items.add(new File([blob], 'flow-drawing.png', { type: 'image/png' }));
    const fileInput = $('.page-try input[type=file]');
    fileInput.files = dt.files; fileInput.dispatchEvent(new Event('change', { bubbles: true }));
    await until(() => vis($('.ie-preview img')) && /flow-drawing\.png/.test($('.page-try').textContent), 'preview');
    ok(true, 'test bench: the chosen picture shows');
    type($$('.page-try input').find((i) => vis(i) && /snow/.test(i.placeholder || '')), 'make it night');
    await click('.page-try .anvil-role-btn-primary button', 'Send to the queue');
    await until(() => vis($('.ie-result')) && /queue|PC/.test($('.ie-result .anvil-role-msg-note').textContent), 'the result box', 30000);
    ok(/job\//.test($('.ie-result a').getAttribute('href')), 'test bench: sent; the result box links to the job');

    // styles: edit + reset
    await page('#styles', () => $$('.ie-style').length === 10);
    const first = $('.ie-style');
    type(first.querySelector('input'), 'Storybook');
    first.querySelector('.anvil-role-btn-primary button').click();
    await until(() => /changed/.test(first.textContent), 'saved');
    ok(true, 'styles: rename and save');
    await until(() => byText('.ie-style button', 'Original words'), 'reset button');
    byText('.ie-style button', 'Original words').click();
    await until(() => first.querySelector('input').value === "Kids' picture book", 'reset');
    ok(true, 'styles: back to the original words');

    // connect page
    await page('#setup', () => $('.ie-steps'));
    ok(/\/_\/api\/v1$/.test(norm($('.page-setup .anvil-role-ie-code').textContent)), 'connect: the app\'s API address');
    ok(!/API_BASE/.test($('.page-setup').textContent) && /\/_\/api\/v1\/jobs/.test($('.page-setup').textContent), 'connect: code samples use the real address');
    const cfg = $$('.ie-cfg input');
    type(cfg[0], '15');
    await click('.page-setup .anvil-role-btn-primary button', 'Save settings');
    await until(() => /Settings saved/.test(document.body.textContent), 'settings saved');
    ok(true, 'connect: settings save');

    // keys: switch off, replace, delete
    await page('#keys', () => $$('.ie-key').some((e) => e.textContent.includes(appName)));
    const row = () => $$('.ie-key').find((e) => e.textContent.includes(appName));
    row().querySelector('.anvil-role-ic-edit button').click();
    const onBox = await until(() => $$('.ie-keyedit input[type=checkbox]').find(vis), 'edit dialog');
    onBox.click();
    await click('.ie-keyedit .anvil-role-btn-primary button');
    await until(() => row() && /Off/.test(row().querySelector('.anvil-role-st').textContent), 'switched off');
    r = await api('GET', '/styles', KEY);
    ok(r.status === 403, 'keys: a switched-off key is refused (403)');
    row().querySelector('.anvil-role-ic-refresh button').click();
    await click('.anvil-modal-content button', 'Replace it');
    const newKey = norm((await until(() => $$('.ie-keymade .anvil-role-ie-code').find((e) => vis(e) && /^ie_/.test(norm(e.textContent)) && norm(e.textContent) !== KEY), 'new key')).textContent);
    await click('.ie-keymade .anvil-role-btn-primary button');
    ok(newKey !== KEY && (await api('GET', '/styles', KEY)).status === 401, 'keys: replacing the key retires the old one');
    await sleep(1200); await until(() => row(), 'list again');
    row().querySelector('.anvil-role-ic-trash button').click();
    await click('.anvil-modal-content button', 'Delete');
    await until(() => !row(), 'deleted');
    ok(true, 'keys: delete');

    // theme + sign out
    await click('.anvil-role-avatar button');
    await click('.ui-menu .ui-seg button', 'Light');
    ok(document.documentElement.getAttribute('data-theme') === 'light', 'menu: Light switches the theme');
    await click('.ui-menu .ui-seg button', 'Dark');
    ok(document.documentElement.getAttribute('data-theme') === 'dark', 'menu: back to Dark (the default)');
    await click('.ui-menu button', 'Sign out');
    await until(() => location.hash === '#landing' && window.UI_READY, 'signed out');
    ok(true, 'sign out');

    say('PASSED');
    return { ok: true, log: log };
  } catch (e) {
    say(String(e && e.message || e));
    return { ok: false, log: log };
  }
})();
