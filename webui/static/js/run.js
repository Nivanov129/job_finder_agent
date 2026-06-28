// «Подбор за период»: выбор периода → /run/start → живая воронка
// (степпер + прогресс-баннер). Сетку результатов наполняет results.js.
(function () {
  "use strict";
  function $(s) { return document.querySelector(s); }
  var idle = $("[data-run-idle]");
  var active = $("[data-run-active]");
  if (!idle || !active) return;
  var days = 7;
  var sel = $(".period-chip--on");
  if (sel) days = parseInt(sel.getAttribute("data-period"), 10) || 7;

  // выбор периода
  document.addEventListener("click", function (ev) {
    var c = ev.target.closest("[data-period]");
    if (c) {
      days = parseInt(c.getAttribute("data-period"), 10) || 7;
      document.querySelectorAll("[data-period]").forEach(function (b) {
        b.classList.toggle("period-chip--on", b === c);
      });
      return;
    }
    if (ev.target.closest("[data-run-start]")) {
      var fd = new FormData();
      fd.append("days", String(days));
      fetch("/run/start", { method: "POST", body: fd }).then(poll);
    }
  });

  var STEPS = ["collect", "normalize", "filter", "score"];
  var ORDER = { collect: 0, normalize: 1, filter: 2, score: 3 };

  function paintStepper(s) {
    var cur = ORDER[s.stage] != null ? ORDER[s.stage] : (s.status === "done" ? 4 : 0);
    STEPS.forEach(function (key, i) {
      var el = $('[data-step="' + key + '"]');
      if (!el) return;
      var done = s.status === "done" || i < cur;
      var activeStep = i === cur && s.status === "running";
      el.className = "step" + (done ? " step--done" : "") + (activeStep ? " step--active" : "");
      var circle = el.querySelector(".step__circle");
      if (circle && done) circle.innerHTML = '<i class="ti ti-check"></i>';
      var sub = el.querySelector("[data-step-sub]");
      if (sub) {
        sub.textContent =
          key === "collect" ? (s.collected ? s.collected + " постов" : "") :
          key === "normalize" ? (s.to_normalize ? (s.normalized || 0) + " / " + s.to_normalize : "") :
          key === "filter" ? (s.after_filter ? s.after_filter + " финалистов" : "") :
          key === "score" ? (s.after_filter ? (s.scored || 0) + " / " + s.after_filter : "") : "";
      }
    });
  }

  function paintProgress(s) {
    var title = $("[data-run-ptitle]"), sub = $("[data-run-psub]");
    var bar = $("[data-run-pbar]"), pct = $("[data-run-ppct]"), pic = $("[data-run-picon]");
    var p = 0, t = "Прогон…", sb = "";
    if (s.stage === "collect" || (!s.stage && s.status === "running")) { t = "Собираю вакансии"; p = 8; }
    else if (s.stage === "normalize") { t = "AI читает посты"; sb = "нормализую " + (s.normalized || 0) + " / " + (s.to_normalize || "?"); p = s.to_normalize ? 10 + 50 * (s.normalized / s.to_normalize) : 30; }
    else if (s.stage === "score") { t = "Скоринг · два процента"; sb = "оцениваю " + (s.scored || 0) + " / " + (s.after_filter || "?"); p = s.after_filter ? 65 + 35 * (s.scored / s.after_filter) : 70; }
    if (s.status === "done") { t = "Готово"; sb = "собрано " + s.collected + " · финалистов " + (s.after_filter || 0) + " · в выгрузке " + (s.written || 0); p = 100; }
    if (s.status === "error") { t = "Ошибка прогона"; sb = s.message || ""; }
    if (title) title.textContent = t;
    if (sub) sub.textContent = sb;
    if (bar) bar.style.width = Math.round(p) + "%";
    if (pct) pct.textContent = s.status === "running" ? Math.round(p) + "%" : (s.status === "done" ? "100%" : "");
    if (pic) pic.className = "run-progress__icon" + (s.status === "done" ? " run-progress__icon--done" : "");
    if (pic) pic.innerHTML = '<i class="ti ' + (s.status === "done" ? "ti-circle-check" : s.status === "error" ? "ti-alert-triangle" : "ti-loader") + '"></i>';
  }

  function poll() {
    fetch("/run/status").then(function (r) { return r.json(); }).then(function (s) {
      var running = s.status === "running" || s.status === "done" || s.status === "error";
      idle.hidden = running;
      active.hidden = !running;
      if (running) { paintStepper(s); paintProgress(s); }
    }).catch(function () {});
  }
  setInterval(poll, 1500);
  poll();
})();
