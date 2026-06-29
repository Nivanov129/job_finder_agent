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

  // ── Способы входа: переключение вкладок (QR / телефон / строка сессии) ──
  function selectMethod(method) {
    Array.prototype.forEach.call(document.querySelectorAll(".tg-tab"), function (b) {
      b.classList.toggle("is-active", b.getAttribute("data-tg-method") === method);
    });
    Array.prototype.forEach.call(document.querySelectorAll(".tg-panel"), function (p) {
      p.hidden = p.getAttribute("data-tg-panel") !== method;
    });
    loginMsg(""); // чистим прошлые сообщения при смене способа
  }

  // ── Вход по QR: показать QR и опрашивать сервер, пока не подтвердят ──
  var qrPolling = false;
  function pollQr() {
    if (!qrPolling) return;
    post("/telegram/login/qr/poll", {}).then(function (r) {
      if (!qrPolling) return;
      if (!r.ok) { qrPolling = false; return loginMsg("✗ " + (r.body.message || "ошибка QR"), "is-error"); }
      var st = r.body.stage;
      if (st === "qr") {
        var box = document.querySelector("[data-tg-qr]");
        if (box && r.body.qr) box.innerHTML = '<img alt="QR" src="' + r.body.qr + '">';
        setTimeout(pollQr, 2000);
      } else if (st === "password") {
        qrPolling = false;
        passwordForm();
        subMsg("Аккаунт защищён паролем (2FA) — введи его.", "is-ok");
      } else if (st === "done") {
        qrPolling = false;
        var box2 = document.querySelector("[data-tg-qr]");
        if (box2) box2.hidden = true;
        loginMsg("✓ вход выполнен — выгрузите каналы ниже", "is-ok");
      } else {
        setTimeout(pollQr, 2000);
      }
    }).catch(function () { if (qrPolling) setTimeout(pollQr, 3000); });
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
    if (ev.target.closest(".tg-tab")) {
      qrPolling = false; // уходим с QR — гасим опрос
      selectMethod(ev.target.closest(".tg-tab").getAttribute("data-tg-method"));
      return;
    }
    if (ev.target.closest(".tg-qr")) {
      var box = document.querySelector("[data-tg-qr]");
      if (box) box.hidden = false, (box.innerHTML = '<div class="login-flow__msg">Готовлю QR…</div>');
      post("/telegram/login/qr", {
        api_id: field("api_id"),
        api_hash: field("api_hash"),
      }).then(function (r) {
        if (!r.ok) return loginMsg("✗ " + (r.body.message || "ошибка"), "is-error");
        if (box && r.body.qr) box.innerHTML = '<img alt="QR" src="' + r.body.qr + '">';
        loginMsg(r.body.message || "Отсканируй QR в приложении Telegram.", "is-ok");
        qrPolling = true;
        setTimeout(pollQr, 2000);
      }).catch(function () { loginMsg("✗ сеть", "is-error"); });
      return;
    }
    if (ev.target.closest(".tg-session-btn")) {
      loginMsg("Проверяю сессию…");
      post("/telegram/login/session", {
        api_id: field("api_id"),
        api_hash: field("api_hash"),
        session: field("tg_session"),
      }).then(function (r) {
        if (!r.ok) return loginMsg("✗ " + (r.body.message || "ошибка"), "is-error");
        loginMsg("✓ вход выполнен — выгрузите каналы ниже", "is-ok");
      }).catch(function () { loginMsg("✗ сеть", "is-error"); });
      return;
    }
    if (ev.target.closest(".tg-start")) {
      loginMsg("Отправляю код…");
      post("/telegram/login/start", {
        phone: field("tg_phone"),
        api_id: field("api_id"),
        api_hash: field("api_hash"),
      }).then(function (r) {
        if (!r.ok) return loginMsg("✗ " + (r.body.message || "ошибка"), "is-error");
        codeForm();
        // важно: показать, КУДА придёт код (в приложение Telegram, не SMS)
        subMsg(r.body.message || "Код отправлен в приложение Telegram (не SMS).", "is-ok");
      }).catch(function () { loginMsg("✗ сеть", "is-error"); });
      return;
    }
    if (ev.target.closest(".tg-logout")) {
      post("/telegram/logout", {}).then(function () { location.reload(); });
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
        var jobN = (r.body.job_count != null) ? r.body.job_count : chs.filter(function (c) { return c.job; }).length;
        if (st) st.textContent = "✓ всего " + chs.length + " · с вакансиями: " + jobN, (st.className = "path-input__status is-ok");
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
