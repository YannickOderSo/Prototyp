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
