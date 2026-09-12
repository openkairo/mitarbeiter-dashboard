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

*Zurzeit nichts.*

## 1.4.0 — 12.09.2026

Diese Fassung repariert das Aktualisieren selbst. Bisher dauerte es im
Normalfall einen Tag, bis eine neue Version überhaupt auffiel, das Aufspielen
brauchte über eine Minute — und am Ende stand im Kasten weiter „Baue den
Container neu …", obwohl längst alles fertig war.

**Bestehende Instanzen müssen nichts nachtragen.** `UPDATE_REPO` hat eine
Vorgabe; wer seinen Stand aus einem eigenen Fork holt, trägt ihn dort ein.

> **Eine Eigenheit beim Aufspielen dieser Version:** Die Wache nimmt
> `update.sh` aus ihrer Arbeitskopie des Repos. Der Update-Lauf, der 1.4.0
> installiert, benutzt deshalb noch das alte Skript und zieht die Arbeitskopie
> dabei erst nach. Die Beschleunigungen greifen vollständig **ab dem nächsten**
> Update.

- **Der Update-Kasten blieb stehen, obwohl das Update längst durch war.**
  Während des Neubaus ist das Dashboard ein paar Sekunden nicht erreichbar —
  die Nachfrage schlug fehl, und der Fehlerzweig setzte **keinen neuen
  Termin**. Danach fragte die Seite nie wieder: Stehen blieb „Baue den
  Container neu …", bis jemand von Hand neu lud. Jetzt bleibt die Seite dran,
  nennt den Ausfall beim Namen („Container startet neu …") und **lädt sich
  nach „fertig" einmal selbst neu** — sonst hinge sie weiter am alten
  JavaScript und zeigte die alte Nummer. Nach einem **Fehlschlag** lädt sie
  bewusst nicht neu: Die rote Meldung ist die einzige Spur.
- **Das Aufspielen dauert nur noch einen Bruchteil.** Gemessen auf dem Server:
  - Der Bau eines Updates, bei dem sich nur das Programm geändert hat, dauert
    **0,98 s statt 27 s**. Die Abhängigkeiten wurden bei jedem Bau neu aus dem
    Netz installiert (18,9 s) und als 56-MB-Schicht neu exportiert (8 s),
    obwohl sich an `requirements.txt` seit Wochen nichts geändert hatte. Der
    heruntergeladene Vorrat bleibt jetzt liegen. Ändert sich doch einmal etwas
    an den Abhängigkeiten, installiert pip **aus dem Vorrat statt aus dem
    Netz** — nachgemessen: 78 Pakete aus dem Vorrat, kein einziger Download.
  - Die Wache sieht **viermal pro Minute** nach statt einmal. Aus „bis zu 60
    Sekunden, bis überhaupt etwas passiert" wurden gemessene **7 bis 8**.
  - Neu: `.dockerignore`. Der Baukontext war bisher der ganze Instanzordner —
    samt Datenbank, bis zu fünf vollständigen Sicherungen und der `.env` mit
    allen Zugängen. Die hat im Baukontext nichts verloren.
  - Die Sicherungen verlinken jetzt, was sich nicht geändert hat
    (`rsync --link-dest`), statt es fünfmal zu kopieren.
  - Das Warten auf die wieder erreichbare Seite fragt sekündlich statt alle
    drei Sekunden.
- **Das Update-Log schreibt Uhrzeiten.** Ohne sie liess sich nicht mehr
  feststellen, welcher Schritt die Zeit gekostet hat — die Dauer musste aus
  Ordnernamen und dem Docker-Journal zusammengesucht werden.

- **Eine neue Version fällt jetzt sofort auf.** Bisher wusste nur der Server
  davon: Eine Wache auf dem Host holte den Stand per `git fetch` — angestoßen
  von Hand oder einmal täglich. Zwischen einer Veröffentlichung und dem Hinweis
  im Dashboard lag damit im Normalfall ein ganzer Tag. Jetzt liest das
  Dashboard die Datei `VERSION` selbst aus dem Repo und vergleicht die Nummer;
  gemessen 0,03 Sekunden. Das **Aufspielen** bleibt unverändert bei der Wache —
  dafür braucht es Rechte, die im Container nichts zu suchen haben.
  - „Nachsehen" prüft sofort, statt eine Anforderung abzulegen, auf die eine
    Wache erst in der nächsten Minute stößt.
  - Verglichen werden **Zahlen, keine Zeichenketten**: Als Text wäre `1.3.9`
    größer als `1.3.10`, und das Update wäre ab der zehnten Korrektur
    unsichtbar geworden.
  - Der frische Vergleich schlägt die Zustandsdatei. Nach einem Aufspielen
    stand dort noch „liegt bereit", obwohl die Nummern längst gleich waren.
  - Ist GitHub nicht erreichbar, bleibt es beim zuletzt bekannten Stand —
    ohne Fehlermeldung auf einer Seite, an der niemand etwas reparieren kann.
  - Der Update-Kasten war beim zweiten Öffnen der Einstellungen ein Standbild.
  - `deploy/update-einrichten.sh` richtet den täglichen Prüflauf jetzt mit ein.
    Er stand bisher nur von Hand im Crontab — und wäre beim nächsten Einrichten
    stillschweigend gelöscht worden.

## 1.3.1 — 12.09.2026

- **Bank-Abgleich: Der Haken zählt jetzt überall.** Kopfkachel und
  Kennzahl „Posten" kamen aus dem Tagesbericht und zählten abgehakte
  Buchungen weiter mit — oben stand „3", in der Badge „2". Die Karte liefert
  die Zahl nicht mehr selbst; gezählt wird, was offen ist. Hintergrund:
  Buchungen ohne Beleg (Cashback, Zinsen) kann die Automation nicht auflösen,
  weil Lexware Bankumsätze nicht über die Schnittstelle hergibt — sie werden
  im Dashboard abgehakt, und der Haken hält über jeden neuen Bericht.

## 1.3.0 — 11.09.2026

Der Schwerpunkt liegt auf der **Einrichtung**: Ein Assistent führt durch den
ersten Aufruf, der Google-Kalender kommt ohne Schlüsseldatei auf dem Server
aus, und ein Fehler in `install.sh` ist behoben, der jede frische Installation
unbenutzbar machte — ohne dass irgendwo etwas danach ausgesehen hätte. Dazu
eine Kleinigkeit fürs Tagesgeschäft: Die Einträge einer Karte lassen sich nach
Datum sortieren.

**Bestehende Instanzen müssen nichts nachtragen.** Alles Neue ist abschaltbar
oder greift erst, wenn jemand es einträgt.

- **Die Änderungsliste im Update-Kasten riss Sätze auseinander**, sobald eine
  Folgezeile mit einem fett gesetzten Wort begann — das Sternchen galt als
  neuer Aufzählungspunkt. Ein Aufzählungszeichen braucht jetzt ein Leerzeichen
  dahinter.

- **Einträge lassen sich je Karte nach Datum sortieren.** Ein neuer Knopf im
  Kartenkopf schaltet zwischen der bisherigen Ordnung (dringendste zuerst),
  **neueste zuerst** und **älteste zuerst** um. Jede Karte behält ihre eigene
  Wahl, gemerkt pro Gerät wie Reihenfolge und Ein-/Ausklappen; weicht eine
  Karte von der Vorgabe ab, ist der Knopf farbig — sonst sucht man später,
  warum sie anders aussieht.
  - Abgehaktes bleibt in **beiden** Richtungen am Ende der Liste.
  - Einträge ohne Datum stehen in beiden Richtungen unten.
  - Der Posteingang gibt jetzt die **Uhrzeit** zur Sortierung mit. Vorher kannte
    er nur den Tag, und die Reihenfolge mehrerer Mails desselben Tages war
    damit zufällig — im Posteingang der Normalfall.
  - Rechnungen und Bestellungen zeigen nur die 20 neuesten. Stellt man sie auf
    „älteste zuerst", sagt die Karte das jetzt ausdrücklich: Sortiert wird nur
    das Angezeigte. Ohne diesen Satz hätte sie behauptet, die älteste offene
    Rechnung zu zeigen.

- **Der Google-Kalender lässt sich jetzt per normaler Anmeldung anbinden.**
  Bisher ging es nur über eine Dienstkonto-Datei, die auf dem Server liegen und
  als Volume eingehängt werden musste — der einzige Zugang im ganzen Dashboard,
  für den SSH nötig war, und deshalb der einzige, nach dem der
  Einrichtungsassistent nicht fragen konnte. Neu unter **Settings → Kalender**:
  Client-ID und Geheimnis eintragen, „Mit Google anmelden" drücken, zustimmen.
  Die nötige Weiterleitungs-Adresse zeigt das Dashboard selbst an — der
  häufigste Fehler (`redirect_uri_mismatch`) entsteht durch Abtippen.
  Danach ist auch der Kalender aus einer Liste wählbar statt abzutippen.
  - **Das Dienstkonto bleibt.** Wer es nutzt, merkt nichts; liegt beides vor,
    gilt die Anmeldung. Keine bestehende Instanz ändert sich von selbst.
  - Die Kalenderkarte erscheint jetzt nur noch, wenn sie auch etwas holen kann.
    Vorher stand sie da und meldete den fehlenden Zugang erst beim Abruf.
  - Googles Fehlermeldungen kommen im Klartext: fehlende Calendar-API,
    falsche Client-Angaben — und vor allem die abgelaufene Anmeldung, die
    entsteht, wenn der Zustimmungsbildschirm auf „Test" steht. Google
    widerruft dann **nach 7 Tagen**, ohne dass es irgendwo stünde.

- **`install.sh` schrieb einen Hash, mit dem sich niemand anmelden konnte.**
  Beim Verdoppeln der Dollarzeichen für die `.env` stand `$$` unmaskiert im
  Ersetzungstext — Bash setzt dort die Prozess-ID ein. Statt `$apr1$…` landete
  also die PID des Installationslaufs an den drei entscheidenden Stellen.
  Besonders ärgerlich war das stille Scheitern: Der Container lief, `/healthz`
  meldete grün, die Installation nannte ein Passwort, das nie gepasst hat.
  Dagegen jetzt vier Dinge:
  - Die Ersetzung ist maskiert, wie in `deploy/zugang-anlegen.sh` schon länger.
  - `install.sh` **probiert die Anmeldung am Ende wirklich aus** und bricht ab,
    statt Erfolg zu melden. `/healthz` läuft an der Anmeldung vorbei und taugt
    dafür nicht.
  - `deploy/zugang-anlegen.sh --pruefen` sagt zu einer **bestehenden** `.env`,
    ob ihre Hashes brauchbar sind. Der Fix heilt keine schon geschriebene
    Datei; wer vorher installiert hat, repariert sie mit
    `zugang-anlegen.sh <name>`. Ein Update meldet den Zustand von selbst.
  - Neu: `deploy/pruef-dollar.sh` — prüft die Falle im ganzen Repo und weist
    dabei zuerst nach, dass die alte Schreibweise den Fehler wirklich erzeugt.

- **Erstinstallations-Assistent.** Ein frisch aufgesetztes Dashboard zeigt
  jetzt statt des leeren Rasters eine Führung: erst Name, Rolle, Firma und
  Ansprechpartner, danach Karte für Karte die Zugänge — jede mit „Speichern
  und prüfen", jede überspringbar. Wer fertig ist, drückt einmal auf „Fertig";
  wer später etwas nachtragen will, öffnet ihn unter **Settings → Wartung**
  wieder. Der Assistent verschwindet von selbst, sobald eine Person und eine
  eingerichtete Karte da sind.

## 1.2.1 — 10.09.2026

- Der Update-Kasten zeigte als Änderungsliste die leere Sammelstelle
  „Unveröffentlicht" statt der Punkte der bereitliegenden Version. Genommen
  wird jetzt der erste Abschnitt mit einer **Nummer**.

## 1.2.0 — 10.09.2026

Diese Fassung macht das Dashboard auf einem fremden Server installierbar.

> **Beim Aktualisieren einer bestehenden Instanz beachten:** Die vier
> Zulieferungen von außen kommen jetzt aus der `.env`. Wer sie nutzt, trägt
> dort `BANK_ORDNER_HOST`, `WIDERRUF_ORDNER_HOST`, `WATCHDOG_ORDNER_HOST` und
> `GOOGLE_ORDNER_HOST` ein — **sonst hängt still ein leerer Ordner drin** und
> die betroffenen Karten melden sich als „nicht eingerichtet".

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
