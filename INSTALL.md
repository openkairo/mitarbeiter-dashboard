# Installieren

Diese Anleitung ist so geschrieben, dass eine KI sie ausführen kann. Sie nennt
die Voraussetzungen zuerst, weil das Dashboard ohne sie zwar startet, aber
niemand es erreicht.

## Was der Server mitbringen muss

| Voraussetzung | Warum |
|---|---|
| Docker mit `docker compose` v2 | das alte `docker-compose` reicht nicht |
| **Traefik**, der bereits läuft | das Dashboard bringt keinen eigenen Webserver mit |
| ein externes Docker-Netz, standardmäßig `traefik` | darüber findet Traefik den Container |
| ein Zertifikatsauflöser, standardmäßig `letsencrypt` | sonst gibt es kein HTTPS |
| ein Eingang namens `websecure` | so heißt Traefiks HTTPS-Eingang üblicherweise |
| `openssl` und `curl` | für das Anmelde-Passwort und die Abschlussprüfung |

Heißen Netz oder Auflöser anders, sag es dem Skript mit `--netz` und
`--aufloeser`.

## Reihenfolge — der DNS-Eintrag zuerst

**Vor** dem ersten Start muss ein A-Eintrag auf diesen Server zeigen. Traefik
holt beim Start ein Zertifikat; zeigt der Name noch woandershin, scheitert das,
und der Fehlversuch wird für Stunden gemerkt. Ein Dashboard, das man deswegen
nicht erreicht, sieht aus wie ein kaputtes Programm.

1. A-Eintrag setzen: `dashboard.example.org` → IP dieses Servers
2. Warten, bis mehrere Resolver ihn kennen (`dig +short @1.1.1.1 dashboard.example.org`)
3. Erst dann installieren

## Code holen

Das Repo ist **privat**. Drei Wege, je nachdem, was du hast:

```bash
# a) mit einem Lese-Token (Fine-grained, nur „Contents: read")
git clone https://<TOKEN>@github.com/openkairo/mitarbeiter-dashboard.git

# b) mit einem Bereitstellungsschlüssel, der auf dem Server liegt
git clone git@github.com:openkairo/mitarbeiter-dashboard.git

# c) ist das Repo öffentlich
git clone https://github.com/openkairo/mitarbeiter-dashboard.git
```

Ohne einen dieser Wege kommt niemand an den Code — eine KI, die nur die
Adresse bekommt, sieht `404`.

## Prüfen, dann installieren

```bash
cd mitarbeiter-dashboard

# Erst nur nachsehen — ändert nichts:
./install.sh --pruefen --host dashboard.example.org

# Dann einrichten:
./install.sh \
  --host dashboard.example.org \
  --instanz dashboard \
  --person "Alex" \
  --titel "Buchhaltung" \
  --firma "Beispiel GmbH" \
  --benutzer alex
```

Das Skript bricht ab, **bevor** es etwas anlegt, wenn eine Voraussetzung fehlt.
Läuft es durch, nennt es am Ende Adresse, Anmeldename und ein erzeugtes
Passwort. Ein eigenes Passwort geht mit `--passwort`.

Angelegt wird `/docker/smg-<instanz>/` mit `.env` (Rechte 600) und `data/`.
Ein anderer Ort geht mit `--ordner`.

## Danach: Karten einrichten

Nach der Installation ist das Dashboard leer — **das ist richtig so**. Jede
Karte erscheint, sobald ihre Zugangsdaten unter *Settings* stehen. Bis dahin
steht sie unter dem Raster in einer Zeile „noch nicht eingerichtet". Eine
Karte, die „Nichts offen" zeigt, weil niemand nachgesehen hat, behauptet
Feierabend.

Welche Karte was braucht, steht in der [README](README.md).

## Mehrere Personen

Für jede weitere Person eine eigene Instanz: eigener Ordner, eigene `.env`,
eigene Datenbank, eigener Hostname. Derselbe Code, `install.sh` noch einmal mit
anderem `--host` und `--instanz`.

## Zulieferungen von außen (optional)

Bank-Abgleich, Widerruf-Wache, Watchdog und der Google-Schlüssel kommen aus
Ordnern auf dem Server. Ohne Angabe wird ein leerer Ordner eingehängt und die
betroffenen Karten melden sich als „nicht eingerichtet". Wer sie hat, trägt in
der `.env` ein:

    BANK_ORDNER_HOST=/pfad/zur/bank-abgleich-automation
    WIDERRUF_ORDNER_HOST=/pfad/zur/widerruf-wache
    WATCHDOG_ORDNER_HOST=/pfad/zum/watchdog
    GOOGLE_ORDNER_HOST=/pfad/zum/ordner-mit-dem-google-schluessel   # Ordner mit google-key.json

## Später aktualisieren

Einmalig `deploy/update-einrichten.sh` von einem Rechner mit `gh`-Anmeldung.
Danach steht in den Einstellungen unter *Wartung* ein Knopf, der die neue
Version aus dem Repo holt — je Instanz einzeln, mit Rücknahme bei Fehlschlag.
