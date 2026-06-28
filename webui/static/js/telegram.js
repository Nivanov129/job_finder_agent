// Страница «Telegram»: логин (телефон → код → 2FA) и выгрузка/подбор каналов.
(function () {
  "use strict";

  function post(url, data) {
    var fd = new FormData();
    Object.keys(data).forEach(function (k) { fd.append(k, data[k]); });
    return fetch(url, { method: "POST", body: fd }).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, body: j }; });
    });
  }

  var out = document.querySelector("[data-tg-login]");
  function loginMsg(text, cls) {
    if (out) out.innerHTML = '<div class="login-flow__msg ' + (cls || "") + '">' + text + "</div>";
  }
  function field(name) { var el = document.querySelector('[name="' + name + '"]'); return el ? el.value.trim() : ""; }

  function codeForm() {
    out.innerHTML =
      '<div class="login-flow__row"><input class="input" data-tg-code ' +
      'placeholder="код из Telegram"><button type="button" class="btn btn--accent" ' +
      'data-tg-code-btn>Войти</button></div><div class="login-flow__msg" data-tg-msg></div>';
  }
  function passwordForm() {
    out.innerHTML =
      '<div class="login-flow__row"><input class="input" type="password" data-tg-pass ' +
      'placeholder="пароль 2FA"><button type="button" class="btn btn--accent" ' +
      'data-tg-pass-btn>Подтвердить</button></div><div class="login-flow__msg" data-tg-msg></div>';
  }
  function subMsg(text, cls) {
    var m = document.querySelector("[data-tg-msg]");
    if (m) m.className = "login-flow__msg " + (cls || ""), (m.textContent = text);
  }

  function renderChannels(channels) {
    var list = document.querySelector("[data-tg-channels-list]");
    if (!list) return;
    var rows = channels.map(function (c) {
      var checked = c.job ? " checked" : "";
      var tag = c.job ? ' <span class="hint-set">вакансии</span>' : "";
      return (
        '<label class="field" style="flex-direction:row;align-items:center;gap:8px">' +
        '<input type="checkbox" class="tg-ch" value="' + c.id + '"' + checked + ">" +
        "<span>" + (c.title || c.id) + tag + "</span></label>"
      );
    });
    list.innerHTML = rows.join("");
    var save = document.querySelector(".tg-save");
    if (save) save.hidden = false;
  }

  document.addEventListener("click", function (ev) {
    if (ev.target.closest(".copy-cmd")) {
      var b = ev.target.closest(".copy-cmd");
      if (navigator.clipboard) navigator.clipboard.writeText(b.getAttribute("data-copy") || "");
      return;
    }
    if (ev.target.closest(".tg-start")) {
      loginMsg("Отправляю код…");
      post("/telegram/login/start", {
        api_id: field("tg_api_id"), api_hash: field("tg_api_hash"), phone: field("tg_phone"),
      }).then(function (r) {
        if (!r.ok) return loginMsg("✗ " + (r.body.message || "ошибка"), "is-error");
        codeForm();
      }).catch(function () { loginMsg("✗ сеть", "is-error"); });
      return;
    }
    if (ev.target.closest("[data-tg-code-btn]")) {
      var code = document.querySelector("[data-tg-code]").value.trim();
      subMsg("Проверяю код…");
      post("/telegram/login/code", { code: code }).then(function (r) {
        if (!r.ok) return subMsg("✗ " + (r.body.message || "ошибка"), "is-error");
        if (r.body.stage === "password") return passwordForm();
        loginMsg("✓ вход выполнен — выгрузите каналы ниже", "is-ok");
      }).catch(function () { subMsg("✗ сеть", "is-error"); });
      return;
    }
    if (ev.target.closest("[data-tg-pass-btn]")) {
      var pass = document.querySelector("[data-tg-pass]").value;
      subMsg("Проверяю пароль…");
      post("/telegram/login/password", { password: pass }).then(function (r) {
        if (!r.ok) return subMsg("✗ " + (r.body.message || "ошибка"), "is-error");
        loginMsg("✓ вход выполнен — выгрузите каналы ниже", "is-ok");
      }).catch(function () { subMsg("✗ сеть", "is-error"); });
      return;
    }
    if (ev.target.closest(".tg-channels")) {
      var st = document.querySelector("[data-tg-channels-status]");
      if (st) st.textContent = "Выгружаю каналы и классифицирую…", (st.className = "path-input__status");
      post("/telegram/channels", {}).then(function (r) {
        if (st) st.textContent = "";
        var chs = r.body.channels || [];
        if (!chs.length) {
          if (st) st.textContent = "✗ " + (r.body.message || "каналов нет"), (st.className = "path-input__status is-error");
          return;
        }
        renderChannels(chs);
        if (st) st.textContent = "✓ каналов: " + chs.length, (st.className = "path-input__status is-ok");
      }).catch(function () { if (st) st.textContent = "✗ сеть", (st.className = "path-input__status is-error"); });
      return;
    }
    if (ev.target.closest(".tg-save")) {
      var ids = Array.prototype.slice.call(document.querySelectorAll(".tg-ch:checked")).map(function (c) { return c.value; });
      var form = document.createElement("form");
      form.method = "post";
      form.action = "/telegram/save";
      ids.forEach(function (id) {
        var i = document.createElement("input");
        i.type = "hidden"; i.name = "channel"; i.value = id; form.appendChild(i);
      });
      document.body.appendChild(form);
      form.submit();
    }
  });
})();
