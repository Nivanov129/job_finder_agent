// Интерактивность экрана «Настройка» (Task 5.1) — без внешних зависимостей.
// Повторяемая карточка направления (добавление/удаление, минимум одна),
// акцентная рамка выбранного движка через CSS :has, живой % порога.
(function () {
  "use strict";

  var list = document.getElementById("tracks-list");
  var tpl = document.getElementById("track-template");
  var addBtn = document.getElementById("add-track");

  function refreshRemovable() {
    // Минимум одно направление: при единственной карточке прячем «удалить».
    var cards = list.querySelectorAll(".track-card");
    cards.forEach(function (card) {
      var btn = card.querySelector(".track-remove");
      if (btn) btn.style.display = cards.length > 1 ? "" : "none";
    });
  }

  if (addBtn && tpl && list) {
    addBtn.addEventListener("click", function () {
      var node = tpl.content.cloneNode(true);
      list.appendChild(node);
      refreshRemovable();
    });
  }

  if (list) {
    list.addEventListener("click", function (e) {
      var btn = e.target.closest(".track-remove");
      if (!btn) return;
      var cards = list.querySelectorAll(".track-card");
      if (cards.length > 1) {
        btn.closest(".track-card").remove();
        refreshRemovable();
      }
    });
    refreshRemovable();
  }

  // ── Загрузка файлов рядом с полями-путями ──────────────────────────
  // Делегирование на document, чтобы работало и в клонированных карточках.
  function setStatus(el, text, cls) {
    if (!el) return;
    el.textContent = text;
    el.className = "path-input__status" + (cls ? " " + cls : "");
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".file-upload");
    if (!btn) return;
    // Скрытый file-input — сосед кнопки в той же .path-input.
    var fileInput = btn.parentNode.querySelector(".file-upload__input");
    if (fileInput) fileInput.click();
  });

  // ── Генерация «Допустимых ролей» из резюме (gate включения в подборку) ──
  function deriveRoles(card, path, statusEl) {
    var rolesInput = card && card.querySelector('input[name="track_roles"]');
    if (!rolesInput || !path) return;
    if (statusEl) { statusEl.textContent = "ИИ читает резюме и подбирает роли…"; statusEl.className = "field__hint"; }
    var fd = new FormData();
    fd.append("path", path);
    fetch("/roles/derive", { method: "POST", body: fd })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
      .then(function (res) {
        if (!res.ok) throw new Error(res.body.error || "не удалось");
        var roles = res.body.roles || [];
        if (roles.length) {
          rolesInput.value = roles.join(", ");
          if (statusEl) { statusEl.textContent = "✓ роли из резюме: " + roles.length; statusEl.className = "field__hint is-ok"; }
        } else if (statusEl) {
          statusEl.textContent = "резюме прочитано, но ролей не нашлось — впиши вручную";
          statusEl.className = "field__hint";
        }
      })
      .catch(function (err) {
        if (statusEl) { statusEl.textContent = "✗ " + err.message; statusEl.className = "field__hint is-error"; }
      });
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-derive-roles]");
    if (!btn) return;
    var card = btn.closest(".track-card");
    var pathField = card && card.querySelector('input[name="track_resume"]');
    var path = pathField && pathField.value.trim();
    var statusEl = card && card.querySelector("[data-roles-status]");
    if (!path) {
      if (statusEl) { statusEl.textContent = "сначала загрузи или укажи резюме"; statusEl.className = "field__hint is-error"; }
      return;
    }
    deriveRoles(card, path, statusEl);
  });

  document.addEventListener("change", function (e) {
    var fileInput = e.target;
    if (!fileInput.classList || !fileInput.classList.contains("file-upload__input")) return;
    var file = fileInput.files && fileInput.files[0];
    if (!file) return;

    var row = fileInput.closest(".path-input");
    var pathField = row.querySelector(".input");
    var kind = row.querySelector(".file-upload").getAttribute("data-kind");
    var status = row.parentNode.querySelector(".path-input__status");

    setStatus(status, "Загрузка " + file.name + "…", "");
    var fd = new FormData();
    fd.append("file", file);
    fd.append("kind", kind);
    fetch("/upload", { method: "POST", body: fd })
      .then(function (r) {
        return r.json().then(function (j) {
          return { ok: r.ok, body: j };
        });
      })
      .then(function (res) {
        if (!res.ok) throw new Error(res.body.error || "ошибка загрузки");
        if (pathField) pathField.value = res.body.path;
        setStatus(status, "✓ " + res.body.name, "is-ok");
        // Загрузили резюме → сразу подбираем «Допустимые роли» из него.
        if (kind === "resume") {
          var card = row.closest(".track-card");
          var rolesStatus = card && card.querySelector("[data-roles-status]");
          deriveRoles(card, res.body.path, rolesStatus);
        }
      })
      .catch(function (err) {
        setStatus(status, "✗ " + err.message, "is-error");
      })
      .finally(function () {
        fileInput.value = ""; // позволяет повторно выбрать тот же файл
      });
  });
})();
