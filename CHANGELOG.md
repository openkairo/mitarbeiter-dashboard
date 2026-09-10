# Änderungen

Kurzfassung dessen, was sich je Version geändert hat. Die Nummer wächst nach
dem Muster **Haupt.Neben.Korrektur**: die letzte Stelle für Fehlerbehebungen,
die mittlere für neue Funktionen, die erste für Umbauten, bei denen jemand
etwas nachtragen muss (etwa eine neue Pflichtangabe in der `.env`).

## Unveröffentlicht

Hier sammelt sich, was seit der letzten Nummer dazugekommen ist. Beim
Veröffentlichen wird daraus eine Nummer nach Haupt.Neben.Korrektur — die
Nummer wächst also nur, wenn ein Stand bewusst freigegeben wird, nicht bei
jedem einzelnen Arbeitsschritt.

- Das Repo ist **öffentlich**. Der Server liest die Updates seither über
  HTTPS statt über einen Bereitstellungsschlüssel — nichts zu verwalten,
  nichts zu widerrufen. `update-einrichten.sh` erkennt das selbst und legt
  nur bei einem privaten Repo noch einen Schlüssel an.
- **`install.sh` richtet eine Instanz auf einem frischen Server ein** und
  prüft vorher die Voraussetzungen: Docker, Traefik samt externem Netz und
  Zertifikatsauflöser, und ob der A-Eintrag wirklich auf diesen Server zeigt.
  Fehlt etwas, bricht es ab, **bevor** es etwas anlegt. `--pruefen` sieht nur
  nach und ändert nichts.
- **`INSTALL.md`**: Voraussetzungen und Reihenfolge — DNS zuerst, dann Netz,
  dann installieren. Geschrieben, damit auch eine KI sie ausführen kann.
- **Die vier Zulieferungen von außen sind optional geworden** (Bank-Abgleich,
  Widerruf-Wache, Watchdog, Google-Schlüssel). Ohne Angabe wird ein leerer
  Ordner eingehängt; die betroffenen Karten melden sich als „nicht
  eingerichtet". Der Google-Schlüssel hängt jetzt als Ordner statt als Datei —
  sonst legte Docker auf einer frischen Maschine ein Verzeichnis namens
  `google-key.json` an, gegen das der Kalender lief.
- Zwei kleine Prüfwerkzeuge unter `deploy/`: `pruef-abzug.py` zieht Karten,
  Einstellungen, Haken und Notizen einer Instanz als Datei, `pruef-vergleich.py`
  stellt zwei solche Abzüge gegenüber. Damit lässt sich vor und nach einem
  Update belegen, dass nichts verloren geht.

## 1.1.3 — 10.09.2026

- In der Oberfläche heißt es überall „Version“ statt „Fassung“.

## 1.1.2 — 10.09.2026

- Beim Nachsehen wurde die Arbeitskopie auf dem Server nicht mitgezogen, also
  lief dort weiter ein altes Update-Skript. Sie wird jetzt in beiden
  Betriebsarten aktualisiert.

## 1.1.1 — 10.09.2026

- Die Punkte der Änderungsliste brachen mitten im Satz um; umbrochene Zeilen
  werden jetzt zusammengezogen.

## 1.1.0 — 10.09.2026

- **Versionsnummern statt Commit-Kennungen.** Der Update-Kasten zeigt, welche
  Version läuft und welche bereitliegt — und was die neue bringt, bevor man
  sie aufspielt.
- **Diese Liste ist auch im Dashboard einsehbar**, eingeklappt unter
  *Settings → Wartung*.
- **Der Update-Knopf steht nicht mehr zwischen den Zugängen**, sondern unter
  einer eigenen Überschrift „Wartung". Ein Update ist keine Zugangsdatei,
  sondern eine Handlung am Server.

## 1.0.0 — 10.09.2026

Erste nummerierte Version. Vorher gab es nur Commit-Kennungen wie `0f1c7f3f`,
die niemandem sagen, ob etwas Großes oder eine Kleinigkeit dazukam.

- **Karten entstehen durch Zugangsdaten.** Wer einen Zugang einträgt, bekommt
  die Karte beim nächsten Abruf; ohne Zugang steht sie nicht im Raster.
- **Tagesfortschritt erkennt Erledigtes selbst** — am Verschwinden eines
  Postens aus seiner Quelle, ohne dass jemand einen Haken setzt.
- **Posteingang: beliebig viele Postfächer**, je Postfach Anbieter-API oder
  IMAP, anlegen und löschen in der Oberfläche.
- **Superchat: Postfächer per Auswahl** statt abgetippter Kennung, dazu eine
  Farbe je Postfach und wählbare Zuordnung über `SUPERCHAT_FARBEN`.
- **Zurufe der KI lassen sich ersetzen und schließen** (`nachricht_ersetzen`,
  `nachricht_erledigen`) — kein Stapeln mehr bei mehrfachem Nachhaken.
- **Update aus dem Code-Verzeichnis** mit Rücknahme bei Fehlschlag, je Instanz
  einzeln, und ein täglicher Blick, ob etwas Neues bereitliegt.
- **Personenneutral:** keine Namen, Adressen, Kennungen oder Arbeitszeiten
  mehr im Quelltext — alles kommt aus der `.env` oder den Einstellungen.
