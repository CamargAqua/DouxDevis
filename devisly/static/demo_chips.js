// Puces mots-clés cliquables pour la démo Caubet (motif comptoir + travaux atelier).
// Différent de phrases.js (Tab-sur-focus) : ici on veut un clic direct, cf. artifact validé.
(function () {
  function wire(container) {
    var targetSel = container.getAttribute("data-target");
    var target = document.querySelector(targetSel);
    if (!target) return;
    container.querySelectorAll("[data-phrase]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var phrase = btn.getAttribute("data-phrase");
        target.value = (target.value ? target.value.trim() + " " : "") + phrase;
        target.focus();
      });
    });
  }
  document.querySelectorAll("[data-chip-group]").forEach(wire);

  // Combobox maison (texte libre + suggestions filtrées, cliquables) pour Marque et Pièce —
  // remplace select/datalist natifs (peu stylables, cf. retour "c'est moche"). getOptions()
  // est ré-évalué à chaque ouverture, donc la liste Pièce se scope automatiquement sur la
  // marque tapée dans l'autre combobox, sans câblage dédié entre les deux.
  function wireCombo(input, list, getOptions) {
    if (!input || !list) return;
    function render() {
      var q = input.value.trim().toLowerCase();
      var opts = getOptions().filter(function (o) { return o.toLowerCase().includes(q); });
      list.innerHTML = "";
      if (!opts.length) {
        var empty = document.createElement("li");
        empty.textContent = "Aucune suggestion — texte libre accepté";
        empty.setAttribute("data-empty", "");
        list.appendChild(empty);
      } else {
        opts.forEach(function (o) {
          var li = document.createElement("li");
          li.textContent = o;
          li.addEventListener("mousedown", function (e) {
            e.preventDefault(); // avant le blur, sinon la liste se cache avant le clic
            input.value = o;
            list.hidden = true;
            input.dispatchEvent(new Event("change"));
          });
          list.appendChild(li);
        });
      }
      list.hidden = false;
    }
    input.addEventListener("focus", render);
    input.addEventListener("input", render);
    input.addEventListener("blur", function () {
      setTimeout(function () { list.hidden = true; }, 120);
    });
  }

  (function wireDemoFicheCombos() {
    var marquesEl = document.getElementById("marquesData");
    var modelsEl = document.getElementById("pieceModelsData");
    var marqueField = document.getElementById("marqueField");
    var pieceField = document.getElementById("pieceField");
    if (!marquesEl || !modelsEl) return;
    var marques = JSON.parse(marquesEl.textContent || "[]");
    var models = JSON.parse(modelsEl.textContent || "{}");
    wireCombo(marqueField, document.getElementById("marqueList"), function () { return marques; });
    wireCombo(pieceField, document.getElementById("pieceList"), function () {
      return models[marqueField.value] || [];
    });
  })();
})();
