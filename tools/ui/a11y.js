/* Accessibility check (WCAG 2.2 A + AA), run inside the real app by tools/ui_test.py through tools/live/drive.mjs.
   1. axe-core (APP_MAKER/vendor/axe-core, injected by ui_test.py) on every page, signed out and signed in, light and
      dark: a "serious" or "critical" WCAG problem fails the run; smaller ones and best-practice hints are notes.
   2. Keyboard and screen-reader checks on the sign-in page: a real main heading, toggle buttons that say which one is
      on, autocomplete on the fields, the Google logo marked as decoration, errors read out, and the Privacy & Terms page
      keeping Tab inside.
   Add the app's own pages to PUBLIC and MEMBER below, and keyboard checks for its own pickers and forms
   (state.focus_key/refocus keep the focus on a choice when a RepeatingPanel redraws: test that here).
   Resolves to {ok, log}. Keep log lines ASCII (the Windows console). */
(async function () {
  /*AXE*/
  const PUBLIC = ['#landing', '#auth', '#auth/signup'];  // add the app's public pages
  const MEMBER = ['#home', '#try', '#keys', '#styles', '#setup', '#job/job_demo0001', '#profile', '#admin/overview'];                  // add every member page
  const log = [], bad = [];
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function until(fn, what, ms) {
    const end = Date.now() + (ms || 30000);
    while (Date.now() < end) { try { const v = fn(); if (v) return v; } catch (e) {} await sleep(150); }
    throw new Error('timed out waiting for: ' + what);
  }
  const $ = (s) => document.querySelector(s), $$ = (s) => Array.from(document.querySelectorAll(s));
  const vis = (e) => e && e.getBoundingClientRect().width > 0;
  const ascii = (s) => String(s).normalize('NFD').replace(/[^\x20-\x7e]/g, '');
  const ok = (cond, msg) => { if (cond) log.push('ok   ' + msg); else { bad.push(msg); log.push('FAIL ' + msg); } };
  function type(input, value) {
    input.focus(); input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true })); input.dispatchEvent(new Event('change', { bubbles: true }));
  }
  async function page(hash, ready) {
    if (location.hash !== hash) window.UI_READY = false;
    location.hash = hash;
    await until(() => window.UI_READY && location.hash === hash && (!ready || ready()), hash, 60000);
    await sleep(900);
  }
  if (!window.axe) { const s = document.createElement('script'); s.textContent = window.__AXE_SRC; document.head.appendChild(s); }

  async function scan(hash, ready) {
    await page(hash, ready);
    for (const theme of ['light', 'dark']) { window.UI.setTheme(theme); await sleep(900); /* let colour transitions and toasts settle */ await axeRun(hash + ' ' + theme); }
    window.UI.setTheme('auto');
  }
  async function axeRun(hash) {
    const res = await window.axe.run(document, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'] },
    });
    let serious = 0;
    for (const v of res.violations) {
      const wcag = v.tags.some((t) => /^wcag2/.test(t));
      const fail = wcag && (v.impact === 'serious' || v.impact === 'critical');
      const where = v.nodes.slice(0, 2).map((n) => ascii(n.target.join(' ')).slice(0, 70)).join(' | ');
      log.push((fail ? 'FAIL ' : 'note ') + hash + ' ' + v.id + ' (' + v.impact + ', ' + v.nodes.length + 'x): ' + where);
      if (fail) {
        serious++; bad.push(hash + ' ' + v.id);
        for (const n of v.nodes.slice(0, 3)) log.push('       ' + ascii(n.html).replace(/\s+/g, ' ').slice(0, 150) + ' :: ' + ascii((n.failureSummary || '').split(/\n/).slice(1).join(' ')).slice(0, 150));
      }
    }
    if (!serious) log.push('ok   ' + hash + ': no serious WCAG problems (' + res.passes.length + ' rules pass)');
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
    // ---------------------------------------------------------------- the sign-in page
    await page('#auth', () => $$('.au-card input').length >= 2);
    ok(!!$('[role=heading][aria-level="1"]'), 'sign-in: the title is the main heading');
    const tabs = $$('.au-card .ui-seg button');
    ok(tabs.length === 2 && tabs[0].getAttribute('aria-pressed') === 'true' && tabs[1].getAttribute('aria-pressed') === 'false',
      'sign-in: Sign in / Create account say which one is chosen (aria-pressed)');
    ok(!$('.au-card [role=tablist]'), 'sign-in: no half-built tab list (the switch is a group of toggle buttons)');
    ok($$('.au-card input').some((i) => i.autocomplete === 'email') && $$('.au-card input').some((i) => i.autocomplete === 'current-password'),
      'sign-in: email and password have autocomplete');
    const g = $('.anvil-role-au-google img');
    ok(!g || g.getAttribute('alt') === '', 'sign-in: the Google logo is marked as decoration (alt="")');
    $$('.anvil-role-btn-block button').find((b) => vis(b) && /Sign in/.test(b.textContent)).click();  // empty form
    await until(() => $$('.au-card .anvil-role-msg-error').some(vis), 'the error');
    ok($$('.au-card .anvil-role-msg-error').find(vis).getAttribute('role') === 'alert', 'sign-in: the error is read out (role=alert)');
    const tick = $('.au-card input[type=checkbox]') || $('input[type=checkbox]');
    if (tick) {
      // a script's focus() doesn't always count as keyboard focus, so check the app's CSS: no app.css rule may drop the
      // outline of a focused tick box
      const kills = [];
      for (const sh of document.styleSheets) { if (!/app\.css/.test(sh.href || '')) continue; for (const r of sh.cssRules) if (r.selectorText && /:focus/.test(r.selectorText) && /outline:\s*(none|0)/.test(r.cssText) && /input|checkbox/.test(r.selectorText) && !/:not\(\[type=\"?checkbox\"?\]\)/.test(r.selectorText)) kills.push(r.selectorText); }
      ok(!kills.length, 'tick boxes keep their focus ring' + (kills.length ? ' (' + kills.join(', ') + ')' : ''));
    }

    // ---------------------------------------------------------------- Privacy & Terms keeps Tab inside
    const lk = $$('[data-lk-open]').find(vis);
    if (lk) {
      lk.click();
      await until(() => window.LegalKit && window.LegalKit.isOpen(), 'the Privacy page');
      const behind = Array.from(document.body.children).filter((e) => e.id !== 'lk-root' && e.tagName !== 'SCRIPT');
      ok(behind.length && behind.every((e) => e.inert), 'privacy page: the app behind it is inert (Tab stays inside)');
      window.LegalKit.close();
      ok(Array.from(document.body.children).every((e) => !e.inert), 'privacy page: closing it gives the app back');
    }

    // ---------------------------------------------------------------- axe on every page
    for (const h of PUBLIC) await scan(h);
    await adminIn();
    for (const h of MEMBER) await scan(h);
    log.push(bad.length ? 'PROBLEMS: ' + bad.join(' | ') : 'PASSED');
    return { ok: !bad.length, log: log };
  } catch (e) {
    log.push(String(e && e.message || e));
    return { ok: false, log: log };
  }
})();
