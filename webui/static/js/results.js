// «Подборка»: строит карточки с двойными кольцами по /run/results (живой прогон).
(function () {
  "use strict";
  var grid = document.querySelector("[data-res-grid]");
  var empty = document.querySelector("[data-res-empty]");
  var filtersEl = document.querySelector("[data-res-filters]");
  var sliderEl = document.querySelector("[data-res-slider]");
  var minEl = document.querySelector("[data-res-min]");
  var minValEl = document.querySelector("[data-res-minval]");
  var countEl = document.querySelector("[data-res-count]");
  if (!grid) return;
  var filter = "all";
  var minPct = 0;
  var lastData = [];   // последняя выборка с сервера — фильтруем её ползунком без перезапроса
  var last = "";

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function card(r) {
    var v = window.verdictOf(r.verdict, r.resume);
    var summary = r.verdict_summary ? " · " + esc(r.verdict_summary) : "";
    var letter = r.has_cover
      ? '<button class="res-btn"><i class="ti ti-mail"></i>Письмо</button>' : "";
    var open = r.link
      ? '<a class="res-btn" href="' + esc(r.link) + '" target="_blank" rel="noopener"><i class="ti ti-external-link"></i>Открыть</a>'
      : '<button class="res-btn"><i class="ti ti-external-link"></i>Открыть</button>';
    return (
      '<div class="res-card" data-match-key="' + esc(r.key || "") + '">' +
      '<div class="res-card__head"><div class="res-card__main">' +
      '<div class="res-card__role">' + esc(r.role) + "</div>" +
      '<div class="res-card__co">' + esc(r.company) + "</div>" +
      (r.track ? '<span class="track-tag">' + esc(r.track) + "</span>" : "") +
      '</div><div class="res-card__ring">' + window.scoreRing(r.resume, r.map) +
      '<div class="res-card__map"><i class="ti ti-map-2"></i>карта ' + r.map + "%</div></div></div>" +
      '<div class="verdict" style="color:' + v.c + '"><i class="ti ' + v.ic + '"></i>' + v.lbl + summary + "</div>" +
      '<div class="res-card__gap">' + esc(r.gap) + "</div>" +
      investigatorBlock(r.investigation) +
      '<div class="res-card__btns">' + open + letter +
      '<button class="res-btn" data-find-contact data-role="' + esc(r.role) +
      '" data-company="' + esc(r.company) + '" data-link="' + esc(r.link || "") +
      '"><i class="ti ti-user-search"></i>Контакт</button>' +
      (r.key ? '<button class="res-btn" data-archive title="убрать из подборки"><i class="ti ti-archive"></i>В архив</button>' : "") +
      '</div>' +
      '<div class="res-card__contacts" data-card-contacts hidden></div></div>'
    );
  }

  // Доп. выдача от инвестигатора контактов (с именем) — ранжированные контакты.
  function investigatorBlock(list) {
    if (!list || !list.length) return "";
    var rows = list.map(function (c) {
      var conf = c.confidence ? '<span class="inv-row__conf mono">' + c.confidence + "%</span>" : "";
      var route = c.route ? '<span class="inv-row__route">' + esc(c.route) + "</span>" : "";
      var name = c.link
        ? '<a href="' + esc(c.link) + '" target="_blank" rel="noopener">' + esc(c.name) + "</a>"
        : esc(c.name);
      return '<div class="inv-row">' + conf +
        '<div class="inv-row__main"><div class="inv-row__name">' + name +
        (c.role ? ' · <span class="inv-row__role">' + esc(c.role) + "</span>" : "") + "</div>" +
        route + "</div></div>";
    }).join("");
    return (
      '<details class="inv"><summary class="inv__head">' +
      '<i class="ti ti-user-search"></i>Контакты · инвестигатор' +
      '<span class="inv__count">' + list.length + "</span></summary>" +
      '<div class="inv__list">' + rows + "</div></details>"
    );
  }

  function chip(label, key) {
    return '<button class="res-chip' + (filter === key ? " res-chip--on" : "") +
      '" data-rf="' + esc(key) + '">' + esc(label) + "</button>";
  }

  // Перерисовать сетку из кэша по текущему направлению и порогу ползунка.
  // Не ходит в сеть — двигать ползунок дёшево.
  function paint() {
    var results = lastData;
    if (!results.length) {
      grid.innerHTML = "";
      if (empty) empty.hidden = false;
      if (filtersEl) filtersEl.innerHTML = "";
      if (sliderEl) sliderEl.hidden = true;
      return;
    }
    if (empty) empty.hidden = true;
    if (sliderEl) sliderEl.hidden = false;

    var tracks = [];
    results.forEach(function (r) { if (r.track && tracks.indexOf(r.track) < 0) tracks.push(r.track); });
    if (filtersEl) filtersEl.innerHTML =
      chip("Все", "all") + tracks.map(function (t) { return chip(t, t); }).join("");

    // Включение в подборку — по названию/направлению (это решает пайплайн);
    // здесь, внутри подборки, фильтруем по карте (map %) ползунком.
    var byTrack = results.filter(function (r) { return filter === "all" || r.track === filter; });
    var shown = byTrack.filter(function (r) { return r.map >= minPct; });
    shown.sort(function (a, b) { return b.map - a.map; });
    grid.innerHTML = shown.map(card).join("");

    if (minValEl) minValEl.textContent = minPct + "%";
    if (countEl) countEl.textContent = "показано " + shown.length + " из " + byTrack.length;
  }

  document.addEventListener("click", function (ev) {
    var c = ev.target.closest("[data-rf]");
    if (!c) return;
    filter = c.getAttribute("data-rf");
    paint();
  });

  // «Контакт» в карточке: ищем контакты по должности+компании прямо здесь.
  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest("[data-find-contact]");
    if (!btn) return;
    var box = btn.closest(".res-card").querySelector("[data-card-contacts]");
    if (box && !box.hidden && box.getAttribute("data-loaded")) { box.hidden = true; box.removeAttribute("data-loaded"); return; }
    if (box) { box.hidden = false; box.innerHTML = '<div class="contact-block__sub"><span class="spin"></span> Ищу контакты…</div>'; }
    btn.disabled = true;
    var fd = new FormData();
    fd.append("role", btn.getAttribute("data-role") || "");
    fd.append("company", btn.getAttribute("data-company") || "");
    fd.append("link", btn.getAttribute("data-link") || "");
    fetch("/contacts/search", { method: "POST", body: fd })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
      .then(function (res) {
        if (!res.ok) throw new Error(res.body.error || "ошибка");
        var c = res.body.contacts || {};
        var cands = (c.candidates || []).map(function (x) {
          return '<div class="inv-row"><div class="inv-row__main"><div class="inv-row__name">' +
            (x.link ? '<a href="' + esc(x.link) + '" target="_blank" rel="noopener">' + esc(x.name) + "</a>" : esc(x.name)) +
            (x.role ? " · " + esc(x.role) : "") + "</div>" +
            (x.source ? '<span class="inv-row__route">' + esc(x.source) + "</span>" : "") + "</div></div>";
        }).join("");
        var fb = (c.fallback_paths || []).length
          ? '<div class="contact-block__sub">Куда смотреть: ' + c.fallback_paths.map(esc).join(" · ") + "</div>" : "";
        var draft = c.draft_message
          ? '<details class="inv"><summary class="inv__head"><i class="ti ti-mail"></i>Черновик обращения</summary>' +
            '<div class="inv__list"><textarea class="input contact-draft__text" rows="5" readonly>' + esc(c.draft_message) + "</textarea></div></details>" : "";
        if (box) {
          box.innerHTML = (cands || '<div class="contact-block__sub">Прямых контактов не нашлось.</div>') + fb + draft;
          box.setAttribute("data-loaded", "1");
        }
      })
      .catch(function (err) { if (box) box.innerHTML = '<div class="contact-block__sub">✗ ' + esc(err.message) + "</div>"; })
      .finally(function () { btn.disabled = false; });
  });

  // «В архив»: скрыть вакансию из подборки (статус archived в БД).
  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest("[data-archive]");
    if (!btn) return;
    var cardEl = btn.closest(".res-card");
    var key = cardEl ? cardEl.getAttribute("data-match-key") : "";
    if (!key) return;
    btn.disabled = true;
    var fd = new FormData();
    fd.append("key", key);
    fetch("/run/match/archive", { method: "POST", body: fd })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j.ok) { btn.disabled = false; return; }
        lastData = lastData.filter(function (x) { return x.key !== key; });
        last = JSON.stringify(lastData);  // чтобы poll не вернул карточку обратно
        paint();
      })
      .catch(function () { btn.disabled = false; });
  });

  if (minEl) minEl.addEventListener("input", function () {
    minPct = parseInt(minEl.value, 10) || 0;
    paint();
  });

  function poll(force) {
    fetch("/run/results").then(function (r) { return r.json(); }).then(function (d) {
      var data = d.results || [];
      var key = JSON.stringify(data);
      if (!force && key === last) return;
      last = key;
      lastData = data;
      paint();
    }).catch(function () {});
  }

  setInterval(poll, 2500);
  poll();
})();
