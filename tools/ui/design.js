/* Design check on the rendered pages (APP_MAKER/design/README.md), run inside the real app by tools/ui_test.py through
   tools/live/drive.mjs, at desktop (1280) and phone (390) width. It measures what a source scan can't:
   - ban:  a tiny uppercase label right above a heading (eyebrow/kicker), gradient text
   - fail: content still invisible after the page settled, sideways scroll on the page
   - warn: text under 11px (12px for running text), lines over ~85 characters, body text touching the screen edge,
           tight line-height on paragraphs, touch targets under 24px on phone, transition: all, a heading sitting closer
           to the block above than to its own content
   - note: fonts that are on every generated site, touch targets under 44px on phone
   Bans and fails make the run fail; warnings are listed for the facelift to fix (or explain).
   The master copy is APP_MAKER/design/design.js; apps copy it into tools/ui/. Add the app's pages to PUBLIC/MEMBER.
   Resolves to {ok, log}. Keep log lines ASCII (the Windows console). */
(async function () {
  const PUBLIC = ['#landing', '#auth/signup'];  // add the app's public pages
  const MEMBER = ['#home', '#try', '#keys', '#styles', '#setup', '#job/job_demo0001', '#profile', '#admin/overview'];         // add every member page
  const OVERUSED = ['inter', 'roboto', 'plus jakarta sans', 'geist', 'space grotesk', 'fraunces'];
  const phone = window.innerWidth < 600;
  const log = [], bad = [];
  let warns = 0;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function until(fn, what, ms) {
    const end = Date.now() + (ms || 30000);
    while (Date.now() < end) { try { const v = fn(); if (v) return v; } catch (e) {} await sleep(150); }
    throw new Error('timed out waiting for: ' + what);
  }
  const $ = (s) => document.querySelector(s), $$ = (s) => Array.from(document.querySelectorAll(s));
  const ascii = (s) => String(s).normalize('NFD').replace(/[^\x20-\x7e]/g, '').replace(/\s+/g, ' ').trim();
  const cs = (e) => getComputedStyle(e);
  function shown(e) {
    const r = e.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    for (let n = e; n && n !== document.body; n = n.parentElement) {
      const s = cs(n);
      if (s.display === 'none' || s.visibility === 'hidden' || +s.opacity === 0) return false;
      if (n.inert || n.getAttribute('aria-hidden') === 'true') return false;
    }
    return true;
  }
  function name(e) {
    const c = (e.className && typeof e.className === 'string') ? '.' + e.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
    return e.tagName.toLowerCase() + c + ' "' + ascii(e.textContent).slice(0, 30) + '"';
  }
  function ownText(e) { return Array.from(e.childNodes).filter((n) => n.nodeType === 3).map((n) => n.textContent).join('').trim(); }
  function type(input, value) {
    input.focus(); input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true })); input.dispatchEvent(new Event('change', { bubbles: true }));
  }
  async function page(hash, ready) {
    if (location.hash !== hash) window.UI_READY = false;
    location.hash = hash;
    await until(() => window.UI_READY && location.hash === hash && (!ready || ready()), hash, 60000);
    await sleep(1400);  // entrances finish
  }
  function report(level, where, what, items) {
    if (!items.length) return;
    const line = level.toUpperCase().padEnd(4) + ' ' + where + ' ' + what + ' (' + items.length + 'x): ' + items.slice(0, 3).join(' | ');
    log.push(line.slice(0, 400));
    if (level === 'ban' || level === 'fail') bad.push(where + ' ' + what); else if (level === 'warn') warns++;
  }

  function scan(where) {
    const texts = $$('body *').filter((e) => ownText(e).length > 1 && !/^(SCRIPT|STYLE|NOSCRIPT|OPTION|SVG|TEXT|TSPAN|TITLE|CODE|PRE|KBD|SUP|SUB)$/i.test(e.tagName));
    const vis = texts.filter(shown);
    // content hidden at rest (failed reveal)
    const hidden = texts.filter((e) => !shown(e) && e.getBoundingClientRect().width > 0 && +cs(e).opacity === 0 && !e.closest('[aria-hidden=true],[inert],.anvil-spinner,#loadingSpinner'));
    const share = hidden.reduce((n, e) => n + ownText(e).length, 0) / Math.max(1, vis.reduce((n, e) => n + ownText(e).length, 0));
    if (share > 0.25) report('fail', where, 'text still invisible after load', hidden.slice(0, 3).map(name));
    // sideways scroll
    const over = document.documentElement.scrollWidth - window.innerWidth;
    if (over > 1) {
      const wide = $$('body *').filter((e) => shown(e) && e.getBoundingClientRect().right > window.innerWidth + 1).slice(-3);
      report('fail', where, 'page scrolls sideways by ' + over + 'px', wide.map(name));
    }
    const tiny = [], measure = [], edge = [], leading = [], kicker = [], gradient = [], small = [], smallish = [], all = [], fonts = new Set();
    for (const e of vis) {
      const s = cs(e), fs = parseFloat(s.fontSize), txt = ownText(e);
      const running = /^(P|LI|DD|BLOCKQUOTE|FIGCAPTION|TD)$/.test(e.tagName) && txt.length > 60;
      if (fs < 11 || (running && fs < 12)) if (!e.closest('.lk-root,#lk-root,footer,.ui-footer,[class*=legal]') || fs < 10) tiny.push(name(e) + ' ' + fs + 'px');
      if (running) {
        const r = e.getBoundingClientRect(), lh = parseFloat(s.lineHeight) || fs * 1.2;
        if (r.width / (fs * 0.5) > 92 && r.height > lh * 1.8) measure.push(name(e) + ' ~' + Math.round(r.width / (fs * 0.5)) + 'ch');
        if (r.left < (phone ? 12 : 16) || window.innerWidth - r.right < (phone ? 12 : 16)) edge.push(name(e));
        if (lh / fs < 1.3 && r.height > lh * 1.8) leading.push(name(e) + ' ' + (lh / fs).toFixed(2));
      }
      if (s.backgroundClip === 'text' || s.webkitBackgroundClip === 'text' || (s.webkitTextFillColor === 'rgba(0, 0, 0, 0)' && /gradient/.test(s.backgroundImage))) gradient.push(name(e));
      fonts.add(s.fontFamily.split(',')[0].replace(/["']/g, '').trim().toLowerCase());
    }
    // kicker / eyebrow: small, tracked, uppercase line directly above a heading
    for (const h of $$('h1, h2, h3, [role=heading]').filter(shown)) {
      const prev = h.previousElementSibling;
      if (!prev || !shown(prev)) continue;
      const ps = cs(prev), hs = cs(h);
      const t = ascii(prev.textContent);
      if (t && t.length < 48 && parseFloat(ps.fontSize) < parseFloat(hs.fontSize) * 0.6 &&
          (ps.textTransform === 'uppercase' || (t === t.toUpperCase() && /[A-Z]/.test(t))) && parseFloat(ps.letterSpacing || 0) > parseFloat(ps.fontSize) * 0.04)
        kicker.push(name(prev) + ' above "' + ascii(h.textContent).slice(0, 30) + '"');
    }
    // touch targets on phone
    if (phone) {
      for (const e of $$('button, a[href], input:not([type=hidden]), select, textarea, [role=button], [role=tab], [role=link]').filter(shown)) {
        if (e.closest('p, li p, .lk-root, #lk-root') && e.tagName === 'A') continue;  // inline links in text are exempt
        if (cs(e).display === 'inline' && e.parentElement && ownText(e.parentElement).length > 20) continue;  // WCAG 2.5.8 inline exception: a word inside a sentence
        const r = e.getBoundingClientRect();
        const lab = e.closest('label');
        const lr = lab ? lab.getBoundingClientRect() : r;
        const w = Math.round(Math.max(r.width, lr.width)), h = Math.round(Math.max(r.height, lr.height));
        if (w < 24 || h < 24) small.push(name(e) + ' ' + Math.round(w) + 'x' + Math.round(h));
        else if (w < 44 || h < 44) smallish.push(name(e) + ' ' + Math.round(w) + 'x' + Math.round(h));
      }
    }
    // transition: all
    for (const e of $$('body *').filter(shown)) {
      const s = cs(e);
      if (/(^|,\s*)all\b/.test(s.transitionProperty) && s.transitionDuration.split(',').some((d) => parseFloat(d) > 0)) all.push(name(e));
      if (all.length > 5) break;
    }
    // heading rhythm: more space above a heading than below it
    let tight = 0, total = 0;
    const tightEx = [];
    for (const h of $$('h2, h3').filter(shown)) {
      const prev = h.previousElementSibling, next = h.nextElementSibling;
      if (!prev || !next || !shown(prev) || !shown(next)) continue;
      const r = h.getBoundingClientRect(), above = r.top - prev.getBoundingClientRect().bottom, below = next.getBoundingClientRect().top - r.bottom;
      if (above < 0 || below < 0 || above > 400) continue;
      total++;
      if (above <= below) { tight++; tightEx.push('"' + ascii(h.textContent).slice(0, 26) + '" ' + Math.round(above) + '/' + Math.round(below) + 'px'); }
    }
    report('ban', where, 'eyebrow/kicker label above a heading', kicker);
    report('ban', where, 'gradient text', gradient);
    report('warn', where, 'text too small', tiny);
    report('warn', where, 'lines too long (aim 45-75 characters)', measure);
    report('warn', where, 'running text touches the screen edge', edge);
    report('warn', where, 'tight line-height on running text', leading);
    report('warn', where, 'touch targets under 24px', small);
    report('warn', where, 'transition: all', all);
    if (total >= 2 && tight / total > 0.5) report('warn', where, 'headings closer to the block above than to their content (above/below)', tightEx);
    report('note', where, 'touch targets under 44px', smallish);
    const over_ = Array.from(fonts).filter((f) => OVERUSED.includes(f));
    if (over_.length) report('note', where, 'fonts on every generated site', over_);
    if (!log.some((l) => l.includes(' ' + where + ' '))) log.push('ok   ' + where);
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
    const w = phone ? 'phone' : 'desktop';
    for (const h of PUBLIC) { await page(h); scan(h + ' ' + w); }
    await adminIn();
    for (const h of MEMBER) { await page(h); scan(h + ' ' + w); }
    log.push((bad.length ? 'PROBLEMS: ' + bad.join(' | ') : 'PASSED') + ' (' + warns + ' warnings to fix or explain)');
    return { ok: !bad.length, log: log };
  } catch (e) {
    log.push(String(e && e.message || e));
    return { ok: false, log: log };
  }
})();
