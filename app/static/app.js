/* Buchhaltungs-Dashboard — Oberflaeche.
 *
 * ES2018. Kein `?.`, kein `??`, kein `flat()`, kein `fromEntries`, kein
 * `replaceAll`, kein `.at()`. Grund: ein iPhone 6 im Team laeuft auf iOS 12.5.8,
 * und Safari 12 wirft die GANZE Datei weg, bevor eine Zeile laeuft — die Seite
 * zeigt dann nur den Kopf und sieht aus wie ein Layoutfehler. Es gibt keinen
 * Build-Schritt, der das abfaengt.
 *
 * Pruefen mit:
 *   grep -nE '\?\.|\?\?|\bflat\(|fromEntries|matchAll|\.at\(|replaceAll' app.js
 */
(function () {
  "use strict";

  // Jede Instanz merkt sich ihre eigene Ansicht. Die Dashboards liegen zwar
  // auf verschiedenen Adressen und teilen sich den Speicher ohnehin nicht —
  // aber ein Schlüssel, der nach der falschen Instanz heißt, führt beim
  // Nachsehen in die Irre.
  var INSTANZ = document.body.getAttribute("data-instanz") || "buchhaltung";
  var PERSON = document.body.getAttribute("data-person") || "";
  // An wen man sich wendet, wenn etwas unklar ist. Ohne Eintrag stehen
  // allgemeine Saetze da statt eines erfundenen Namens.
  var ANSPRECHPARTNER = document.body.getAttribute("data-ansprechpartner") || "";
  var SCHLUESSEL_THEMA = "smg-buchhaltung-thema";
  var SCHLUESSEL_ORDNUNG = "smg-" + INSTANZ + "-reihenfolge";
  var SCHLUESSEL_ZU = "smg-" + INSTANZ + "-zugeklappt";
  var SCHLUESSEL_SORTIERUNG = "smg-" + INSTANZ + "-sortierung";

  var karten = {};      // name -> {element, daten, erledigteZeigen, zeitgeber}
  var suchtext = "";

  var geld = new Intl.NumberFormat("de-DE", {
    style: "currency", currency: "EUR", maximumFractionDigits: 2
  });

  /* ------------------------------------------------------------ Werkzeug */

  function speicherLesen(schluessel, standard) {
    try {
      var wert = localStorage.getItem(schluessel);
      return wert === null ? standard : wert;
    } catch (e) { return standard; }
  }

  function speicherSchreiben(schluessel, wert) {
    try { localStorage.setItem(schluessel, wert); } catch (e) { /* gesperrt */ }
  }

  function holen(pfad, methode, koerper) {
    var einstellungen = { method: methode || "GET", headers: {} };
    if (koerper) {
      einstellungen.headers["Content-Type"] = "application/json";
      einstellungen.body = JSON.stringify(koerper);
    }
    return fetch(pfad, einstellungen).then(function (antwort) {
      if (antwort.ok) { return antwort.json(); }
      // Den Klartext des Servers durchreichen. Ohne das stuende in der Karte
      // nur "HTTP 502" — und der eigentliche Satz ("In Todomaster ließ sich das
      // nicht ändern …") ginge verloren.
      return antwort.json().then(function (daten) {
        throw new Error(daten && daten.fehler ? daten.fehler : "HTTP " + antwort.status);
      }, function () {
        throw new Error("HTTP " + antwort.status);
      });
    });
  }

  function alsText(wert) {
    return wert === null || wert === undefined ? "" : String(wert);
  }

  function datumKurz(iso) {
    if (!iso) { return ""; }
    var teile = String(iso).slice(0, 10).split("-");
    if (teile.length !== 3) { return ""; }
    return teile[2] + "." + teile[1] + ".";
  }

  function relativ(iso) {
    if (!iso) { return ""; }
    var d = new Date(String(iso).slice(0, 10) + "T12:00:00");
    if (isNaN(d.getTime())) { return ""; }
    var heute = new Date();
    var tage = Math.round((heute - d) / 86400000);
    // Zukunft nicht als "heute" ausgeben: Eine Aufgabe mit Frist 01.10. stand
    // sonst mit "heute" in der Liste und sah dringend aus, obwohl noch drei
    // Wochen Zeit waren.
    if (tage < 0) {
      if (tage === -1) { return "morgen"; }
      if (tage > -30) { return "in " + Math.abs(tage) + " Tagen"; }
      return datumKurz(iso);
    }
    if (tage === 0) { return "heute"; }
    if (tage === 1) { return "gestern"; }
    if (tage < 30) { return "vor " + tage + " Tagen"; }
    return datumKurz(iso);
  }

  function uhrzeit(iso) {
    if (!iso) { return "–"; }
    var d = new Date(iso);
    if (isNaN(d.getTime())) { return "–"; }
    var stunde = ("0" + d.getHours()).slice(-2);
    var minute = ("0" + d.getMinutes()).slice(-2);
    return stunde + ":" + minute;
  }

  function leeren(element) {
    while (element.firstChild) { element.removeChild(element.firstChild); }
  }

  function bauen(art, klasse, text) {
    var el = document.createElement(art);
    if (klasse) { el.className = klasse; }
    if (text !== undefined && text !== null) { el.textContent = String(text); }
    return el;
  }

  /* -------------------------------------------------------------- Thema */

  var themaKnopf = document.getElementById("thema-wechseln");

  function themaAnzeigen() {
    var dunkel = document.documentElement.getAttribute("data-theme") === "dark";
    // Der Knopf zeigt, wohin es geht, nicht wo man ist.
    themaKnopf.textContent = dunkel ? "☀️" : "🌙";
  }

  themaKnopf.addEventListener("click", function () {
    var dunkel = document.documentElement.getAttribute("data-theme") === "dark";
    if (dunkel) {
      document.documentElement.removeAttribute("data-theme");
      speicherSchreiben(SCHLUESSEL_THEMA, "hell");
    } else {
      document.documentElement.setAttribute("data-theme", "dark");
      speicherSchreiben(SCHLUESSEL_THEMA, "dunkel");
    }
    themaAnzeigen();
  });
  themaAnzeigen();

  /* --------------------------------------------------- Leiste ein/ausklappen */

  var SCHLUESSEL_LEISTE = "smg-" + INSTANZ + "-leiste";
  var leisteSchalter = document.getElementById("leiste-schalter");

  function leisteAnzeigen() {
    var zu = document.body.classList.contains("leiste-zu");
    leisteSchalter.textContent = zu ? "»" : "«";
    leisteSchalter.title = zu ? "Seitenleiste ausklappen" : "Seitenleiste einklappen";
    leisteSchalter.setAttribute("aria-label", leisteSchalter.title);
  }

  if (speicherLesen(SCHLUESSEL_LEISTE, "auf") === "zu") {
    document.body.classList.add("leiste-zu");
  }
  leisteSchalter.addEventListener("click", function () {
    var zu = document.body.classList.toggle("leiste-zu");
    speicherSchreiben(SCHLUESSEL_LEISTE, zu ? "zu" : "auf");
    leisteAnzeigen();
  });
  leisteAnzeigen();

  /* ------------------------------------------------------------- Abmelden */

  document.getElementById("abmelden").addEventListener("click", function () {
    // Basic-Auth kennt kein Abmelden. Der Umweg: eine Anfrage mit absichtlich
    // falschen Daten verwirft die gespeicherten im Browser.
    fetch("/", { headers: { Authorization: "Basic " + btoa("abmelden:abmelden") } })
      .catch(function () { /* der 401 ist genau das Ziel */ })
      .then(function () { window.location.href = "/abgemeldet"; });
  });

  /* ---------------------------------------------------------------- Gruss */

  function grussSetzen(person) {
    var stunde = new Date().getHours();
    var wort = stunde < 11 ? "Guten Morgen" : (stunde < 18 ? "Hallo" : "Guten Abend");
    document.getElementById("gruss").textContent =
      PERSON ? (wort + ", " + PERSON + "!") : (wort + "!");

    var satz = "Das ist deine Übersicht für heute.";
    if (person && person.abwesend_bis) {
      satz = "Laut Kalender bist du bis " + datumKurz(person.abwesend_bis)
             + " nicht da"
             + (ANSPRECHPARTNER ? " — " + ANSPRECHPARTNER + " übernimmt." : ".");
    } else if (person && person.heute_da === false) {
      satz = "Laut Kalender arbeitest du heute nicht. Schön, dass du trotzdem reinschaust.";
    }
    document.getElementById("kopf-unter").textContent = satz;
  }

  function stunden(sekunden) {
    var m = Math.round((sekunden || 0) / 60);
    return Math.floor(m / 60) + ":" + ("0" + (m % 60)).slice(-2);
  }

  function zeitZeigen(zeit) {
    var el = document.getElementById("zeitzeile");
    if (!zeit) { el.hidden = true; return; }          // clockin klemmt — dann nichts
    leeren(el);
    if (!zeit.erfasst && !zeit.seit) {
      el.appendChild(document.createTextNode("Heute noch keine Zeit erfasst."));
    } else {
      el.appendChild(document.createTextNode("Heute "));
      el.appendChild(bauen("b", "", stunden(zeit.erfasst)
        + (zeit.soll ? " von " + stunden(zeit.soll) : "") + " Std."));
      if (zeit.laeuft) {
        el.appendChild(document.createTextNode(" · "));
        el.appendChild(bauen("span", "laeuft", "läuft seit " + zeit.seit));
      } else if (zeit.bis) {
        el.appendChild(document.createTextNode(" · zuletzt " + zeit.bis));
      }
    }
    if (zeit.monat && zeit.monat.erfasst) {
      // Nur die Summe, kein Soll-Vergleich: Im Urlaub liefe das Soll weiter
      // und die Zeile behauptete ein Minus, das es nicht gibt.
      el.appendChild(document.createTextNode(" · Monat "));
      el.appendChild(bauen("b", "", stunden(zeit.monat.erfasst) + " Std."));
      if (zeit.monat.tage) {
        el.appendChild(document.createTextNode(
          " (" + zeit.monat.tage + (zeit.monat.tage === 1 ? " Tag)" : " Tage)")));
      }
    }
    el.hidden = false;
  }

  /* --------------------------------------------------------- Nachrichten */

  function fehlerHinweis(eltern, text) {
    var alt = eltern.querySelector(".nachricht-fehler");
    if (alt) { eltern.removeChild(alt); }
    eltern.appendChild(bauen("div", "nachricht-fehler", text));
  }

  function nachrichtenZeichnen(liste) {
    var bereich = document.getElementById("nachrichten");
    if (!bereich) { return; }
    leeren(bereich);
    if (!liste || !liste.length) { bereich.hidden = true; return; }
    bereich.hidden = false;

    for (var i = 0; i < liste.length; i++) {
      (function (n) {
        var kasten = bauen("div", "nachricht" + (n.dringlichkeit === "wichtig" ? " wichtig" : ""));
        kasten.appendChild(bauen("span", "nachricht-icon",
          n.dringlichkeit === "wichtig" ? "❗" : "💬"));

        var mitte = bauen("div", "nachricht-mitte");
        // Eine Zeile darueber sagt, was das ist — sonst haelt man den Kasten
        // beim ersten Mal fuer eine Systemmeldung des Dashboards.
        mitte.appendChild(bauen("span", "nachricht-marke",
          n.dringlichkeit === "wichtig" ? "Wichtig" : "Nachricht"));
        mitte.appendChild(bauen("p", "nachricht-text", n.text));

        var fuss = bauen("div", "nachricht-fuss",
          "von " + (n.von || "Claude") + " · " + relativ(n.am) + " " + uhrzeit(n.am));
        if (n.karte && karten[n.karte]) {
          var link = bauen("a", "", "zur Karte „"
            + karten[n.karte].element.querySelector("h2").textContent + "“");
          link.href = "#" + n.karte;
          fuss.appendChild(link);
        }
        mitte.appendChild(fuss);
        kasten.appendChild(mitte);

        var knoepfe = bauen("div", "nachricht-knoepfe");

        var antworten = bauen("button", "nachricht-antworten", "Antworten");
        antworten.type = "button";
        antworten.addEventListener("click", function () {
          if (mitte.querySelector(".nachricht-feld")) { return; }
          var feld = document.createElement("textarea");
          feld.className = "nachricht-feld";
          feld.placeholder = "Antwort an " + (n.von || "Claude")
            + " — z. B. „passt, erledigt“ oder „stimmt nicht, der Betrag gehört zu …“";
          mitte.appendChild(feld);

          var senden = bauen("button", "nachricht-senden", "Antwort senden");
          senden.type = "button";
          var abbruch = bauen("button", "nachricht-abbruch", "Abbrechen");
          abbruch.type = "button";
          var zeile = bauen("div", "nachricht-feld-knoepfe");
          zeile.appendChild(senden);
          zeile.appendChild(abbruch);
          mitte.appendChild(zeile);
          feld.focus();

          function abschicken() {
            if (!feld.value.trim()) { feld.focus(); return; }
            senden.disabled = true;
            senden.textContent = "wird gesendet …";
            holen("/api/nachrichten/" + n.id + "/antwort", "POST",
                  { text: feld.value })
              .then(function (d) { nachrichtenZeichnen(d.nachrichten); })
              .catch(function (f) {
                senden.disabled = false;
                senden.textContent = "Antwort senden";
                fehlerHinweis(mitte, f.message);
              });
          }
          senden.addEventListener("click", abschicken);
          abbruch.addEventListener("click", function () {
            mitte.removeChild(feld);
            mitte.removeChild(zeile);
          });
          feld.addEventListener("keydown", function (e) {
            // Strg+Enter schickt ab — dieselbe Geste wie bei den Notizen.
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { abschicken(); }
            if (e.key === "Escape") { abbruch.click(); }
          });
        });
        knoepfe.appendChild(antworten);

        var weg = bauen("button", "nachricht-erledigt", "Erledigt");
        weg.type = "button";
        weg.addEventListener("click", function () {
          weg.disabled = true;
          holen("/api/nachrichten/" + n.id + "/erledigt", "POST")
            .then(function (d) { nachrichtenZeichnen(d.nachrichten); })
            .catch(function () { weg.disabled = false; });
        });
        knoepfe.appendChild(weg);
        kasten.appendChild(knoepfe);
        bereich.appendChild(kasten);
      })(liste[i]);
    }
  }

  function nachrichtenLaden() {
    return holen("/api/nachrichten")
      .then(function (d) { nachrichtenZeichnen(d.nachrichten); })
      .catch(function () { /* naechster Versuch in einer Minute */ });
  }

  /* ---------------------------------------------------------- Kopfzahlen */

  function kopfzahlenZeichnen(kopf) {
    var behaelter = document.getElementById("kopfzahlen");
    leeren(behaelter);
    for (var i = 0; i < kopf.length; i++) {
      var k = kopf[i];
      var kachel = bauen("button", "kopfzahl");
      kachel.type = "button";
      kachel.setAttribute("data-ziel", k.quelle);

      var icon = bauen("span", "kopfzahl-icon", k.icon);
      var text = bauen("span", "kopfzahl-text");
      text.appendChild(bauen("span", "kopfzahl-titel", k.titel));
      text.appendChild(bauen("span", "kopfzahl-zahl", alsText(k.zahl)));

      // Eine Kachel ohne Warntext ist ein Ausschnitt (etwa ein zweites
      // Postfach), kein Gesamtbild. "nichts Dringendes" wäre dort eine
      // Entwarnung, die niemand gegeben hat.
      if (k.fehlt) {
        // Die Kennzahl gibt es nicht mehr — meist, weil das Postfach in
        // Superchat umbenannt wurde. Eine stille Null sähe aus wie Ruhe.
        text.appendChild(bauen("span", "kopfzahl-warnung",
          "❗ Kennzahl fehlt — umbenannt?"));
      } else if (k.warntext) {
        text.appendChild(k.warnung
          ? bauen("span", "kopfzahl-warnung", "❗ " + k.warnung + " " + k.warntext)
          : bauen("span", "kopfzahl-warnung ruhig", "nichts Dringendes"));
      }

      kachel.appendChild(icon);
      kachel.appendChild(text);
      kachel.addEventListener("click", springenZu(k.quelle));
      behaelter.appendChild(kachel);
    }
  }

  /* ----------------------------------------------------------- Zugaenge */

  var zugaengeBereich = document.getElementById("einstellungen");
  var zugaengeGeladen = false;

  function standZeile(f) {
    if (f.gesetzt) {
      return bauen("div", "e-stand da", "Quelle: " + f.herkunft);
    }
    // Optionale Felder nicht rot anmahnen: Die IMAP-Angaben werden nur
    // gebraucht, wenn oben IMAP gewaehlt ist. Rot bedeutet sonst irgendwann
    // gar nichts mehr.
    return f.optional
      ? bauen("div", "e-stand da", "nicht gesetzt — nur nötig, wenn dieser Weg benutzt wird")
      : bauen("div", "e-stand fehlt", "fehlt noch");
  }

  function zugaengeZeichnen(felder, gruppenKarte) {
    var behaelter = document.getElementById("einstellungen-gruppen");
    leeren(behaelter);
    var reihenfolge = [];
    var nachGruppe = {};
    for (var i = 0; i < felder.length; i++) {
      var g = felder[i].gruppe;
      if (!nachGruppe[g]) { nachGruppe[g] = []; reihenfolge.push(g); }
      nachGruppe[g].push(felder[i]);
    }

    for (var r = 0; r < reihenfolge.length; r++) {
      (function (gruppe) {
        var kasten = bauen("div", "e-gruppe");
        kasten.setAttribute("data-bereich", gruppe);
        var kopf = bauen("div", "e-gruppe-kopf");
        kopf.appendChild(bauen("h3", "", gruppe));

        var karte = gruppenKarte[gruppe];
        var ergebnis = bauen("span", "e-ergebnis", "");
        if (karte) {
          var pruefen = bauen("button", "e-pruefen", "Verbindung prüfen");
          pruefen.type = "button";
          pruefen.addEventListener("click", function () {
            pruefen.disabled = true;
            ergebnis.className = "e-ergebnis";
            ergebnis.textContent = "wird geprüft …";
            holen("/api/einstellungen/pruefen/" + karte, "POST")
              .then(function (a) {
                ergebnis.className = "e-ergebnis " + (a.ok ? "gut" : "schlecht");
                ergebnis.textContent = (a.ok ? "✓ " : "✗ ") + a.meldung;
              })
              .catch(function (f) {
                ergebnis.className = "e-ergebnis schlecht";
                ergebnis.textContent = "✗ " + f.message;
              })
              .then(function () { pruefen.disabled = false; });
          });
          kopf.appendChild(pruefen);
        }
        kopf.appendChild(ergebnis);
        kasten.appendChild(kopf);

        // Der Kalender ist der einzige Zugang, der sich nicht abtippen laesst.
        // Er wird angeklickt — deshalb steht hier ein Block statt eines Felds.
        if (gruppe === "Kalender") { googleAnmeldung(kasten); }

        var liste = nachGruppe[gruppe];
        for (var j = 0; j < liste.length; j++) {
          var f = liste[j];
          var feld = bauen("div", "e-feld");
          var kennung = "e-" + f.schluessel;
          var beschriftung = bauen("label", "", f.titel);
          beschriftung.setAttribute("for", kennung);
          feld.appendChild(beschriftung);

          var eingabe;
          if (f.auswahl && f.auswahl.length) {
            // Eine Auswahl statt eines Textfelds: "api" oder "imap" tippt man
            // sonst falsch, und der Fehler faellt erst am leeren Posteingang auf.
            eingabe = document.createElement("select");
            for (var o = 0; o < f.auswahl.length; o++) {
              var option = document.createElement("option");
              option.value = f.auswahl[o].wert;
              option.textContent = f.auswahl[o].titel;
              if ((f.wert || f.auswahl[0].wert) === f.auswahl[o].wert) {
                option.selected = true;
              }
              eingabe.appendChild(option);
            }
            eingabe.id = kennung;
            eingabe.setAttribute("data-schluessel", f.schluessel);
            feld.appendChild(eingabe);
            if (f.hilfe) { feld.appendChild(bauen("div", "e-hilfe", f.hilfe)); }
            var standAuswahl = standZeile(f);
            if (f.gesetzt && f.herkunft.indexOf("hier eingetragen") === 0) {
              (function (feldname, beschriftung) {
                var weg = bauen("button", "e-entfernen", "entfernen");
                weg.type = "button";
                weg.addEventListener("click", function () {
                  if (!window.confirm("„" + beschriftung + "“ hier entfernen?")) { return; }
                  holen("/api/einstellungen", "POST", { werte: {}, loeschen: [feldname] })
                    .then(function () { return holen("/api/einstellungen"); })
                    .then(function (d) {
                      zugaengeZeichnen(d.felder, d.gruppen_karte);
                      postfaecherLaden().then(webhookLaden).then(mcpLaden).then(updateLaden).then(reiterBauen);
                    });
                });
                standAuswahl.appendChild(weg);
              })(f.schluessel, f.titel);
            }
            feld.appendChild(standAuswahl);
            kasten.appendChild(feld);
            continue;
          }
          eingabe = document.createElement("input");
          eingabe.id = kennung;
          eingabe.type = "text";
          eingabe.setAttribute("data-schluessel", f.schluessel);
          eingabe.setAttribute("autocomplete", "off");
          if (f.geheim) {
            // Geheimnisse kommen nie zurueck — das Feld bleibt leer und zeigt
            // im Platzhalter nur, dass etwas hinterlegt ist.
            eingabe.placeholder = f.gesetzt
              ? "hinterlegt (" + f.wert + ") — zum Ändern neu eintragen"
              : (f.optional ? "nicht gesetzt" : "noch nichts hinterlegt");
          } else {
            eingabe.value = f.wert || "";
            // Kein Platzhalter: Er stand bisher wortgleich noch einmal unter
            // dem Feld. Zweimal dasselbe zu lesen hilft niemandem — die
            // Erklaerung steht darunter, und zwar nur dort.
            eingabe.placeholder = "";
          }
          feld.appendChild(eingabe);
          // Postfach-Kennungen tippt niemand fehlerfrei ab — dafür gibt es
          // eine Auswahl, die die Namen aus Superchat holt.
          if (f.schluessel === "SUPERCHAT_INBOX_ID") { postfachwahl(feld, eingabe); }
          // Eine Kalenderadresse tippt man einmal falsch und sucht dann lange.
          // Sobald eine Anmeldung steht, liefert Google die Liste selbst.
          if (f.schluessel === "KALENDER_ID") { kalenderwahl(feld, eingabe); }

          if (f.hilfe) { feld.appendChild(bauen("div", "e-hilfe", f.hilfe)); }

          var stand = standZeile(f);
          // Entfernen gibt es nur fuer das, was HIER eingetragen wurde. Was in
          // der .env auf dem Server steht, gehoert dem Server — das laesst
          // sich von der Oberflaeche aus nicht anfassen.
          if (f.gesetzt && f.herkunft.indexOf("hier eingetragen") === 0) {
            (function (feldname, beschriftung) {
              var weg = bauen("button", "e-entfernen", "entfernen");
              weg.type = "button";
              weg.title = "Diesen Eintrag löschen";
              weg.addEventListener("click", function () {
                if (!window.confirm("„" + beschriftung + "“ hier entfernen?\n\n"
                    + "Danach gilt wieder der Wert aus der .env auf dem Server — "
                    + "gibt es dort keinen, ist das Feld leer.")) { return; }
                weg.disabled = true;
                holen("/api/einstellungen", "POST", { werte: {}, loeschen: [feldname] })
                  .then(function () { return holen("/api/einstellungen"); })
                  .then(function (d) {
                    zugaengeZeichnen(d.felder, d.gruppen_karte);
                    postfaecherLaden().then(webhookLaden).then(mcpLaden).then(updateLaden).then(reiterBauen);
                  })
                  .catch(function () { weg.disabled = false; });
              });
              stand.appendChild(weg);
            })(f.schluessel, f.titel);
          }
          feld.appendChild(stand);
          kasten.appendChild(feld);
        }
        behaelter.appendChild(kasten);
      })(reihenfolge[r]);
    }
  }

  /* --------------------------------------------- Einrichtungsassistent */

  /* Ein frisch installiertes Dashboard ist leer — richtig so, aber ohne
     Führung steht man davor und weiß nicht, wo man anfängt. Der Assistent
     fragt zuerst den Namen und geht danach die Karten durch.

     Er blendet das Raster aus, solange er läuft: Ein halb gefülltes Dashboard
     daneben würde ablenken und den Eindruck erwecken, es sei schon fertig. */

  function assistentZeigen(d) {
    var kasten = document.getElementById("assistent");
    var raster = document.getElementById("raster");
    if (!kasten) { return; }
    kasten.hidden = false;
    if (raster) { raster.hidden = true; }
    var fehlend = document.getElementById("karten-fehlend");
    if (fehlend) { fehlend.hidden = true; }
    leeren(kasten);

    var kopf = bauen("div", "assi-kopf");
    kopf.appendChild(bauen("h2", "", "Willkommen — richten wir dein Dashboard ein"));
    kopf.appendChild(bauen("p", "",
      "Zwei Schritte: erst dein Name, dann die Zugänge. Jede Karte erscheint, "
      + "sobald ihr Zugang steht — was du überspringst, kannst du später unter "
      + "Settings nachtragen."));
    kasten.appendChild(kopf);

    /* --- Schritt 1: die Person ------------------------------------------ */
    var eins = bauen("div", "assi-schritt");
    eins.appendChild(bauen("h3", "", "1. Für wen ist dieses Dashboard?"));
    var pfelder = {};
    var personFelder = [
      ["PERSON_NAME", "Name", "Steht in der Begrüßung oben.", "z. B. Alex"],
      ["TITEL", "Rolle", "Die Überschrift in der Seitenleiste.", "z. B. Buchhaltung"],
      ["FIRMA", "Firma", "Die kleine Zeile darunter. Darf leer bleiben.", ""],
      ["ANSPRECHPARTNER", "Hilfe von", "Wer hilft, wenn etwas unklar ist. Darf leer bleiben.", ""]
    ];
    for (var i = 0; i < personFelder.length; i++) {
      var pf = personFelder[i];
      var feld = bauen("div", "e-feld");
      var b = bauen("label", "", pf[1]);
      b.setAttribute("for", "assi-" + pf[0]);
      feld.appendChild(b);
      var ein = document.createElement("input");
      ein.id = "assi-" + pf[0];
      ein.type = "text";
      ein.value = (d.person && d.person[pf[0]]) || "";
      if (pf[3]) { ein.placeholder = pf[3]; }
      feld.appendChild(ein);
      feld.appendChild(bauen("div", "e-hilfe", pf[2]));
      eins.appendChild(feld);
      pfelder[pf[0]] = ein;
    }
    var personMeldung = bauen("span", "e-ergebnis", "");
    var personSpeichern = bauen("button", "knopf-haupt", "Speichern");
    personSpeichern.type = "button";
    personSpeichern.addEventListener("click", function () {
      var werte = {};
      for (var k in pfelder) {
        if (Object.prototype.hasOwnProperty.call(pfelder, k)) { werte[k] = pfelder[k].value; }
      }
      personSpeichern.disabled = true;
      personMeldung.className = "e-ergebnis";
      personMeldung.textContent = "wird gespeichert …";
      holen("/api/einstellungen", "POST", { werte: werte }).then(function () {
        personMeldung.className = "e-ergebnis gut";
        personMeldung.textContent = "✓ gespeichert — steht beim nächsten Laden oben";
      }).catch(function (f) {
        personMeldung.className = "e-ergebnis schlecht";
        personMeldung.textContent = "✗ " + f.message;
      }).then(function () { personSpeichern.disabled = false; });
    });
    var pfuss = bauen("div", "assi-fuss");
    pfuss.appendChild(personSpeichern);
    pfuss.appendChild(personMeldung);
    eins.appendChild(pfuss);
    kasten.appendChild(eins);

    /* --- Schritt 2: die Zugänge ----------------------------------------- */
    var zwei = bauen("div", "assi-schritt");
    zwei.appendChild(bauen("h3", "", "2. Welche Karten möchtest du?"));
    zwei.appendChild(bauen("p", "assi-hinweis",
      "Trag ein, was du hast. Alles andere lässt du frei — die Karte bleibt "
      + "dann einfach aus, und nichts geht kaputt."));
    for (var s = 0; s < d.schritte.length; s++) {
      zwei.appendChild(assiKarte(d.schritte[s]));
    }
    kasten.appendChild(zwei);

    /* --- Abschluss ------------------------------------------------------ */
    var ende = bauen("div", "assi-schritt assi-ende");
    var fertig = bauen("button", "knopf-haupt", "Fertig — zum Dashboard");
    fertig.type = "button";
    fertig.addEventListener("click", function () {
      fertig.disabled = true;
      holen("/api/einrichtung/fertig", "POST", {}).then(function () {
        window.location.href = window.location.pathname + "?frisch=" + Date.now();
      }).catch(function () { fertig.disabled = false; });
    });
    ende.appendChild(fertig);
    ende.appendChild(bauen("p", "assi-hinweis",
      "Du kannst den Assistenten später unter Settings → Wartung wieder öffnen."));
    kasten.appendChild(ende);
  }

  function assistentSchliessen() {
    var kasten = document.getElementById("assistent");
    if (!kasten || kasten.hidden) { return; }
    kasten.hidden = true;
    leeren(kasten);
    var raster = document.getElementById("raster");
    if (raster) { raster.hidden = false; }
  }

  function assiKarte(schritt) {
    var block = bauen("details", "assi-karte");
    if (schritt.eingerichtet) { block.className += " fertig"; }
    var titel = document.createElement("summary");
    titel.appendChild(bauen("span", "assi-icon", schritt.icon));
    titel.appendChild(bauen("strong", "", schritt.titel));
    titel.appendChild(bauen("span", "assi-stand",
      schritt.eingerichtet ? "eingerichtet" : "offen"));
    block.appendChild(titel);

    // Der Posteingang hat keine Felder, sondern Postfächer — dafür gibt es
    // einen eigenen Editor in den Einstellungen.
    if (schritt.postfaecher) {
      var p = bauen("p", "assi-hinweis",
        "Postfächer legst du unter Settings → Postfächer an, je Postfach "
        + "entweder über die Anbieter-API oder per IMAP.");
      block.appendChild(p);
      var hin = bauen("a", "", "Zu den Postfächern");
      hin.href = "#einstellungen";
      block.appendChild(hin);
      return block;
    }

    // Der Kalender braucht eine Anmeldung, kein Textfeld — derselbe Block
    // wie in den Einstellungen, damit man nicht dorthin wechseln muss.
    if (schritt.karte === "kalender") { googleAnmeldung(block); }

    var eingaben = {};
    for (var i = 0; i < schritt.felder.length; i++) {
      var f = schritt.felder[i];
      var noetig = schritt.braucht.indexOf(f.schluessel) !== -1;
      var feld = bauen("div", "e-feld");
      var b = bauen("label", "", f.titel + (noetig ? "" : " (optional)"));
      b.setAttribute("for", "assi-" + f.schluessel);
      feld.appendChild(b);
      var ein;
      if (f.auswahl && f.auswahl.length) {
        // Steht der Schluessel schon, liefert der Server die Liste — dann ist
        // Tippen einer Kennung wie „ib_…“ nur eine Fehlerquelle.
        ein = document.createElement("select");
        for (var w = 0; w < f.auswahl.length; w++) {
          var opt = document.createElement("option");
          opt.value = f.auswahl[w].wert;
          opt.appendChild(document.createTextNode(f.auswahl[w].titel));
          if (f.auswahl[w].wert === f.wert) { opt.selected = true; }
          ein.appendChild(opt);
        }
      } else {
        ein = document.createElement("input");
        ein.type = "text";
      }
      ein.id = "assi-" + f.schluessel;
      ein.setAttribute("autocomplete", "off");
      if (f.geheim) {
        ein.value = "";
        ein.placeholder = f.gesetzt ? "hinterlegt — zum Ändern neu eintragen" : "";
      } else {
        ein.value = f.wert || "";
      }
      feld.appendChild(ein);
      if (f.hilfe) { feld.appendChild(bauen("div", "e-hilfe", f.hilfe)); }
      block.appendChild(feld);
      eingaben[f.schluessel] = ein;
    }

    var meldung = bauen("span", "e-ergebnis", "");
    var knopf = bauen("button", "knopf-haupt", "Speichern und prüfen");
    knopf.type = "button";
    knopf.addEventListener("click", function () {
      var werte = {};
      for (var k in eingaben) {
        if (!Object.prototype.hasOwnProperty.call(eingaben, k)) { continue; }
        if (!eingaben[k].value) { continue; }   // leer heißt "unverändert"
        werte[k] = eingaben[k].value;
      }
      knopf.disabled = true;
      meldung.className = "e-ergebnis";
      meldung.textContent = "wird gespeichert …";
      holen("/api/einstellungen", "POST", { werte: werte }).then(function () {
        meldung.textContent = "wird geprüft …";
        return holen("/api/einstellungen/pruefen/" + schritt.karte, "POST");
      }).then(function (a) {
        meldung.className = "e-ergebnis " + (a.ok ? "gut" : "schlecht");
        meldung.textContent = (a.ok ? "✓ " : "✗ ") + a.meldung;
        if (a.ok) {
          block.className = "assi-karte fertig";
          block.querySelector(".assi-stand").textContent = "eingerichtet";
        }
      }).catch(function (f) {
        meldung.className = "e-ergebnis schlecht";
        meldung.textContent = "✗ " + f.message;
      }).then(function () { knopf.disabled = false; });
    });
    var fuss = bauen("div", "assi-fuss");
    fuss.appendChild(knopf);
    fuss.appendChild(meldung);
    block.appendChild(fuss);
    return block;
  }

  function einrichtungLaden() {
    return holen("/api/einrichtung").then(function (d) {
      if (d.noetig) { assistentZeigen(d); }
    }).catch(function () { /* ohne Antwort einfach das normale Dashboard */ });
  }

  /* ----------------------------------------------------------- Update */

  // Läuft gerade ein Update? Dann bleibt die Seite dran, auch wenn der Server
  // zwischendurch nicht antwortet.
  var updateWacht = false;
  var updateVersuche = 0;

  function updateLaden(frisch, dran) {
    var kasten = document.getElementById("update-stand");
    if (!kasten) { return Promise.resolve(); }
    if (!dran) { updateVersuche = 0; }
    return holen("/api/update" + (frisch ? "?frisch=1" : "")).then(function (d) {
      updateVersuche = 0;
      leeren(kasten);
      var s = d.stand || {};
      // `stand` sagt, was der Server zuletzt TAT; `lage` sagt frisch
      // verglichen, ob etwas BEREITLIEGT. Nach einem Aufspielen steht in der
      // Datei noch „verfügbar“, obwohl die Nummern längst gleich sind.
      var l = d.lage || {};
      var laeuft = s.zustand === "laeuft" || d.angefordert;

      var zeile = bauen("p", "update-zeile");
      if (d.fassung) {
        zeile.appendChild(bauen("span", "", "Läuft auf Version "));
        zeile.appendChild(bauen("strong", "", d.fassung));
      } else if (s.commit) {
        // Versionsnummern gibt es erst seit 1.0.0; ältere Stände haben nur eine
        // Commit-Kennung.
        zeile.appendChild(bauen("span", "", "Läuft auf Stand "));
        zeile.appendChild(bauen("code", "", s.commit));
      } else {
        zeile.appendChild(bauen("span", "", "Der laufende Stand ist noch nicht vermerkt — "
          + "einmal „Nachsehen“ drücken."));
      }
      kasten.appendChild(zeile);

      // Was die laufende Version gebracht hat — eingeklappt, damit es nur
      // liest, wer es wissen will.
      if (d.aenderungen_hier && d.aenderungen_hier.length) {
        var auf = document.createElement("details");
        var titel = document.createElement("summary");
        titel.textContent = "Was Version " + (d.fassung || "diese") + " gebracht hat";
        auf.appendChild(titel);
        var liste = bauen("ul", "");
        for (var h = 0; h < d.aenderungen_hier.length; h++) {
          liste.appendChild(bauen("li", "", d.aenderungen_hier[h]));
        }
        auf.appendChild(liste);
        auf.className = "update-aenderungen";
        kasten.appendChild(auf);
      }

      // Was die neue Version bringt — bevor man sie aufspielt, nicht danach.
      if (l.verfuegbar && l.aenderungen && l.aenderungen.length) {
        var was = bauen("div", "update-aenderungen");
        was.appendChild(bauen("strong", "", "Neu in " + (l.neue_fassung || "dieser Version") + ":"));
        var ul = bauen("ul", "");
        for (var i = 0; i < l.aenderungen.length; i++) {
          var text = l.aenderungen[i].replace(/^[-*]\s*/, "").replace(/\*\*/g, "");
          ul.appendChild(bauen("li", "", text));
        }
        was.appendChild(ul);
        kasten.appendChild(was);
      }

      // „läuft" und „fehler" sagen, was der Server GERADE tut — die gehören
      // nach vorn. „fertig" gehört NICHT dazu: Der Zustand bleibt nach einem
      // Update für immer stehen, und die Erfolgsmeldung verdeckte damit jede
      // neue Version. Liegt etwas bereit, zählt deshalb immer der frische
      // Vergleich; steht nichts an, darf „Auf Version X gebracht" stehen.
      // Der Punkt in der Seitenleiste kommt sonst erst mit der Übersicht im
      // Minutentakt nach — nach einem „Nachsehen" stünden Kasten und Leiste
      // bis zu eine Minute lang im Widerspruch.
      updateHinweisZeichnen({ verfuegbar: l.verfuegbar, meldung: l.meldung });

      var jetzt = s.zustand === "laeuft" || s.zustand === "fehler";
      var meldung = jetzt ? s.meldung
        : (l.verfuegbar ? l.meldung : (s.meldung || l.meldung));
      var wann = jetzt ? s.am : (l.verfuegbar ? l.am : (s.am || l.am));
      if (meldung) {
        var art = s.zustand === "fehler" ? " schlecht"
          : (l.verfuegbar ? "" : " gut");
        var m = bauen("p", "e-ergebnis" + art, meldung);
        if (wann) { m.appendChild(bauen("small", "", " · " + wann.replace("T", " ").slice(0, 16))); }
        kasten.appendChild(m);
      }

      var knopf = bauen("button", "knopf-haupt", laeuft ? "läuft …" : "Jetzt aufspielen");
      knopf.type = "button";
      knopf.disabled = laeuft;
      knopf.addEventListener("click", function () {
        if (!window.confirm("Diese Instanz auf den neuen Stand bringen?\n\n"
            + "Die Seite ist dabei ein bis zwei Minuten nicht erreichbar. "
            + "Zugangsdaten und alles Eingetragene bleiben erhalten, und bei "
            + "einem Fehlschlag kommt der vorherige Stand zurück.")) { return; }
        knopf.disabled = true;
        anfordern({});
      });
      kasten.appendChild(knopf);
      // Solange etwas läuft, von selbst nachsehen — sonst muss man raten,
      // wann es durch ist.
      if (laeuft) {
        updateWacht = true;
        window.setTimeout(function () { updateLaden(false, true); }, 2000);
      } else if (updateWacht) {
        // Gerade noch gelaufen, jetzt fertig: Die Seite hängt bis hierhin am
        // ALTEN JavaScript und zeigte die alte Nummer. Einmal neu laden.
        updateWacht = false;
        if (s.zustand === "fertig") {
          // Kein reload(): Safari holt die Seite dann gern aus dem Cache.
          window.location.href = window.location.pathname + "?frisch=" + Date.now()
            + "#einstellungen";
        }
        // Bei „fehler" bewusst NICHT neu laden — die rote Meldung ist die
        // einzige Spur, was schiefgegangen ist.
      }
    }).catch(function () {
      // Genau hier stand der Kasten still: Beim Neubau ist das Dashboard ein
      // paar Sekunden weg, die Nachfrage scheitert — und ohne neuen Termin
      // fragte die Seite nie wieder. Stehen blieb „Baue den Container neu …",
      // obwohl das Update längst durch war. Während eines Laufs ist der
      // Ausfall der ERWARTETE Zustand, kein Grund aufzugeben.
      if (!updateWacht) { return; }
      updateVersuche += 1;
      if (updateVersuche > 90) {           // drei Minuten
        updateWacht = false;
        var kasten2 = document.getElementById("update-stand");
        if (kasten2) {
          leeren(kasten2);
          kasten2.appendChild(bauen("p", "e-ergebnis schlecht",
            "Das Dashboard antwortet seit drei Minuten nicht. Lade die Seite "
            + "neu — das Update läuft auf dem Server weiter."));
        }
        return;
      }
      var kasten = document.getElementById("update-stand");
      if (kasten) {
        leeren(kasten);
        kasten.appendChild(bauen("p", "e-ergebnis", "Container startet neu …"));
      }
      window.setTimeout(function () { updateLaden(false, true); }, 2000);
    });
  }

  function anfordern(daten) {
    return holen("/api/update", "POST", daten).then(function () {
      // Ab jetzt drangeblieben: Der Neubau wirft die Seite gleich kurz aus
      // der Leitung, und ohne diesen Schalter gälte der Ausfall als Abbruch.
      updateWacht = true;
      updateVersuche = 0;
      window.setTimeout(function () { updateLaden(false, true); }, 1500);
    }).catch(function (fehler) {
      var kasten = document.getElementById("update-stand");
      if (kasten) {
        var m = bauen("p", "e-ergebnis schlecht", fehler.message);
        kasten.appendChild(m);
      }
    });
  }

  var updatePruefen = document.getElementById("update-pruefen");
  if (updatePruefen) {
    updatePruefen.addEventListener("click", function () {
      // Fragt direkt bei GitHub nach der Versionsnummer — das dauert
      // Sekundenbruchteile. Früher legte der Knopf eine Anforderung ab, auf
      // die eine Wache erst in der nächsten Minute stieß.
      updatePruefen.disabled = true;
      updatePruefen.textContent = "sieht nach …";
      updateLaden(true).then(function () {
        updatePruefen.disabled = false;
        updatePruefen.textContent = "Nachsehen";
      });
    });
  }

  /* -------------------------------------------- Superchat-Postfachwahl */

  /* Statt eine Kennung wie `ib_a1B2c3D4e5F6g7H8i9J0k` abzutippen: eine Liste mit Namen.

     Die Kennungen stehen in der Weboberfläche von Superchat an derselben
     Stelle wie die Kennung eines geöffneten Gesprächs (`cv_…`). Wer die
     falsche erwischt, bekommt eine Karte, die still leer bleibt — und das
     sieht aus wie ein ruhiger Tag, nicht wie ein Fehler.

     Das Textfeld bleibt der Träger des Werts und wird nur verborgen: Klemmt
     die Verbindung zu Superchat, kann man weiterhin von Hand eintragen,
     statt vor einer leeren Auswahl zu stehen. */

  function postfachwahl(feld, eingabe) {
    var kasten = bauen("div", "pfwahl");
    var gewaehlt = bauen("div", "pfwahl-liste");
    var zeile = bauen("div", "pfwahl-zeile");
    var wahl = document.createElement("select");
    wahl.className = "pfwahl-menue";
    var meldung = bauen("span", "e-ergebnis", "");
    var umschalter = bauen("button", "e-entfernen", "von Hand eintragen");
    umschalter.type = "button";
    var alle = [];

    function kennungen() {
      var roh = (eingabe.value || "").split(",");
      var raus = [];
      for (var i = 0; i < roh.length; i++) {
        var k = roh[i].replace(/^\s+|\s+$/g, "");
        if (k && raus.indexOf(k) === -1) { raus.push(k); }
      }
      return raus;
    }

    function name(kennung) {
      for (var i = 0; i < alle.length; i++) {
        if (alle[i].id === kennung) { return alle[i].name; }
      }
      return "";
    }

    function setzen(liste) {
      eingabe.value = liste.join(",");
      zeichnen();
    }

    function zeichnen() {
      var jetzt = kennungen();
      leeren(gewaehlt);
      if (!jetzt.length) {
        gewaehlt.appendChild(bauen("span", "pfwahl-leer",
          "Noch kein Postfach gewählt — die Karte bleibt so lange leer."));
      }
      for (var i = 0; i < jetzt.length; i++) {
        (function (kennung) {
          var chip = bauen("span", "pfwahl-chip");
          var wie = name(kennung);
          chip.appendChild(bauen("strong", "", wie || kennung));
          if (wie) { chip.appendChild(bauen("small", "", kennung)); }
          var weg = bauen("button", "pfwahl-weg", "×");
          weg.type = "button";
          weg.title = "Postfach entfernen";
          weg.addEventListener("click", function () {
            var rest = [];
            var jetzt2 = kennungen();
            for (var j = 0; j < jetzt2.length; j++) {
              if (jetzt2[j] !== kennung) { rest.push(jetzt2[j]); }
            }
            setzen(rest);
          });
          chip.appendChild(weg);
          gewaehlt.appendChild(chip);
        })(jetzt[i]);
      }
      // Schon Gewähltes gehört nicht noch einmal ins Menü.
      leeren(wahl);
      var kopf = document.createElement("option");
      kopf.value = "";
      kopf.textContent = "Postfach hinzufügen …";
      wahl.appendChild(kopf);
      var frei = 0;
      for (var o = 0; o < alle.length; o++) {
        if (jetzt.indexOf(alle[o].id) !== -1) { continue; }
        var opt = document.createElement("option");
        opt.value = alle[o].id;
        opt.textContent = alle[o].name;
        wahl.appendChild(opt);
        frei += 1;
      }
      wahl.disabled = frei === 0;
      if (frei === 0 && alle.length) { kopf.textContent = "alle gewählt"; }
    }

    wahl.addEventListener("change", function () {
      if (!wahl.value) { return; }
      var jetzt = kennungen();
      jetzt.push(wahl.value);
      setzen(jetzt);
    });

    umschalter.addEventListener("click", function () {
      var versteckt = eingabe.style.display === "none";
      eingabe.style.display = versteckt ? "" : "none";
      umschalter.textContent = versteckt ? "Auswahl benutzen" : "von Hand eintragen";
      if (versteckt) { eingabe.focus(); } else { zeichnen(); }
    });

    zeile.appendChild(wahl);
    zeile.appendChild(umschalter);
    zeile.appendChild(meldung);
    kasten.appendChild(gewaehlt);
    kasten.appendChild(zeile);
    feld.appendChild(kasten);

    eingabe.style.display = "none";
    meldung.textContent = "Postfächer werden geholt …";
    zeichnen();

    holen("/api/superchat/postfaecher").then(function (d) {
      alle = d.postfaecher || [];
      meldung.textContent = alle.length ? "" : "Keine Postfächer gefunden.";
      zeichnen();
    }).catch(function (fehler) {
      // Ohne Liste ist das Textfeld der einzige Weg — also aufmachen und
      // sagen, warum. Eine leere Auswahl ohne Erklärung wäre eine Sackgasse.
      alle = [];
      eingabe.style.display = "";
      wahl.disabled = true;
      umschalter.textContent = "Auswahl benutzen";
      meldung.className = "e-ergebnis schlecht";
      meldung.textContent = "Liste nicht abrufbar (" + fehler.message
        + ") — Kennung von Hand eintragen.";
      zeichnen();
    });
  }

  /* --------------------------------------------- Anmeldung bei Google */

  /* Zwei Wege fuehren zum Kalender: die normale Anmeldung oder eine
     Dienstkonto-Datei auf dem Server. Dieser Block zeigt, welcher gerade
     traegt — sonst sieht man bei einem laufenden Dienstkonto „nicht
     angemeldet" und haelt eine funktionierende Karte fuer kaputt. */

  function googleAnmeldung(kasten) {
    var block = bauen("div", "g-anmeldung");
    kasten.appendChild(block);
    googleZeichnen(block);
    return block;
  }

  function googleZeichnen(block) {
    leeren(block);
    block.appendChild(bauen("span", "e-ergebnis", "Stand wird geholt …"));
    return holen("/api/google/anmeldung").then(function (d) {
      leeren(block);
      var zeile = bauen("div", "g-zeile");

      if (d.angemeldet) {
        zeile.appendChild(bauen("span", "g-stand gut",
          "✓ Mit Google angemeldet" + (d.konto ? " als " + d.konto : "")));
        var loesen = bauen("button", "e-pruefen", "Verbindung lösen");
        loesen.type = "button";
        loesen.addEventListener("click", function () {
          if (!window.confirm("Die Google-Anmeldung lösen?\n\n"
              + (d.dienstkonto
                 ? "Die Karte fällt danach auf das Dienstkonto zurück."
                 : "Die Kalenderkarte hat danach keinen Zugang mehr."))) { return; }
          loesen.disabled = true;
          holen("/api/google/abmelden", "POST").then(function () {
            googleZeichnen(block);
          }).catch(function () { loesen.disabled = false; });
        });
        zeile.appendChild(loesen);
        block.appendChild(zeile);
        if (d.fehler) {
          block.appendChild(bauen("p", "e-ergebnis schlecht", "✗ " + d.fehler));
        }
        return;
      }

      var knopf = bauen("button", "knopf-haupt", "Mit Google anmelden");
      knopf.type = "button";
      knopf.disabled = !d.client_da;
      var meldung = bauen("span", "e-ergebnis", "");
      knopf.addEventListener("click", function () {
        knopf.disabled = true;
        meldung.className = "e-ergebnis";
        meldung.textContent = "Google wird geöffnet …";
        holen("/api/google/anmeldung", "POST").then(function (a) {
          window.open(a.adresse, "_blank");
          meldung.textContent = "Im neuen Fenster zustimmen — hier wird nachgesehen.";
          // Nachsehen statt fragen: Der Vorgang endet in einem anderen Tab,
          // von dem diese Seite nichts erfaehrt.
          var versuche = 0;
          var takt = window.setInterval(function () {
            versuche += 1;
            holen("/api/google/anmeldung").then(function (n) {
              if (n.angemeldet) {
                window.clearInterval(takt);
                googleZeichnen(block).then(kalenderlisteNachladen);
              } else if (versuche > 60) {
                window.clearInterval(takt);
                meldung.className = "e-ergebnis schlecht";
                meldung.textContent = "Nichts angekommen. Fenster geschlossen?";
                knopf.disabled = false;
              }
            });
          }, 3000);
        }).catch(function (f) {
          meldung.className = "e-ergebnis schlecht";
          meldung.textContent = "✗ " + f.message;
          knopf.disabled = false;
        });
      });
      zeile.appendChild(knopf);
      zeile.appendChild(meldung);
      block.appendChild(zeile);

      if (d.dienstkonto) {
        block.appendChild(bauen("p", "e-hilfe",
          "Die Karte läuft zurzeit über ein Dienstkonto auf dem Server. Eine "
          + "Anmeldung hier hat Vorrang; ohne sie bleibt alles wie es ist."));
      }

      // Die Adresse, die in der Google-Konsole stehen muss. Sie zu zeigen
      // spart den haeufigsten Fehler: redirect_uri_mismatch.
      var anleitung = document.createElement("details");
      anleitung.className = "g-anleitung";
      var titel = document.createElement("summary");
      titel.textContent = d.client_da
        ? "Wo die Weiterleitungs-Adresse hin muss"
        : "Was du einmal in der Google-Konsole tun musst";
      anleitung.appendChild(titel);
      var schritte = document.createElement("ol");
      var texte = [
        "console.cloud.google.com öffnen, ein Projekt wählen oder anlegen.",
        "Unter „APIs & Dienste“ die Google-Calendar-API aktivieren.",
        "Zustimmungsbildschirm einrichten und auf „In Produktion“ setzen — "
          + "bleibt er auf „Test“, verfällt die Anmeldung nach 7 Tagen.",
        "OAuth-Client vom Typ „Webanwendung“ anlegen und unten diese Adresse "
          + "als autorisierte Weiterleitungs-URI eintragen:",
        "Client-ID und Geheimnis in die Felder darunter eintragen und speichern."
      ];
      for (var s = 0; s < texte.length; s++) {
        schritte.appendChild(bauen("li", "", texte[s]));
      }
      anleitung.appendChild(schritte);
      var adresse = bauen("div", "g-rueckweg");
      adresse.appendChild(bauen("code", "", d.rueckweg));
      var kopieren = bauen("button", "e-pruefen", "kopieren");
      kopieren.type = "button";
      kopieren.addEventListener("click", function () {
        if (navigator.clipboard) {
          navigator.clipboard.writeText(d.rueckweg).then(function () {
            kopieren.textContent = "kopiert";
          });
        }
      });
      adresse.appendChild(kopieren);
      anleitung.appendChild(adresse);
      block.appendChild(anleitung);
    }).catch(function (f) {
      leeren(block);
      block.appendChild(bauen("p", "e-ergebnis schlecht", "✗ " + f.message));
    });
  }

  /* Die Auswahl der Kalender haengt an der Anmeldung: Ein Dienstkonto sieht
     in seiner Liste meist gar nichts, deshalb bleibt dort das Textfeld. */

  var kalenderNachladen = null;

  function kalenderlisteNachladen() {
    if (kalenderNachladen) { kalenderNachladen(); }
  }

  function kalenderwahl(feld, eingabe) {
    var zeile = bauen("div", "pfwahl");
    var wahl = document.createElement("select");
    var meldung = bauen("span", "e-ergebnis", "");
    var umschalter = bauen("button", "pfwahl-hand", "von Hand eintragen");
    umschalter.type = "button";

    function zeichnen(liste) {
      leeren(wahl);
      var kopf = document.createElement("option");
      kopf.value = "";
      kopf.textContent = "Kalender wählen …";
      wahl.appendChild(kopf);
      for (var i = 0; i < liste.length; i++) {
        var opt = document.createElement("option");
        opt.value = liste[i].wert;
        opt.textContent = liste[i].titel;
        if (liste[i].wert === eingabe.value) { opt.selected = true; }
        wahl.appendChild(opt);
      }
      // Ein leeres, graues Klappfeld sieht nach kaputt aus. Ohne Liste steht
      // hier gar nichts — dann ist das Textfeld der ganz normale Weg.
      wahl.style.display = liste.length ? "" : "none";
    }

    function laden() {
      meldung.className = "e-ergebnis";
      meldung.textContent = "Kalender werden geholt …";
      return holen("/api/google/kalender").then(function (d) {
        var liste = d.kalender || [];
        zeichnen(liste);
        eingabe.style.display = liste.length ? "none" : "";
        umschalter.style.display = liste.length ? "" : "none";
        umschalter.textContent = "von Hand eintragen";
        meldung.textContent = liste.length ? "" : "Keine Kalender gefunden.";
      }).catch(function () {
        // Ohne Anmeldung ist das Textfeld der normale Weg, kein Fehlerfall —
        // deshalb hier kein rotes „✗", sondern schlicht nichts.
        zeichnen([]);
        eingabe.style.display = "";
        umschalter.style.display = "none";
        meldung.textContent = "";
      });
    }

    wahl.addEventListener("change", function () {
      if (wahl.value) { eingabe.value = wahl.value; }
    });
    umschalter.addEventListener("click", function () {
      var versteckt = eingabe.style.display === "none";
      eingabe.style.display = versteckt ? "" : "none";
      umschalter.textContent = versteckt ? "Auswahl benutzen" : "von Hand eintragen";
      if (versteckt) { eingabe.focus(); }
    });

    zeile.appendChild(wahl);
    zeile.appendChild(umschalter);
    zeile.appendChild(meldung);
    feld.appendChild(zeile);
    kalenderNachladen = laden;
    laden();
  }

  /* ------------------------------------------------------- Postfaecher */

  /* Jedes Postfach traegt seinen eigenen Weg: Hostinger-Mail-API oder IMAP.
     Frueher war das ein globaler Schalter — dann gab es entweder ein
     API-Postfach oder beliebig viele IMAP-Postfaecher, nie beides und das
     erste nie zum Loeschen. */

  var WEGE = [["api", "Hostinger-Mail-API"], ["imap", "IMAP"]];
  // Welche Felder welcher Weg braucht. Was hier nicht steht, bleibt verborgen —
  // ein Server-Feld beim API-Weg waere eine Frage ohne Antwort.
  var WEG_FELDER = {
    api: ["bezeichnung", "benutzer", "passwort", "postfach_id", "webmail"],
    imap: ["bezeichnung", "host", "port", "benutzer", "passwort", "ordner", "webmail"]
  };
  // Dieselben Spalten heissen je nach Weg anders. „Passwort“ fuer einen Token
  // zu sagen, schickt jeden auf die Suche nach einem Passwort, das es nicht gibt.
  var WEG_NAMEN = {
    api: { benutzer: "Adresse", passwort: "API-Token" },
    imap: { benutzer: "Benutzer", passwort: "Passwort" }
  };

  function postfachFeld(kasten, konto, schluessel, beschriftung, typ, hinweis) {
    var feld = bauen("div", "e-feld");
    var kennung = "pf-" + (konto.id || "neu") + "-" + schluessel;
    var b = bauen("label", "", beschriftung);
    b.setAttribute("for", kennung);
    feld.appendChild(b);
    var ein = document.createElement("input");
    ein.id = kennung;
    ein.type = typ || "text";
    ein.setAttribute("data-feld", schluessel);
    ein.setAttribute("autocomplete", "off");
    if (schluessel === "passwort") {
      // Wie überall: hinterlegte Geheimnisse gehen nie zurück an den Browser.
      ein.value = "";
      ein.placeholder = konto.passwort_gesetzt
        ? ("hinterlegt (" + (konto.spur || "····") + ") — zum Ändern neu eintragen")
        : "noch nicht hinterlegt";
    } else {
      ein.value = konto[schluessel] === undefined || konto[schluessel] === null
        ? "" : String(konto[schluessel]);
      if (hinweis) { ein.placeholder = hinweis; }
    }
    feld.appendChild(ein);
    kasten.appendChild(feld);
    return ein;
  }

  function postfachZeichnen(konto) {
    var kasten = bauen("div", "postfach");
    var kopf = bauen("div", "postfach-kopf");
    var titel = bauen("strong", "",
      konto.bezeichnung || konto.benutzer || "Neues Postfach");
    kopf.appendChild(titel);

    var ergebnis = bauen("span", "e-ergebnis", "");
    var pruefen = bauen("button", "e-pruefen postfach-weg", "Prüfen");
    pruefen.type = "button";
    kopf.appendChild(pruefen);
    kasten.appendChild(kopf);

    var felder = bauen("div", "postfach-felder");

    var wegFeld = bauen("div", "e-feld");
    var wegBeschriftung = bauen("label", "", "Weg");
    wegFeld.appendChild(wegBeschriftung);
    var wegWahl = document.createElement("select");
    for (var w = 0; w < WEGE.length; w++) {
      var o = document.createElement("option");
      o.value = WEGE[w][0];
      o.textContent = WEGE[w][1];
      wegWahl.appendChild(o);
    }
    wegWahl.value = konto.weg === "api" ? "api" : "imap";
    wegFeld.appendChild(wegWahl);
    var wegHilfe = bauen("p", "e-hilfe",
      "Die Anbieter-API braucht kein Passwort, kennt aber nur Postfächer, die "
      + "dort geführt werden. IMAP funktioniert mit jedem Anbieter.");
    wegFeld.appendChild(wegHilfe);
    felder.appendChild(wegFeld);

    var eingaben = {
      bezeichnung: postfachFeld(felder, konto, "bezeichnung", "Name", "text",
                                "z. B. Buchhaltung"),
      host: postfachFeld(felder, konto, "host", "Server", "text",
                         "Posteingangsserver des Anbieters"),
      port: postfachFeld(felder, konto, "port", "Port", "text", "993"),
      benutzer: postfachFeld(felder, konto, "benutzer", "Benutzer", "text",
                             "meist die volle Adresse"),
      passwort: postfachFeld(felder, konto, "passwort", "Passwort", "password"),
      postfach_id: postfachFeld(felder, konto, "postfach_id", "Postfach-Kennung",
                                "text", "leer lassen — wird selbst gesucht"),
      ordner: postfachFeld(felder, konto, "ordner", "Ordner", "text", "INBOX"),
      webmail: postfachFeld(felder, konto, "webmail", "Webmail-Adresse", "text",
                            "https://webmail.anbieter.de — nicht die E-Mail-Adresse")
    };
    kasten.appendChild(felder);

    function wegAnwenden() {
      var weg = wegWahl.value === "api" ? "api" : "imap";
      var erlaubt = WEG_FELDER[weg];
      for (var k in eingaben) {
        if (!Object.prototype.hasOwnProperty.call(eingaben, k)) { continue; }
        var dabei = erlaubt.indexOf(k) !== -1;
        // display statt hidden: .e-feld setzt eigene Regeln, und ein
        // verborgenes Feld darf keine Lücke hinterlassen.
        eingaben[k].parentNode.style.display = dabei ? "" : "none";
        var name = WEG_NAMEN[weg][k];
        if (dabei && name) {
          eingaben[k].parentNode.firstChild.textContent = name;
        }
      }
      if (weg === "api" && !eingaben.webmail.value) {
        eingaben.webmail.placeholder = "z. B. https://mail.hostinger.com/";
      }
    }
    wegAnwenden();
    wegWahl.addEventListener("change", wegAnwenden);

    var fuss = bauen("div", "postfach-fuss");
    var speichern = bauen("button", "knopf-haupt", "Speichern");
    speichern.type = "button";
    fuss.appendChild(speichern);

    var aktivFeld = bauen("label", "postfach-aktiv");
    var aktiv = document.createElement("input");
    aktiv.type = "checkbox";
    aktiv.checked = konto.aktiv !== false;
    aktivFeld.appendChild(aktiv);
    aktivFeld.appendChild(document.createTextNode("wird gelesen"));
    fuss.appendChild(aktivFeld);
    fuss.appendChild(ergebnis);

    var weg = bauen("button", "postfach-loeschen",
                    konto.id ? "Postfach löschen" : "Verwerfen");
    weg.type = "button";
    weg.addEventListener("click", function () {
      // Ein noch nicht gespeichertes Postfach steht nirgends — es einfach
      // wegzunehmen ist ehrlicher als eine Rückfrage nach etwas, das es in
      // der Datenbank gar nicht gibt.
      if (!konto.id) {
        if (kasten.parentNode) { kasten.parentNode.removeChild(kasten); }
        return;
      }
      var name = konto.bezeichnung || konto.benutzer || "Dieses Postfach";
      if (!window.confirm(name + " wirklich löschen? Der hinterlegte Zugang "
                          + "wird dabei mit gelöscht.")) { return; }
      holen("/api/mailkonten/" + konto.id, "DELETE").then(function (d) {
        postfaecherZeichnen(d.konten);
      }).catch(function (f) {
        ergebnis.className = "e-ergebnis schlecht";
        ergebnis.textContent = f.message;
      });
    });
    fuss.appendChild(weg);
    kasten.appendChild(fuss);

    function sammeln() {
      var d = { id: konto.id, aktiv: aktiv.checked, weg: wegWahl.value };
      var erlaubt = WEG_FELDER[d.weg];
      for (var k in eingaben) {
        if (!Object.prototype.hasOwnProperty.call(eingaben, k)) { continue; }
        // Leeres Passwort heisst "unveraendert lassen", nicht "loeschen".
        if (k === "passwort" && !eingaben[k].value) { continue; }
        // Felder des anderen Wegs werden nicht mitgeschickt, aber auch nicht
        // geleert: Wer versehentlich umschaltet, verliert seine IMAP-Angaben
        // nicht.
        if (erlaubt.indexOf(k) === -1) { continue; }
        d[k] = eingaben[k].value;
      }
      return d;
    }

    speichern.addEventListener("click", function () {
      speichern.disabled = true;
      ergebnis.className = "e-ergebnis";
      ergebnis.textContent = "wird gespeichert …";
      holen("/api/mailkonten", "POST", sammeln()).then(function (d) {
        postfaecherZeichnen(d.konten);
      }).catch(function (f) {
        ergebnis.className = "e-ergebnis schlecht";
        ergebnis.textContent = f.message;
      }).then(function () { speichern.disabled = false; });
    });

    pruefen.addEventListener("click", function () {
      if (!konto.id) {
        ergebnis.className = "e-ergebnis schlecht";
        ergebnis.textContent = "erst speichern, dann prüfen";
        return;
      }
      pruefen.disabled = true;
      ergebnis.className = "e-ergebnis";
      ergebnis.textContent = "wird geprüft …";
      holen("/api/mailkonten/" + konto.id + "/pruefen", "POST").then(function (a) {
        ergebnis.className = "e-ergebnis " + (a.ok ? "gut" : "schlecht");
        ergebnis.textContent = (a.ok ? "✓ " : "✗ ") + a.meldung;
      }).catch(function (f) {
        ergebnis.className = "e-ergebnis schlecht";
        ergebnis.textContent = "✗ " + f.message;
      }).then(function () { pruefen.disabled = false; });
    });

    return kasten;
  }

  function postfaecherZeichnen(konten) {
    var liste = document.getElementById("postfach-liste");
    if (!liste) { return; }
    leeren(liste);
    if (!konten.length) {
      liste.appendChild(bauen("p", "mcp-text postfach-leer",
        "Noch kein Postfach hinterlegt. Mit „+ Postfach“ eines anlegen — "
        + "die Karte „Posteingang“ bleibt so lange leer."));
      return;
    }
    for (var i = 0; i < konten.length; i++) {
      liste.appendChild(postfachZeichnen(konten[i]));
    }
  }

  function postfaecherLaden() {
    return holen("/api/mailkonten").then(function (d) {
      postfaecherZeichnen(d.konten);
    }).catch(function () { /* Kasten bleibt leer */ });
  }

  var postfachNeu = document.getElementById("postfach-neu");
  if (postfachNeu) {
    postfachNeu.addEventListener("click", function () {
      var liste = document.getElementById("postfach-liste");
      // Der Platzhaltertext „noch keines hinterlegt“ muss weg, sobald das
      // erste Postfach angelegt wird — sonst steht er über dem Formular.
      var leer = liste.querySelector(".postfach-leer");
      if (leer) { liste.removeChild(leer); }
      liste.appendChild(postfachZeichnen(
        { weg: "imap", port: 993, ordner: "INBOX", aktiv: true }));
    });
  }

  function webhookLaden() {
    var kasten = document.querySelector('[data-bereich="Rückmeldungen"]');
    if (!kasten) { return; }
    var alt = kasten.querySelector(".webhook-stand");
    if (alt) { kasten.removeChild(alt); }

    return holen("/api/webhook").then(function (d) {
      var zeile = bauen("div", "webhook-stand");
      var test = bauen("button", "e-pruefen", "Probemeldung senden");
      test.type = "button";
      var ergebnis = bauen("span", "e-ergebnis", "");

      if (!d.eingerichtet) {
        zeile.appendChild(bauen("p", "mcp-text",
          "Kein Webhook eingerichtet. Ohne ihn holt die KI die Antworten "
            + "selbst ab (antworten_lesen) — das funktioniert genauso, nur nicht sofort."));
        test.disabled = true;
      } else {
        var s = d.stand || {};
        var text = d.bearer ? "Mit Authorization: Bearer. " : "OHNE Bearer — Cursor lehnt das mit 401 ab. ";
        text += d.signiert ? "Zusätzlich HMAC-signiert. " : "";
        if (s.zuletzt) {
          text += (s.ok ? "Zuletzt zugestellt " : "Zuletzt fehlgeschlagen ")
            + relativ(s.zuletzt) + " " + uhrzeit(s.zuletzt)
            + (s.meldung ? " (" + s.meldung + ")" : "");
        } else {
          text += "Noch nichts gemeldet.";
        }
        var p = bauen("p", "mcp-text", text);
        if (!d.bearer || (s.zuletzt && !s.ok)) { p.className = "mcp-text webhook-warnung"; }
        zeile.appendChild(p);
        // Der Klartext-Hinweis aus dem Fehlerfall — er sagt, was zu tun ist,
        // statt nur, dass etwas nicht ging.
        if (s.hinweis) { zeile.appendChild(bauen("p", "webhook-hinweis", s.hinweis)); }
      }

      test.addEventListener("click", function () {
        test.disabled = true;
        ergebnis.className = "e-ergebnis";
        ergebnis.textContent = "wird gesendet …";
        holen("/api/webhook/test", "POST").then(function () {
          // Der Versand laeuft im Hintergrund; erst danach lohnt der Blick
          // auf den Stand.
          window.setTimeout(function () {
            holen("/api/webhook").then(function (neu) {
              var s2 = neu.stand || {};
              ergebnis.className = "e-ergebnis " + (s2.ok ? "gut" : "schlecht");
              ergebnis.textContent = (s2.ok ? "✓ " : "✗ ") + (s2.meldung || "keine Rückmeldung");
              test.disabled = false;
              webhookLaden();   // Hinweis und Zustand gleich mit auffrischen
            });
          }, 3500);
        }).catch(function (f) {
          ergebnis.className = "e-ergebnis schlecht";
          ergebnis.textContent = "✗ " + f.message;
          test.disabled = false;
        });
      });

      var knopfzeile = bauen("div", "webhook-knoepfe");
      knopfzeile.appendChild(test);
      knopfzeile.appendChild(ergebnis);
      zeile.appendChild(knopfzeile);
      kasten.appendChild(zeile);
    }).catch(function () { /* Bereich bleibt ohne Zusatz */ });
  }

  function mcpLaden() {
    var kasten = document.getElementById("mcp-kasten");
    if (!kasten) { return; }
    return holen("/api/mcp").then(function (d) {
      if (!d.vorhanden) { kasten.hidden = true; return; }
      kasten.hidden = false;
      document.getElementById("mcp-adresse").textContent = d.adresse_maskiert;
      document.getElementById("mcp-befehl").textContent =
        "claude mcp add --transport http smg-" + INSTANZ + " " + d.adresse_maskiert;
      var liste = document.getElementById("mcp-werkzeuge");
      leeren(liste);
      for (var i = 0; i < d.werkzeuge.length; i++) {
        var li = document.createElement("li");
        li.appendChild(bauen("b", "", d.werkzeuge[i].name));
        li.appendChild(document.createTextNode(" — " + d.werkzeuge[i].beschreibung));
        liste.appendChild(li);
      }
    }).catch(function () { kasten.hidden = true; });
  }

  function mcpMeldung(text, gut) {
    var m = document.getElementById("mcp-meldung");
    m.className = "e-ergebnis " + (gut ? "gut" : "schlecht");
    m.textContent = text;
  }

  function mcpAdresseHolen() {
    return holen("/api/mcp/adresse").then(function (d) { return d.adresse; });
  }

  function mcpEinsetzen(adresse) {
    document.getElementById("mcp-adresse").textContent = adresse;
    document.getElementById("mcp-befehl").textContent =
      "claude mcp add --transport http smg-" + INSTANZ + " " + adresse;
  }

  var mcpKopieren = document.getElementById("mcp-kopieren");
  if (mcpKopieren) {
    mcpKopieren.addEventListener("click", function () {
      mcpMeldung("wird geholt …", true);
      mcpAdresseHolen().then(function (adresse) {
        // In die Zwischenablage, ohne sie auf den Bildschirm zu schreiben —
        // so landet der Token nicht in einem Bildschirmfoto.
        if (navigator.clipboard && navigator.clipboard.writeText) {
          return navigator.clipboard.writeText(adresse).then(function () {
            mcpMeldung("✓ kopiert — jetzt im Connector einfügen", true);
          }, function () {
            // Aeltere Browser (Safari 12) koennen das nicht; dann zeigen.
            mcpEinsetzen(adresse);
            mcpMeldung("Kopieren geht hier nicht — Adresse steht jetzt oben", true);
          });
        }
        mcpEinsetzen(adresse);
        mcpMeldung("Kopieren geht hier nicht — Adresse steht jetzt oben", true);
      }).catch(function (f) { mcpMeldung("✗ " + f.message, false); });
    });
  }

  var mcpZeigen = document.getElementById("mcp-zeigen");
  if (mcpZeigen) {
    mcpZeigen.addEventListener("click", function () {
      mcpAdresseHolen().then(function (adresse) {
        mcpEinsetzen(adresse);
        mcpMeldung("sichtbar — nicht abfotografieren", false);
      }).catch(function (f) { mcpMeldung("✗ " + f.message, false); });
    });
  }

  var SCHLUESSEL_BEREICH = "smg-" + INSTANZ + "-settings-bereich";

  function bereichSetzen(name) {
    var kaesten = document.querySelectorAll("#einstellungen .e-gruppe");
    for (var i = 0; i < kaesten.length; i++) {
      var eigener = kaesten[i].getAttribute("data-bereich");
      // Kästen ohne Bereich gehören zu keinem Reiter und bleiben immer
      // stehen — die Wartung unten ist kein Zugang, den man umschaltet.
      if (!eigener) { continue; }
      kaesten[i].classList.toggle("aus", eigener !== name);
    }
    var knoepfe = document.querySelectorAll("#e-reiter button");
    for (var j = 0; j < knoepfe.length; j++) {
      knoepfe[j].classList.toggle("aktiv",
        knoepfe[j].getAttribute("data-bereich") === name);
    }
    speicherSchreiben(SCHLUESSEL_BEREICH, name);
    // Der Speichern-Knopf gilt weiter für ALLE Felder, auch die gerade
    // ausgeblendeten — sonst ginge beim Umschalten eine Eingabe verloren.
  }

  function reiterBauen() {
    var leiste = document.getElementById("e-reiter");
    if (!leiste) { return; }
    leeren(leiste);
    var kaesten = document.querySelectorAll("#einstellungen .e-gruppe");
    var namen = [];
    for (var i = 0; i < kaesten.length; i++) {
      var n = kaesten[i].getAttribute("data-bereich");
      if (n && namen.indexOf(n) === -1) { namen.push(n); }
    }
    for (var k = 0; k < namen.length; k++) {
      (function (name) {
        var knopf = document.createElement("button");
        knopf.type = "button";
        knopf.setAttribute("data-bereich", name);
        knopf.appendChild(document.createTextNode(name));
        var kasten = document.querySelector('[data-bereich="' + name + '"]');
        // Bei den Postfächern zählen die Postfächer, nicht die Eingabefelder:
        // Drei Postfächer haben zusammen 27 Felder, und „27“ am Reiter sagt
        // niemandem, dass es drei sind.
        var faecher = kasten ? kasten.querySelectorAll(".postfach").length : 0;
        var zahl = faecher || (kasten ? kasten.querySelectorAll(".e-feld").length : 0);
        if (zahl) {
          knopf.appendChild(bauen("span", "e-reiter-zahl", String(zahl)));
        }
        knopf.addEventListener("click", function () { bereichSetzen(name); });
        leiste.appendChild(knopf);
      })(namen[k]);
    }
    var gemerkt = speicherLesen(SCHLUESSEL_BEREICH, "");
    bereichSetzen(namen.indexOf(gemerkt) !== -1 ? gemerkt : namen[0]);
  }

  function zugaengeLaden() {
    return holen("/api/einstellungen").then(function (d) {
      zugaengeZeichnen(d.felder, d.gruppen_karte);
      // Erst alle Kästen da, dann die Reiter — sie zählen die Felder je Bereich.
      postfaecherLaden().then(webhookLaden).then(mcpLaden).then(updateLaden).then(reiterBauen);
      zugaengeGeladen = true;
    }).catch(function (f) {
      var m = document.getElementById("einstellungen-meldung");
      m.className = "einstellungen-meldung schlecht";
      m.textContent = f.message;
    });
  }

  var speichern = document.getElementById("einstellungen-speichern");
  if (speichern) {
    speichern.addEventListener("click", function () {
      var werte = {};
      var eingaben = document.querySelectorAll(
        "#einstellungen-gruppen input, #einstellungen-gruppen select");
      for (var i = 0; i < eingaben.length; i++) {
        var schluessel = eingaben[i].getAttribute("data-schluessel");
        var platzhalter = eingaben[i].placeholder || "";
        var geheim = platzhalter.indexOf("hinterlegt") === 0
          || platzhalter.indexOf("noch nichts") === 0;
        // Bei Geheimnissen zaehlt nur, was wirklich eingetippt wurde: Ein
        // leeres Feld heisst "unveraendert lassen", nicht "loeschen".
        if (geheim && !eingaben[i].value) { continue; }
        werte[schluessel] = eingaben[i].value;
      }
      var m = document.getElementById("einstellungen-meldung");
      speichern.disabled = true;
      m.className = "einstellungen-meldung";
      m.textContent = "wird gespeichert …";
      holen("/api/einstellungen", "POST", { werte: werte })
        .then(function (a) {
          zugaengeZeichnen(a.felder, {});
          return holen("/api/einstellungen");
        })
        .then(function (d) {
          zugaengeZeichnen(d.felder, d.gruppen_karte);
          reiterBauen();
          m.textContent = "Gespeichert. Betroffene Karten werden neu geholt.";
        })
        .catch(function (f) {
          m.className = "einstellungen-meldung schlecht";
          m.textContent = f.message;
        })
        .then(function () { speichern.disabled = false; });
    });
  }

  /* ------------------------------------------------ Einzelansicht je Karte */

  // Ein Klick in der Leiste oeffnet die Karte als eigene Seite. Der Zustand
  // haengt an der Adresse (#name), damit der Zurueck-Knopf des Browsers das
  // Erwartete tut und man eine Ansicht verschicken kann.
  var gruss = document.getElementById("gruss");
  var grussText = "";

  function ansichtSetzen(name) {
    // Jede Navigation beendet den Assistenten — sonst stuenden Assistent und
    // Raster untereinander, und man saehe zweimal dasselbe Dashboard.
    assistentSchliessen();
    var zugaenge = name === "einstellungen" && Boolean(zugaengeBereich);
    document.body.classList.toggle("zugaenge", zugaenge);
    zugaengeBereich.hidden = !zugaenge;
    if (zugaenge && !zugaengeGeladen) {
      zugaengeLaden();
    } else if (zugaenge) {
      // Beim zweiten Öffnen blieb der Update-Kasten auf dem Stand von vorhin
      // stehen — `zugaengeGeladen` verhinderte jedes Nachladen. Die Zugänge
      // selbst müssen nicht neu geholt werden, der Versionsstand schon.
      updateLaden();
    }

    var einzeln = Boolean(name) && Boolean(karten[name]);
    document.body.classList.toggle("einzel", einzeln);

    for (var n in karten) {
      if (!Object.prototype.hasOwnProperty.call(karten, n)) { continue; }
      var el = karten[n].element;
      el.classList.toggle("aus", einzeln && n !== name);
      if (einzeln && n === name) { el.classList.remove("zu"); }
    }

    var knoepfe = document.querySelectorAll(".nav-punkt");
    for (var i = 0; i < knoepfe.length; i++) {
      var ziel = knoepfe[i].getAttribute("data-ziel");
      knoepfe[i].classList.toggle("aktiv",
        (einzeln || zugaenge) ? ziel === name : ziel === "oben");
    }

    if (!grussText) { grussText = gruss.textContent; }
    if (zugaenge) {
      gruss.textContent = "Settings";
      document.title = "Settings — Buchhaltung";
      window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    gruss.textContent = einzeln
      ? (karten[name].daten && karten[name].daten.titel
         ? karten[name].daten.titel
         : karten[name].element.querySelector("h2").textContent)
      : grussText;

    document.title = einzeln ? gruss.textContent + " — Buchhaltung" : "Buchhaltung — SMG";
    window.scrollTo({ top: 0, behavior: "smooth" });
    suchen();
  }

  function ausAdresse() {
    var roh = (window.location.hash || "").replace("#", "");
    if (roh === "einstellungen" && zugaengeBereich) { ansichtSetzen(roh); return; }
    ansichtSetzen(karten[roh] ? roh : "");
  }

  function springenZu(name) {
    return function () {
      // Adresse setzen; das Umschalten macht der hashchange-Empfaenger — so
      // gibt es genau EINEN Weg in die Ansicht, egal ob geklickt, per
      // Zurueck-Knopf oder mit einem verschickten Link.
      window.location.hash = (karten[name] || name === "einstellungen") ? name : "";
    };
  }

  /* --------------------------------------------------------- Fortschritt */

  function fortschrittZeichnen(f, dringend) {
    var gesamt = f.gesamt || 0;
    var erledigt = f.erledigt || 0;
    var anteil = gesamt ? erledigt / gesamt : 0;
    var umfang = 2 * Math.PI * 52;
    document.getElementById("ring-wert").style.strokeDashoffset =
      String(umfang - umfang * anteil);
    document.getElementById("ring-zahl").textContent = erledigt + " von " + gesamt;
    document.getElementById("f-erledigt").textContent = erledigt;
    document.getElementById("f-offen").textContent = f.offen || 0;
    document.getElementById("f-dringend").textContent = dringend;

    // Was die Quellen von selbst als erledigt erkannt haben — nur zeigen,
    // wenn es etwas zu zeigen gibt. Eine Zeile „davon 0 von selbst" stuende
    // jeden Morgen da und wuerde nach zwei Tagen nicht mehr gelesen.
    var vonSelbst = f.von_selbst || 0;
    var erkannt = document.getElementById("fortschritt-erkannt");
    if (erkannt) {
      erkannt.hidden = vonSelbst === 0;
      erkannt.textContent = "davon " + vonSelbst + " von selbst erkannt — "
        + "ohne Haken, weil es in der Quelle erledigt wurde";
    }

    var satz;
    if (gesamt === 0) {
      satz = "Noch nichts zu tun — die Karten füllen sich gerade.";
    } else if (dringend > 0) {
      satz = "Zuerst das Rote: " + dringend + (dringend === 1 ? " Punkt brennt" :
             " Punkte brennen") + ". Der Rest kann warten.";
    } else if (anteil >= 1) {
      satz = "Alles abgehakt. Feierabend im Kopf ist erlaubt.";
    } else {
      satz = "Du hast " + Math.round(anteil * 100) + " % erledigt. Nichts Dringendes offen.";
    }
    document.getElementById("fortschritt-satz").textContent = satz;
  }

  /* --------------------------------------------------------- Karte malen */

  /* Farbe je Postfach — aber nur, wenn es mehrere gibt.

     Farbe heißt auf diesem Dashboard sonst überall Dringlichkeit: rot brennt,
     gelb heute, blau zur Kenntnis. Eine zweite Farbsprache daneben wäre eine
     Falle. Deshalb bekommt das Postfach keinen farbigen Hintergrund und keine
     Pille, sondern einen schmalen Streifen an der linken Kante der Zeile und
     den Namen in derselben Farbe. Das liest sich als Zugehörigkeit, nicht als
     Warnung — dasselbe Mittel, mit dem Kalender ihre Kalender auseinanderhalten.

     Bei einem einzigen Postfach bleibt alles grau: Eine Farbe, die nichts
     unterscheidet, ist nur Dekoration. */
  var FACH_FARBEN = 6;

  function fachPlatz(daten) {
    var namen = (daten.extra && daten.extra.postfaecher) || [];
    var wunsch = (daten.extra && daten.extra.postfach_farben) || {};
    var karte = {};
    for (var i = 0; i < namen.length; i++) {
      // Ein ausdrücklicher Farbwunsch schlägt den Platz in der Liste.
      karte[namen[i]] = wunsch[namen[i]] || String((i % FACH_FARBEN) + 1);
    }
    return karte;
  }

  function zeileBauen(karteName, p, abhakbar, faecher) {
    var li = bauen("li", "zeile" + (p.erledigt ? " ist-erledigt" : ""));
    var fach = p.zusatz && p.zusatz.postfach;
    var platz = faecher && fach ? faecher[fach] : 0;
    if (platz) { li.className += " fach fach-" + platz; }
    li.setAttribute("data-suche", (
      alsText(p.titel) + " " + alsText(p.text) + " " + alsText(p.marke) + " " +
      alsText(p.betrag) + " " + alsText(p.notiz)
    ).toLowerCase());

    if (!abhakbar) {
      // Keine Attrappe hinstellen: Ein Kaestchen, das nichts tut, sieht aus
      // wie ein Fehler. Die Zeile rueckt stattdessen einfach nach links.
      li.className += " ohne-haken";
    }
    var haken = bauen("button", "haken" + (p.erledigt ? " an" : ""), "✓");
    haken.type = "button";
    haken.title = p.erledigt ? "wieder öffnen" : "erledigt";
    haken.addEventListener("click", function () {
      // Sofort umschalten, damit der Klick sich anfuehlt wie ein Klick — der
      // Rueckweg nach Todomaster braucht eine Sekunde. Geht er daneben,
      // springt der Haken zurueck und die Karte sagt warum.
      var vorher = haken.className;
      haken.className = p.erledigt ? "haken" : "haken an";
      holen("/api/erledigt", "POST",
            { schluessel: p.schluessel, erledigt: !p.erledigt, titel: p.titel })
        .then(function (daten) { karteZeichnen(karteName, daten); alleZahlen(); })
        .catch(function (fehler) {
          haken.className = vorher;
          fehlerZeigen(karteName, fehler.message);
        });
    });
    if (abhakbar) { li.appendChild(haken); }

    var mitte = bauen("div", "zeile-mitte");
    mitte.appendChild(bauen("div", "zeile-titel", p.titel));
    if (p.text) { mitte.appendChild(bauen("div", "zeile-text", p.text)); }
    if (p.notiz) { mitte.appendChild(bauen("div", "zeile-notiz", "📝 " + p.notiz)); }

    // Notiz aufklappen: ein Klick auf die Mitte, kein eigener Knopf — die Zeile
    // soll nicht zum Schalterbrett werden.
    mitte.addEventListener("click", function () {
      if (mitte.querySelector(".zeile-notiz-feld")) { return; }
      var feld = document.createElement("textarea");
      feld.className = "zeile-notiz-feld";
      feld.value = p.notiz || "";
      feld.placeholder = "Notiz (speichert beim Verlassen)";
      mitte.appendChild(feld);
      feld.focus();
      feld.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { feld.blur(); }
        if (e.key === "Escape") { feld.value = p.notiz || ""; feld.blur(); }
      });
      feld.addEventListener("blur", function () {
        if (feld.value === (p.notiz || "")) { mitte.removeChild(feld); return; }
        holen("/api/notiz", "POST", { schluessel: p.schluessel, text: feld.value })
          .then(function (daten) { karteZeichnen(karteName, daten); });
      });
    });
    li.appendChild(mitte);

    var rechts = bauen("div", "zeile-rechts");
    if (typeof p.betrag === "number") {
      rechts.appendChild(bauen("span", "zeile-betrag", geld.format(p.betrag)));
    }
    if (p.datum) { rechts.appendChild(bauen("span", "zeile-datum", relativ(p.datum))); }
    if (p.marke) { rechts.appendChild(bauen("span", "pille " + p.ampel, p.marke)); }
    if (p.link) {
      var a = bauen("a", "zeile-link", "öffnen ↗");
      a.href = p.link;
      a.target = "_blank";
      a.rel = "noopener";
      rechts.appendChild(a);
    }
    li.appendChild(rechts);
    return li;
  }

  function fehlerZeigen(name, text) {
    var el = karten[name].element.querySelector(".karte-fehler");
    el.textContent = text;
    el.hidden = false;
  }

  function karteZeichnen(name, daten) {
    var eintrag = karten[name];
    if (!eintrag) { return; }
    eintrag.daten = daten;
    var el = eintrag.element;

    var badge = el.querySelector(".badge");
    badge.textContent = String(daten.offen);
    badge.hidden = !daten.offen;
    var navZahl = document.getElementById("nav-" + name);
    if (navZahl) {
      navZahl.textContent = String(daten.offen);
      navZahl.hidden = !daten.offen;
      navZahl.className = "nav-zahl" + (daten.ampel === "rot" ? " warnung" : "");
    }
    el.querySelector(".punkt").className = "punkt " + (daten.ampel || "");

    var faecher = fachPlatz(daten);

    var kennzahlen = el.querySelector(".kennzahlen");
    leeren(kennzahlen);
    for (var schluessel in daten.kennzahlen) {
      if (!Object.prototype.hasOwnProperty.call(daten.kennzahlen, schluessel)) { continue; }
      var wert = daten.kennzahlen[schluessel];
      // Heißt die Kennzahl wie ein Postfach, trägt sie dessen Farbe — dann
      // führt der Blick von der Zahl oben zu den Zeilen darunter.
      var kasten = bauen("span", "kennzahl"
        + (faecher[schluessel] ? " fach fach-" + faecher[schluessel] : ""));
      kasten.appendChild(bauen("span", "kennzahl-name", schluessel));
      var anzeige = (schluessel.toLowerCase().indexOf("summe") === 0 ||
                     schluessel.toLowerCase().indexOf("summe") > 0)
        ? geld.format(wert || 0) : alsText(wert);
      kasten.appendChild(bauen("b", "", anzeige));
      kennzahlen.appendChild(kasten);
    }

    var liste = el.querySelector(".posten");
    leeren(liste);
    var offene = [], fertige = [];
    for (var i = 0; i < daten.posten.length; i++) {
      (daten.posten[i].erledigt ? fertige : offene).push(daten.posten[i]);
    }
    // Getrennt sortieren: Abgehaktes bleibt am Ende, sonst wanderte es je
    // nach Datum mitten in die offene Liste.
    var richtung = eintrag.sortierung || "";
    var zeigen = nachDatum(offene, richtung)
                 .concat(eintrag.erledigteZeigen ? nachDatum(fertige, richtung) : []);
    sortierKnopfZeichnen(el, richtung);
    if (!zeigen.length) {
      var leer = bauen("li", "leer");
      // Eine leere Karte MIT Hinweis heisst nicht „alles erledigt“, sondern
      // „es kam nichts an“ — etwa weil kein Postfach hinterlegt ist. „Hier ist
      // gerade nichts zu tun“ wäre an der Stelle eine falsche Entwarnung.
      if (daten.hinweis && !fertige.length) {
        leer.appendChild(bauen("strong", "", "Nichts zu zeigen."));
        leer.appendChild(document.createTextNode(
          "Der Hinweis unten sagt, woran es liegt."));
      } else {
        leer.appendChild(bauen("strong", "",
          daten.abhakbar === false ? "Nichts eingetragen."
            : (fertige.length ? "Alles abgehakt." : "Nichts offen.")));
        leer.appendChild(document.createTextNode(
          daten.abhakbar === false ? "Für diesen Zeitraum steht nichts an."
            : (fertige.length ? "Alle " + fertige.length + " Posten sind erledigt."
                              : "Hier ist gerade nichts zu tun.")));
      }
      liste.appendChild(leer);
    } else {
      for (var j = 0; j < zeigen.length; j++) {
        liste.appendChild(zeileBauen(name, zeigen[j], daten.abhakbar !== false,
                                     faecher));
      }
    }

    var erledigteKnopf = el.querySelector(".erledigte-zeigen");
    erledigteKnopf.hidden = !fertige.length || daten.abhakbar === false;
    erledigteKnopf.textContent = eintrag.erledigteZeigen
      ? "Erledigte ausblenden" : "Erledigte zeigen (" + fertige.length + ")";

    var hinweis = el.querySelector(".karte-hinweis");
    var text = alsText(daten.hinweis);
    // Rechnungen und Bestellungen schneiden schon auf dem Server auf die
    // neuesten zwanzig ab. „Aelteste zuerst" kann hier deshalb nur die
    // aeltesten DIESER zwanzig meinen — das muss dastehen, sonst behauptet
    // die Karte, die aelteste offene Rechnung zu zeigen.
    var gekuerzt = (daten.extra && daten.extra.gekuerzt) || 0;
    if (richtung === "alt" && gekuerzt) {
      text += (text ? " " : "")
        + "Sortiert wird nur das Angezeigte — die ältesten von " + gekuerzt
        + " stehen nicht darunter.";
    }
    hinweis.textContent = text;
    hinweis.hidden = !text;

    var fehler = el.querySelector(".karte-fehler");
    if (daten.fehler) {
      fehler.textContent = "Letzter Abruf misslungen: " + daten.fehler +
                           " — angezeigt ist der Stand von " + uhrzeit(daten.stand) + ".";
      fehler.hidden = false;
    } else {
      fehler.hidden = true;
    }

    el.querySelector(".karte-stand").textContent =
      daten.stand ? "Stand " + uhrzeit(daten.stand) : "wird geladen …";

    var link = el.querySelector(".karte-link");
    if (link) {
      if (daten.link) { link.href = daten.link; link.hidden = false; }
      else { link.hidden = true; }
    }

    suchen();
  }

  function auffrischen(name, knopf) {
    // Anstossen und dann warten, bis der Stand sich WIRKLICH geaendert hat.
    // Vorher stand hier ein festes setTimeout(2500) — die Shop-Karte braucht
    // aber neun Sekunden und Superchat im Erstlauf Minuten. Der Knopf sah
    // dadurch kaputt aus: Man klickte, und es stand weiter der alte Stand da.
    var eintrag = karten[name];
    var el = eintrag.element;
    var vorher = eintrag.daten && eintrag.daten.stand ? eintrag.daten.stand : "";
    var bis = Date.now() + 120000;

    el.classList.add("laedt");
    if (knopf) { knopf.disabled = true; }
    el.querySelector(".karte-stand").textContent = "wird aufgefrischt …";

    function fertig(text) {
      el.classList.remove("laedt");
      if (knopf) { knopf.disabled = false; }
      if (text) { el.querySelector(".karte-stand").textContent = text; }
      alleZahlen();
    }

    function nachsehen() {
      karteHolen(name).then(function () {
        var jetzt = eintrag.daten && eintrag.daten.stand ? eintrag.daten.stand : "";
        if (jetzt && jetzt !== vorher) { fertig(null); return; }
        if (Date.now() > bis) {
          fertig("dauert länger als sonst — Stand " + uhrzeit(jetzt));
          return;
        }
        el.querySelector(".karte-stand").textContent = "wird aufgefrischt …";
        window.setTimeout(nachsehen, 1500);
      }, function () {
        fertig(null);
      });
    }

    return holen("/api/karten/" + name + "/refresh", "POST").then(function () {
      window.setTimeout(nachsehen, 1000);
    }, function () {
      fertig("Auffrischen ging nicht");
    });
  }

  function karteHolen(name) {
    return holen("/api/karten/" + name)
      .then(function (daten) { karteZeichnen(name, daten); })
      .catch(function (fehler) {
        var el = karten[name].element.querySelector(".karte-fehler");
        el.textContent = "Die Karte lässt sich gerade nicht laden (" + fehler.message + ").";
        el.hidden = false;
      });
  }

  /* Laeuft diese Seite noch mit den Dateien, die der Server ausliefert?

     Eine Seite, die seit Stunden offen steht, merkt von einem Deploy nichts.
     Sie ruft weiter dieselben Endpunkte auf, aber mit dem JavaScript von
     vorher — Knoepfe, die es inzwischen anders gibt, tun dann scheinbar
     nichts, und niemand kann sich erklaeren, warum. Genau so ging am
     10.09.2026 ein Loeschklick verloren, der nie am Server ankam. */
  var EIGENE_FASSUNG = document.body.getAttribute("data-fassung") || "";
  var fassungGemeldet = false;

  function fassungPruefen(serverFassung) {
    if (!serverFassung || !EIGENE_FASSUNG) { return; }
    if (serverFassung === EIGENE_FASSUNG || fassungGemeldet) { return; }
    fassungGemeldet = true;
    var kasten = document.getElementById("fassung-hinweis");
    if (!kasten) { return; }
    kasten.hidden = false;
  }

  var fassungKnopf = document.getElementById("fassung-neuladen");
  if (fassungKnopf) {
    fassungKnopf.addEventListener("click", function () {
      // location.reload() allein holt in Safari gern die Seite aus dem Cache.
      // Der Zeitstempel erzwingt einen echten Gang zum Server.
      window.location.href = window.location.pathname + "?frisch=" +
        Date.now() + window.location.hash;
    });
  }

  /* Karten ohne hinterlegten Zugang gehören nicht ins Raster.

     Eine Karte, die „Nichts offen“ zeigt, weil niemand die Zugangsdaten
     eingetragen hat, behauptet Feierabend, wo in Wahrheit gar nicht
     nachgesehen wurde — die gefährlichste Falschaussage auf einem
     Dashboard. Sie steht deshalb unten in einer Zeile, bis jemand unter
     Settings den Zugang einträgt; danach erscheint sie von selbst, beim
     nächsten Abruf und ohne Neustart. */
  /* Ein Punkt am Settings-Eintrag, wenn eine neue Version bereitliegt.

     Bewusst nur ein Punkt und kein Kasten: Die Meldung richtet sich an den,
     der das Dashboard pflegt, nicht an den, der damit arbeitet. Aufgespielt
     wird ohnehin nichts von allein — wann die Seite eine Minute weg ist,
     entscheidet ein Mensch. */
  function updateHinweisZeichnen(u) {
    var punkt = document.getElementById("nav-update");
    if (!punkt) { return; }
    var da = !!(u && u.verfuegbar);
    punkt.hidden = !da;
    var knopf = punkt.parentNode;
    if (knopf) {
      knopf.title = da ? ((u.meldung || "Neue Version verfügbar")
                          + " — unter Settings → Update aufspielen")
                       : "Settings";
    }
  }

  function einrichtungZeichnen(karten) {
    var fehlt = [];
    for (var i = 0; i < karten.length; i++) {
      var k = karten[i];
      var el = document.querySelector('[data-karte="' + k.name + '"]');
      var nav = document.querySelector('.nav-punkt[data-ziel="' + k.name + '"]');
      var da = k.eingerichtet !== false;
      if (el) { el.style.display = da ? "" : "none"; }
      if (nav) { nav.style.display = da ? "" : "none"; }
      if (!da) { fehlt.push(k.titel); }
    }
    // Werkzeug-Karten stehen nicht in /api/karten; ihr Stand kommt beim
    // Seitenaufbau aus der Vorlage.
    var werkzeuge = document.querySelectorAll("[data-werkzeug]");
    for (var w = 0; w < werkzeuge.length; w++) {
      if (werkzeuge[w].getAttribute("data-eingerichtet") === "nein") {
        werkzeuge[w].style.display = "none";
        var wnav = document.querySelector(
          '.nav-punkt[data-ziel="' + werkzeuge[w].getAttribute("data-karte") + '"]');
        if (wnav) { wnav.style.display = "none"; }
        var h2 = werkzeuge[w].querySelector("h2");
        if (h2) { fehlt.push(h2.textContent); }
      }
    }
    var zeile = document.getElementById("karten-fehlend");
    if (!zeile) { return; }
    var assi = document.getElementById("assistent");
    zeile.hidden = fehlt.length === 0 || Boolean(assi && !assi.hidden);
    leeren(zeile);
    if (!fehlt.length) { return; }
    zeile.appendChild(document.createTextNode(
      "Noch nicht eingerichtet: " + fehlt.join(", ") + ". "));
    var link = bauen("a", "", "Zugangsdaten eintragen");
    link.href = "#einstellungen";
    zeile.appendChild(link);
  }

  function alleZahlen() {
    return holen("/api/karten").then(function (daten) {
      fassungPruefen(daten.fassung);
      updateHinweisZeichnen(daten.update);
      einrichtungZeichnen(daten.karten);
      kopfzahlenZeichnen(daten.kopf);
      var dringend = 0;
      for (var i = 0; i < daten.karten.length; i++) {
        if (daten.karten[i].ampel === "rot") { dringend += 1; }
      }
      fortschrittZeichnen(daten.fortschritt, dringend);
      grussSetzen(daten.person);
      zeitZeigen(daten.zeit);
      var neuester = "";
      for (var j = 0; j < daten.karten.length; j++) {
        if (daten.karten[j].stand > neuester) { neuester = daten.karten[j].stand; }
      }
      var kurz = document.getElementById("stand-kurz");
      if (daten.takt && !daten.takt.holt) {
        // Nicht heimlich veralten lassen: Wenn nichts geholt wird, muss man
        // das sehen — sonst haelt man alte Zahlen fuer aktuelle.
        kurz.textContent = "pausiert · Stand " + uhrzeit(neuester);
        kurz.title = daten.takt.grund;
      } else {
        kurz.textContent = neuester ? "zuletzt " + uhrzeit(neuester) : "wird geladen …";
        kurz.title = "";
      }
    }).catch(function () { /* naechster Takt versucht es erneut */ });
  }

  /* --------------------------------------------------------------- Suche */

  function suchen() {
    var name, i;
    for (name in karten) {
      if (!Object.prototype.hasOwnProperty.call(karten, name)) { continue; }
      var el = karten[name].element;
      var zeilen = el.querySelectorAll(".posten li.zeile");
      var sichtbar = 0;
      for (i = 0; i < zeilen.length; i++) {
        var passt = !suchtext ||
          zeilen[i].getAttribute("data-suche").indexOf(suchtext) !== -1;
        zeilen[i].hidden = !passt;
        if (passt) { sichtbar += 1; }
      }
      // Beim Suchen verschwinden leere Karten, damit der Blick nicht wandert.
      // In der Einzelansicht bleibt die gewaehlte Karte aber stehen, auch
      // wenn gerade nichts passt — sonst starrt man auf eine leere Seite und
      // weiss nicht, ob die Suche oder die Karte schuld ist.
      var alleine = document.body.classList.contains("einzel");
      el.hidden = Boolean(suchtext) && sichtbar === 0 && !alleine;
    }
  }

  var sucheFeld = document.getElementById("suche");
  sucheFeld.addEventListener("input", function () {
    suchtext = sucheFeld.value.trim().toLowerCase();
    suchen();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && document.activeElement === sucheFeld) {
      sucheFeld.value = ""; suchtext = ""; suchen(); sucheFeld.blur();
      return;
    }
    var tippt = e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey;
    var imFeld = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
    if (tippt && !imFeld) { sucheFeld.focus(); }
  });

  /* ------------------------------------------------- Reihenfolge, Klappen */

  function ordnungLesen() {
    try {
      var roh = JSON.parse(speicherLesen(SCHLUESSEL_ORDNUNG, "[]"));
      return Array.isArray(roh) ? roh : [];
    } catch (e) { return []; }
  }

  function ordnungSchreiben() {
    var raster = document.getElementById("raster");
    var namen = [];
    var kinder = raster.children;
    for (var i = 0; i < kinder.length; i++) {
      var n = kinder[i].getAttribute("data-karte");
      if (n) { namen.push(n); }
    }
    speicherSchreiben(SCHLUESSEL_ORDNUNG, JSON.stringify(namen));
  }

  function ordnungAnwenden() {
    var raster = document.getElementById("raster");
    var namen = ordnungLesen();
    for (var i = 0; i < namen.length; i++) {
      var el = document.getElementById("karte-" + namen[i]);
      if (el) { raster.appendChild(el); }
    }
  }

  function zugeklappteLesen() {
    try {
      var roh = JSON.parse(speicherLesen(SCHLUESSEL_ZU, "[]"));
      return Array.isArray(roh) ? roh : [];
    } catch (e) { return []; }
  }

  function zugeklappteSchreiben() {
    var zu = [];
    for (var name in karten) {
      if (!Object.prototype.hasOwnProperty.call(karten, name)) { continue; }
      if (karten[name].element.classList.contains("zu")) { zu.push(name); }
    }
    speicherSchreiben(SCHLUESSEL_ZU, JSON.stringify(zu));
  }

  /* ------------------------------------------------------ Sortierung */

  /* Die Karten ordnen serverseitig nach Dringlichkeit: das Wichtigste oben,
     darin das Aelteste zuerst. Das ist die richtige Vorgabe fuer die taegliche
     Arbeit, beantwortet aber nicht „was kam zuletzt herein?". Deshalb hier ein
     Umschalter je Karte — die Vorgabe bleibt die Vorgabe, die Abweichung ist
     sichtbar und wird pro Geraet gemerkt. */

  var SORT_FOLGE = ["", "neu", "alt"];
  var SORT_TEXT = {
    "": "dringendste zuerst",
    "neu": "neueste zuerst",
    "alt": "älteste zuerst"
  };
  var SORT_ZEICHEN = { "": "↕", "neu": "⇣", "alt": "⇡" };

  function sortierungLesen() {
    try {
      var roh = JSON.parse(speicherLesen(SCHLUESSEL_SORTIERUNG, "{}"));
      // Ein Array oder null waere auch "object" — beides hier wertlos.
      return (roh && typeof roh === "object" && !Array.isArray(roh)) ? roh : {};
    } catch (e) { return {}; }
  }

  function sortierungSchreiben(name, wert) {
    var alle = sortierungLesen();
    if (wert) { alle[name] = wert; } else { delete alle[name]; }
    speicherSchreiben(SCHLUESSEL_SORTIERUNG, JSON.stringify(alle));
  }

  /* Wonach verglichen wird. Die Mail- und die Kalenderkarte legen die volle
     Uhrzeit in zusatz.sortier ab — ohne sie waere die Reihenfolge mehrerer
     Eintraege desselben Tages zufaellig. */
  function sortierwert(p, leer) {
    var z = p.zusatz && p.zusatz.sortier ? p.zusatz.sortier : p.datum;
    return z ? String(z) : leer;
  }

  function nachDatum(liste, richtung) {
    if (!richtung) { return liste; }
    // Datumslose Posten gehoeren in BEIDEN Richtungen ans Ende — deshalb je
    // Richtung ein anderer Ersatzwert.
    var leer = richtung === "alt" ? "9999-99-99" : "";
    var kopie = liste.slice();
    kopie.sort(function (a, b) {
      var x = sortierwert(a, leer), y = sortierwert(b, leer);
      if (x === y) { return 0; }
      if (richtung === "alt") { return x < y ? -1 : 1; }
      return x > y ? -1 : 1;
    });
    return kopie;
  }

  function sortierKnopfZeichnen(el, richtung) {
    var knopf = el.querySelector(".sortieren");
    if (!knopf) { return; }
    var naechste = SORT_FOLGE[(SORT_FOLGE.indexOf(richtung) + 1) % SORT_FOLGE.length];
    knopf.textContent = SORT_ZEICHEN[richtung];
    // Stand UND naechster Schritt im Klartext: Ein Pfeil allein sagt nicht,
    // was er gerade bedeutet.
    var text = "Sortierung: " + SORT_TEXT[richtung]
             + " — klicken für " + SORT_TEXT[naechste];
    knopf.title = text;
    knopf.setAttribute("aria-label", text);
    knopf.classList.toggle("aktiv", Boolean(richtung));
  }

  /* ---------------------------------------------------------- Karten-Setup */

  var gezogen = null;

  function karteEinrichten(el) {
    var name = el.getAttribute("data-karte");
    // Eine Werkzeug-Karte holt nichts: kein Takt, kein Auffrischen, kein
    // Erledigt-Knopf. Sie liegt trotzdem in `karten`, damit Verschieben,
    // Zuklappen und die Seitenleiste für sie genauso funktionieren.
    var istWerkzeug = el.hasAttribute("data-werkzeug");
    // Anders als `erledigteZeigen` ueberlebt die Sortierung das Neuladen —
    // sie ist eine Entscheidung ueber die Karte, keine Momentaufnahme.
    karten[name] = { element: el, daten: null, erledigteZeigen: false,
                     sortierung: sortierungLesen()[name] || "",
                     zeitgeber: null, werkzeug: istWerkzeug };
    sortierKnopfZeichnen(el, karten[name].sortierung);

    var sortKnopf = el.querySelector(".sortieren");
    if (sortKnopf) {
      sortKnopf.addEventListener("click", function () {
        var jetzt = karten[name].sortierung || "";
        var neu = SORT_FOLGE[(SORT_FOLGE.indexOf(jetzt) + 1) % SORT_FOLGE.length];
        karten[name].sortierung = neu;
        sortierungSchreiben(name, neu);
        sortierKnopfZeichnen(el, neu);
        // Nur neu zeichnen, nicht neu holen: Die Daten liegen schon hier.
        if (karten[name].daten) { karteZeichnen(name, karten[name].daten); }
      });
    }

    el.querySelector(".klappen").addEventListener("click", function () {
      el.classList.toggle("zu");
      zugeklappteSchreiben();
    });
    if (!istWerkzeug) {
      var frischKnopf = el.querySelector(".auffrischen");
      frischKnopf.addEventListener("click", function () {
        auffrischen(name, frischKnopf);
      });
      // Auch der Stand selbst ist anklickbar — dort schaut man hin, wenn man
      // wissen will, ob die Zahlen noch stimmen.
      el.querySelector(".karte-stand").addEventListener("click", function () {
        auffrischen(name, frischKnopf);
      });
      el.querySelector(".erledigte-zeigen").addEventListener("click", function () {
        karten[name].erledigteZeigen = !karten[name].erledigteZeigen;
        karteZeichnen(name, karten[name].daten);
      });
    }
    el.querySelector(".hoch").addEventListener("click", function () {
      var vorher = el.previousElementSibling;
      if (vorher) { el.parentNode.insertBefore(el, vorher); ordnungSchreiben(); }
    });
    el.querySelector(".runter").addEventListener("click", function () {
      var danach = el.nextElementSibling;
      if (danach) { el.parentNode.insertBefore(danach, el); ordnungSchreiben(); }
    });

    // Ziehen: auf dem Telefon uebernehmen die Pfeile — HTML5-Drag&Drop
    // funktioniert dort nicht zuverlaessig.
    el.addEventListener("dragstart", function (e) {
      gezogen = el;
      el.classList.add("zieht");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", name);
    });
    el.addEventListener("dragend", function () {
      el.classList.remove("zieht");
      gezogen = null;
      ordnungSchreiben();
    });
    el.addEventListener("dragover", function (e) {
      if (!gezogen || gezogen === el) { return; }
      e.preventDefault();
      el.classList.add("ziel");
    });
    el.addEventListener("dragleave", function () { el.classList.remove("ziel"); });
    el.addEventListener("drop", function (e) {
      e.preventDefault();
      el.classList.remove("ziel");
      if (!gezogen || gezogen === el) { return; }
      var kinder = Array.prototype.slice.call(el.parentNode.children);
      var vorZiel = kinder.indexOf(gezogen) < kinder.indexOf(el);
      el.parentNode.insertBefore(gezogen, vorZiel ? el.nextSibling : el);
      ordnungSchreiben();
    });
  }

  /* ------------------------------------------------------------- Anlaufen */

  var kartenElemente = document.querySelectorAll(".karte[data-karte]");
  for (var i = 0; i < kartenElemente.length; i++) {
    karteEinrichten(kartenElemente[i]);
  }
  ordnungAnwenden();

  var zu = zugeklappteLesen();
  for (var z = 0; z < zu.length; z++) {
    if (karten[zu[z]]) { karten[zu[z]].element.classList.add("zu"); }
  }

  var navKnoepfe = document.querySelectorAll(".nav-punkt");
  for (var n = 0; n < navKnoepfe.length; n++) {
    (function (knopf) {
      knopf.addEventListener("click", function () {
        var ziel = knopf.getAttribute("data-ziel");
        window.location.hash = ziel === "oben" ? "" : ziel;
        if (ziel === "oben") { ausAdresse(); }   // leerer Hash loest nichts aus
      });
    })(navKnoepfe[n]);
  }

  document.getElementById("alles-aktualisieren").addEventListener("click", function () {
    document.getElementById("stand-kurz").textContent = "wird aufgefrischt …";
    for (var name in karten) {
      if (!Object.prototype.hasOwnProperty.call(karten, name)) { continue; }
      if (karten[name].werkzeug) { continue; }
      auffrischen(name, karten[name].element.querySelector(".auffrischen"));
    }
  });

  // Jede Karte hat ihren eigenen Takt: eine Kette aus setTimeout, damit sich
  // langsame Antworten nicht stapeln (das taete setInterval).
  function taktStarten(name) {
    var ttl = 120;
    function runde() {
      // Im Hintergrund nicht abfragen — aber nur, wenn schon einmal etwas da
      // war. Sonst bliebe eine Karte, die im verdeckten Tab geoeffnet wurde,
      // fuer immer im Ladezustand: das sah aus wie ein kaputtes Dashboard.
      if (document.hidden && karten[name].daten) {
        karten[name].zeitgeber = window.setTimeout(runde, 30000);
        return;
      }
      karteHolen(name).then(function () {
        var daten = karten[name].daten;
        // Der Server holt nur alle 30 Minuten; oefter als alle zwei Minuten
        // nachzusehen bringt nichts. Es ist zwar nur ein Griff in die eigene
        // Datenbank, aber acht Karten im Minutentakt sind trotzdem Rauschen.
        var wartezeit = Math.max(120, Math.round((daten && daten.ttl ? daten.ttl : ttl) / 2));
        karten[name].zeitgeber = window.setTimeout(runde, wartezeit * 1000);
      });
    }
    runde();
  }

  for (var name in karten) {
    if (!Object.prototype.hasOwnProperty.call(karten, name)) { continue; }
    if (karten[name].werkzeug) { continue; }
    taktStarten(name);
  }
  document.getElementById("zurueck").addEventListener("click", function () {
    window.location.hash = "";
    ausAdresse();
  });
  window.addEventListener("hashchange", ausAdresse);

  alleZahlen().then(ausAdresse, ausAdresse).then(einrichtungLaden, einrichtungLaden);
  window.setInterval(alleZahlen, 60000);

  // Ganz am Anfang steht statt des Rasters der Assistent. Die Takte oben
  // laufen trotzdem weiter — sobald ein Zugang steht, ist die Karte gefuellt,
  // wenn der Assistent zur Seite geht.

  var assiKnopf = document.getElementById("assistent-oeffnen");
  if (assiKnopf) {
    assiKnopf.addEventListener("click", function () {
      assiKnopf.disabled = true;
      holen("/api/einrichtung/erneut", "POST").then(function () {
        return holen("/api/einrichtung");
      }).then(function (d) {
        // Zurueck aus den Einstellungen, sonst stuenden beide untereinander.
        // Die Adresse wird dabei ohne hashchange geleert: Das Ereignis kaeme
        // erst NACH dem Aufbau und wuerde den Assistenten sofort schliessen.
        ansichtSetzen("");
        if (window.history && window.history.replaceState) {
          window.history.replaceState(null, "", window.location.pathname);
        }
        window.scrollTo(0, 0);
        assistentZeigen(d);
      }).catch(function () { /* nichts zu tun */ })
        .then(function () { assiKnopf.disabled = false; });
    });
  }

  // Nachrichten haeufiger nachsehen als die Karten: Sie kommen aus der eigenen
  // Datenbank, kosten also nichts, und ein Zuruf soll nicht bis zum naechsten
  // 30-Minuten-Takt liegen bleiben.
  nachrichtenLaden();
  window.setInterval(function () {
    if (!document.hidden) { nachrichtenLaden(); }
  }, 45000);

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) { return; }
    // Zurueck auf der Seite: alles nachziehen, statt bis zu 30 Sekunden auf
    // den naechsten Takt zu warten.
    alleZahlen();
    nachrichtenLaden();
    for (var offen in karten) {
      if (!Object.prototype.hasOwnProperty.call(karten, offen)) { continue; }
      if (karten[offen].werkzeug) { continue; }
      karteHolen(offen);
    }
  });

  /* ------------------------------------------------------- FAQ-Nachschlag */

  /* Die einzige Karte, die fragt statt zu holen. Wichtig ist hier nicht die
     Antwort allein, sondern wie sicher sie ist: Ein Entwurf aus der
     Wissensbasis ist ein Vorschlag, keine Auskunft. Wer ihn ungeprueft an
     einen Kunden weitergibt, gibt eine Vermutung als Zusage aus — deshalb
     steht der Stand neben der Antwort und nicht im Kleingedruckten. */

  var FAQ_VERLAUF = "smg-" + INSTANZ + "-faq-verlauf";
  var FAQ_PILLE = {
    geprueft: ["gruen", "geprüft"],
    entwurf: ["gelb", "Entwurf — nicht freigegeben"],
    unsicher: ["rot", "unsicher — nicht als Auskunft verwenden"]
  };

  function faqVerlaufLesen() {
    try {
      var roh = JSON.parse(speicherLesen(FAQ_VERLAUF, "[]"));
      return Array.isArray(roh) ? roh : [];
    } catch (e) { return []; }
  }

  function faqVerlaufZeichnen() {
    var liste = document.getElementById("faq-verlauf");
    if (!liste) { return; }
    leeren(liste);
    var eintraege = faqVerlaufLesen();
    for (var i = 0; i < eintraege.length; i++) {
      (function (e) {
        var li = bauen("li", "zeile ohne-haken");
        li.setAttribute("data-suche", (e.frage + " " + e.antwort).toLowerCase());
        var mitte = bauen("div", "zeile-mitte");
        mitte.appendChild(bauen("div", "zeile-titel", e.frage));
        mitte.appendChild(bauen("div", "zeile-text", e.antwort));
        li.appendChild(mitte);
        var rechts = bauen("div", "zeile-rechts");
        var art = FAQ_PILLE[e.status] || ["blau", e.status || "—"];
        rechts.appendChild(bauen("span", "pille " + art[0], art[1]));
        li.appendChild(rechts);
        li.addEventListener("click", function () {
          document.getElementById("faq-frage").value = e.frage;
        });
        liste.appendChild(li);
      })(eintraege[i]);
    }
  }

  function faqVerlaufMerken(frage, antwort, status) {
    var eintraege = faqVerlaufLesen();
    // Im Verlauf steht nur eine Vorschau — dort ohne Markdown-Sternchen,
    // weil die Zeile keine Fettschrift kennt.
    eintraege.unshift({ frage: frage,
                        antwort: String(antwort || "").split("**").join("").slice(0, 120),
                        status: status });
    speicherSchreiben(FAQ_VERLAUF, JSON.stringify(eintraege.slice(0, 5)));
    faqVerlaufZeichnen();
  }

  function faqText(klasse, roh) {
    // Das FAQ-Tool antwortet in Markdown. Die Sternchen stehen sonst als
    // Zeichen in der Karte. Gebaut wird das als Textknoten, nicht als HTML:
    // Der Text kommt aus einem fremden System, und `innerHTML` wäre hier ein
    // offenes Scheunentor.
    var p = bauen("p", klasse);
    var teile = String(roh || "").split("**");
    for (var i = 0; i < teile.length; i++) {
      if (!teile[i]) { continue; }
      if (i % 2 === 1) {
        p.appendChild(bauen("strong", "", teile[i]));
      } else {
        p.appendChild(document.createTextNode(teile[i]));
      }
    }
    return p;
  }

  function faqZeichnen(d) {
    var kasten = document.getElementById("faq-antwort");
    leeren(kasten);
    kasten.hidden = false;
    if (!d.gefunden) {
      kasten.appendChild(bauen("p", "faq-warnung",
        "Nichts in der Wissensbasis. Nicht raten — lieber "
        + (ANSPRECHPARTNER ? "an " + ANSPRECHPARTNER : "im Team")
        + " nachfragen und die Frage danach im FAQ-Tool ergänzen."));
      return;
    }
    var kopf = bauen("div", "faq-kopf");
    var art = FAQ_PILLE[d.status] || ["blau", d.status || "ohne Angabe"];
    kopf.appendChild(bauen("span", "pille " + art[0], art[1]));
    kasten.appendChild(kopf);
    // Die Fundstelle steht groß und zuerst, nicht klein am Rand: Das
    // FAQ-Tool sucht nach Ähnlichkeit und antwortet auch auf eine Frage,
    // die es gar nicht kennt, mit dem nächstbesten Eintrag. Passt der Titel
    // nicht zur Frage, weiß die Wissensbasis es nicht — und nur der Titel
    // verrät das.
    if (d.titel) {
      kasten.appendChild(bauen("p", "faq-quelle", "Antwort aus: " + d.titel
        + (d.kategorie ? " · " + d.kategorie : "")));
    }
    kasten.appendChild(faqText("faq-kurz", d.antwort));
    if (d.ausfuehrlich && d.ausfuehrlich !== d.antwort) {
      kasten.appendChild(faqText("faq-lang", d.ausfuehrlich));
    }
    if (d.nicht_sagen) {
      kasten.appendChild(faqText("faq-warnung", "Nicht sagen: " + d.nicht_sagen));
    }
    if (d.warnung) {
      kasten.appendChild(bauen("p", "faq-warnung", d.warnung));
    }
    if (d.weitere && d.weitere.length) {
      var mehr = bauen("p", "faq-mehr", "Auch dazu: ");
      for (var i = 0; i < d.weitere.length; i++) {
        (function (w) {
          var knopf = bauen("button", "still faq-weiter", w.titel);
          knopf.type = "button";
          knopf.addEventListener("click", function () {
            document.getElementById("faq-frage").value = w.titel;
            faqFragen();
          });
          mehr.appendChild(knopf);
        })(d.weitere[i]);
      }
      kasten.appendChild(mehr);
    }
  }

  function faqFragen() {
    var feld = document.getElementById("faq-frage");
    var knopf = document.getElementById("faq-fragen");
    var stand = document.getElementById("faq-stand");
    var fehler = document.querySelector('[data-werkzeug="faq"] .karte-fehler');
    var frage = (feld.value || "").trim();
    if (!frage) { feld.focus(); return; }
    knopf.disabled = true;
    fehler.hidden = true;
    stand.className = "e-ergebnis";
    stand.textContent = "wird nachgeschlagen …";
    holen("/api/faq", "POST", { frage: frage }).then(function (d) {
      stand.textContent = "";
      faqZeichnen(d);
      faqVerlaufMerken(frage, d.gefunden ? d.antwort : "nichts gefunden",
                       d.gefunden ? d.status : "");
    }).catch(function (f) {
      stand.textContent = "";
      document.getElementById("faq-antwort").hidden = true;
      fehler.textContent = f.message;
      fehler.hidden = false;
    }).then(function () { knopf.disabled = false; });
  }

  var faqKnopf = document.getElementById("faq-fragen");
  if (faqKnopf) {
    faqKnopf.addEventListener("click", faqFragen);
    document.getElementById("faq-frage").addEventListener("keydown", function (e) {
      // Strg+Enter schickt ab; Enter allein macht eine neue Zeile, weil
      // Kundenfragen gern mehrzeilig hereinkommen.
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { faqFragen(); }
    });
    faqVerlaufZeichnen();
  }
})();
