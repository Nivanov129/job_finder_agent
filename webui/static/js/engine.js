// Страница «AI · авторизация» — без внешних зависимостей.
// 1) подтягивает статус движков (установлен/авторизован) и рисует пилюли;
// 2) кнопки «Проверить» гоняют реальную мини-пробу через /engine/test.
(function () {
  "use strict";

  function pill(ok, text) {
    var state = ok ? "ok" : "bad";
    var glyph = ok ? "ti-circle-check" : "ti-circle-x";
    return (
      '<span class="pill pill--' + state + '">' +
      '<i class="ti ' + glyph + '" aria-hidden="true"></i> ' +
      text +
      "</span>"
    );
  }

  function loadStatus() {
    fetch("/engine/status")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        (data.engines || []).forEach(function (e) {
          var slot = document.querySelector('[data-status="' + e.key + '"]');
          if (!slot) return;
          var parts = [];
          if (e.installed === true) parts.push(pill(true, "установлен"));
          else if (e.installed === false) parts.push(pill(false, "не установлен"));
          parts.push(pill(e.authorized, e.authorized ? "авторизован" : "нет доступа"));
          slot.innerHTML = parts.join(" ");
          slot.title = e.detail || "";
        });
      })
      .catch(function () {});
  }

  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest(".engine-test");
    if (!btn) return;
    var key = btn.getAttribute("data-engine");
    var out = document.querySelector('[data-test="' + key + '"]');
    if (out) { out.textContent = "Проверяю…"; out.className = "path-input__status"; }
    var fd = new FormData();
    fd.append("engine", key);
    fetch("/engine/test", { method: "POST", body: fd })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
      .then(function (res) {
        if (!out) return;
        if (res.ok) {
          out.textContent = "✓ " + (res.body.message || "ok");
          out.className = "path-input__status is-ok";
        } else {
          out.textContent = "✗ " + (res.body.message || "ошибка");
          out.className = "path-input__status is-error";
        }
      })
      .catch(function () {
        if (out) { out.textContent = "✗ сеть"; out.className = "path-input__status is-error"; }
      });
  });

  loadStatus();
})();
