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

  // Подтянуть модели Ollama (облако/свой сервер) в выпадающий список. Свободный
  // ввод остаётся рабочим: select лишь копирует выбор в текстовое поле, поэтому
  // при недоступности сервера форма всё равно отправит введённую вручную модель.
  function loadOllamaModels() {
    var sel = document.querySelector("[data-ollama-model-select]");
    var input = document.querySelector("[data-ollama-model-input]");
    if (!sel || !input) return;
    var url = "/engine/ollama/models";
    var srv = document.querySelector('[name="ollama_url"]');
    if (srv && srv.value.trim()) url += "?url=" + encodeURIComponent(srv.value.trim());
    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var models = data.models || [];
        if (!models.length) return; // сервер недоступен — оставляем свободный ввод
        sel.innerHTML = '<option value="">— выберите модель —</option>';
        models.forEach(function (name) {
          var opt = document.createElement("option");
          opt.value = name;
          opt.textContent = name;
          if (name === input.value) opt.selected = true;
          sel.appendChild(opt);
        });
        sel.hidden = false;
        sel.addEventListener("change", function () {
          if (sel.value) input.value = sel.value;
        });
      })
      .catch(function () {});
  }

  // Реальная мини-проба движка: пишет результат в `out` (✓/✗ + сообщение).
  function runProbe(key, out, okClass, errClass) {
    if (out) { out.textContent = "Проверяю…"; out.className = okClass; }
    var fd = new FormData();
    fd.append("engine", key);
    return fetch("/engine/test", { method: "POST", body: fd })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
      .then(function (res) {
        if (!out) return;
        if (res.ok) {
          out.textContent = "✓ " + (res.body.message || "ok");
          out.className = okClass + " is-ok";
        } else {
          out.textContent = "✗ " + (res.body.message || "ошибка");
          out.className = okClass + " is-error";
        }
      })
      .catch(function () {
        if (out) { out.textContent = "✗ сеть"; out.className = okClass + " is-error"; }
      });
  }

  // Server-driven вход: показать ссылку + (для claude) форму кода.
  function renderLoginOut(engine, data) {
    var out = document.querySelector('[data-login-out="' + engine + '"]');
    if (!out) return;
    var link =
      '<a class="btn" href="' + data.url + '" target="_blank" rel="noopener">' +
      '<i class="ti ti-external-link"></i> Открыть вход</a>';
    var action;
    if (data.mode === "code") {
      action =
        '<input class="input login-code" data-engine="' + engine +
        '" placeholder="вставьте код из браузера">' +
        '<button type="button" class="btn btn--accent login-submit" data-engine="' +
        engine + '">Готово</button>';
    } else {
      action =
        '<button type="button" class="btn btn--accent login-submit" data-engine="' +
        engine + '">Я авторизовался</button>';
    }
    out.innerHTML =
      '<div class="login-flow__row">' + link + "</div>" +
      '<div class="login-flow__row">' + action + "</div>" +
      '<div class="login-flow__msg" data-login-msg="' + engine + '"></div>';
  }

  function setLoginMsg(engine, text, cls) {
    var m = document.querySelector('[data-login-msg="' + engine + '"]');
    if (m) { m.textContent = text; m.className = "login-flow__msg " + (cls || ""); }
  }

  function loginStart(engine) {
    var out = document.querySelector('[data-login-out="' + engine + '"]');
    if (out) out.innerHTML = '<div class="login-flow__msg">Запускаю вход…</div>';
    var fd = new FormData();
    fd.append("engine", engine);
    fetch("/engine/login/start", { method: "POST", body: fd })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
      .then(function (res) {
        if (res.ok && res.body.url) renderLoginOut(engine, res.body);
        else if (out) out.innerHTML =
          '<div class="login-flow__msg is-error">✗ ' +
          (res.body.message || "не удалось начать вход") + "</div>";
      })
      .catch(function () {
        if (out) out.innerHTML = '<div class="login-flow__msg is-error">✗ сеть</div>';
      });
  }

  function loginSubmit(engine) {
    var codeEl = document.querySelector('.login-code[data-engine="' + engine + '"]');
    setLoginMsg(engine, "Завершаю вход…", "");
    var fd = new FormData();
    fd.append("engine", engine);
    fd.append("code", codeEl ? codeEl.value : "");
    fetch("/engine/login/submit", { method: "POST", body: fd })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
      .then(function (res) {
        if (res.ok) { setLoginMsg(engine, "✓ " + (res.body.message || "вход выполнен"), "is-ok"); loadStatus(); }
        else setLoginMsg(engine, "✗ " + (res.body.message || "ошибка"), "is-error");
      })
      .catch(function () { setLoginMsg(engine, "✗ сеть", "is-error"); });
  }

  // Показывать панель только выбранного движка (настройка+статус для него).
  function togglePanels() {
    var sel = document.querySelector('input[name="engine"]:checked');
    var key = sel ? sel.value : "";
    document.querySelectorAll(".auth-panel[data-engine]").forEach(function (p) {
      p.hidden = p.getAttribute("data-engine") !== key;
    });
  }

  document.addEventListener("change", function (ev) {
    if (ev.target && ev.target.name === "engine") togglePanels();
  });

  document.addEventListener("click", function (ev) {
    // Кнопка «копировать команду».
    var copyBtn = ev.target.closest(".copy-cmd");
    if (copyBtn) {
      var text = copyBtn.getAttribute("data-copy") || "";
      if (navigator.clipboard) navigator.clipboard.writeText(text).catch(function () {});
      var prev = copyBtn.getAttribute("title");
      copyBtn.setAttribute("title", "скопировано ✓");
      setTimeout(function () { copyBtn.setAttribute("title", prev || "копировать"); }, 1500);
      return;
    }
    // Server-driven вход: старт / завершение.
    var startBtn = ev.target.closest(".login-start");
    if (startBtn) { loginStart(startBtn.getAttribute("data-engine")); return; }
    var submitBtn = ev.target.closest(".login-submit");
    if (submitBtn) { loginSubmit(submitBtn.getAttribute("data-engine")); return; }
    // Кнопка «Проверить» на панели движка.
    var btn = ev.target.closest(".engine-test");
    if (!btn) return;
    var key = btn.getAttribute("data-engine");
    runProbe(key, document.querySelector('[data-test="' + key + '"]'), "path-input__status");
  });

  // Авто-проверка после сохранения: страница-подтверждение несёт data-autoverify.
  function autoVerify() {
    var el = document.querySelector("[data-autoverify]");
    if (!el) return;
    var key = el.getAttribute("data-autoverify");
    if (key) runProbe(key, el, "autoverify");
  }

  togglePanels();
  loadStatus();
  loadOllamaModels();
  autoVerify();
})();
