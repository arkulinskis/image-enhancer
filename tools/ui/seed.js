/* For screenshots of the console: sign in as the owner, make an API key with a very long app name (worst-case data),
   and send three pictures through the HTTP API with it, so the Queue has waiting jobs. Resolves to window.SEED. */
(async function () {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function until(fn, what, ms) {
    const end = Date.now() + (ms || 30000);
    while (Date.now() < end) { try { const v = fn(); if (v) return v; } catch (e) {} await sleep(150); }
    throw new Error('timed out waiting for: ' + what);
  }
  const $ = (s) => document.querySelector(s), $$ = (s) => Array.from(document.querySelectorAll(s));
  function type(input, value) {
    input.focus(); input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true })); input.dispatchEvent(new Event('change', { bubbles: true }));
  }
  const fields = () => $$('.au-card input[type=text], .au-card input[type=email], .au-card input[type=password]').filter((i) => i.offsetParent);
  function png(w, h, hue) {
    const c = document.createElement('canvas'); c.width = w; c.height = h;
    const g = c.getContext('2d');
    g.fillStyle = 'hsl(' + hue + ',55%,72%)'; g.fillRect(0, 0, w, h);
    g.fillStyle = '#f4c446'; g.beginPath(); g.arc(w * .75, h * .28, h * .12, 0, 7); g.fill();
    g.fillStyle = '#e2533a'; g.beginPath(); g.moveTo(w * .2, h * .62); g.lineTo(w * .4, h * .35); g.lineTo(w * .6, h * .62); g.fill();
    g.fillStyle = '#3a704a'; g.fillRect(0, h * .7, w, h * .3);
    return c.toDataURL('image/png');
  }
  try {
    const pw = 'Hb-local-admin-Kq7-2026';
    if (location.hash !== '#auth') window.UI_READY = false;
    location.hash = '#auth';
    await until(() => window.UI_READY && (location.hash === '#home' || fields().length >= 2), 'sign-in', 60000);
    if (location.hash !== '#home') {
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
    }
    await until(() => location.hash === '#home' && window.UI_READY && $('.ie-pc'), 'home', 60000);
    // a key with a long name, through the real dialog
    window.UI_READY = false; location.hash = '#keys';
    await until(() => window.UI_READY && $('.anvil-role-ic-plus button'), 'keys');
    $('.anvil-role-ic-plus button').click();
    const box = await until(() => $('.ie-keyedit input'), 'dialog');
    type(box, 'Bilderbuchwerkstattverwaltungsprogramm ' + Date.now().toString(36));
    $('.ie-keyedit .anvil-role-btn-primary button').click();
    const keyEl = await until(() => $$('.ie-keymade .anvil-role-ie-code').find((e) => /^ie_/.test(e.textContent.trim())), 'key');
    const key = keyEl.textContent.trim();
    $('.ie-keymade .anvil-role-btn-primary button').click();
    await sleep(800);
    const styles = ['kids_book', 'realistic', 'watercolor'];
    for (let n = 0; n < 3; n++) {
      await fetch(location.origin + '/_/api/v1/jobs', { method: 'POST', headers: { Authorization: 'Bearer ' + key, 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: png(480, 360, 190 + n * 40), style: styles[n], ref: n === 0 ? 'order-2026-11-07-a-very-long-reference-number-0000000001' : 'order-' + (n + 1) }) });
    }
    window.UI_READY = false; location.hash = '#home';
    await until(() => window.UI_READY, 'home again');
    window.SEED = { home: '#home', key: key.slice(0, 9) };
    return window.SEED;
  } catch (e) {
    return { error: String(e && e.message || e) };
  }
})();
