// Testanruf im Browser (J6): gleiche Gesprächsführung wie am Telefon, Antworten optional per lokaler Browser-Stimme.
(function () {
  var wurzel = document.getElementById("testanruf");
  if (!wurzel) return;
  var csrf = wurzel.querySelector("[name=csrfmiddlewaretoken]").value;
  var verlauf = document.getElementById("ta-verlauf");
  var status = document.getElementById("ta-status");
  var kennung = null;
  var aufnahme = null;
  var teile = [];

  function zeile(rolle, text) {
    var li = document.createElement("li");
    li.className = "chat-" + rolle;
    li.textContent = text;
    verlauf.appendChild(li);
    li.scrollIntoView({ block: "nearest" });
  }

  function vorlesen(text) {
    if (!document.getElementById("ta-vorlesen").checked || !window.speechSynthesis) return;
    // Nur lokale Stimmen: der Text verlässt den Rechner nicht
    var stimmen = window.speechSynthesis.getVoices().filter(function (s) { return s.lang.indexOf("de") === 0 && s.localService; });
    if (!stimmen.length) { status.textContent = "Keine lokale deutsche Stimme im Browser gefunden; die Antwort steht oben."; return; }
    var a = new SpeechSynthesisUtterance(text);
    a.voice = stimmen[0];
    a.lang = stimmen[0].lang;
    window.speechSynthesis.speak(a);
  }

  var beschaeftigt = false;
  function sperren(an) {
    beschaeftigt = an;
    ["ta-senden", "ta-mikro", "ta-text"].forEach(function (id) { document.getElementById(id).disabled = an; });
  }

  function senden(url, daten) {
    if (beschaeftigt) return Promise.resolve();
    sperren(true);
    daten.append("csrfmiddlewaretoken", csrf);
    status.textContent = "Der Assistent denkt nach …";
    return fetch(url, { method: "POST", body: daten, credentials: "same-origin" })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (e) {
        status.textContent = "";
        if (!e.ok) { status.textContent = e.j.fehler || "Fehler"; return; }
        if (e.j.gehoert) zeile("anrufer", e.j.gehoert);
        if (e.j.antwort) { zeile("assistent", e.j.antwort); vorlesen(e.j.antwort); }
        if (e.j.ausfallbetrieb) status.textContent = "Hinweis: KI nicht erreichbar, der Assistent arbeitet mit festen Fragen.";
        if (e.j.beendet) ende(e.j.rueckruf);
      })
      .catch(function () { status.textContent = "Verbindung fehlgeschlagen."; })
      .then(function () { sperren(false); });
  }

  function ende(link) {
    document.getElementById("ta-eingabe").classList.add("versteckt");
    var p = document.getElementById("ta-ergebnis");
    p.classList.remove("versteckt");
    p.innerHTML = "";
    var text = document.createTextNode("Gespräch beendet. ");
    p.appendChild(text);
    if (link) {
      var a = document.createElement("a");
      a.href = link;
      a.className = "knopf";
      a.textContent = "Rückruf-Notiz ansehen";
      p.appendChild(a);
    }
    kennung = null;
  }

  document.getElementById("ta-start").addEventListener("click", function () {
    var d = new FormData();
    d.append("nummer", document.getElementById("ta-nummer").value);
    d.append("csrfmiddlewaretoken", csrf);
    fetch(wurzel.dataset.start, { method: "POST", body: d, credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        kennung = j.gespraech;
        verlauf.innerHTML = "";
        document.getElementById("ta-start-reihe").classList.add("versteckt");
        document.getElementById("ta-eingabe").classList.remove("versteckt");
        zeile("assistent", j.antwort);
        vorlesen(j.antwort);
      });
  });

  document.getElementById("ta-senden").addEventListener("click", function () {
    var feld = document.getElementById("ta-text");
    if (!kennung || beschaeftigt || !feld.value.trim()) return;
    var d = new FormData();
    d.append("text", feld.value);
    zeile("anrufer", feld.value);
    feld.value = "";
    var url = wurzel.dataset.basis + kennung + "/nachricht/";
    senden(url, d).then(function () {
      // Text ohne Spracherkennung: die Zeile steht schon oben
    });
  });
  document.getElementById("ta-text").addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); document.getElementById("ta-senden").click(); }
  });

  document.getElementById("ta-mikro").addEventListener("click", function () {
    var knopf = this;
    if (aufnahme && aufnahme.state === "recording") { aufnahme.stop(); return; }
    if (!navigator.mediaDevices || !window.MediaRecorder) { status.textContent = "Ihr Browser unterstützt keine Aufnahme. Bitte tippen."; return; }
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (strom) {
      teile = [];
      aufnahme = new MediaRecorder(strom);
      aufnahme.ondataavailable = function (e) { if (e.data.size) teile.push(e.data); };
      aufnahme.onstop = function () {
        strom.getTracks().forEach(function (t) { t.stop(); });
        knopf.querySelector("span").textContent = "Sprechen";
        var d = new FormData();
        d.append("audio", new Blob(teile, { type: aufnahme.mimeType || "audio/webm" }), "beitrag.webm");
        senden(wurzel.dataset.basis + kennung + "/nachricht/", d);
      };
      aufnahme.start();
      knopf.querySelector("span").textContent = "Fertig";
      status.textContent = "Aufnahme läuft … zum Beenden auf „Fertig“ tippen.";
    }).catch(function () { status.textContent = "Kein Zugriff auf das Mikrofon. Bitte tippen."; });
  });

  document.getElementById("ta-auflegen").addEventListener("click", function () {
    if (!kennung) return;
    senden(wurzel.dataset.basis + kennung + "/ende/", new FormData());
  });
})();
