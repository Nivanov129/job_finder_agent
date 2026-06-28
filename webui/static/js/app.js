// Сайдбар: карточка хоста (агент вкл/пауза) + кнопка паузы. Опрашивает
// /agent/status и шлёт /agent/start|stop. Грузится на каждой странице.
(function () {
  "use strict";

  function paint(a) {
    var on = !!a.enabled;
    document.querySelectorAll("[data-agent-orb]").forEach(function (o) {
      o.className = "orb" + (on ? " orb--on" : " orb--amber");
    });
    var host = document.querySelector("[data-agent-host]");
    var sub = document.querySelector("[data-agent-hostsub]");
    var mode = document.querySelector("[data-agent-mode]");
    if (host) host.textContent = on ? "Агент работает" : "Агент на паузе";
    if (mode) mode.textContent = on ? "always-on" : "на паузе";
    if (sub) {
      var parts = [];
      if (a.last_run) parts.push("скан: " + new Date(a.last_run).toLocaleTimeString());
      if (on && a.seconds_to_next != null) parts.push("след. ~" + Math.ceil(a.seconds_to_next / 60) + " мин");
      sub.textContent = parts.join(" · ") || (on ? "следит за каналами" : "мониторинг на паузе");
    }
  }

  function poll() {
    fetch("/agent/status").then(function (r) { return r.json(); }).then(paint).catch(function () {});
  }

  document.addEventListener("click", function (ev) {
    if (!ev.target.closest("[data-agent-pause]")) return;
    fetch("/agent/status")
      .then(function (r) { return r.json(); })
      .then(function (a) {
        if (a.enabled) return fetch("/agent/stop", { method: "POST" });
        var iv = document.querySelector("[data-agent-interval]");
        var fd = new FormData();
        if (iv) fd.append("interval", iv.value);
        return fetch("/agent/start", { method: "POST", body: fd });
      })
      .then(function () { poll(); });
  });

  setInterval(poll, 5000);
  poll();
})();
