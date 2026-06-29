// «Поиск контактов»: форма по конкретной вакансии → /contacts/search →
// основная выдача (contacts) + блок инвестигатора. Без зависимостей.
(function () {
  "use strict";
  function $(s) { return document.querySelector(s); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  var form = $("[data-contact-form]");
  var statusEl = $("[data-contact-status]");
  var resultEl = $("[data-contact-result]");
  if (!form) return;

  function setStatus(text, cls) {
    if (!statusEl) return;
    statusEl.hidden = !text;
    statusEl.textContent = text || "";
    statusEl.className = "contact-status" + (cls ? " " + cls : "");
  }

  function link(name, url) {
    return url
      ? '<a href="' + esc(url) + '" target="_blank" rel="noopener">' + esc(name) + "</a>"
      : esc(name);
  }

  function contactsCard(c) {
    if (!c) return "";
    var cands = (c.candidates || []).map(function (x) {
      return '<div class="inv-row"><div class="inv-row__main">' +
        '<div class="inv-row__name">' + link(x.name, x.link) +
        (x.role ? ' · <span class="inv-row__role">' + esc(x.role) + "</span>" : "") + "</div>" +
        (x.source ? '<span class="inv-row__route">' + esc(x.source) + "</span>" : "") +
        "</div></div>";
    }).join("");
    var fb = (c.fallback_paths || []).length
      ? '<div class="contact-block__sub">Куда ещё смотреть: ' +
        (c.fallback_paths).map(esc).join(" · ") + "</div>" : "";
    var draft = c.draft_message
      ? '<div class="contact-draft"><div class="contact-block__sub">Черновик обращения</div>' +
        '<textarea class="input contact-draft__text" rows="5" readonly>' + esc(c.draft_message) + "</textarea></div>"
      : "";
    return (
      '<section class="card contact-block">' +
      '<div class="card__title"><i class="ti ti-address-book"></i> Основная выдача</div>' +
      (cands || '<div class="contact-block__sub">Прямых кандидатов не нашлось.</div>') +
      fb + draft + "</section>"
    );
  }

  function investigationCard(inv) {
    if (!inv) return "";
    var rows = (inv.contacts || []).map(function (x) {
      var conf = x.confidence ? '<span class="inv-row__conf mono">' + x.confidence + "%</span>" : "";
      var grade = x.evidence_grade ? '<span class="inv-row__grade">' + esc(x.evidence_grade) + "</span>" : "";
      return '<div class="inv-row">' + conf + '<div class="inv-row__main">' +
        '<div class="inv-row__name">' + link(x.name, x.link) +
        (x.role ? ' · <span class="inv-row__role">' + esc(x.role) + "</span>" : "") + grade + "</div>" +
        (x.contact_route ? '<span class="inv-row__route">' + esc(x.contact_route) + "</span>" : "") +
        (x.rationale ? '<div class="inv-row__why">' + esc(x.rationale) + "</div>" : "") +
        "</div></div>";
    }).join("");
    var checked = (inv.evidence_checked || []).length
      ? '<div class="contact-block__sub">Что проверено: ' + (inv.evidence_checked).map(esc).join(" · ") + "</div>" : "";
    var next = (inv.next_actions || []).length
      ? '<div class="contact-block__sub">Дальше: ' + (inv.next_actions).map(esc).join(" · ") + "</div>" : "";
    return (
      '<section class="card contact-block">' +
      '<div class="card__title"><i class="ti ti-user-search"></i> Инвестигатор · доп. выдача</div>' +
      (rows || '<div class="contact-block__sub">Контактов не нашлось.</div>') +
      checked + next + "</section>"
    );
  }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var btn = $("[data-contact-go]");
    if (btn) btn.disabled = true;
    setStatus("Ищу контакты — AI читает выдачу веб-поиска…", "");
    if (resultEl) resultEl.innerHTML = "";
    var fd = new FormData(form);
    fetch("/contacts/search", { method: "POST", body: fd })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
      .then(function (res) {
        if (!res.ok) throw new Error(res.body.error || "ошибка поиска");
        var b = res.body;
        var html = contactsCard(b.contacts) + investigationCard(b.investigation);
        if (!html) html = '<div class="contact-block__sub">Ничего не нашлось — попробуй уточнить компанию.</div>';
        if (resultEl) resultEl.innerHTML = html;
        var errs = [b.contacts_error, b.investigation_error].filter(Boolean);
        setStatus(errs.length ? "частично: " + errs.join("; ") : "", errs.length ? "is-error" : "");
      })
      .catch(function (err) { setStatus("✗ " + err.message, "is-error"); })
      .finally(function () { if (btn) btn.disabled = false; });
  });
})();
