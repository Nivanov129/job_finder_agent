// Бот-уведомления: «Подключить» (ловит chat_id) и «Отправить тест».
(function () {
  "use strict";
  var out = document.querySelector("[data-bot-out]");
  function say(msg, cls) {
    if (!out) return;
    out.textContent = msg;
    out.className = "login-flow__out " + (cls || "");
  }
  function post(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body || "",
    }).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, body: j }; });
    });
  }

  document.addEventListener("click", function (ev) {
    var connect = ev.target.closest("[data-bot-connect]");
    var test = ev.target.closest("[data-bot-test]");
    if (connect) {
      var tokenEl = document.querySelector('input[name="bot_token"]');
      var token = tokenEl ? tokenEl.value.trim() : "";
      say("Подключаю… (если не нажал Start у бота — сделай это и нажми снова)", "");
      post("/telegram/bot/connect", "bot_token=" + encodeURIComponent(token))
        .then(function (r) {
          if (r.ok && r.body.ok) {
            say("Подключено ✓ chat " + r.body.chat_id + ". Жми «Отправить тест».", "is-ok");
          } else {
            say("✗ " + (r.body.error || "не вышло"), "is-error");
          }
        })
        .catch(function () { say("✗ сеть", "is-error"); });
      return;
    }
    if (test) {
      say("Отправляю тест…", "");
      post("/telegram/bot/test")
        .then(function (r) {
          if (r.ok && r.body.ok) say("Тест отправлен ✓ — проверь Telegram.", "is-ok");
          else say("✗ " + (r.body.error || "бот не принял сообщение"), "is-error");
        })
        .catch(function () { say("✗ сеть", "is-error"); });
    }
  });
})();
