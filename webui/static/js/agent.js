// Дашборд «Агент»: hero+тумблер, статы, лента, хост, сильные совпадения.
// Данные: /agent/status + /run/status + /run/results.
(function () {
  "use strict";
  function $(s) { return document.querySelector(s); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function rbadge(r) {
    var b = r >= 80 ? "green" : r >= 70 ? "amber" : "grey";
    var bg = { green: "#EAF3DE", amber: "#FAEEDA", grey: "#F1EFE8" }[b];
    var fg = { green: "#27500A", amber: "#633806", grey: "#444441" }[b];
    return 'background:' + bg + ';color:' + fg;
  }

  function stat(label, ic, value, hint, tone) {
    var numStyle = tone === "green" ? ' style="color:#3B6D11"' : "";
    var hintStyle = tone === "green" ? ' style="color:#185FA5"' : "";
    return (
      '<div class="stat-card"><div class="stat-card__l"><i class="ti ' + ic + '"></i>' + label + "</div>" +
      '<div class="stat-card__v mono"' + numStyle + ">" + value +
      (hint ? '<span class="stat-card__h"' + hintStyle + ">" + hint + "</span>" : "") + "</div></div>"
    );
  }

  function feedRow(r, scanning) {
    var track = r.track ? '<span class="track-tag">' + esc(r.track) + "</span>" : "";
    var body;
    if (scanning) {
      body = '<div class="feed-row__scan"><span class="spin"></span>' +
        '<span class="blink">AI читает пост и считает совпадение…</span></div>';
    } else {
      var v = window.verdictOf(r.verdict, r.resume);
      var push = r.resume >= 80
        ? '<span class="feed-row__push"><i class="ti ti-brand-telegram"></i>в бот</span>' : "";
      body = '<div class="feed-row__scored">' +
        '<span class="badge" style="' + rbadge(r.resume) + '">резюме ' + r.resume + "%</span>" +
        '<span class="feed-row__map"><i class="ti ti-map-2"></i>карта ' + r.map + "%</span>" +
        '<span class="feed-row__v" style="color:' + v.c + '"><i class="ti ' + v.ic + '"></i>' + v.lbl + "</span>" + push + "</div>";
    }
    return (
      '<div class="feed-row"><div class="feed-row__src"><i class="ti ' + (r.src || "ti-brand-telegram") + '"></i></div>' +
      '<div class="feed-row__main"><div class="feed-row__top"><span class="feed-row__role">' + esc(r.role) + "</span>" + track + "</div>" +
      '<div class="feed-row__meta">' + esc(r.company || "") + "</div>" + body + "</div></div>"
    );
  }

  function render(ag, run, results) {
    var on = !!ag.enabled;
    var title = $("[data-agent-title]"), sub = $("[data-agent-subtitle]");
    var toggle = $("[data-agent-toggle]"), hicon = $("[data-agent-hicon]");
    var hero = document.querySelector(".hero");
    if (hero) hero.classList.toggle("hero--off", !on);
    if (title) title.textContent = on ? "Агент следит за каналами" : "Мониторинг на паузе";
    if (sub) sub.textContent = on
      ? "Каждый новый пост в твоих каналах AI читает и оценивает под резюме — без твоего участия."
      : "Новые посты не оцениваются. Включи, чтобы агент снова реагировал в реалтайме.";
    if (hicon) {
      hicon.className = "hero__icon" + (on ? " hero__icon--on" : " hero__icon--off");
      hicon.innerHTML = '<i class="ti ' + (on ? "ti-radar-2" : "ti-player-pause") + '"></i>';
    }
    if (toggle) {
      toggle.className = "btn hero__toggle agent-toggle" +
        (on ? " hero__toggle--pause" : " btn--accent");
      toggle.innerHTML = '<i class="ti ' + (on ? "ti-player-pause" : "ti-player-play") +
        '"></i>' + (on ? "Пауза" : "Возобновить");
    }

    var top = results.filter(function (r) { return r.resume >= 80; });
    var letters = results.filter(function (r) { return r.has_cover; });
    var statsEl = $("[data-agent-stats]");
    if (statsEl) statsEl.innerHTML =
      stat("Найдено", "ti-inbox", results.length, "за прогон") +
      stat("Топ ≥80%", "ti-flame", top.length, "→ в бот", "green") +
      stat("Оценено", "ti-cpu", run.scored || run.written || 0) +
      stat("Письма готовы", "ti-mail-check", letters.length, "черновики");

    var feed = $("[data-agent-feed]");
    var rate = $("[data-agent-rate]");
    if (feed) {
      var rows = "";
      if (run.status === "running") rows += feedRow({ role: "новый пост", company: run.stage === "score" ? "скоринг…" : "сбор/нормализация…" }, true);
      var recent = results.slice().reverse().slice(0, 6);
      rows += recent.map(function (r) { return feedRow(r, false); }).join("");
      feed.innerHTML = rows ||
        '<div class="feed-empty"><i class="ti ti-radar"></i><div>' +
        (on ? "Агент ждёт новые посты — как появятся, оценю на лету." : "Включи агента или запусти «Подбор за период».") + "</div></div>";
      if (rate) rate.textContent = results.length ? results.length + " оценено" : "";
    }

    var hb = $("[data-agent-hostbadge]");
    if (hb) hb.innerHTML = '<span class="orb ' + (on ? "orb--on" : "orb--amber") + '"></span>' + (on ? "always-on" : "пауза");
    var hd = $("[data-agent-hostdetail]");
    if (hd) {
      function row(l, v) { return '<div class="host-detail__row"><span>' + l + '</span><span class="mono">' + v + "</span></div>"; }
      hd.innerHTML =
        row("этот компьютер", on ? "онлайн" : "пауза") +
        row("последний скан", ag.last_run ? new Date(ag.last_run).toLocaleTimeString() : "—") +
        row("следующий", on && ag.seconds_to_next != null ? "~" + Math.ceil(ag.seconds_to_next / 60) + " мин" : "—") +
        row("интервал", (ag.interval_min || "—") + " мин");
    }

    var pc = $("[data-agent-pushcount]"); if (pc) pc.textContent = top.length;
    var pushes = $("[data-agent-pushes]");
    if (pushes) {
      pushes.innerHTML = top.length
        ? top.slice(0, 4).map(function (r) {
            return '<div class="push-row"><span class="badge" style="' + rbadge(r.resume) + '">' + r.resume + "%</span>" +
              '<div class="push-row__main"><div class="push-row__role">' + esc(r.role) + "</div>" +
              '<div class="push-row__co">' + esc(r.company || "") + "</div></div>" +
              '<i class="ti ti-brand-telegram"></i></div>';
          }).join("")
        : '<div class="push-empty">Пока нет совпадений ≥ 80%. Сильное — придёт сюда и в бот.</div>';
    }
  }

  document.addEventListener("click", function (ev) {
    if (!ev.target.closest("[data-agent-toggle]")) return;
    fetch("/agent/status").then(function (r) { return r.json(); }).then(function (a) {
      if (a.enabled) return fetch("/agent/stop", { method: "POST" });
      var fd = new FormData();
      return fetch("/agent/start", { method: "POST", body: fd });
    }).then(poll);
  });

  function poll() {
    Promise.all([
      fetch("/agent/status").then(function (r) { return r.json(); }).catch(function () { return {}; }),
      fetch("/run/status").then(function (r) { return r.json(); }).catch(function () { return {}; }),
      fetch("/run/results").then(function (r) { return r.json(); }).catch(function () { return { results: [] }; }),
    ]).then(function (x) { render(x[0], x[1], x[2].results || []); });
  }
  setInterval(poll, 2500);
  poll();
})();
