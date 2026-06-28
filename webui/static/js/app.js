// Сайдбар: карточка хоста (агент вкл/пауза) + кнопка паузы. Опрашивает
// /agent/status и шлёт /agent/start|stop. Грузится на каждой странице.
// Двойное кольцо «резюме % / карта %» (внешнее — карта, внутреннее — резюме).
window.scoreRing = function (resume, map) {
  var tone = resume >= 80 ? "#3B6D11" : resume >= 70 ? "#854F0B" : "#8A8980";
  var cR = 2 * Math.PI * 27, cr = 2 * Math.PI * 19;
  return (
    '<div class="ring"><svg width="64" height="64" viewBox="0 0 64 64">' +
    '<circle cx="32" cy="32" r="27" fill="none" stroke="#ECE9E1" stroke-width="5"/>' +
    '<circle cx="32" cy="32" r="19" fill="none" stroke="#F1EFE8" stroke-width="5"/>' +
    '<circle cx="32" cy="32" r="27" fill="none" stroke="#2B7FD4" stroke-width="5" stroke-linecap="round" stroke-dasharray="' + cR.toFixed(1) + '" stroke-dashoffset="' + (cR * (1 - map / 100)).toFixed(1) + '" transform="rotate(-90 32 32)"/>' +
    '<circle cx="32" cy="32" r="19" fill="none" stroke="' + tone + '" stroke-width="5" stroke-linecap="round" stroke-dasharray="' + cr.toFixed(1) + '" stroke-dashoffset="' + (cr * (1 - resume / 100)).toFixed(1) + '" transform="rotate(-90 32 32)"/>' +
    "</svg>" +
    '<div class="ring__c" style="color:' + tone + '">' + Math.round(resume) + "%</div></div>"
  );
};
window.VERD = {
  precise_fit: { ic: "ti-circle-check", c: "#3B6D11", lbl: "точное" },
  stretch: { ic: "ti-arrow-up-right", c: "#854F0B", lbl: "дотянись" },
};
window.verdictOf = function (type, resume) {
  return window.VERD[type] || { ic: "ti-minus", c: "#8A8980", lbl: "на грани" };
};

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
