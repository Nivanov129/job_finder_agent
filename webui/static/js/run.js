// Страница «Прогон»: опрашивает /run/status и показывает прогресс/итог/ошибку.
(function () {
  "use strict";
  var box = document.querySelector("[data-run-status]");
  if (!box) return;

  function render(s) {
    if (s.status === "running") {
      box.className = "run-status";
      var label, detail = "";
      if (s.stage === "normalize") {
        label = "нормализую (AI)";
        detail = " " + (s.normalized || 0) + " / " + (s.to_normalize || "?") +
          (s.collected ? "  · собрано " + s.collected : "");
      } else if (s.stage === "score") {
        label = "скоринг (AI)";
        detail = " " + (s.scored || 0) + " / " + (s.after_filter || "?");
      } else {
        label = "собираю вакансии";
        detail = s.collected ? " собрано " + s.collected : "";
      }
      box.innerHTML = '<i class="ti ti-loader"></i> Прогон: ' + label + "…" + detail;
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

  // ── Режим агента ──────────────────────────────────────────────────
  function pollAgent() {
    fetch("/agent/status")
      .then(function (r) { return r.json(); })
      .then(function (a) {
        var state = document.querySelector("[data-agent-state]");
        var info = document.querySelector("[data-agent-info]");
        var btn = document.querySelector(".agent-toggle");
        if (btn) btn.textContent = a.enabled ? "Выключить агента" : "Включить агента";
        if (state) {
          state.textContent = a.enabled ? "вкл" : "выкл";
          state.className = "run-status" + (a.enabled ? " is-ok" : "");
        }
        if (info) {
          var parts = [];
          if (a.last_run) parts.push("последний прогон: " + new Date(a.last_run).toLocaleString());
          else parts.push("прогонов ещё не было");
          if (a.enabled && a.seconds_to_next != null)
            parts.push("следующий через ~" + Math.ceil(a.seconds_to_next / 60) + " мин");
          info.textContent = parts.join(" · ");
        }
      })
      .catch(function () {});
  }

  document.addEventListener("click", function (ev) {
    if (!ev.target.closest(".agent-toggle")) return;
    fetch("/agent/status")
      .then(function (r) { return r.json(); })
      .then(function (a) {
        if (a.enabled) return fetch("/agent/stop", { method: "POST" });
        var iv = document.querySelector("[data-agent-interval]");
        var fd = new FormData();
        fd.append("interval", iv ? iv.value : "30");
        return fetch("/agent/start", { method: "POST", body: fd });
      })
      .then(function () { pollAgent(); });
  });

  setInterval(poll, 2000);
  setInterval(pollAgent, 5000);
  poll();
  pollAgent();
})();
