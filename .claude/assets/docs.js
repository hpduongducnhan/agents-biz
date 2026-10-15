/* Trang review tài liệu BizWithAgents — viết tay (không sinh). Không phụ thuộc thư viện; sơ đồ là HTML archify nhúng iframe. */
(function () {
  "use strict";

  var doc = document.documentElement;
  var ROOT = doc.getAttribute("data-root") || "";
  var THEME_KEY = "mp-docs-theme";

  function store(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      localStorage.setItem(key, value);
    } catch (e) {
      return null;
    }
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  // ── giao diện sáng / tối ──────────────────────────────────────────────────
  function setTheme(theme) {
    doc.dataset.theme = theme;
    store(THEME_KEY, theme);
    syncDiagrams();
  }

  function initTheme() {
    var btn = document.querySelector(".theme-toggle");
    if (!btn) return;
    btn.addEventListener("click", function () {
      setTheme(doc.dataset.theme === "dark" ? "light" : "dark");
    });
  }

  // ── menu trên màn hẹp ─────────────────────────────────────────────────────
  function initNav() {
    var btn = document.querySelector(".nav-toggle");
    var scrim = document.querySelector(".scrim");
    var sidebar = document.getElementById("sidebar");
    function set(open) {
      document.body.classList.toggle("nav-open", open);
      if (btn) btn.setAttribute("aria-expanded", String(open));
      if (scrim) scrim.hidden = !open;
    }
    if (btn) btn.addEventListener("click", function () { set(!document.body.classList.contains("nav-open")); });
    if (scrim) scrim.addEventListener("click", function () { set(false); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") set(false);
    });
    var active = sidebar && sidebar.querySelector("a.active");
    if (active && sidebar.scrollHeight > sidebar.clientHeight) {
      sidebar.scrollTop = active.offsetTop - sidebar.clientHeight / 3;
    }
  }

  // ── mục lục: đánh dấu mục đang đọc ────────────────────────────────────────
  function initToc() {
    var links = Array.prototype.slice.call(document.querySelectorAll(".toc a[href^='#']"));
    if (!links.length || !("IntersectionObserver" in window)) return;
    var byId = {};
    var targets = [];
    links.forEach(function (a) {
      var id = decodeURIComponent(a.getAttribute("href").slice(1));
      var el = document.getElementById(id);
      if (el) {
        byId[id] = a;
        targets.push(el);
      }
    });
    var visible = {};
    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (en) { visible[en.target.id] = en.isIntersecting; });
        var current = null;
        for (var i = 0; i < targets.length; i++) {
          if (visible[targets[i].id]) { current = targets[i].id; break; }
        }
        if (!current) return;
        links.forEach(function (a) { a.classList.remove("active"); });
        byId[current].classList.add("active");
      },
      { rootMargin: "-64px 0px -65% 0px" }
    );
    targets.forEach(function (t) { io.observe(t); });
  }

  // ── nút sao chép code ─────────────────────────────────────────────────────
  function initCopy() {
    document.querySelectorAll(".code").forEach(function (box) {
      var pre = box.querySelector("pre");
      if (!pre) return;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "copy-btn";
      btn.textContent = "Sao chép";
      btn.addEventListener("click", function () {
        var text = pre.innerText;
        var done = function () {
          btn.textContent = "Đã chép";
          setTimeout(function () { btn.textContent = "Sao chép"; }, 1500);
        };
        if (navigator.clipboard && window.isSecureContext) {
          navigator.clipboard.writeText(text).then(done, function () { fallbackCopy(text); done(); });
        } else {
          fallbackCopy(text);
          done();
        }
      });
      box.appendChild(btn);
    });
  }

  function fallbackCopy(text) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); } catch (e) { /* trình duyệt chặn → bỏ qua */ }
    ta.remove();
  }

  // ── sơ đồ archify: iframe cùng giao diện sáng / tối với trang ─────────────
  function syncDiagrams() {
    var theme = doc.dataset.theme === "dark" ? "dark" : "light";
    document.querySelectorAll("iframe.diagram-frame").forEach(function (f) {
      var base = f.getAttribute("src").split("&theme=")[0];
      var next = base + "&theme=" + theme;
      if (f.getAttribute("src") !== next) f.setAttribute("src", next);
    });
    document.querySelectorAll("a.diagram-open").forEach(function (a) {
      a.setAttribute("href", a.getAttribute("href").split("?")[0] + "?theme=" + theme);
    });
  }

  // ── lọc tài liệu theo trạng thái (trang index) ────────────────────────────
  function initFilters() {
    var chips = Array.prototype.slice.call(document.querySelectorAll(".chip[data-filter]"));
    if (!chips.length) return;
    chips.forEach(function (chip) {
      chip.addEventListener("click", function () {
        var f = chip.getAttribute("data-filter");
        chips.forEach(function (c) {
          c.classList.toggle("active", c === chip);
          c.setAttribute("aria-pressed", String(c === chip));
        });
        document.querySelectorAll(".domain").forEach(function (card) {
          var shown = 0;
          var items = Array.prototype.slice.call(card.querySelectorAll(".doc-list > li"));
          items.forEach(function (li) {
            if (!li.classList.contains("doc")) return;
            var ok = !f || li.getAttribute("data-status") === f;
            li.hidden = !ok;
            if (ok) shown++;
          });
          items.forEach(function (li, i) {  // nhãn mục (Kiến trúc / Thiết kế / Plan) ẩn khi không còn tài liệu bên dưới
            if (!li.classList.contains("doc-sec")) return;
            var any = false;
            for (var j = i + 1; j < items.length && !items[j].classList.contains("doc-sec"); j++) {
              if (!items[j].hidden) { any = true; break; }
            }
            li.hidden = !any;
          });
          card.hidden = f !== "" && shown === 0;
        });
      });
    });
  }

  // ── tìm kiếm (chỉ mục nạp lần đầu gõ) ─────────────────────────────────────
  function fold(s) {
    var out = [];
    for (var ch of s) {
      var c = ch.normalize("NFD")[0].toLowerCase();
      out.push(c === "đ" ? "d" : c);
    }
    return out;
  }

  var index = null;
  var indexReady = null;

  function loadIndex() {
    indexReady = indexReady || loadScript(ROOT + "assets/search-index.js").then(function () {
      index = (window.DOCS_SEARCH || []).map(function (d) {
        return {
          d: d,
          t: fold(d.t).join(""),
          h: d.h.map(function (h) { return fold(h[0]).join(""); }),
          x: fold(d.x).join(""),
          dom: fold(d.d).join(""),
        };
      });
    });
    return indexReady;
  }

  function esc(s) {
    return s.replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; });
  }

  function mark(text, terms) {
    var chars = Array.from(text);
    var folded = fold(text).join("");
    var hits = new Array(chars.length).fill(false);
    terms.forEach(function (t) {
      var at = folded.indexOf(t);
      while (at !== -1) {
        for (var k = at; k < at + t.length; k++) hits[k] = true;
        at = folded.indexOf(t, at + t.length);
      }
    });
    var html = "";
    var open = false;
    chars.forEach(function (c, i) {
      if (hits[i] && !open) { html += "<mark>"; open = true; }
      if (!hits[i] && open) { html += "</mark>"; open = false; }
      html += esc(c);
    });
    return html + (open ? "</mark>" : "");
  }

  function snippet(entry, terms) {
    var at = entry.x.indexOf(terms[0]);
    if (at === -1) return "";
    var chars = Array.from(entry.d.x);
    var start = Math.max(0, at - 50);
    var text = chars.slice(start, at + 110).join("");
    return (start > 0 ? "…" : "") + mark(text, terms) + (at + 110 < chars.length ? "…" : "");
  }

  function search(q) {
    var terms = fold(q.trim()).join("").split(/\s+/).filter(Boolean);
    if (!terms.length || !index) return [];
    var results = [];
    index.forEach(function (e) {
      var score = 0;
      var heading = -1;
      for (var i = 0; i < terms.length; i++) {
        var t = terms[i];
        var s = 0;
        if (e.t.indexOf(t) !== -1) s += e.t.indexOf(t) === 0 ? 14 : 10;
        for (var j = 0; j < e.h.length; j++) {
          if (e.h[j].indexOf(t) !== -1) {
            s += 5;
            if (heading === -1) heading = j;
            break;
          }
        }
        if (e.dom.indexOf(t) !== -1) s += 2;
        if (e.x.indexOf(t) !== -1) s += 1;
        if (!s) return;  // mọi từ phải khớp
        score += s;
      }
      results.push({ e: e, score: score, heading: heading });
    });
    results.sort(function (a, b) { return b.score - a.score; });
    return results.slice(0, 12).map(function (r) {
      var h = r.heading !== -1 ? r.e.d.h[r.heading] : null;
      return {
        href: ROOT + r.e.d.u + (h ? "#" + encodeURIComponent(h[1]) : ""),
        title: mark(r.e.d.t, terms),
        where: esc(r.e.d.d) + (h ? " › " + mark(h[0], terms) : ""),
        status: r.e.d.s,
        snip: h ? "" : snippet(r.e, terms),
      };
    });
  }

  var STATUS_CLASS = { "ĐÃ CHỐT": "locked", "Xong": "done", "ĐỀ XUẤT": "proposed", "TẦM NHÌN": "vision", "Đang làm": "wip", "Chưa bắt đầu": "todo" };

  function initSearch() {
    var input = document.getElementById("search");
    var box = document.getElementById("search-results");
    if (!input || !box) return;
    var sel = -1;

    function items() { return Array.prototype.slice.call(box.querySelectorAll("a")); }

    function select(i) {
      var list = items();
      if (!list.length) return;
      sel = (i + list.length) % list.length;
      list.forEach(function (a, k) { a.setAttribute("aria-selected", String(k === sel)); });
      list[sel].scrollIntoView({ block: "nearest" });
    }

    function show(open) {
      box.hidden = !open;
      input.setAttribute("aria-expanded", String(open));
    }

    function update() {
      var q = input.value;
      if (!q.trim()) { show(false); return; }
      loadIndex().then(function () {
        if (input.value !== q) return;
        var res = search(q);
        sel = -1;
        box.innerHTML = res.length
          ? res.map(function (r) {
              var b = r.status ? '<span class="badge st-' + STATUS_CLASS[r.status] + '">' + esc(r.status) + "</span>" : "";
              return '<a role="option" href="' + esc(r.href) + '"><div class="sr-title">' + r.title + b + '</div><div class="sr-where">' + r.where + "</div>" + (r.snip ? '<div class="sr-snip">' + r.snip + "</div>" : "") + "</a>";
            }).join("")
          : '<div class="sr-empty">Không thấy tài liệu nào khớp “' + esc(q) + "”.</div>";
        show(true);
      }, function () {
        box.innerHTML = '<div class="sr-empty">Không nạp được chỉ mục tìm kiếm.</div>';
        show(true);
      });
    }

    input.addEventListener("input", update);
    input.addEventListener("focus", function () { loadIndex(); if (input.value.trim()) update(); });
    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); select(sel + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); select(sel - 1); }
      else if (e.key === "Enter") {
        var list = items();
        var target = list[sel] || list[0];
        if (target) { e.preventDefault(); window.location.href = target.href; }
      } else if (e.key === "Escape") { show(false); input.blur(); }
    });
    document.addEventListener("click", function (e) {
      if (!box.contains(e.target) && e.target !== input) show(false);
    });
    document.addEventListener("keydown", function (e) {
      var tag = (e.target && e.target.tagName) || "";
      if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(tag) && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        input.focus();
        input.select();
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initTheme();
    initNav();
    initToc();
    initCopy();
    initFilters();
    initSearch();
    syncDiagrams();
  });
})();
