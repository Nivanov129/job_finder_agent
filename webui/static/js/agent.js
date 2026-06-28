// Дашборд «Агент»: сводка-конвейер + лента + совпадения + статистика.
// Пока наполняет сводку из /agent/status и /run/status; лента результатов —
// следующий шаг (стриминг результатов прогона).
(function () {
  "use strict";

  function pipe(run, ag) {
    var el = document.querySelector("[data-agent-pipe]");
    if (!el) return;
    var cols = [
      { l: "Источники", v: run.collected || 0, s: "постов", c: "" },
      { l: "AI оценивает", v: run.normalized || 0, s: "прочитано", c: "var(--text-accent)" },
      { l: "Отсев", v: Math.max(0, (run.collected || 0) - (run.after_filter || 0)), s: "не по профилю", c: "var(--text-muted)" },
      { l: "В подборку", v: run.written || run.after_filter || 0, s: "совпадений", c: "var(--text-success)" },
    ];
    el.innerHTML = cols.map(function (c, i) {
      return (
        '<div class="pipe-col"><span class="pipe-col__l">' + c.l + "</span>" +
        '<span class="pipe-col__v mono" style="color:' + (c.c || "inherit") + '">' + c.v + "</span>" +
        '<span class="pipe-col__s">' + c.s + "</span></div>" +
        (i < cols.length - 1 ? '<i class="ti ti-chevron-right pipe-arrow"></i>' : "")
      );
    }).join("");
  }

  function feed(run) {
    var el = document.querySelector("[data-agent-feed]");
    if (!el) return;
    var live = document.querySelector("[data-agent-live]");
    if (run.status === "running") {
      if (live) live.textContent = "идёт прогон";
      el.innerHTML =
        '<div class="feed-empty"><div class="spin"></div> Прогон идёт — ' +
        (run.stage === "score" ? "скоринг " + (run.scored || 0) + "/" + (run.after_filter || "?") :
         run.stage === "normalize" ? "нормализую " + (run.normalized || 0) + "/" + (run.to_normalize || "?") :
         "собираю вакансии") + "…</div>";
    } else {
      if (live) live.textContent = "ожидание";
      el.innerHTML = '<div class="feed-empty">Пока тихо — запусти «Подбор за период» или включи агента.</div>';
    }
  }

  function poll() {
    Promise.all([
      fetch("/run/status").then(function (r) { return r.json(); }).catch(function () { return {}; }),
      fetch("/agent/status").then(function (r) { return r.json(); }).catch(function () { return {}; }),
    ]).then(function (res) {
      var run = res[0], ag = res[1];
      var title = document.querySelector("[data-agent-title]");
      var sub = document.querySelector("[data-agent-subtitle]");
      if (title) title.textContent = ag.enabled ? "Агент следит за вакансиями" : "Агент на паузе";
      if (sub) sub.textContent = ag.enabled
        ? "оценивает новые посты под твоё резюме в реальном времени"
        : "включи агента в левом меню, чтобы продолжить мониторинг";
      pipe(run, ag);
      feed(run);
    });
  }

  setInterval(poll, 3000);
  poll();
})();
