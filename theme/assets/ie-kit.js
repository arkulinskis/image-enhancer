/* Image Enhancer browser helpers (the test bench). Python calls these through anvil.js; promises are awaited there.
   IE.rasterize(url, maxSide) -> a PNG Blob of an SVG (or any picture the browser can draw), longest side maxSide.
   IE.copy(text)              -> copies text to the clipboard (true / false). */
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
  IE.copy = function (text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(function () { return true; }, function () { return false; });
    }
    return Promise.resolve(false);
  };
})();
