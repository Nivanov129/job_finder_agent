// Страница «Прогон»: опрашивает /run/status и показывает прогресс/итог/ошибку.
(function () {
  "use strict";
  var box = document.querySelector("[data-run-status]");
  if (!box) return;

  function render(s) {
    if (s.status === "running") {
      box.className = "run-status";
      box.innerHTML =
        '<i class="ti ti-loader"></i> Прогон идёт… собрано ' + s.collected +
        " · после фильтра " + s.after_filter;
    } else if (s.status === "done") {
      box.className = "run-status is-ok";
      var dl = s.output
        ? ' · <a class="btn" href="/run/output.xlsx" download>' +
          '<i class="ti ti-download"></i> Скачать .xlsx</a>'
        : "";
      box.innerHTML =
        '<i class="ti ti-circle-check"></i> Готово: собрано ' + s.collected +
        " · после фильтра " + s.after_filter + " · в выгрузке " + s.written + dl;
      clearInterval(timer);
    } else if (s.status === "error") {
      box.className = "run-status is-error";
      box.innerHTML =
        '<i class="ti ti-alert-triangle"></i> Ошибка прогона: ' + (s.message || "");
      clearInterval(timer);
    } else {
      box.className = "run-status";
      box.textContent = "Прогон ещё не запускался.";
    }
  }

  function poll() {
    fetch("/run/status")
      .then(function (r) { return r.json(); })
      .then(render)
      .catch(function () {});
  }

  var timer = setInterval(poll, 2000);
  poll();
})();
