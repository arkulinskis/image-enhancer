/* Image Enhancer browser helpers (the test bench). Python calls these through anvil.js; promises are awaited there.
   IE.rasterize(url, maxSide) -> a PNG Blob of an SVG (or any picture the browser can draw), longest side maxSide.
   IE.copy(text)              -> copies text to the clipboard (true / false).
   IE.heatmap(el, days)       -> draws the Health page's uptime map into el: one row per day, 24 hour squares.
                                 days = [{label, cells: [{state: known|unknown|future, up: 0..1, done, failed, hour}]}] */
(function () {
  var IE = window.IE = window.IE || {};
  IE.rasterize = function (url, maxSide) {
    maxSide = maxSide || 1536;
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () {
        var w = img.naturalWidth || 1024, h = img.naturalHeight || 1024;
        var k = maxSide / Math.max(w, h);
        if (k > 1 && !/\.svg|svg\+xml/i.test(url)) k = 1;  // never enlarge a bitmap; SVGs draw sharp at any size
        var c = document.createElement('canvas');
        c.width = Math.max(1, Math.round(w * k)); c.height = Math.max(1, Math.round(h * k));
        var g = c.getContext('2d');
        g.fillStyle = '#ffffff'; g.fillRect(0, 0, c.width, c.height);  // vector art usually expects a white page
        g.drawImage(img, 0, 0, c.width, c.height);
        c.toBlob(function (b) { if (b) resolve(b); else reject(new Error('Could not draw the picture')); }, 'image/png');
      };
      img.onerror = function () { reject(new Error('The browser could not open that picture')); };
      img.src = url;
    });
  };
  IE.heatmap = function (el, days) {
    if (!el) return;
    var esc = function (t) { return String(t).replace(/[&<>"]/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]; }); };
    var html = '<div class="ie-heat-row ie-heat-hours" aria-hidden="true"><span></span>';
    for (var h = 0; h < 24; h++) html += '<i>' + (h % 6 === 0 ? h : '') + '</i>';
    html += '</div>';
    (days || []).forEach(function (d) {
      html += '<div class="ie-heat-row"><span>' + esc(d.label) + '</span>';
      (d.cells || []).forEach(function (c, i) {
        var lvl = 'f', tip = d.label + ' ' + (i < 10 ? '0' : '') + i + ':00';
        if (c.state === 'unknown') { lvl = 'u'; tip += ': no record yet'; }
        else if (c.state === 'future') { lvl = 'f'; tip = ''; }
        else {
          var up = c.up || 0;
          lvl = up <= 0 ? '0' : up < 0.34 ? '1' : up < 0.67 ? '2' : up < 1 ? '3' : '4';
          tip += ': PC there ' + Math.round(up * 100) + '% of the hour';
          if (c.done) tip += ', ' + c.done + ' done';
          if (c.failed) tip += ', ' + c.failed + ' failed';
        }
        html += '<b class="l' + lvl + (c.failed ? ' x' : '') + '"' + (tip ? ' title="' + esc(tip) + '"' : '') + '></b>';
      });
      html += '</div>';
    });
    el.innerHTML = html;
  };
  IE.copy = function (text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(function () { return true; }, function () { return false; });
    }
    return Promise.resolve(false);
  };
})();
