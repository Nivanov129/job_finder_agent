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
  var detectedEl = $("[data-contact-detected]");
  if (!form) return;

  function setStatus(text, cls) {
    if (!statusEl) return;
    statusEl.hidden = !text;
    statusEl.textContent = text || "";
    statusEl.className = "contact-status" + (cls ? " " + cls : "");
  }

  // ── загрузка PDF/файла вакансии ──
  var pickBtn = $("[data-contact-pick]");
  var fileInput = $("[data-contact-file]");
  var pathInput = $("[data-contact-path]");
  var fnameEl = $("[data-contact-fname]");
  if (pickBtn && fileInput) {
    pickBtn.addEventListener("click", function () { fileInput.click(); });
    fileInput.addEventListener("change", function () {
      var f = fileInput.files && fileInput.files[0];
      if (!f) return;
      if (fnameEl) fnameEl.textContent = "загрузка " + f.name + "…";
      var fd = new FormData();
      fd.append("file", f);
      fd.append("kind", "vacancy");
      fetch("/upload", { method: "POST", body: fd })
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
        .then(function (res) {
          if (!res.ok) throw new Error(res.body.error || "ошибка загрузки");
          if (pathInput) pathInput.value = res.body.path;
          if (fnameEl) fnameEl.textContent = "✓ " + res.body.name;
        })
        .catch(function (err) { if (fnameEl) fnameEl.textContent = "✗ " + err.message; })
        .finally(function () { fileInput.value = ""; });
    });
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

  function showDetected(d, warning) {
    if (!detectedEl) return;
    if (!d || !(d.role || d.company)) { detectedEl.hidden = true; return; }
    detectedEl.hidden = false;
    detectedEl.innerHTML =
      '<i class="ti ti-wand"></i>Распознал: <b>' + esc(d.role || "?") + "</b>" +
      (d.company ? " · " + esc(d.company) : "") +
      (warning ? '<span class="contact-detected__warn">' + esc(warning) + "</span>" : "");
  }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var link = ($("[data-contact-link]") || {}).value || "";
    var path = (pathInput || {}).value || "";
    if (!link.trim() && !path.trim()) {
      setStatus("дай ссылку на вакансию или загрузи PDF", "is-error");
      return;
    }
    var btn = $("[data-contact-go]");
    if (btn) btn.disabled = true;
    if (detectedEl) detectedEl.hidden = true;
    setStatus("Читаю вакансию и ищу контакты…", "");
    if (resultEl) resultEl.innerHTML = "";
    var fd = new FormData(form);
    fetch("/contacts/search", { method: "POST", body: fd })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
      .then(function (res) {
        if (!res.ok) throw new Error(res.body.error || "ошибка поиска");
        var b = res.body;
        showDetected(b.detected, b.warning);
        var html = contactsCard(b.contacts) + investigationCard(b.investigation);
        if (!html) html = '<div class="contact-block__sub">Контактов не нашлось.</div>';
        if (resultEl) resultEl.innerHTML = html;
        var errs = [b.contacts_error, b.investigation_error].filter(Boolean);
        setStatus(errs.length ? "частично: " + errs.join("; ") : "", errs.length ? "is-error" : "");
      })
      .catch(function (err) { setStatus("✗ " + err.message, "is-error"); })
      .finally(function () { if (btn) btn.disabled = false; });
  });
})();
