// «Подборка»: строит карточки с двойными кольцами по /run/results (живой прогон).
(function () {
  "use strict";
  var grid = document.querySelector("[data-res-grid]");
  var empty = document.querySelector("[data-res-empty]");
  var filtersEl = document.querySelector("[data-res-filters]");
  if (!grid) return;
  var filter = "all";
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
      '<div class="res-card">' +
      '<div class="res-card__head"><div class="res-card__main">' +
      '<div class="res-card__role">' + esc(r.role) + "</div>" +
      '<div class="res-card__co">' + esc(r.company) + "</div>" +
      (r.track ? '<span class="track-tag">' + esc(r.track) + "</span>" : "") +
      '</div><div class="res-card__ring">' + window.scoreRing(r.resume, r.map) +
      '<div class="res-card__map"><i class="ti ti-map-2"></i>карта ' + r.map + "%</div></div></div>" +
      '<div class="verdict" style="color:' + v.c + '"><i class="ti ' + v.ic + '"></i>' + v.lbl + summary + "</div>" +
      '<div class="res-card__gap">' + esc(r.gap) + "</div>" +
      '<div class="res-card__btns">' + open + letter +
      '<button class="res-btn"><i class="ti ti-user-search"></i>Контакт</button></div></div>'
    );
  }

  function chip(label, key) {
    return '<button class="res-chip' + (filter === key ? " res-chip--on" : "") +
      '" data-rf="' + esc(key) + '">' + esc(label) + "</button>";
  }

  function render(results) {
    if (!results.length) {
      grid.innerHTML = "";
      if (empty) empty.hidden = false;
      if (filtersEl) filtersEl.innerHTML = "";
      return;
    }
    if (empty) empty.hidden = true;
    var tracks = [];
    results.forEach(function (r) { if (r.track && tracks.indexOf(r.track) < 0) tracks.push(r.track); });
    if (filtersEl) filtersEl.innerHTML = chip("Все", "all") + tracks.map(function (t) { return chip(t, t); }).join("");
    var shown = results.filter(function (r) { return filter === "all" || r.track === filter; });
    shown.sort(function (a, b) { return b.resume - a.resume; });
    grid.innerHTML = shown.map(card).join("");
  }

  document.addEventListener("click", function (ev) {
    var c = ev.target.closest("[data-rf]");
    if (!c) return;
    filter = c.getAttribute("data-rf");
    poll(true);
  });

  function poll(force) {
    fetch("/run/results").then(function (r) { return r.json(); }).then(function (d) {
      var key = JSON.stringify(d.results) + filter;
      if (!force && key === last) return;
      last = key;
      render(d.results || []);
    }).catch(function () {});
  }

  setInterval(poll, 2500);
  poll();
})();
