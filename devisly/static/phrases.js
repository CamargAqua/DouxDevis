(function () {
  var PHRASES_URL = "/static/phrases.json";
  var phrases = null;

  function loadPhrases(cb) {
    if (phrases) { cb(phrases); return; }
    fetch(PHRASES_URL).then(function (r) { return r.json(); }).then(function (data) {
      phrases = data;
      cb(phrases);
    });
  }

  function lastWord(text) {
    var words = text.replace(/\s+$/, "").split(/\s+/);
    return (words[words.length - 1] || "").toLowerCase().replace(/[.,;:!?]+$/, "");
  }

  function attach(textarea) {
    var suggestBox = document.createElement("div");
    suggestBox.style.display = "none";
    suggestBox.style.marginTop = "6px";
    suggestBox.style.padding = "8px 12px";
    suggestBox.style.background = "var(--gold-ultra, #F5EDD6)";
    suggestBox.style.border = "1px solid var(--gold-light, #D4B86A)";
    suggestBox.style.borderRadius = "6px";
    suggestBox.style.fontSize = "12px";
    suggestBox.style.color = "var(--gold-deep, #9A7A1E)";
    // Dans une ligne d'intervention (flex), la suggestion va SOUS la ligne, pas dedans
    var line = textarea.closest ? textarea.closest(".intervention-line") : null;
    (line || textarea).insertAdjacentElement("afterend", suggestBox);

    var currentMatch = null;

    function update() {
      loadPhrases(function (map) {
        if (!textarea.isConnected) { suggestBox.remove(); return; }
        var word = lastWord(textarea.value);
        if (word && map[word]) {
          currentMatch = { word: word, phrase: map[word] };
          suggestBox.textContent = "→ " + map[word] + "  (Tab pour insérer)";
          suggestBox.style.display = "block";
        } else {
          currentMatch = null;
          suggestBox.style.display = "none";
        }
      });
    }

    textarea.addEventListener("input", update);
    textarea.addEventListener("blur", function () {
      setTimeout(function () { suggestBox.style.display = "none"; }, 200);
    });
    textarea.addEventListener("keydown", function (e) {
      if (e.key === "Tab" && currentMatch) {
        e.preventDefault();
        var words = textarea.value.replace(/\s+$/, "").split(/\s+/);
        words[words.length - 1] = currentMatch.phrase;
        textarea.value = words.join(" ") + " ";
        suggestBox.style.display = "none";
        currentMatch = null;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-phrase-assist]").forEach(attach);
  });

  // Attachement manuel pour les éléments créés dynamiquement (lignes d'intervention)
  window.phraseAssist = attach;
})();
