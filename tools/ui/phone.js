/* Phone-width check (run at 390 px wide by tools/ui_test.py): every page loads without errors and without sideways
   scrolling, signed out and signed in. Resolves to {ok, log}. */
(async function () {
  const log = [], bad = [];
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function until(fn, what, ms) {
    const end = Date.now() + (ms || 20000);
    while (Date.now() < end) { try { const v = fn(); if (v) return v; } catch (e) {} await sleep(150); }
    throw new Error('timed out waiting for: ' + what);
  }
  const $ = (s) => document.querySelector(s), $$ = (s) => Array.from(document.querySelectorAll(s));
  function type(input, value) {
    input.focus(); input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true })); input.dispatchEvent(new Event('change', { bubbles: true }));
  }
  async function check(hash, ready) {
    if (location.hash !== hash) window.UI_READY = false;  // the old page stays until the router runs
    location.hash = hash;
    await until(() => window.UI_READY && location.hash === hash && (!ready || ready()), hash, 30000);
    await sleep(500);
    const w = document.documentElement.scrollWidth, vw = window.innerWidth;
    const wide = $$('body *').filter((e) => { const r = e.getBoundingClientRect(); return r.width && r.right > vw + 1; })
      .slice(0, 3).map((e) => e.tagName.toLowerCase() + '.' + String(e.className).split(' ').slice(0, 2).join('.'));
    if (w > vw + 1) bad.push(hash + ' scrolls sideways (' + w + ' > ' + vw + ') ' + wide.join(' '));
    log.push((w > vw + 1 ? 'WIDE ' : 'ok   ') + hash + ' (' + w + ')');
  }
  async function adminIn() {  /* the console is owner-only: sign in as the ADMIN_EMAILS account (made on first run) */
    const fields = () => $$('.au-card input[type=text], .au-card input[type=email], .au-card input[type=password]').filter((i) => i.offsetParent);
    const pw = 'Hb-local-admin-Kq7-2026';
    if (location.hash !== '#auth') window.UI_READY = false;
    location.hash = '#auth';
    await until(() => window.UI_READY && (location.hash === '#home' || fields().length >= 2), 'sign-in page', 60000);
    if (location.hash === '#home') return;
    type(fields()[0], 'arkulinskis@gmail.com'); type(fields()[1], pw);
    $$('.anvil-role-btn-block button').find((b) => b.offsetParent && /Sign in/.test(b.textContent)).click();
    const end = Date.now() + 8000;
    while (Date.now() < end && location.hash !== '#home') await sleep(200);
    if (location.hash !== '#home') {
      $$('.au-card .ui-seg button').find((b) => /Create account/.test(b.textContent)).click();
      await sleep(500);
      const i = fields(); type(i[0], 'Local Admin'); type(i[1], 'arkulinskis@gmail.com'); type(i[2], pw);
      const tick = $('.au-card input[type=checkbox]'); if (tick && !tick.checked) tick.click();
      $$('.anvil-role-btn-block button').find((b) => b.offsetParent && /Create account/.test(b.textContent)).click();
    }
    await until(() => location.hash === '#home' && window.UI_READY && document.querySelector('.ie-pc'), 'signed in as the owner', 60000);
  }
  try {
    for (const h of ['#landing', '#auth', '#auth/signup']) await check(h);  // add the app's public pages
    await adminIn();
    for (const h of ['#home', '#try', '#keys', '#styles', '#setup', '#job/job_demo0001', '#profile', '#admin/overview']) await check(h);  // add every member page
    log.push(bad.length ? 'PROBLEMS: ' + bad.join(' | ') : 'PASSED');
    return { ok: !bad.length, log: log };
  } catch (e) {
    log.push(String(e && e.message || e));
    return { ok: false, log: log };
  }
})();
