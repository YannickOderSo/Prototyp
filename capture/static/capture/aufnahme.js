// Sprachaufnahme im Browser (MediaRecorder), höchstens 5 Minuten, Upload per fetch mit CSRF-Token.
(function () {
  const bereich = document.getElementById("aufnahme");
  if (!bereich) return;
  const start = document.getElementById("aufnahme-start");
  const stopp = document.getElementById("aufnahme-stopp");
  const status = document.getElementById("aufnahme-status");
  const maxSekunden = parseInt(bereich.dataset.maxSekunden || "300", 10);
  let recorder = null;
  let teile = [];
  let uhr = null;
  let sekunden = 0;

  function csrf() {
    const feld = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return feld ? feld.value : "";
  }

  function zeigen(text) { status.textContent = text; }

  if (!window.MediaRecorder || !navigator.mediaDevices) {
    start.disabled = true;
    zeigen("Ihr Browser unterstützt keine Aufnahme. Bitte laden Sie eine Audiodatei hoch.");
    return;
  }

  start.addEventListener("click", async function () {
    try {
      const strom = await navigator.mediaDevices.getUserMedia({ audio: true });
      const typ = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
      recorder = typ ? new MediaRecorder(strom, { mimeType: typ }) : new MediaRecorder(strom);
      teile = [];
      sekunden = 0;
      recorder.ondataavailable = function (e) { if (e.data && e.data.size) teile.push(e.data); };
      recorder.onstop = hochladen;
      recorder.start(1000);
      start.disabled = true;
      stopp.disabled = false;
      zeigen("Aufnahme läuft … 0:00");
      uhr = setInterval(function () {
        sekunden += 1;
        zeigen("Aufnahme läuft … " + Math.floor(sekunden / 60) + ":" + String(sekunden % 60).padStart(2, "0"));
        if (sekunden >= maxSekunden) recorder.stop();
      }, 1000);
    } catch (fehler) {
      zeigen("Kein Zugriff auf das Mikrofon. Bitte erlauben Sie den Zugriff oder laden Sie eine Datei hoch.");
    }
  });

  stopp.addEventListener("click", function () { if (recorder && recorder.state !== "inactive") recorder.stop(); });

  async function hochladen() {
    clearInterval(uhr);
    stopp.disabled = true;
    recorder.stream.getTracks().forEach(function (t) { t.stop(); });
    zeigen("Wird hochgeladen …");
    const daten = new FormData();
    const typ = (recorder.mimeType || "audio/webm").split(";")[0];
    const endung = typ.indexOf("mp4") >= 0 ? "m4a" : (typ.indexOf("ogg") >= 0 ? "ogg" : "webm");
    daten.append("aufnahme", new Blob(teile, { type: typ }), "aufnahme." + endung);
    daten.append("csrfmiddlewaretoken", csrf());
    try {
      const antwort = await fetch(bereich.dataset.ziel, {
        method: "POST",
        body: daten,
        headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" },
        credentials: "same-origin",
      });
      const json = await antwort.json();
      if (antwort.ok && json.weiter) { window.location.href = json.weiter; return; }
      zeigen(json.fehler || "Hochladen fehlgeschlagen.");
    } catch (fehler) {
      zeigen("Hochladen fehlgeschlagen. Bitte erneut versuchen.");
    }
    start.disabled = false;
  }
})();
