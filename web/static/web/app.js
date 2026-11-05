// Kleine Helfer ohne Inline-Skripte (CSP: script-src 'self').
document.addEventListener("click", function (ereignis) {
  const ziel = ereignis.target.closest("[data-bestaetigen]");
  if (ziel && !window.confirm(ziel.getAttribute("data-bestaetigen"))) {
    ereignis.preventDefault();
  }
});

// "Alle markieren" für Sammelfreigaben
document.addEventListener("change", function (ereignis) {
  const schalter = ereignis.target.closest("[data-alle-markieren]");
  if (!schalter) return;
  const gruppe = schalter.getAttribute("data-alle-markieren");
  document.querySelectorAll('input[type="checkbox"][data-gruppe="' + gruppe + '"]').forEach(function (feld) {
    feld.checked = schalter.checked;
  });
});

// „Mehr“-Menü der unteren Leiste: schließt beim Tippen daneben und mit Escape
document.addEventListener("click", function (ereignis) {
  document.querySelectorAll("details.mehr[open]").forEach(function (menue) {
    if (!menue.contains(ereignis.target)) menue.removeAttribute("open");
  });
});
document.addEventListener("keydown", function (ereignis) {
  if (ereignis.key !== "Escape") return;
  document.querySelectorAll("details.mehr[open]").forEach(function (menue) { menue.removeAttribute("open"); });
});
