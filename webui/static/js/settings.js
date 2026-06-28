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
})();
