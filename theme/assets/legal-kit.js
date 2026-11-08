/* LegalKit: the "Privacy & Terms" page shared by every Arkvital app.
 *
 * Built from APP_MAKER/legal-kit (runtime/legal-kit.js + the app's generated content).
 * Edit it there and re-run build.py + install.py; don't edit the copies inside the apps.
 *
 * What it does:
 *   - LegalKit.open(tab)          shows the full-screen legal page (tabs: overview, privacy, terms, cookies)
 *   - LegalKit.setUser(state)     tells it who is signed in and what they accepted; shows a slim reminder
 *                                 bar if a signed-in person hasn't accepted the current version
 *   - LegalKit.consentField()     HTML for the "I'm 16+ and agree" tick box on sign-up forms
 *   - LegalKit.consentChecked(el) true when the tick box inside el is ticked
 *   - any element with data-lk-open="privacy|terms|cookies|overview" opens that tab when clicked
 *   - #legal or #legal/<tab> in the URL opens the page on load (for links from emails and stores)
 *   - LegalKit.setOpenHandler(fn)  inside an iframe: hand "open" to the host page instead
 *
 * The app connects it to its server with configure({...}) and setAcceptHandler(fn), where
 * fn(version, source) records the acceptance and returns {ok, accepted_version, accepted_at}
 * (or a Promise / JSON string of it).
 */
(function () {
  'use strict';
  if (window.LegalKit && window.LegalKit._runtime) { return; }

  var LK = window.LegalKit = window.LegalKit || {};
  LK._runtime = 1;

  var TABS = ['overview', 'privacy', 'terms', 'cookies'];
  var PENDING_KEY = 'lk.signupConsent';
  var LANG_KEY = 'lk.lang';
  var LATER_KEY = 'lk.later';
  var PENDING_DAYS = 7;

  var cfg = { theme: {}, mode: 'auto', lang: null, onChange: null };
  var acceptFn = null, openFn = null;
  var user = { signedIn: false };
  var page = null, banner = null, lastFocus = null, currentTab = 'overview', busy = false;

  // ------------------------------------------------------------------ small helpers
  function store(kind) { try { return window[kind]; } catch (e) { return null; } }
  function sget(k, kind) { try { var s = store(kind || 'localStorage'); return s ? s.getItem(k) : null; } catch (e) { return null; } }
  function sset(k, v, kind) { try { var s = store(kind || 'localStorage'); if (s) { if (v == null) s.removeItem(k); else s.setItem(k, v); } } catch (e) { /* private mode */ } }
  function parse(x) { if (typeof x === 'string') { try { return JSON.parse(x); } catch (e) { return {}; } } return x || {}; }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function fill(s, vars) { return String(s).replace(/\{(\w+)\}/g, function (m, k) { return vars && vars[k] != null ? vars[k] : m; }); }
  function C() { return LK.content || { version: '', app: { name: '' }, operator: {}, langs: {} }; }
  function lang() {
    var langs = C().langs, l = cfg.lang || sget(LANG_KEY) || ((navigator.language || 'en').slice(0, 2).toLowerCase());
    return langs[l] ? l : 'en';
  }
  function L() { return C().langs[lang()] || C().langs.en || { tabs: [], ui: {} }; }
  function T(key, vars) {
    var ui = L().ui || {}, en = (C().langs.en || {}).ui || {};
    return fill(ui[key] != null ? ui[key] : (en[key] != null ? en[key] : key), Object.assign({ app: esc(C().app.name) }, vars || {}));
  }
  function fmtDate(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d)) return esc(iso);
    try { return d.toLocaleDateString(lang() === 'fr' ? 'fr-CA' : 'en-CA', { year: 'numeric', month: 'long', day: 'numeric' }); }
    catch (e) { return d.toISOString().slice(0, 10); }
  }
  function accepted() { return !!(user.signedIn && user.accepted_version && user.accepted_version === C().version); }
  function needsConsent() { return !!(user.signedIn && !accepted()); }

  // Dark mode: follow the app. Explicit setting first, then the page's own background, then the OS.
  function isDark() {
    if (cfg.mode === 'dark') return true;
    if (cfg.mode === 'light') return false;
    var els = [document.body, document.documentElement];
    for (var i = 0; i < els.length; i++) {
      if (!els[i]) continue;
      var m = (getComputedStyle(els[i]).backgroundColor || '').match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?/);
      if (m && (m[4] === undefined || parseFloat(m[4]) > 0.5)) {
        return (0.299 * m[1] + 0.587 * m[2] + 0.114 * m[3]) < 110;
      }
    }
    return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
  }

  // ------------------------------------------------------------------ styles
  var CSS = [
    '#lk-root,#lk-bar{--lk-accent:#2f5bd3;--lk-accent-ink:#fff;--lk-bg:#fbfbf9;--lk-card:#fff;--lk-ink:#1d1f24;--lk-muted:#5d6370;--lk-line:rgba(20,24,32,.12);--lk-soft:rgba(20,24,32,.05);--lk-radius:14px;',
    '  font-family:var(--lk-font,inherit);color:var(--lk-ink);-webkit-font-smoothing:antialiased;box-sizing:border-box;line-height:1.55;letter-spacing:normal;text-transform:none}',
    '#lk-root.lk-dark,#lk-bar.lk-dark{--lk-bg:#15171c;--lk-card:#1d2027;--lk-ink:#eceef2;--lk-muted:#a4abb8;--lk-line:rgba(255,255,255,.13);--lk-soft:rgba(255,255,255,.06)}',
    '#lk-root *,#lk-bar *{box-sizing:border-box}',
    '#lk-root{position:fixed;inset:0;z-index:2147483000;background:var(--lk-bg);display:flex;flex-direction:column;font-size:16px;animation:lk-in .18s ease-out}',
    '@keyframes lk-in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}',
    '#lk-root .lk-top{flex:none;border-bottom:1px solid var(--lk-line);background:var(--lk-card)}',
    '#lk-root .lk-topin{max-width:820px;margin:0 auto;padding:10px 16px;display:flex;align-items:center;gap:10px}',
    '#lk-root .lk-back{display:inline-flex;align-items:center;gap:6px;border:0;background:transparent;color:var(--lk-ink);font:inherit;font-size:15px;font-weight:600;padding:8px 10px 8px 4px;border-radius:10px;cursor:pointer;min-height:40px}',
    '#lk-root .lk-back:hover{background:var(--lk-soft)}',
    '#lk-root .lk-back svg{width:20px;height:20px}',
    '#lk-root .lk-sp{flex:1}',
    '#lk-root .lk-ghost{border:1px solid var(--lk-line);background:transparent;color:var(--lk-ink);font:inherit;font-size:13px;font-weight:600;padding:7px 11px;border-radius:999px;cursor:pointer;min-height:34px}',
    '#lk-root .lk-ghost:hover{background:var(--lk-soft)}',
    '#lk-root .lk-tabs{max-width:820px;margin:0 auto;padding:0 12px;display:flex;gap:4px;overflow-x:auto;scrollbar-width:none}',
    '#lk-root .lk-tabs::-webkit-scrollbar{display:none}',
    '#lk-root .lk-tab{flex:none;border:0;background:transparent;color:var(--lk-muted);font:inherit;font-size:14px;font-weight:600;padding:10px 12px 12px;cursor:pointer;border-bottom:2.5px solid transparent;white-space:nowrap}',
    '#lk-root .lk-tab[aria-selected=true]{color:var(--lk-ink);border-bottom-color:var(--lk-accent)}',
    '#lk-root .lk-scroll{flex:1;overflow-y:auto;-webkit-overflow-scrolling:touch}',
    '#lk-root .lk-doc{max-width:820px;margin:0 auto;padding:22px 20px 40px}',
    '#lk-root .lk-eyebrow{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--lk-accent);margin:0 0 6px}',
    '#lk-root.lk-dark .lk-eyebrow{filter:brightness(1.5)}',
    '#lk-root h1:focus{outline:none}',
    '#lk-root h1{font-size:28px;line-height:1.2;margin:0 0 6px;font-family:var(--lk-head,inherit);color:var(--lk-ink)}',
    '#lk-root .lk-meta{color:var(--lk-muted);font-size:13px;margin:0 0 22px}',
    '#lk-root h2{font-size:19px;line-height:1.3;margin:28px 0 8px;font-family:var(--lk-head,inherit);color:var(--lk-ink)}',
    '#lk-root h3{font-size:16px;margin:20px 0 6px;color:var(--lk-ink)}',
    '#lk-root p,#lk-root li{font-size:15.5px;color:var(--lk-ink)}',
    '#lk-root p{margin:0 0 12px}',
    '#lk-root ul{margin:0 0 14px;padding-left:22px}',
    '#lk-root li{margin:0 0 6px}',
    '#lk-root a{color:var(--lk-accent);text-underline-offset:2px}',
    '#lk-root.lk-dark a{filter:brightness(1.45)}',
    '#lk-root .lk-card{background:var(--lk-card);border:1px solid var(--lk-line);border-radius:var(--lk-radius);padding:16px 18px;margin:0 0 14px}',
    '#lk-root .lk-key{list-style:none;padding:0;margin:0 0 18px}',
    '#lk-root .lk-key li{display:flex;gap:12px;align-items:flex-start;padding:12px 0;border-bottom:1px solid var(--lk-line);margin:0}',
    '#lk-root .lk-key li:last-child{border-bottom:0}',
    '#lk-root .lk-key .lk-ico{flex:none;width:30px;height:30px;border-radius:9px;background:var(--lk-soft);display:grid;place-items:center;font-size:16px}',
    '#lk-root .lk-actions{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 4px}',
    '#lk-root .lk-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;border:1px solid var(--lk-line);background:var(--lk-card);color:var(--lk-ink);font:inherit;font-size:14px;font-weight:600;padding:9px 14px;border-radius:999px;cursor:pointer;text-decoration:none;min-height:40px}',
    '#lk-root .lk-btn:hover{background:var(--lk-soft)}',
    '#lk-root .lk-btn.lk-primary,#lk-bar .lk-primary{background:var(--lk-accent);border-color:var(--lk-accent);color:var(--lk-accent-ink)}',
    '#lk-root .lk-btn.lk-primary:hover{filter:brightness(1.08)}',
    '#lk-root .lk-btn[disabled]{opacity:.45;cursor:not-allowed}',
    '#lk-root .lk-foot{flex:none;border-top:1px solid var(--lk-line);background:var(--lk-card)}',
    '#lk-root .lk-footin{max-width:820px;margin:0 auto;padding:12px 16px calc(12px + env(safe-area-inset-bottom));display:flex;align-items:center;gap:12px;flex-wrap:wrap}',
    '#lk-root .lk-footin p{margin:0;font-size:14px;flex:1;min-width:220px;color:var(--lk-muted)}',
    '#lk-root .lk-ok{color:var(--lk-ink)!important}',
    '#lk-root .lk-ok b{color:#2e8540}',
    '#lk-root.lk-dark .lk-ok b{color:#6fcf86}',
    '#lk-root .lk-err{color:#c0392b;font-size:13px;width:100%}',
    '.lk-consent{display:flex!important;gap:10px;align-items:flex-start;font-size:14px;line-height:1.45;text-align:left;cursor:pointer;margin:4px 0;font-weight:400}',
    '.lk-consent input{flex:none;width:18px;height:18px;margin:1px 0 0;accent-color:var(--lk-accent,currentColor);cursor:pointer}',
    '.lk-consent a{color:inherit;text-decoration:underline;text-underline-offset:2px;font-weight:600;cursor:pointer}',
    '.lk-consent.lk-shake{animation:lk-shake .35s}',
    '@keyframes lk-shake{20%,60%{transform:translateX(-5px)}40%,80%{transform:translateX(5px)}}',
    '.lk-consent-err{color:#c0392b;font-size:13px;margin:2px 0 0 28px}',
    '#lk-bar{position:fixed;left:12px;right:12px;bottom:calc(12px + env(safe-area-inset-bottom));z-index:2147482999;max-width:620px;margin:0 auto;background:var(--lk-card);border:1px solid var(--lk-line);border-radius:16px;box-shadow:0 10px 34px rgba(0,0,0,.18);padding:12px 12px 12px 16px;display:flex;align-items:center;gap:10px;font-size:14px;animation:lk-in .25s ease-out}',
    '#lk-bar p{margin:0;flex:1;color:var(--lk-ink);font-size:14px;line-height:1.4}',
    '#lk-bar button{border:1px solid var(--lk-line);background:transparent;color:var(--lk-ink);font:inherit;font-size:13.5px;font-weight:600;padding:8px 13px;border-radius:999px;cursor:pointer;white-space:nowrap;min-height:38px}',
    '#lk-bar .lk-later{border-color:transparent;color:var(--lk-muted)}',
    '@media (max-width:520px){#lk-bar{flex-wrap:wrap}#lk-bar p{flex-basis:100%}#lk-bar .lk-sp{flex:1}#lk-root h1{font-size:24px}#lk-root .lk-doc{padding:18px 16px 32px}}',
    '@media print{html.lk-open body>*:not(#lk-root){display:none!important}#lk-root{position:static;background:#fff;color:#000}#lk-root .lk-top,#lk-root .lk-foot,#lk-root .lk-noprint{display:none!important}#lk-root .lk-scroll{overflow:visible}}'
  ].join('\n');

  function ensureStyle() {
    if (document.getElementById('lk-style')) return;
    var st = document.createElement('style');
    st.id = 'lk-style';
    st.textContent = CSS;
    (document.head || document.documentElement).appendChild(st);
  }

  function applyTheme(el) {
    var t = Object.assign({}, C().theme || {}, cfg.theme || {});
    var map = { accent: '--lk-accent', accentInk: '--lk-accent-ink', font: '--lk-font', headingFont: '--lk-head', radius: '--lk-radius' };
    Object.keys(map).forEach(function (k) { if (t[k]) el.style.setProperty(map[k], t[k]); });
    el.classList.toggle('lk-dark', isDark());
    if (isDark() && t.accentDark) el.style.setProperty('--lk-accent', t.accentDark);
    // text on accent buttons must reach 4.5:1 (WCAG AA): keep the app's ink if it does, else white or near-black
    var acc = (isDark() && t.accentDark) || t.accent;
    if (acc && /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(acc)) {
      var ink = t.accentInk || '#ffffff';
      if (contrast(ink, acc) < 4.5) ink = contrast('#ffffff', acc) >= contrast('#14161a', acc) ? '#ffffff' : '#14161a';
      el.style.setProperty('--lk-accent-ink', ink);
    }
  }

  function lum(hex) {
    var h = hex.replace('#', '');
    if (h.length === 3) h = h.replace(/./g, function (c) { return c + c; });
    var v = [0, 2, 4].map(function (i) {
      var c = parseInt(h.substr(i, 2), 16) / 255;
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
  }
  function contrast(a, b) {
    if (!/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(a)) return 21;  // a colour we can't read: trust the app
    var x = lum(a), y = lum(b);
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
  }

  // ------------------------------------------------------------------ the page
  var ICON_BACK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6"/></svg>';

  function tabData(id) {
    var tabs = L().tabs || [];
    for (var i = 0; i < tabs.length; i++) if (tabs[i].id === id) return tabs[i];
    return tabs[0] || { id: id, title: id, html: '' };
  }

  function mailto(kind) {
    var op = C().operator || {}, vars = { email: user.email || T('your_email') };
    var subject = T('mail_' + kind + '_subject', vars), body = T('mail_' + kind + '_body', vars);
    return 'mailto:' + encodeURIComponent(op.email || '') + '?subject=' + encodeURIComponent(subject) + '&body=' + encodeURIComponent(body);
  }

  function rightsHTML() {
    return '<div class="lk-actions lk-noprint">' +
      '<a class="lk-btn" href="' + esc(mailto('access')) + '">' + T('btn_access') + '</a>' +
      '<a class="lk-btn" href="' + esc(mailto('delete')) + '">' + T('btn_delete') + '</a>' +
      '<a class="lk-btn" href="' + esc(mailto('question')) + '">' + T('btn_question') + '</a></div>';
  }

  function docHTML(id) {
    var t = tabData(id), c = C();
    var html = String(t.html || '').replace('<!--lk:rights-->', rightsHTML());
    return '<p class="lk-eyebrow">' + esc(c.app.name) + '</p>' +
      '<h1 tabindex="-1">' + esc(t.heading || t.title) + '</h1>' +
      '<p class="lk-meta">' + T('effective', { date: esc(L().effective || c.version), version: esc(c.version) }) + '</p>' + html;
  }

  function footHTML() {
    if (!user.signedIn) return '<p>' + T('guest_note') + '</p>';
    if (accepted()) return '<p class="lk-ok"><b>&#10003;</b> ' + T('accepted_on', { date: fmtDate(user.accepted_at) }) + '</p>';
    return '<label class="lk-consent" style="flex:1;min-width:220px"><input type="checkbox" class="lk-agree-box"> <span>' + T('page_consent') + '</span></label>' +
      '<button type="button" class="lk-btn lk-primary lk-agree" disabled>' + T('agree') + '</button>' +
      '<div class="lk-err" hidden></div>';
  }

  function render() {
    if (!page) return;
    var tabs = (L().tabs || []).map(function (t) {
      return '<button type="button" role="tab" class="lk-tab" data-lk-tab="' + t.id + '" aria-selected="' + (t.id === currentTab) + '">' + esc(t.title) + '</button>';
    }).join('');
    var other = lang() === 'fr' ? 'en' : 'fr', hasOther = !!C().langs[other];
    page.innerHTML =
      '<div class="lk-top">' +
        '<div class="lk-topin">' +
          '<button type="button" class="lk-back" data-lk-close>' + ICON_BACK + '<span>' + T('back') + '</span></button>' +
          '<span class="lk-sp"></span>' +
          (hasOther ? '<button type="button" class="lk-ghost" data-lk-lang="' + other + '" lang="' + other + '">' + esc(C().langs[other].ui.lang_name) + '</button>' : '') +
          '<button type="button" class="lk-ghost" data-lk-print>' + T('print') + '</button>' +
        '</div>' +
        '<div class="lk-tabs" role="tablist" aria-label="' + T('title') + '">' + tabs + '</div>' +
      '</div>' +
      '<div class="lk-scroll"><article class="lk-doc" role="tabpanel">' + docHTML(currentTab) + '</article></div>' +
      '<div class="lk-foot"><div class="lk-footin">' + footHTML() + '</div></div>';
    page.setAttribute('lang', lang());
    applyTheme(page);
  }

  function onPageClick(e) {
    var el = e.target.closest ? e.target.closest('[data-lk-tab],[data-lk-close],[data-lk-lang],[data-lk-print],.lk-agree,[data-lk-goto]') : null;
    if (!el) return;
    if (el.hasAttribute('data-lk-tab')) { show(el.getAttribute('data-lk-tab')); }
    else if (el.hasAttribute('data-lk-goto')) { e.preventDefault(); show(el.getAttribute('data-lk-goto')); }
    else if (el.hasAttribute('data-lk-close')) { LK.close(); }
    else if (el.hasAttribute('data-lk-lang')) { sset(LANG_KEY, el.getAttribute('data-lk-lang')); cfg.lang = null; render(); }
    else if (el.hasAttribute('data-lk-print')) { window.print(); }
    else if (el.classList.contains('lk-agree')) { doAccept('page'); }
  }

  function onPageChange(e) {
    if (e.target.classList && e.target.classList.contains('lk-agree-box')) {
      var b = page.querySelector('.lk-agree');
      if (b) b.disabled = !e.target.checked;
    }
  }

  function show(tab) {
    currentTab = TABS.indexOf(tab) >= 0 ? tab : 'overview';
    render();
    var sc = page.querySelector('.lk-scroll');
    if (sc) sc.scrollTop = 0;
    var h = page.querySelector('h1');
    if (h) { try { h.focus({ preventScroll: true }); } catch (err) { h.focus(); } }
  }

  function onKey(e) { if (e.key === 'Escape' && page) LK.close(); }

  /* While the page is open, the app behind it is inert: Tab and screen readers stay inside the dialog (WCAG 2.4.3).
     Only touches elements that weren't inert already, and gives them back on close. */
  var inerted = [];
  function setInert(on) {
    if (on) {
      inerted = [];
      Array.prototype.forEach.call(document.body.children, function (el) {
        if (el !== page && !el.hasAttribute('inert') && el.tagName !== 'SCRIPT') { el.setAttribute('inert', ''); inerted.push(el); }
      });
    } else {
      inerted.forEach(function (el) { el.removeAttribute('inert'); });
      inerted = [];
    }
  }

  LK.open = function (tab) {
    if (openFn) { openFn(typeof tab === 'string' ? tab : 'overview'); return; }
    if (!document.body) { document.addEventListener('DOMContentLoaded', function () { LK.open(tab); }); return; }
    ensureStyle();
    if (!page) {
      lastFocus = document.activeElement;
      page = document.createElement('div');
      page.id = 'lk-root';
      page.setAttribute('role', 'dialog');
      page.setAttribute('aria-modal', 'true');
      page.setAttribute('aria-label', T('title'));
      page.addEventListener('click', onPageClick);
      page.addEventListener('change', onPageChange);
      document.body.appendChild(page);
      setInert(true);
      document.documentElement.classList.add('lk-open');
      page._overflow = document.documentElement.style.overflow;
      document.documentElement.style.overflow = 'hidden';
      document.addEventListener('keydown', onKey);
    }
    show(typeof tab === 'string' ? tab : 'overview');
    hideBar();
  };

  LK.close = function () {
    if (!page) return;
    document.removeEventListener('keydown', onKey);
    setInert(false);
    document.documentElement.style.overflow = page._overflow || '';
    document.documentElement.classList.remove('lk-open');
    page.remove();
    page = null;
    if (/^#legal(\/\w+)?$/.test(location.hash)) {
      try { history.replaceState(null, '', location.pathname + location.search); } catch (err) { /* ignore */ }
    }
    if (lastFocus && lastFocus.focus) { try { lastFocus.focus(); } catch (err) { /* gone */ } }
    updateBar();
  };

  LK.isOpen = function () { return !!page; };

  // ------------------------------------------------------------------ accepting
  function doAccept(source) {
    if (busy || !acceptFn) return;
    busy = true;
    var btn = page && page.querySelector('.lk-agree'), err = page && page.querySelector('.lk-err');
    if (btn) { btn.disabled = true; btn.textContent = T('saving'); }
    var v = C().version;
    Promise.resolve().then(function () { return acceptFn(v, source); }).then(function (r) {
      r = parse(r);
      busy = false;
      if (r && r.ok) {
        user.accepted_version = r.accepted_version || v;
        user.accepted_at = r.accepted_at || new Date().toISOString();
        sset(PENDING_KEY, null);
        render();
        updateBar();
        if (cfg.onChange) { try { cfg.onChange(user); } catch (e) { /* app's problem */ } }
      } else { throw new Error((r && r.error) || 'failed'); }
    }).catch(function () {
      busy = false;
      if (btn) { btn.disabled = false; btn.textContent = T('agree'); }
      if (err) { err.hidden = false; err.textContent = T('save_error'); }
    });
  }

  // A tick on the sign-up form is remembered for a few days, so it can be recorded as soon as the new
  // account is signed in (also when the app asks people to confirm their email first).
  function pendingSignup() {
    var p = parse(sget(PENDING_KEY));
    return !!(p && p.v === C().version && p.at && (Date.now() - p.at) < PENDING_DAYS * 864e5);
  }

  LK.markSignupConsent = function (on) {
    sset(PENDING_KEY, on === false ? null : JSON.stringify({ v: C().version, at: Date.now() }));
  };

  // ------------------------------------------------------------------ reminder bar
  function hideBar() { if (banner) { banner.remove(); banner = null; } }

  function updateBar() {
    if (page || !document.body) return;
    if (!needsConsent() || sget(LATER_KEY, 'sessionStorage') === C().version || cfg.bar === false) { hideBar(); return; }
    ensureStyle();
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'lk-bar';
      banner.setAttribute('role', 'region');
      banner.setAttribute('aria-label', T('title'));
      banner.addEventListener('click', function (e) {
        var b = e.target.closest('button');
        if (!b) return;
        if (b.classList.contains('lk-later')) { sset(LATER_KEY, C().version, 'sessionStorage'); hideBar(); }
        else LK.open('overview');
      });
      document.body.appendChild(banner);
    }
    banner.innerHTML = '<p>' + T(user.accepted_version ? 'bar_updated' : 'bar_new') + '</p><span class="lk-sp"></span>' +
      '<button type="button" class="lk-later">' + T('later') + '</button>' +
      '<button type="button" class="lk-primary">' + T('review') + '</button>';
    applyTheme(banner);
  }

  // ------------------------------------------------------------------ public API
  LK.load = function (content) { LK.content = parse(content); };

  LK.configure = function (opts) {
    opts = parse(opts);
    Object.keys(opts).forEach(function (k) { cfg[k] = opts[k]; });
    if (page) render();
    updateBar();
    return LK;
  };

  LK.setAcceptHandler = function (fn) { acceptFn = fn; return LK; };

  /* For a page inside an iframe: send "open" to the host page instead of drawing the page here. */
  LK.setOpenHandler = function (fn) { openFn = fn; return LK; };

  LK.setUser = function (state) {
    state = parse(state);
    user = {
      signedIn: !!state.signedIn,
      accepted_version: state.accepted_version || null,
      accepted_at: state.accepted_at || null,
      email: state.email || null
    };
    if (needsConsent() && pendingSignup()) { doAccept('signup'); }
    if (page) render();
    updateBar();
    return LK;
  };

  LK.state = function () { return JSON.stringify({ version: C().version, user: user, needsConsent: needsConsent() }); };
  LK.needsConsent = needsConsent;
  LK.version = function () { return C().version; };
  LK.t = function (key) { return T(key); };

  /* The tick box for sign-up forms. The box is required, so a normal <form> won't submit without it;
   * apps that submit from a click handler should also check LegalKit.consentChecked(form). */
  LK.consentField = function (opts) {
    ensureStyle();
    opts = parse(opts);
    var txt = T('signup_consent')
      .replace('[terms]', '<a role="button" tabindex="0" data-lk-open="terms">').replace('[/terms]', '</a>')
      .replace('[privacy]', '<a role="button" tabindex="0" data-lk-open="privacy">').replace('[/privacy]', '</a>');
    return '<label class="lk-consent' + (opts.className ? ' ' + esc(opts.className) : '') + '">' +
      '<input type="checkbox" name="lk_consent" class="lk-consent-box" required> <span>' + txt + '</span></label>';
  };

  /* True if the tick box inside root is ticked. If not, it shakes it and shows a short message. */
  LK.consentChecked = function (root, quiet) {
    root = root || document;
    var box = root.querySelector ? root.querySelector('.lk-consent-box') : null;
    if (!box) return true;
    if (box.checked) return true;
    if (!quiet) {
      var lab = box.closest('.lk-consent');
      if (lab) {
        lab.classList.remove('lk-shake'); void lab.offsetWidth; lab.classList.add('lk-shake');
        var next = lab.nextElementSibling;
        if (!next || !next.classList.contains('lk-consent-err')) {
          var m = document.createElement('div');
          m.className = 'lk-consent-err';
          m.setAttribute('role', 'alert');
          m.textContent = T('signup_required');
          lab.parentNode.insertBefore(m, lab.nextSibling);
        }
      }
      try { box.focus(); } catch (e) { /* ignore */ }
    }
    return false;
  };

  /* HTML for a small "Privacy & Terms" link, for footers and menus. */
  LK.linkHTML = function (opts) {
    opts = parse(opts);
    return '<a role="button" tabindex="0" data-lk-open="' + esc(opts.tab || 'overview') + '"' +
      (opts.className ? ' class="' + esc(opts.className) + '"' : '') + ' style="cursor:pointer">' + esc(opts.text || T('title')) + '</a>';
  };

  // ------------------------------------------------------------------ global listeners
  // Capture phase, so links inside app components (and inside <label>s) open the page and nothing else.
  function openFromEvent(e) {
    var el = e.target && e.target.closest ? e.target.closest('[data-lk-open]') : null;
    if (!el || (page && page.contains(el))) return;
    e.preventDefault();
    e.stopPropagation();
    LK.open(el.getAttribute('data-lk-open') || 'overview');
  }
  document.addEventListener('click', openFromEvent, true);
  document.addEventListener('keydown', function (e) {
    if ((e.key === 'Enter' || e.key === ' ') && e.target && e.target.matches && e.target.matches('[data-lk-open]')) openFromEvent(e);
  }, true);
  document.addEventListener('change', function (e) {
    var t = e.target;
    if (t && t.classList && t.classList.contains('lk-consent-box')) {
      LK.markSignupConsent(t.checked);
      var lab = t.closest('.lk-consent'), next = lab && lab.nextElementSibling;
      if (t.checked && next && next.classList.contains('lk-consent-err')) next.remove();
    }
  }, true);

  function fromHash() {
    var m = /^#legal(?:\/(\w+))?$/.exec(location.hash || '');
    if (m) LK.open(m[1] || 'overview');
  }
  window.addEventListener('hashchange', fromHash);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fromHash);
  else setTimeout(fromHash, 0);
})();

window.LegalKit.load({"version": "2026-10-31", "app": {"key": "imageenhancer", "name": "Image Enhancer", "url": "https://image-enhancer.anvil.app"}, "theme": {"accent": "#b8381f"}, "operator": {"name": "Arkvital", "email": "arkvital@outlook.com"}, "langs": {"en": {"tabs": [{"id": "overview", "title": "Overview", "heading": "Privacy & Terms", "html": "<p>Image Enhancer is a private service that repaints pictures sent by Arkvital's own apps in a chosen style (picture book, sci-fi, photo-realistic and others), using an image model on the operator's own computer. It is run by Arkvital, based in Montréal, Québec, Canada. This page explains in plain words what we do with your information and the rules for using Image Enhancer. The full documents are in the other tabs.</p>\n<h2>The short version</h2>\n<ul class=\"lk-key\"><li><span class=\"lk-ico\" aria-hidden=\"true\">📋</span><span><b>What we collect:</b> your email address and display name (console accounts), and the pictures Arkvital's apps send to be restyled, with their results.</span></li><li><span class=\"lk-ico\" aria-hidden=\"true\">👀</span><span><b>What others see:</b> nothing: only the operator can open the console, and each app can only see its own pictures.</span></li><li><span class=\"lk-ico\" aria-hidden=\"true\">🚫</span><span><b>Never sold.</b> No ads, no tracking, and your information is never used to train AI.</span></li><li><span class=\"lk-ico\" aria-hidden=\"true\">🔒</span><span><b>Stored securely</b> by our hosting provider, Anvil, with encrypted connections and hashed passwords.</span></li><li><span class=\"lk-ico\" aria-hidden=\"true\">🎂</span><span><b>16+ for accounts.</b></span></li><li><span class=\"lk-ico\" aria-hidden=\"true\">✉️</span><span><b>Your data, your call.</b> Get a copy, fix it, or delete your account at any time by email.</span></li></ul>\n<h2>Your choices</h2>\n<p>You can ask for a copy of your data, ask us to correct it, or delete your account at any time. Email us at <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a> and we'll reply within 30 days, free of charge.</p>\n<!--lk:rights-->\n<h2>The full documents</h2>\n<ul><li><a href=\"#\" data-lk-goto=\"privacy\">Privacy Policy</a>: what we collect, why, who helps us run Image Enhancer, and your rights.</li><li><a href=\"#\" data-lk-goto=\"terms\">Terms of Use</a>: the rules for using Image Enhancer.</li><li><a href=\"#\" data-lk-goto=\"cookies\">Cookies &amp; Storage</a>: what Image Enhancer keeps in your browser.</li></ul>"}, {"id": "privacy", "title": "Privacy Policy", "heading": "Privacy Policy", "html": "<p>This Privacy Policy explains how Arkvital (\"we\", \"us\") collects, uses, shares and protects personal information in Image Enhancer (https://image-enhancer.anvil.app), and the rights you have. We wrote it to meet Québec's <i>Act respecting the protection of personal information in the private sector</i> (Law 25), Canada's PIPEDA, and the EU and UK General Data Protection Regulation (GDPR).</p>\n<h2>1. Who is responsible</h2>\n<p>Image Enhancer is run by <b>Arkvital</b>, Montréal, Québec, Canada. We are responsible for the personal information described here.</p>\n<p>Our person in charge of the protection of personal information can be reached at <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a>.</p>\n<h2>2. What this policy covers</h2>\n<p>This policy covers Image Enhancer and the information you give us or that we collect when you use it.</p>\n<h2>3. What we collect</h2>\n<p><b>Information you give us</b></p>\n<ul><li><b>Console account:</b> your email address and a password, stored only as a secure hash (or your Google account's email address if you continue with Google), and your display name. Only the operator's account can use the console.</li><li><b>Pictures:</b> each picture an app sends, its file name and size, the style and options asked for (extra words for the model, how closely to follow the picture, size, file type, seed), the app's own reference for it, and the restyled result.</li><li><b>Job details:</b> which app sent it, when it was sent, started and finished, how many tries it took, any error, and the address the app asked to be told at (callback URL) with whether that call worked.</li><li><b>App keys:</b> the name of each app allowed to send pictures, a secure hash of its key (the key itself is not kept), its hourly limit, a note, and when it was last used.</li><li><b>Activity log:</b> short lines such as \"a picture was sent for Watercolour\" or \"the PC didn't answer\".</li><li><b>Feedback:</b> see 7 (Feedback through Prepsto).</li></ul>\n<p><b>Information collected automatically</b></p>\n<ul><li><b>Sign-in information:</b> when you signed up and last signed in, and failed sign-in attempts (to protect your account).</li><li><b>Technical logs:</b> our hosting provider records technical details such as IP addresses, browser type and error messages, to keep the service secure and working.</li></ul>\n<p>We don't collect more than we need. We don't ask for, and you shouldn't add, sensitive information such as health details, government ID numbers or financial account numbers.</p>\n<h2>4. Why we use it, and our legal bases</h2>\n<ul><li><b>To provide Image Enhancer:</b> create and run your account and the features you use. <i>Basis: needed to provide the service you asked for (contract).</i></li><li><b>To keep Image Enhancer safe and working:</b> prevent abuse and fraud, fix problems, make backups. <i>Basis: our legitimate interest in a secure, reliable service.</i></li><li><b>To contact you about your account:</b> for example password resets. <i>Basis: needed to provide the service. You can switch off optional notifications.</i></li><li><b>For optional features</b> that need your permission, listed in section 6. <i>Basis: your consent, which you can withdraw at any time.</i></li><li><b>To meet legal obligations</b> and respond to lawful requests. <i>Basis: legal obligation.</i></li></ul>\n<p>We do <b>not</b> sell your personal information, show ads, build advertising profiles, or use your information to train AI models.</p>\n<p>We only email you about your account and the service you use. We won't send you marketing or newsletters unless you've asked for them, and any such email will have a working unsubscribe link.</p>\n<p>We use your information only for the purposes in this section.</p>\n<h2>5. What other people can see</h2>\n<ul><li><b>The operator</b> sees every picture, result and job in the console.</li><li><b>Each app</b> sees only the pictures it sent itself, through its own key.</li><li><b>Anyone with a result link</b> (a long random address the app receives) can open that one picture, until the job is deleted.</li></ul>\n<p>Everything else stays private between you and us.</p>\n<h2>6. Device permissions and optional features</h2>\n<p>Image Enhancer doesn't use your camera, microphone or location, or any tracking technology that identifies you, locates you or builds a profile of you.</p>\n<h2>7. Feedback through Prepsto</h2>\n<p>All feedback about Image Enhancer goes through its <b>Submit feedback</b> button, which opens Prepsto (prepsto.com), our own feedback tool, also run by Arkvital and hosted by Anvil. You don't need an account. If you send feedback, Prepsto receives:</p>\n<ul><li>the kind of message (idea, bug, question or praise) and what you write;</li><li>an email address, only if you give one so we can reply;</li><li>the address of the page you were on and of the page that led you there, your screen size, your browser type and version, and your browser language, so we can understand and fix what you describe.</li></ul>\n<p>You get a private tracking link where you can follow what happens to your message, read our replies and answer them; your answers are kept with the message. Anyone who has the link can open it, so keep it to yourself. Prepsto remembers your tracking links in your browser so it can show \"Your feedback\", and records when a tracking page was last opened.</p>\n<p><b>Your feedback stays in Prepsto</b> and follows <a href=\"https://prepsto.com/#legal/privacy\" target=\"_blank\" rel=\"noopener\">Prepsto's Privacy Policy</a>; Image Enhancer doesn't keep its own copy. Because Image Enhancer is one of our own apps, we are responsible for your feedback directly, and only the people who run Image Enhancer read it. We keep it until we've dealt with it, and no longer than 24 months, unless you ask us to delete it sooner. The button's small script loads from prepsto.com when Image Enhancer opens and sets no cookies; the feedback window itself loads only when you click the button.</p>\n<h2>8. Where pictures are processed</h2>\n<p>Pictures are not sent to any outside AI company. The queue runs on Anvil (our host); each picture is handed, one at a time, to a computer owned by the operator, where an open image model (FLUX.2 [klein] 4B in ComfyUI) repaints it and sends the result back. The picture's working copies on that computer are deleted after each job.</p>\n<h2>9. The apps that use this service</h2>\n<p>Image Enhancer only receives pictures from Arkvital's own apps. If you use one of those apps, its own Privacy &amp; Terms say which of your pictures it sends here and why.</p>\n<h2>10. Who helps us run Image Enhancer</h2>\n<p>We share personal information only with service providers who help us run Image Enhancer, and only what they need:</p>\n<ul><li><b>Anvil</b> (Anvil Works Ltd, United Kingdom): hosts Image Enhancer, its database and sign-in.</li><li><b>Google Sign-In</b> (Google LLC, United States): only if you choose \"Continue with Google\". Google confirms who you are and gives us your email address. Google's own privacy policy covers your Google account.</li><li><b>Google Fonts</b> (Google LLC, United States): delivers the typefaces. Your browser sends your IP address and browser details to Google when a page loads.</li><li><b>Prepsto</b> (prepsto.com, our own feedback tool, run by Arkvital and hosted by Anvil in the United Kingdom): the <b>Submit feedback</b> button loads a small script from prepsto.com, which receives your IP address and browser details. If you send feedback, it stays in Prepsto and is kept as described in the Privacy Policy.</li></ul>\n<p>These providers process information on our behalf, or deliver content directly to your browser, under their own privacy commitments. We may also disclose information when the law requires it, to protect someone's safety, or as part of a sale or reorganisation of our business (the new owner would have to respect this policy).</p>\n<h2>11. Where your information is stored</h2>\n<p>Our hosting provider stores your information on servers that may be outside Québec and Canada, including in the United Kingdom and the European Union. Before sending information outside Québec, we assessed that it will be adequately protected. The UK and the EU are recognised as giving adequate protection, and Canada has an EU adequacy decision for commercial organisations. Where a provider is in the United States, it relies on the EU–US Data Privacy Framework or standard contractual clauses.</p>\n<h2>12. How long we keep it</h2>\n<ul><li>Pictures, results and job details are deleted automatically 30 days after the picture was sent (the operator can set 1 to 365 days), or earlier when the operator or the app deletes them.</li><li>Deleting an app's key cancels its waiting pictures; its finished jobs stay until they are deleted as above.</li><li>The activity log keeps the latest 400 lines.</li><li><b>Your account and what you add:</b> for as long as your account is open.</li><li><b>When you delete your account</b> (or ask us to): we delete or anonymise your personal information within 30 days. Copies in our hosting provider's backups disappear as those backups are replaced.</li><li>If the law requires us to keep something longer, we keep only that, and only for as long as required.</li></ul>\n<h2>13. How we protect it</h2>\n<p>Connections to Image Enhancer are encrypted (HTTPS). Passwords are stored only as secure hashes, so we can't read them. Only the people who run Image Enhancer can access the data, and only when they need to. No system is perfectly secure. If a security incident creates a risk of serious harm to you, we'll tell you and the relevant authorities as the law requires, and keep a record of it.</p>\n<h2>14. Your rights</h2>\n<p>Wherever you live, you can ask us to:</p>\n<ul><li><b>access</b> the personal information we hold about you, and get a copy;</li><li><b>correct</b> information that is wrong or incomplete;</li><li><b>delete</b> your account and personal information;</li><li><b>move</b> your information: we'll give it to you in a common, structured format;</li><li><b>withdraw your consent</b> to optional uses at any time;</li><li><b>object to or restrict</b> some uses, if you're in the EU or the UK;</li><li><b>stop the dissemination</b> of your information, or have a link to it de-indexed, if you're in Québec and the legal conditions are met.</li></ul>\n<p>To use these rights, email <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a> from the address linked to your account (or tell us how to confirm it's you). It's free. We reply within 30 days.</p>\n<!--lk:rights-->\n<p><b>If you live in the United States:</b> in California and other states with privacy laws, you also have the right to know what personal information we collect, use and disclose, and not to be treated differently for using your rights. We collect the categories described in section 3 (identifiers such as your email address, what you add to Image Enhancer, and technical information about your device), from you and your device, for the purposes in this policy, and share them only with the service providers listed here. We don't sell personal information or share it for targeted advertising, and we don't use sensitive information to infer things about you. Because we don't track you, there is nothing for a Global Privacy Control or \"Do Not Track\" signal to switch off; we treat such a signal as a request not to sell or share, which we already honour. Someone you authorise in writing can make a request for you.</p>\n<p>If you're not satisfied with our answer, you can complain to the Commission d'accès à l'information du Québec (cai.gouv.qc.ca), the Office of the Privacy Commissioner of Canada (priv.gc.ca), or, in the EU or the UK, your local data protection authority.</p>\n<h2>15. Children</h2>\n<p>Image Enhancer accounts are for people <b>16 and older</b>. We don't knowingly collect personal information from children under 16. If you think a child under 16 has created an account, tell us and we'll delete it.</p>\n<h2>16. Automated decisions</h2>\n<p>We don't make decisions about you based only on automated processing that have legal or similarly significant effects on you. Pictures are repainted automatically by an image model. The result can differ from the original in details, and the model can make mistakes; the app that sent the picture decides what to do with it.</p>\n<h2>17. Cookies and browser storage</h2>\n<p>Image Enhancer uses only the cookies and browser storage it needs to work: no advertising or tracking. See <a href=\"#\" data-lk-goto=\"cookies\">Cookies &amp; Storage</a>.</p>\n<h2>18. Changes to this policy</h2>\n<p>Every version is dated, and we keep a copy of each one. If we make a change that matters, we'll tell you in Image Enhancer (or by email) before it applies and ask you to review it. We'll ask for your consent before using your information for a new purpose, unless the law allows it without consent.</p>\n<h2>19. Contact</h2>\n<p>Questions, requests or complaints: <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a>. Our person in charge of the protection of personal information: Arkvital, Montréal, Québec, Canada.</p>"}, {"id": "terms", "title": "Terms of Use", "heading": "Terms of Use", "html": "<p>These Terms of Use are an agreement between you and <b>Arkvital</b> (\"we\", \"us\"), Montréal, Québec, Canada, the operator of Image Enhancer (https://image-enhancer.anvil.app). By creating an account or using Image Enhancer, you agree to them. If you don't agree, please don't use Image Enhancer.</p>\n<h2>1. What Image Enhancer is</h2>\n<p>Image Enhancer is a private service that repaints pictures sent by Arkvital's own apps in a chosen style (picture book, sci-fi, photo-realistic and others), using an image model on the operator's own computer. Our <a href=\"#\" data-lk-goto=\"privacy\">Privacy Policy</a> explains how we handle your personal information and is part of these terms.</p>\n<h2>2. Who can use Image Enhancer</h2>\n<ul><li>You must be <b>16 or older</b> to create an account.</li><li>If you use Image Enhancer for a business or organisation, you confirm that you're allowed to accept these terms for it, and \"you\" includes that business.</li><li>You may not use Image Enhancer if we've suspended your account before, or if the law doesn't allow you to.</li></ul>\n<h2>3. Your account</h2>\n<ul><li>Give accurate information and keep it up to date.</li><li>Keep your password secret. You're responsible for what happens in your account. Tell us right away at <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a> if you think someone else has used it.</li><li>One person per account. Don't share your account or create one for someone else without their permission.</li></ul>\n<h2>4. Your content</h2>\n<p>\"Your content\" means anything you add to Image Enhancer: pictures.</p>\n<ul><li><b>You keep ownership</b> of your content.</li><li><b>You give us permission</b> (a worldwide, non-exclusive, royalty-free licence) to store, copy, display, adapt the format of and share your content, but only to run, show and improve Image Enhancer, and only to the people your settings allow. This permission ends when you delete the content or your account, except for copies other people have already received, and backups until they're replaced.</li><li><b>You're responsible</b> for your content. You confirm that you have the rights to post it, that it's accurate to the best of your knowledge, and that it follows these terms and the law.</li><li>If you think content on Image Enhancer infringes your rights, email <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a> with a link to it and an explanation. We'll look into it promptly.</li></ul>\n<h2>5. Acceptable use</h2>\n<p>When you use Image Enhancer, don't:</p>\n<ul><li>break the law, or help anyone else break it;</li><li>harass, threaten, bully, discriminate against or impersonate anyone;</li><li>post content that is hateful, sexually explicit, violent, misleading, or that infringes someone else's rights (including copyright, trademarks and privacy);</li><li>share other people's personal information without their permission;</li><li>send spam or advertising that people didn't ask for;</li><li>try to get into accounts or data that aren't yours, test or break our security, or disrupt the service;</li><li>copy the service, or collect data from it with bots or scrapers, without our written permission;</li><li>upload viruses or harmful code.</li></ul>\n<h2>6. Moderation and enforcement</h2>\n<p>We may review, hide or remove content, and limit, suspend or close accounts, if we reasonably believe someone has broken these terms or the law, or to protect people or Image Enhancer. Where it's reasonable, we'll tell you why. If you think we got it wrong, email <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a> and we'll take another look.</p>\n<h2>7. Who may use the service</h2>\n<p>Only apps given a key by the operator may send pictures, and only the operator may use the console. Keys are for servers: an app must never put its key in a web page or a phone app. A key may be switched off or replaced at any time.</p>\n<h2>8. Pictures and results</h2>\n<p>An app may only send pictures it has the right to use and to have changed. Whoever owns a picture keeps their rights in it; the operator claims no rights in pictures or results. Results are made by an image model and are provided as they are, without any promise about how they look or when they are ready: estimated times are only estimates, and pictures wait while the operator's computer is off.</p>\n<h2>9. Our rights in Image Enhancer</h2>\n<p>Image Enhancer's software, design, text, graphics and other content we provide belong to us or to those who licensed them to us. We give you a personal, non-exclusive, non-transferable, revocable right to use Image Enhancer as these terms allow. If you send us ideas or feedback, we may use them freely, without owing you anything.</p>\n<h2>10. Other services and links</h2>\n<p>Image Enhancer relies on services run by others (listed in the Privacy Policy) and may link to other websites. We aren't responsible for their content or how they work, and your use of them is governed by their own terms.</p>\n<h2>11. Changes and availability</h2>\n<p>We're always improving Image Enhancer, so features may change. We may also suspend or stop part or all of Image Enhancer. We'll try to give reasonable notice of important changes, and before closing Image Enhancer we'll give you a way to get a copy of your information. We don't promise that Image Enhancer will always be available or free of errors.</p>\n<h2>12. Disclaimers</h2>\n<p>Image Enhancer is provided <b>\"as is\" and \"as available\"</b>. To the extent the law allows, we make no promises or warranties beyond those in these terms, including about fitness for a particular purpose or that content (ours or other users') is accurate.</p>\n<h2>13. Limitation of liability</h2>\n<p>To the extent the law allows, we are not liable for indirect, incidental or consequential losses, such as lost profits, lost data or lost opportunities, and our total liability to you for any claim about Image Enhancer is limited to the greater of the amount you paid us for Image Enhancer in the 12 months before the claim, or CAD $100.</p>\n<p>We aren't responsible for delays or failures caused by events beyond our reasonable control, such as outages of the internet or of our service providers, power failures, natural disasters or government action.</p>\n<p>Nothing in these terms limits liability that can't be limited by law, including for bodily or moral injury, or for intentional or gross fault, and nothing takes away rights you have as a consumer under the law where you live (for example, under Québec's <i>Consumer Protection Act</i>).</p>\n<h2>14. Responsibility for misuse</h2>\n<p>If you break these terms or the law while using Image Enhancer, and someone makes a claim against us because of it, you're responsible for the harm this causes us, as the law provides. If you use Image Enhancer for a business or organisation, that business also agrees to compensate us (indemnify us) for losses, damages and reasonable legal costs arising from such claims, including claims about its content. This paragraph doesn't apply where the law doesn't allow it, and it never makes you responsible for our own mistakes.</p>\n<h2>15. Ending your use</h2>\n<p>You can stop using Image Enhancer at any time and ask us to delete your account at <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a>. We may suspend or close your account as described in section 6. Sections that by their nature should continue (for example 9, 12, 13, 14 and 17) continue after your account ends.</p>\n<h2>16. Changes to these terms</h2>\n<p>We may update these terms. Every version is dated, and we keep a copy of each one. If a change matters, we'll tell you in Image Enhancer or by email, with the new wording and the date it applies, at least 30 days before it applies to your account, and ask you to accept it. If you don't accept the change, you can refuse it by closing your account, at no cost, up to 30 days after it applies. People who create an account after a change agree to the version shown to them.</p>\n<h2>17. Law and disputes</h2>\n<p>These terms are governed by the laws of Québec and the federal laws of Canada that apply there. Any dispute will be heard by the courts of the judicial district of Montréal, Québec, unless the law where you live gives you the right to go to your local courts. Before going to court, please contact us at <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a>: most problems can be solved quickly.</p>\n<h2>18. General</h2>\n<ul><li><b>The whole agreement:</b> these terms, the Privacy Policy and any rules shown to you for a specific feature are the whole agreement between you and us about Image Enhancer.</li><li><b>If one part doesn't hold:</b> if a court finds part of these terms invalid, the rest still applies, and the invalid part is replaced by a valid one that comes as close as possible to what was intended.</li><li><b>No waiver:</b> if we don't enforce a part of these terms right away, we can still enforce it later.</li><li><b>Transfer:</b> we may transfer these terms to a business that takes over Image Enhancer, and your rights under them and under the Privacy Policy stay the same. You may not transfer your account or these terms to someone else without our permission.</li><li><b>Notices:</b> we may contact you through Image Enhancer or at the email address of your account, and you can reach us at <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a>. Messages sent this way count as written notice.</li></ul>\n<h2>19. Language</h2>\n<p>These terms are available in French and in English. The French version was made available to you first, and you have chosen to use the version in the language you're reading. <i>Ces conditions sont offertes en français et en anglais.</i></p>\n<h2>20. Contact</h2>\n<p>Arkvital, Montréal, Québec, Canada. Email: <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a>.</p>"}, {"id": "cookies", "title": "Cookies & Storage", "heading": "Cookies & Storage", "html": "<p>This page explains the cookies and browser storage Image Enhancer uses. In short: <b>only what Image Enhancer needs to work</b>. There are no advertising, analytics or tracking cookies, and we don't follow you around the web. That's why there is no cookie banner.</p>\n<h2>What Image Enhancer stores in your browser</h2>\n<ul><li><b>Sign-in session</b> (cookie, set by our hosting provider Anvil): keeps you signed in while you use Image Enhancer and protects against forged requests. It's deleted when you close the browser or sign out.</li><li><b>\"Remember me\"</b> (only if you choose it when signing in): keeps you signed in on this device for a limited time.</li><li><b>Preferences</b> (local storage): light or dark theme, and the test bench's last style and fidelity.</li><li><b>Feedback</b> (only after you click <b>Submit feedback</b>): the feedback window comes from prepsto.com and may use its own essential session cookie, plus local storage that remembers the private tracking links of the messages you sent, so it can show \"Your feedback\". The button's script sets nothing until you click it.</li><li><b>Privacy &amp; Terms preferences</b> (local storage): your language on this page, that you ticked the agreement box while signing up, and whether you chose \"Later\" on the reminder. Nothing personal.</li></ul>\n<p>All of these are strictly necessary to provide the service you asked for, so the law doesn't require us to ask for consent first. We'll ask before we ever add anything that isn't, such as analytics.</p>\n<h2>Content loaded from other services</h2>\n<p>To show Image Enhancer, your browser fetches a few things directly from other services. When it does, they receive your IP address and basic browser information, as with any website:</p>\n<ul><li><b>Google Fonts</b> (Google LLC, United States): delivers the typefaces. Your browser sends your IP address and browser details to Google when a page loads.</li><li><b>Prepsto</b> (prepsto.com, our own feedback tool, run by Arkvital and hosted by Anvil in the United Kingdom): the <b>Submit feedback</b> button loads a small script from prepsto.com, which receives your IP address and browser details. If you send feedback, it stays in Prepsto and is kept as described in the Privacy Policy.</li></ul>\n<p>They don't receive your account information from us.</p>\n<h2>Your control</h2>\n<p>You can delete cookies and site data at any time in your browser settings. If you do, you'll be signed out. You can also block cookies, but then you won't be able to sign in.</p>\n<p>Questions: <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a>.</p>"}], "ui": {"lang_name": "English", "title": "Privacy & Terms", "back": "Back to {app}", "print": "Print", "effective": "In effect since {date} · Version {version}", "guest_note": "Nothing to accept while you're not signed in. We'll ask when you create an account.", "accepted_on": "You accepted the Terms of Use and Privacy Policy on {date}.", "page_consent": "I'm 16 or older, I agree to the Terms of Use, and I have read the Privacy Policy.", "agree": "I agree", "saving": "Saving…", "save_error": "Couldn't save your answer. Please check your connection and try again.", "bar_new": "{app} now has a Privacy Policy and Terms of Use. Please take a moment to review them.", "bar_updated": "We've updated the Terms of Use and Privacy Policy for {app}. Please review them.", "later": "Later", "review": "Review", "btn_access": "Request a copy of my data", "btn_delete": "Delete my account", "btn_question": "Ask a privacy question", "your_email": "(the email address of my account)", "mail_access_subject": "{app}: request for a copy of my data", "mail_access_body": "Hello,\n\nPlease send me a copy of the personal information {app} holds about me.\n\nAccount email: {email}\n\nThank you.", "mail_delete_subject": "{app}: please delete my account", "mail_delete_body": "Hello,\n\nPlease delete my {app} account and the personal information linked to it.\n\nAccount email: {email}\n\nThank you.", "mail_question_subject": "{app}: privacy question", "mail_question_body": "Hello,\n\n", "signup_consent": "I'm 16 or older and I agree to the [terms]Terms of Use[/terms] and the [privacy]Privacy Policy[/privacy].", "signup_required": "Please tick the box to continue.", "link": "Privacy & Terms"}, "effective": "October 31, 2026"}, "fr": {"tabs": [{"id": "overview", "title": "Aperçu", "heading": "Confidentialité et conditions", "html": "<p>Image Enhancer est un service privé qui repeint, dans le style demandé (livre illustré, science-fiction, photoréaliste et autres), les images envoyées par les applications d'Arkvital, à l'aide d'un modèle d'image installé sur l'ordinateur de l'exploitant. L'application est exploitée par Arkvital, à Montréal (Québec), Canada. Cette page explique simplement ce que nous faisons de vos renseignements et les règles d'utilisation de Image Enhancer. Les documents complets se trouvent dans les autres onglets.</p>\n<h2>L'essentiel</h2>\n<ul class=\"lk-key\"><li><span class=\"lk-ico\" aria-hidden=\"true\">📋</span><span><b>Ce que nous recueillons :</b> votre adresse courriel et votre nom d'affichage (comptes de la console), et les images que les applications d'Arkvital envoient pour être restylées, avec leurs résultats.</span></li><li><span class=\"lk-ico\" aria-hidden=\"true\">👀</span><span><b>Ce que les autres voient :</b> rien : seul l'exploitant peut ouvrir la console, et chaque application ne voit que ses propres images.</span></li><li><span class=\"lk-ico\" aria-hidden=\"true\">🚫</span><span><b>Jamais vendus.</b> Aucune publicité, aucun pistage, et vos renseignements ne servent jamais à entraîner une IA.</span></li><li><span class=\"lk-ico\" aria-hidden=\"true\">🔒</span><span><b>Conservés en sécurité</b> par notre hébergeur, Anvil, avec des connexions chiffrées et des mots de passe hachés.</span></li><li><span class=\"lk-ico\" aria-hidden=\"true\">🎂</span><span><b>Comptes réservés aux 16 ans et plus.</b></span></li><li><span class=\"lk-ico\" aria-hidden=\"true\">✉️</span><span><b>Vos données, votre choix.</b> Obtenez-en une copie, corrigez-les ou supprimez votre compte en tout temps, par courriel.</span></li></ul>\n<h2>Vos choix</h2>\n<p>Vous pouvez en tout temps demander une copie de vos données, les faire corriger ou supprimer votre compte. Écrivez-nous à <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a> : nous répondons dans un délai de 30 jours, sans frais.</p>\n<!--lk:rights-->\n<h2>Les documents complets</h2>\n<ul><li><a href=\"#\" data-lk-goto=\"privacy\">Politique de confidentialité</a> : ce que nous recueillons, pourquoi, qui nous aide à faire fonctionner Image Enhancer et vos droits.</li><li><a href=\"#\" data-lk-goto=\"terms\">Conditions d'utilisation</a> : les règles d'utilisation de Image Enhancer.</li><li><a href=\"#\" data-lk-goto=\"cookies\">Témoins et stockage</a> : ce que Image Enhancer conserve dans votre navigateur.</li></ul>"}, {"id": "privacy", "title": "Confidentialité", "heading": "Politique de confidentialité", "html": "<p>La présente politique de confidentialité explique comment Arkvital (« nous ») recueille, utilise, communique et protège les renseignements personnels dans Image Enhancer (https://image-enhancer.anvil.app), ainsi que les droits dont vous disposez. Elle a été rédigée pour respecter la <i>Loi sur la protection des renseignements personnels dans le secteur privé</i> du Québec (Loi 25), la LPRPDE du Canada et le Règlement général sur la protection des données (RGPD) de l'Union européenne et du Royaume-Uni.</p>\n<h2>1. Qui est responsable</h2>\n<p>Image Enhancer est exploitée par <b>Arkvital</b>, Montréal (Québec), Canada. Nous sommes responsables des renseignements personnels décrits ici.</p>\n<p>Vous pouvez joindre notre responsable de la protection des renseignements personnels à <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a>.</p>\n<h2>2. Portée de cette politique</h2>\n<p>Cette politique s'applique à Image Enhancer et aux renseignements que vous nous fournissez ou que nous recueillons lorsque vous l'utilisez.</p>\n<h2>3. Ce que nous recueillons</h2>\n<p><b>Les renseignements que vous nous fournissez</b></p>\n<ul><li><b>Compte de la console :</b> votre adresse courriel et un mot de passe, conservé uniquement sous forme de hachage sécurisé (ou l'adresse de votre compte Google si vous continuez avec Google), et votre nom d'affichage. Seul le compte de l'exploitant peut utiliser la console.</li><li><b>Images :</b> chaque image envoyée par une application, son nom de fichier et sa taille, le style et les options demandés (mots ajoutés pour le modèle, fidélité à l'image, taille, type de fichier, graine), la référence de l'application et le résultat restylé.</li><li><b>Détails des tâches :</b> l'application qui l'a envoyée, les heures d'envoi, de début et de fin, le nombre d'essais, une éventuelle erreur, et l'adresse que l'application a demandé de prévenir (URL de rappel) avec le résultat de cet appel.</li><li><b>Clés des applications :</b> le nom de chaque application autorisée, un hachage sécurisé de sa clé (la clé elle-même n'est pas conservée), sa limite horaire, une note et sa dernière utilisation.</li><li><b>Journal d'activité :</b> de courtes lignes comme « une image a été envoyée pour Aquarelle » ou « le PC n'a pas répondu ».</li><li><b>Commentaires :</b> voir 7 (Commentaires via Prepsto).</li></ul>\n<p><b>Les renseignements recueillis automatiquement</b></p>\n<ul><li><b>Renseignements de connexion :</b> la date de votre inscription et de votre dernière connexion, ainsi que les tentatives de connexion échouées (pour protéger votre compte).</li><li><b>Journaux techniques :</b> notre hébergeur enregistre des détails techniques comme les adresses IP, le type de navigateur et les messages d'erreur, afin d'assurer la sécurité et le bon fonctionnement du service.</li></ul>\n<p>Nous ne recueillons que ce qui est nécessaire. Nous ne demandons pas, et vous ne devriez pas ajouter, de renseignements sensibles comme des renseignements de santé, des numéros de pièces d'identité ou des numéros de comptes financiers.</p>\n<h2>4. Pourquoi nous les utilisons et sur quelles bases</h2>\n<ul><li><b>Pour fournir Image Enhancer :</b> créer et gérer votre compte et les fonctions que vous utilisez. <i>Base : nécessaire pour fournir le service demandé (contrat).</i></li><li><b>Pour assurer la sécurité et le bon fonctionnement de Image Enhancer :</b> prévenir les abus et la fraude, corriger les problèmes, faire des sauvegardes. <i>Base : notre intérêt légitime à offrir un service sûr et fiable.</i></li><li><b>Pour communiquer avec vous au sujet de votre compte :</b> par exemple pour réinitialiser votre mot de passe. <i>Base : nécessaire pour fournir le service. Vous pouvez désactiver les avis facultatifs.</i></li><li><b>Pour les fonctions facultatives</b> qui nécessitent votre permission, énumérées à la section 6. <i>Base : votre consentement, que vous pouvez retirer en tout temps.</i></li><li><b>Pour respecter nos obligations légales</b> et répondre aux demandes légitimes des autorités. <i>Base : obligation légale.</i></li></ul>\n<p>Nous ne <b>vendons pas</b> vos renseignements personnels, n'affichons pas de publicité, ne créons pas de profils publicitaires et n'utilisons pas vos renseignements pour entraîner des modèles d'IA.</p>\n<p>Nous vous écrivons seulement au sujet de votre compte et du service que vous utilisez. Nous ne vous enverrons ni messages promotionnels ni infolettres sans que vous l'ayez demandé, et chacun de ces courriels comportera un lien de désabonnement fonctionnel.</p>\n<p>Nous utilisons vos renseignements seulement aux fins décrites dans cette section.</p>\n<h2>5. Ce que les autres peuvent voir</h2>\n<ul><li><b>L'exploitant</b> voit toutes les images, résultats et tâches dans la console.</li><li><b>Chaque application</b> ne voit que les images qu'elle a envoyées, avec sa propre clé.</li><li><b>Toute personne ayant le lien d'un résultat</b> (une longue adresse aléatoire que reçoit l'application) peut ouvrir cette image, jusqu'à la suppression de la tâche.</li></ul>\n<p>Tout le reste demeure confidentiel entre vous et nous.</p>\n<h2>6. Autorisations de l'appareil et fonctions facultatives</h2>\n<p>Image Enhancer n'utilise ni votre caméra, ni votre microphone, ni votre position, ni aucune technologie de pistage permettant de vous identifier, de vous localiser ou d'effectuer un profilage.</p>\n<h2>7. Commentaires par Prepsto</h2>\n<p>Tous les commentaires sur Image Enhancer passent par son bouton <b>Envoyer un commentaire</b> (<i>Submit feedback</i>), qui ouvre Prepsto (prepsto.com), notre propre outil de rétroaction, lui aussi exploité par Arkvital et hébergé par Anvil. Aucun compte n'est nécessaire. Si vous envoyez un commentaire, Prepsto reçoit :</p>\n<ul><li>le type de message (idée, bogue, question ou compliment) et ce que vous écrivez;</li><li>une adresse courriel, seulement si vous en donnez une pour que nous puissions vous répondre;</li><li>l'adresse de la page où vous étiez et de la page qui vous y a mené, la taille de votre écran, le type et la version de votre navigateur, et la langue de votre navigateur, pour nous aider à comprendre et à corriger ce que vous décrivez.</li></ul>\n<p>Vous recevez un lien de suivi privé où vous pouvez suivre ce que devient votre message, lire nos réponses et y répondre; vos réponses sont conservées avec le message. Toute personne qui a ce lien peut l'ouvrir : gardez-le pour vous. Prepsto mémorise vos liens de suivi dans votre navigateur pour afficher « Vos commentaires », et enregistre la dernière ouverture d'une page de suivi.</p>\n<p><b>Vos commentaires restent dans Prepsto</b> et suivent la <a href=\"https://prepsto.com/#legal/privacy\" target=\"_blank\" rel=\"noopener\">politique de confidentialité de Prepsto</a>; Image Enhancer n'en garde aucune copie. Comme Image Enhancer est l'une de nos propres applications, nous sommes directement responsables de vos commentaires, et seules les personnes qui exploitent Image Enhancer les lisent. Nous les conservons jusqu'à ce que nous les ayons traités, et au plus 24 mois, à moins que vous ne nous demandiez de les supprimer plus tôt. Le petit script du bouton est chargé depuis prepsto.com à l'ouverture de Image Enhancer et ne dépose aucun témoin; la fenêtre de commentaire elle-même ne se charge que lorsque vous cliquez sur le bouton.</p>\n<h2>8. Où les images sont traitées</h2>\n<p>Les images ne sont envoyées à aucune entreprise d'IA externe. La file d'attente fonctionne sur Anvil (notre hébergeur) ; chaque image est confiée, une à la fois, à un ordinateur appartenant à l'exploitant, où un modèle d'image ouvert (FLUX.2 [klein] 4B dans ComfyUI) la repeint et renvoie le résultat. Les copies de travail sur cet ordinateur sont supprimées après chaque tâche.</p>\n<h2>9. Les applications qui utilisent ce service</h2>\n<p>Image Enhancer ne reçoit des images que des applications d'Arkvital. Si vous utilisez l'une d'elles, sa propre page Confidentialité et conditions indique quelles images elle envoie ici et pourquoi.</p>\n<h2>10. Qui nous aide à faire fonctionner Image Enhancer</h2>\n<p>Nous communiquons des renseignements personnels uniquement aux fournisseurs de services qui nous aident à faire fonctionner Image Enhancer, et seulement ce dont ils ont besoin :</p>\n<ul><li><b>Anvil</b> (Anvil Works Ltd, Royaume-Uni) : héberge Image Enhancer, sa base de données et la connexion.</li><li><b>Connexion avec Google</b> (Google LLC, États-Unis) : seulement si vous choisissez « Continuer avec Google ». Google confirme votre identité et nous transmet votre adresse courriel. La politique de confidentialité de Google s'applique à votre compte Google.</li><li><b>Google Fonts</b> (Google LLC, États-Unis) : fournit les polices de caractères. Votre navigateur transmet votre adresse IP et des détails sur le navigateur à Google au chargement d'une page.</li><li><b>Prepsto</b> (prepsto.com, notre propre outil de rétroaction, exploité par Arkvital et hébergé par Anvil au Royaume-Uni) : le bouton <b>Envoyer un commentaire</b> charge un petit script depuis prepsto.com, qui reçoit votre adresse IP et des détails sur votre navigateur. Si vous envoyez un commentaire, il reste dans Prepsto et est conservé comme le décrit la politique de confidentialité.</li></ul>\n<p>Ces fournisseurs traitent les renseignements pour notre compte, ou transmettent du contenu directement à votre navigateur, selon leurs propres engagements en matière de confidentialité. Nous pouvons aussi communiquer des renseignements lorsque la loi l'exige, pour protéger la sécurité d'une personne, ou dans le cadre d'une vente ou d'une réorganisation de notre entreprise (le nouvel exploitant devra respecter cette politique).</p>\n<h2>11. Où vos renseignements sont conservés</h2>\n<p>Notre hébergeur conserve vos renseignements sur des serveurs qui peuvent se trouver à l'extérieur du Québec et du Canada, notamment au Royaume-Uni et dans l'Union européenne. Avant de communiquer des renseignements à l'extérieur du Québec, nous avons évalué qu'ils y bénéficieront d'une protection adéquate. Le Royaume-Uni et l'Union européenne sont reconnus comme offrant une protection adéquate, et le Canada bénéficie d'une décision d'adéquation de l'UE pour les organisations commerciales. Lorsqu'un fournisseur est situé aux États-Unis, il s'appuie sur le cadre de protection des données UE–États-Unis ou sur des clauses contractuelles types.</p>\n<h2>12. Combien de temps nous les conservons</h2>\n<ul><li>Les images, résultats et détails des tâches sont supprimés automatiquement 30 jours après l'envoi (l'exploitant peut choisir de 1 à 365 jours), ou plus tôt si l'exploitant ou l'application les supprime.</li><li>Supprimer la clé d'une application annule ses images en attente ; ses tâches terminées restent jusqu'à leur suppression comme ci-dessus.</li><li>Le journal d'activité garde les 400 dernières lignes.</li><li><b>Votre compte et ce que vous y ajoutez :</b> tant que votre compte est ouvert.</li><li><b>Lorsque vous supprimez votre compte</b> (ou nous le demandez) : nous supprimons ou anonymisons vos renseignements personnels dans un délai de 30 jours. Les copies dans les sauvegardes de notre hébergeur disparaissent à mesure que ces sauvegardes sont remplacées.</li><li>Si la loi nous oblige à conserver un renseignement plus longtemps, nous ne conservons que celui-ci, et seulement le temps requis.</li></ul>\n<h2>13. Comment nous les protégeons</h2>\n<p>Les connexions à Image Enhancer sont chiffrées (HTTPS). Les mots de passe sont conservés uniquement sous forme de hachages sécurisés : nous ne pouvons pas les lire. Seules les personnes qui exploitent Image Enhancer peuvent accéder aux données, et seulement lorsque c'est nécessaire. Aucun système n'est parfaitement sûr. Si un incident de confidentialité présente un risque de préjudice sérieux pour vous, nous vous en aviserons, ainsi que les autorités concernées, comme la loi l'exige, et nous le consignerons dans un registre.</p>\n<h2>14. Vos droits</h2>\n<p>Où que vous viviez, vous pouvez nous demander :</p>\n<ul><li>d'<b>accéder</b> aux renseignements personnels que nous détenons sur vous et d'en obtenir une copie;</li><li>de <b>rectifier</b> des renseignements inexacts ou incomplets;</li><li>de <b>supprimer</b> votre compte et vos renseignements personnels;</li><li>de <b>transférer</b> vos renseignements : nous vous les remettrons dans un format structuré et couramment utilisé;</li><li>de <b>retirer votre consentement</b> aux utilisations facultatives, en tout temps;</li><li>de vous <b>opposer à certaines utilisations ou de les limiter</b>, si vous êtes dans l'UE ou au Royaume-Uni;</li><li>de <b>cesser la diffusion</b> de vos renseignements ou de <b>désindexer</b> un hyperlien qui y mène, si vous êtes au Québec et que les conditions prévues par la loi sont remplies.</li></ul>\n<p>Pour exercer ces droits, écrivez à <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a> depuis l'adresse liée à votre compte (ou indiquez-nous comment confirmer votre identité). C'est gratuit. Nous répondons dans un délai de 30 jours.</p>\n<!--lk:rights-->\n<p><b>Si vous habitez aux États-Unis :</b> en Californie et dans les autres États dotés de lois sur la vie privée, vous avez aussi le droit de savoir quels renseignements personnels nous recueillons, utilisons et communiquons, et de ne pas être traité différemment parce que vous exercez vos droits. Nous recueillons les catégories décrites à la section 3 (des identifiants comme votre adresse courriel, ce que vous ajoutez à Image Enhancer et des renseignements techniques sur votre appareil), auprès de vous et de votre appareil, aux fins décrites dans cette politique, et ne les communiquons qu'aux fournisseurs de services énumérés ici. Nous ne vendons pas de renseignements personnels, ne les partageons pas à des fins de publicité ciblée et n'utilisons pas de renseignements sensibles pour tirer des conclusions à votre sujet. Comme nous ne vous pistons pas, un signal Global Privacy Control ou « Do Not Track » n'a rien à désactiver; nous le traitons comme une demande de ne pas vendre ni partager vos renseignements, ce que nous respectons déjà. Une personne que vous autorisez par écrit peut faire une demande en votre nom.</p>\n<p>Si vous n'êtes pas satisfait de notre réponse, vous pouvez porter plainte auprès de la Commission d'accès à l'information du Québec (cai.gouv.qc.ca), du Commissariat à la protection de la vie privée du Canada (priv.gc.ca) ou, dans l'UE ou au Royaume-Uni, de votre autorité locale de protection des données.</p>\n<h2>15. Enfants</h2>\n<p>Les comptes Image Enhancer sont réservés aux personnes de <b>16 ans et plus</b>. Nous ne recueillons pas sciemment de renseignements personnels auprès d'enfants de moins de 16 ans. Si vous pensez qu'un enfant de moins de 16 ans a créé un compte, dites-le-nous et nous le supprimerons.</p>\n<h2>16. Décisions automatisées</h2>\n<p>Nous ne prenons pas de décisions à votre sujet fondées exclusivement sur un traitement automatisé qui produisent des effets juridiques ou des effets importants similaires. Les images sont repeintes automatiquement par un modèle d'image. Le résultat peut différer de l'original dans les détails et le modèle peut se tromper ; l'application qui a envoyé l'image décide de ce qu'elle en fait.</p>\n<h2>17. Témoins et stockage dans le navigateur</h2>\n<p>Image Enhancer n'utilise que les témoins et le stockage dont l'application a besoin pour fonctionner : aucune publicité, aucun pistage. Voir <a href=\"#\" data-lk-goto=\"cookies\">Témoins et stockage</a>.</p>\n<h2>18. Modifications de cette politique</h2>\n<p>Chaque version est datée, et nous en gardons une copie. Si nous apportons un changement important, nous vous en informerons dans Image Enhancer (ou par courriel) avant son entrée en vigueur et vous demanderons d'en prendre connaissance. Nous vous demanderons votre consentement avant d'utiliser vos renseignements à une nouvelle fin, sauf si la loi le permet sans consentement.</p>\n<h2>19. Nous joindre</h2>\n<p>Questions, demandes ou plaintes : <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a>. Notre responsable de la protection des renseignements personnels : Arkvital, Montréal (Québec), Canada.</p>"}, {"id": "terms", "title": "Conditions", "heading": "Conditions d'utilisation", "html": "<p>Les présentes conditions d'utilisation constituent une entente entre vous et <b>Arkvital</b> (« nous »), Montréal (Québec), Canada, exploitant de Image Enhancer (https://image-enhancer.anvil.app). En créant un compte ou en utilisant Image Enhancer, vous les acceptez. Si vous ne les acceptez pas, veuillez ne pas utiliser Image Enhancer.</p>\n<h2>1. Ce qu'est Image Enhancer</h2>\n<p>Image Enhancer est un service privé qui repeint, dans le style demandé (livre illustré, science-fiction, photoréaliste et autres), les images envoyées par les applications d'Arkvital, à l'aide d'un modèle d'image installé sur l'ordinateur de l'exploitant. Notre <a href=\"#\" data-lk-goto=\"privacy\">politique de confidentialité</a> explique comment nous traitons vos renseignements personnels et fait partie des présentes conditions.</p>\n<h2>2. Qui peut utiliser Image Enhancer</h2>\n<ul><li>Vous devez avoir <b>16 ans ou plus</b> pour créer un compte.</li><li>Si vous utilisez Image Enhancer pour une entreprise ou une organisation, vous confirmez être autorisé à accepter ces conditions en son nom, et « vous » inclut alors cette entreprise.</li><li>Vous ne pouvez pas utiliser Image Enhancer si nous avons déjà suspendu votre compte, ou si la loi vous l'interdit.</li></ul>\n<h2>3. Votre compte</h2>\n<ul><li>Fournissez des renseignements exacts et tenez-les à jour.</li><li>Gardez votre mot de passe secret. Vous êtes responsable de ce qui se passe dans votre compte. Prévenez-nous sans délai à <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a> si vous pensez que quelqu'un d'autre l'a utilisé.</li><li>Un compte par personne. Ne partagez pas votre compte et n'en créez pas pour quelqu'un d'autre sans sa permission.</li></ul>\n<h2>4. Votre contenu</h2>\n<p>« Votre contenu » désigne tout ce que vous ajoutez à Image Enhancer : images.</p>\n<ul><li><b>Vous demeurez propriétaire</b> de votre contenu.</li><li><b>Vous nous donnez la permission</b> (une licence mondiale, non exclusive et gratuite) de conserver, copier, afficher, adapter le format et partager votre contenu, mais uniquement pour faire fonctionner, présenter et améliorer Image Enhancer, et uniquement auprès des personnes que vos réglages autorisent. Cette permission prend fin lorsque vous supprimez le contenu ou votre compte, sauf pour les copies que d'autres personnes ont déjà reçues et pour les sauvegardes jusqu'à leur remplacement.</li><li><b>Vous êtes responsable</b> de votre contenu. Vous confirmez détenir les droits nécessaires pour le publier, qu'il est exact au meilleur de votre connaissance et qu'il respecte ces conditions et la loi.</li><li>Si vous pensez qu'un contenu sur Image Enhancer porte atteinte à vos droits, écrivez à <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a> en indiquant le lien et vos explications. Nous examinerons la situation rapidement.</li></ul>\n<h2>5. Utilisation acceptable</h2>\n<p>Lorsque vous utilisez Image Enhancer, vous ne devez pas :</p>\n<ul><li>enfreindre la loi ou aider quelqu'un à l'enfreindre;</li><li>harceler, menacer, intimider, discriminer ou usurper l'identité de quiconque;</li><li>publier du contenu haineux, sexuellement explicite, violent, trompeur ou qui porte atteinte aux droits d'autrui (notamment le droit d'auteur, les marques de commerce et la vie privée);</li><li>communiquer les renseignements personnels d'autres personnes sans leur permission;</li><li>envoyer des pourriels ou de la publicité non sollicitée;</li><li>tenter d'accéder à des comptes ou à des données qui ne sont pas les vôtres, tester ou contourner notre sécurité, ou perturber le service;</li><li>copier le service ou en extraire des données au moyen de robots ou d'outils de moissonnage sans notre permission écrite;</li><li>téléverser des virus ou du code malveillant.</li></ul>\n<h2>6. Modération et application des règles</h2>\n<p>Nous pouvons examiner, masquer ou retirer du contenu, et restreindre, suspendre ou fermer des comptes, si nous croyons raisonnablement qu'une personne a enfreint ces conditions ou la loi, ou pour protéger des personnes ou Image Enhancer. Lorsque c'est raisonnable, nous vous en expliquerons la raison. Si vous pensez que nous avons fait erreur, écrivez à <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a> et nous réexaminerons la situation.</p>\n<h2>7. Qui peut utiliser le service</h2>\n<p>Seules les applications ayant reçu une clé de l'exploitant peuvent envoyer des images, et seul l'exploitant peut utiliser la console. Les clés sont réservées aux serveurs : une application ne doit jamais placer sa clé dans une page web ou une application mobile. Une clé peut être désactivée ou remplacée à tout moment.</p>\n<h2>8. Images et résultats</h2>\n<p>Une application ne peut envoyer que des images qu'elle a le droit d'utiliser et de faire modifier. Les propriétaires des images conservent leurs droits ; l'exploitant ne revendique aucun droit sur les images ni sur les résultats. Les résultats sont produits par un modèle d'image et fournis tels quels, sans garantie sur leur apparence ni sur leur délai : les temps estimés ne sont que des estimations, et les images attendent tant que l'ordinateur de l'exploitant est éteint.</p>\n<h2>9. Nos droits sur Image Enhancer</h2>\n<p>Le logiciel, le design, les textes, les illustrations et les autres contenus que nous fournissons dans Image Enhancer nous appartiennent ou appartiennent à ceux qui nous ont accordé une licence. Nous vous accordons un droit personnel, non exclusif, non transférable et révocable d'utiliser Image Enhancer conformément à ces conditions. Si vous nous transmettez des idées ou des commentaires, nous pouvons les utiliser librement, sans rien vous devoir.</p>\n<h2>10. Autres services et liens</h2>\n<p>Image Enhancer s'appuie sur des services exploités par des tiers (énumérés dans la politique de confidentialité) et peut contenir des liens vers d'autres sites. Nous ne sommes pas responsables de leur contenu ni de leur fonctionnement, et leur utilisation est régie par leurs propres conditions.</p>\n<h2>11. Changements et disponibilité</h2>\n<p>Nous améliorons constamment Image Enhancer : les fonctions peuvent donc changer. Nous pouvons aussi suspendre ou cesser tout ou partie de Image Enhancer. Nous tenterons de donner un préavis raisonnable des changements importants et, avant de fermer Image Enhancer, nous vous offrirons un moyen d'obtenir une copie de vos renseignements. Nous ne garantissons pas que Image Enhancer sera toujours disponible ou exempte d'erreurs.</p>\n<h2>12. Avis de non-responsabilité</h2>\n<p>Image Enhancer est fournie <b>« telle quelle » et « selon sa disponibilité »</b>. Dans la mesure permise par la loi, nous ne donnons aucune garantie autre que celles prévues dans ces conditions, notamment quant à l'adaptation à un usage particulier ou à l'exactitude du contenu (le nôtre ou celui des autres utilisateurs).</p>\n<h2>13. Limitation de responsabilité</h2>\n<p>Dans la mesure permise par la loi, nous ne sommes pas responsables des pertes indirectes, accessoires ou consécutives, comme une perte de profits, de données ou d'occasions, et notre responsabilité totale envers vous pour toute réclamation liée à Image Enhancer est limitée au plus élevé des montants suivants : la somme que vous nous avez versée pour Image Enhancer au cours des 12 mois précédant la réclamation, ou 100 $ CA.</p>\n<p>Nous ne sommes pas responsables des retards ou des défaillances causés par des événements hors de notre contrôle raisonnable, comme une panne d'Internet ou de nos fournisseurs de services, une panne de courant, une catastrophe naturelle ou une décision gouvernementale.</p>\n<p>Rien dans ces conditions ne limite une responsabilité qui ne peut l'être en vertu de la loi, notamment pour un préjudice corporel ou moral, ou pour une faute intentionnelle ou lourde, et rien ne vous prive des droits que vous accorde, en tant que consommateur, la loi de l'endroit où vous vivez (par exemple, la <i>Loi sur la protection du consommateur</i> du Québec).</p>\n<h2>14. Responsabilité en cas d'usage abusif</h2>\n<p>Si vous enfreignez ces conditions ou la loi en utilisant Image Enhancer et que quelqu'un présente une réclamation contre nous pour cette raison, vous êtes responsable du préjudice que cela nous cause, comme le prévoit la loi. Si vous utilisez Image Enhancer pour une entreprise ou une organisation, celle-ci s'engage aussi à nous indemniser des pertes, dommages et frais juridiques raisonnables découlant de telles réclamations, y compris celles qui visent son contenu. Ce paragraphe ne s'applique pas là où la loi l'interdit, et il ne vous rend jamais responsable de nos propres erreurs.</p>\n<h2>15. Fin de l'utilisation</h2>\n<p>Vous pouvez cesser d'utiliser Image Enhancer en tout temps et nous demander de supprimer votre compte à <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a>. Nous pouvons suspendre ou fermer votre compte comme décrit à la section 6. Les sections qui, par leur nature, doivent survivre (par exemple les sections 9, 12, 13, 14 et 17) demeurent en vigueur après la fermeture de votre compte.</p>\n<h2>16. Modifications de ces conditions</h2>\n<p>Nous pouvons mettre à jour ces conditions. Chaque version est datée, et nous en gardons une copie. Si un changement est important, nous vous en informerons dans Image Enhancer ou par courriel, avec le nouveau texte et sa date d'entrée en vigueur, au moins 30 jours avant qu'il s'applique à votre compte, et vous demanderons de l'accepter. Si vous n'acceptez pas le changement, vous pouvez le refuser en fermant votre compte, sans frais, jusqu'à 30 jours après son entrée en vigueur. Les personnes qui créent un compte après un changement acceptent la version qui leur est présentée.</p>\n<h2>17. Droit applicable et différends</h2>\n<p>Ces conditions sont régies par les lois du Québec et les lois fédérales du Canada qui s'y appliquent. Tout différend sera soumis aux tribunaux du district judiciaire de Montréal (Québec), sauf si la loi de l'endroit où vous vivez vous permet de vous adresser aux tribunaux de votre région. Avant de vous adresser aux tribunaux, veuillez nous écrire à <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a> : la plupart des problèmes se règlent rapidement.</p>\n<h2>18. Dispositions générales</h2>\n<ul><li><b>L'entente complète :</b> ces conditions, la politique de confidentialité et les règles qui vous sont présentées pour une fonction précise forment l'entente complète entre vous et nous au sujet de Image Enhancer.</li><li><b>Si une partie est invalide :</b> si un tribunal juge une partie de ces conditions invalide, le reste continue de s'appliquer, et la partie invalide est remplacée par une disposition valide aussi proche que possible de l'intention d'origine.</li><li><b>Aucune renonciation :</b> si nous n'exigeons pas tout de suite le respect d'une partie de ces conditions, nous pouvons quand même l'exiger plus tard.</li><li><b>Cession :</b> nous pouvons céder ces conditions à une entreprise qui reprend Image Enhancer, et vos droits en vertu de celles-ci et de la politique de confidentialité restent les mêmes. Vous ne pouvez pas céder votre compte ni ces conditions à quelqu'un d'autre sans notre permission.</li><li><b>Avis :</b> nous pouvons communiquer avec vous dans Image Enhancer ou à l'adresse courriel de votre compte, et vous pouvez nous joindre à <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a>. Les messages envoyés de cette façon valent avis écrit.</li></ul>\n<h2>19. Langue</h2>\n<p>Ces conditions sont offertes en français et en anglais. La version française vous a d'abord été présentée, et vous avez choisi d'utiliser la version dans la langue que vous lisez. <i>These terms are available in French and in English.</i></p>\n<h2>20. Nous joindre</h2>\n<p>Arkvital, Montréal (Québec), Canada. Courriel : <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a>.</p>"}, {"id": "cookies", "title": "Témoins", "heading": "Témoins et stockage", "html": "<p>Cette page explique les témoins (cookies) et le stockage dans le navigateur qu'utilise Image Enhancer. En bref : <b>uniquement ce dont Image Enhancer a besoin pour fonctionner</b>. Aucun témoin publicitaire, analytique ou de pistage, et nous ne vous suivons pas sur le Web. C'est pourquoi il n'y a pas de bandeau sur les témoins.</p>\n<h2>Ce que Image Enhancer conserve dans votre navigateur</h2>\n<ul><li><b>Session de connexion</b> (témoin déposé par notre hébergeur Anvil) : vous garde connecté pendant que vous utilisez Image Enhancer et protège contre les requêtes falsifiées. Il est supprimé lorsque vous fermez le navigateur ou vous déconnectez.</li><li><b>« Se souvenir de moi »</b> (seulement si vous le choisissez à la connexion) : vous garde connecté sur cet appareil pendant une durée limitée.</li><li><b>Préférences</b> (stockage local) : thème clair ou sombre, et le dernier style et la dernière fidélité du banc d'essai.</li><li><b>Commentaires</b> (seulement après un clic sur <b>Envoyer un commentaire</b>) : la fenêtre de commentaire provient de prepsto.com et peut utiliser son propre témoin de session essentiel, ainsi qu'un stockage local qui mémorise les liens de suivi privés des messages que vous avez envoyés, pour afficher « Vos commentaires ». Le script du bouton ne dépose rien tant que vous n'avez pas cliqué.</li><li><b>Préférences de la page Confidentialité et conditions</b> (stockage local) : votre langue sur cette page, le fait que vous avez coché la case d'acceptation à l'inscription, et si vous avez choisi « Plus tard » dans le rappel. Rien de personnel.</li></ul>\n<p>Tous ces éléments sont strictement nécessaires pour fournir le service demandé : la loi n'exige donc pas votre consentement préalable. Nous vous le demanderons avant d'ajouter quoi que ce soit qui ne l'est pas, comme des outils d'analyse.</p>\n<h2>Contenu chargé depuis d'autres services</h2>\n<p>Pour afficher Image Enhancer, votre navigateur récupère quelques éléments directement auprès d'autres services. Ceux-ci reçoivent alors votre adresse IP et des renseignements de base sur votre navigateur, comme pour tout site Web :</p>\n<ul><li><b>Google Fonts</b> (Google LLC, États-Unis) : fournit les polices de caractères. Votre navigateur transmet votre adresse IP et des détails sur le navigateur à Google au chargement d'une page.</li><li><b>Prepsto</b> (prepsto.com, notre propre outil de rétroaction, exploité par Arkvital et hébergé par Anvil au Royaume-Uni) : le bouton <b>Envoyer un commentaire</b> charge un petit script depuis prepsto.com, qui reçoit votre adresse IP et des détails sur votre navigateur. Si vous envoyez un commentaire, il reste dans Prepsto et est conservé comme le décrit la politique de confidentialité.</li></ul>\n<p>Ils ne reçoivent pas de notre part les renseignements de votre compte.</p>\n<h2>Vos choix</h2>\n<p>Vous pouvez supprimer les témoins et les données du site en tout temps dans les réglages de votre navigateur. Vous serez alors déconnecté. Vous pouvez aussi bloquer les témoins, mais vous ne pourrez plus vous connecter.</p>\n<p>Questions : <a href=\"mailto:arkvital@outlook.com\">arkvital@outlook.com</a>.</p>"}], "ui": {"lang_name": "Français", "title": "Confidentialité et conditions", "back": "Retour à {app}", "print": "Imprimer", "effective": "En vigueur depuis le {date} · Version {version}", "guest_note": "Rien à accepter tant que vous n'êtes pas connecté. Nous vous le demanderons à la création de votre compte.", "accepted_on": "Vous avez accepté les conditions d'utilisation et la politique de confidentialité le {date}.", "page_consent": "J'ai 16 ans ou plus, j'accepte les conditions d'utilisation et j'ai lu la politique de confidentialité.", "agree": "J'accepte", "saving": "Enregistrement…", "save_error": "Impossible d'enregistrer votre réponse. Vérifiez votre connexion et réessayez.", "bar_new": "{app} a maintenant une politique de confidentialité et des conditions d'utilisation. Prenez un moment pour les consulter.", "bar_updated": "Nous avons mis à jour les conditions d'utilisation et la politique de confidentialité de {app}. Veuillez les consulter.", "later": "Plus tard", "review": "Consulter", "btn_access": "Obtenir une copie de mes données", "btn_delete": "Supprimer mon compte", "btn_question": "Poser une question", "your_email": "(l'adresse courriel de mon compte)", "mail_access_subject": "{app} : demande de copie de mes données", "mail_access_body": "Bonjour,\n\nVeuillez m'envoyer une copie des renseignements personnels que {app} détient à mon sujet.\n\nCourriel du compte : {email}\n\nMerci.", "mail_delete_subject": "{app} : suppression de mon compte", "mail_delete_body": "Bonjour,\n\nVeuillez supprimer mon compte {app} et les renseignements personnels qui y sont liés.\n\nCourriel du compte : {email}\n\nMerci.", "mail_question_subject": "{app} : question sur la confidentialité", "mail_question_body": "Bonjour,\n\n", "signup_consent": "J'ai 16 ans ou plus et j'accepte les [terms]conditions d'utilisation[/terms] et la [privacy]politique de confidentialité[/privacy].", "signup_required": "Veuillez cocher la case pour continuer.", "link": "Confidentialité et conditions"}, "effective": "31 octobre 2026"}}});
