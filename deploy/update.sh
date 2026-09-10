#!/usr/bin/env bash
# Bringt EINE Instanz auf den Stand von GitHub. Laeuft auf dem Server.
#
#   /opt/smg-update/update.sh <instanz> [pruefen]
#
# „pruefen“ holt nur den neuesten Stand und schreibt, ob es etwas Neues gibt —
# es wird nichts angefasst.
#
# Drei Dinge, die dieses Skript NIE tut:
#   1. `.env` oder `data/` einer Instanz anfassen. Dort stehen Zugangsdaten,
#      Haken, Notizen und Nachrichten — das ist die Arbeit von Wochen.
#   2. Einen anderen Ordner unter /docker anfassen. Auf dem Server laufen zwei
#      Dutzend fremder Dienste; `docker compose` wird ausschliesslich IM
#      Instanzordner aufgerufen, nie mit -p oder global.
#   3. Aufraeumen. Kein `prune`, kein `down`, kein `--volumes`. Ein Update, das
#      Platz schafft, loescht irgendwann das Falsche.
#
# Geht der Neustart schief, wird der vorherige Stand zurueckgespielt und die
# Instanz noch einmal gebaut. Lieber die alte Version als eine tote Seite.

set -euo pipefail

INSTANZ="${1:-}"
MODUS="${2:-aufspielen}"
REPO="/opt/smg-update/repo"
BASIS="${DEPLOY_ORDNER:-/docker}"
ORDNER="$BASIS/smg-$INSTANZ"
STAND="$ORDNER/data/update-stand.json"
SICHERUNGEN="$ORDNER/.vorher"
BEHALTEN=5

if [[ -z "$INSTANZ" ]]; then
    echo "✗ Ohne Instanznamen geht nichts." >&2; exit 2
fi

melden() {  # zustand, text, [commit], [neue-fassung], [aenderungen]
    mkdir -p "$(dirname "$STAND")"
    python3 - "$1" "$2" "${3:-}" "$STAND" "${4:-}" "${5:-}" <<'PY'
import json, sys, datetime, os
zustand, text, commit, ziel = sys.argv[1:5]
fassung = sys.argv[5] if len(sys.argv) > 5 else ""
aenderungen = sys.argv[6] if len(sys.argv) > 6 else ""
alt = {}
if os.path.exists(ziel):
    try:
        alt = json.load(open(ziel))
    except Exception:
        alt = {}
alt.update({"zustand": zustand, "meldung": text,
            "am": datetime.datetime.now().isoformat(timespec="seconds")})
if commit:
    alt["commit"] = commit
if fassung:
    alt["neue_fassung"] = fassung
# Die Kurzfassung der Aenderungen: Wer auf „aufspielen" drueckt, soll vorher
# lesen koennen, was dann anders ist.
# In der Aenderungsliste bricht ein Punkt ueber mehrere Zeilen um. Roh
# uebernommen stuenden auf der Seite Satzfetzen — deshalb wird an den
# Aufzaehlungszeichen getrennt und alles dazwischen zusammengezogen.
punkte = []
for z in aenderungen.split(chr(10)):
    z = z.strip()
    if not z:
        continue
    if z[:1] in "-*":
        punkte.append(z[1:].strip())
    elif punkte:
        punkte[-1] += " " + z
alt["aenderungen"] = [p.replace("**", "") for p in punkte]
json.dump(alt, open(ziel, "w"), ensure_ascii=False, indent=1)
PY
    echo "[$INSTANZ] $1: $2"
}

# Versionsnummer statt Commit-Kennung: „1.2.0" sagt, ob etwas Grosses oder eine
# Kleinigkeit dazukommt — „0f1c7f3f" sagt niemandem etwas.
fassung() { tr -d " \t\n\r" < "$1/VERSION" 2>/dev/null || echo ""; }

kurz() { git -C "$REPO" rev-parse --short=8 "$1" 2>/dev/null || echo "?"; }

[[ -d "$ORDNER" ]]      || { melden fehler "Ordner $ORDNER gibt es nicht."; exit 1; }
[[ -f "$ORDNER/.env" ]] || { melden fehler "In $ORDNER fehlt die .env — hier wird nichts eingerichtet."; exit 1; }

# Die wichtigste Sperre dieses Skripts.
#
# Unter /docker liegen auch fremde Projekte, die zufaellig mit smg- anfangen —
# andere Werkzeuge desselben Hauses. Ein Aufspielen dort wuerde
# deren Code durch diesen ersetzen und das Projekt zerstoeren. Angefasst wird
# deshalb nur, was nachweislich DIESE Anwendung ist: zwei Dateien, die es
# ausschliesslich hier gibt. Fehlt eine, wird abgebrochen, bevor irgendetwas
# geschrieben ist. (Am 10.09.2026 hat die taegliche Pruefung Anforderungen in
# sechs fremde Ordner geschrieben — folgenlos, weil nur geprueft wurde, aber
# ohne diese Sperre waere es beim Aufspielen anders ausgegangen.)
for beweis in app/profil.py app/quellen/superchat.py; do
    if [[ ! -f "$ORDNER/$beweis" ]]; then
        echo "[$INSTANZ] ABGELEHNT: $ORDNER ist keine Instanz dieses Dashboards ($beweis fehlt)." >&2
        exit 3
    fi
done
[[ -d "$REPO/.git" ]]   || { melden fehler "Kein Repo unter $REPO — erst update-einrichten.sh laufen lassen."; exit 1; }

melden laeuft "Hole den Stand von GitHub …"
if ! git -C "$REPO" fetch --quiet origin main 2>/tmp/smg-update-git.log; then
    melden fehler "GitHub nicht erreichbar: $(tail -1 /tmp/smg-update-git.log | cut -c1-160)"
    exit 1
fi
NEU="$(kurz origin/main)"
# Die Arbeitskopie sofort mitziehen, in BEIDEN Betriebsarten.
#
# Die Wache fuehrt das Skript aus dieser Arbeitskopie aus. Wurde sie nur beim
# Aufspielen nachgezogen, lief beim Pruefen monatelang eine alte Version des
# Skripts — genau das ist am 10.09.2026 passiert: Die Meldung sprach noch von
# Commit-Kennungen, obwohl die Versionslogik laengst im Repo lag. Die
# Arbeitskopie anzufassen ist ungefaehrlich, sie ist keine Instanz.
git -C "$REPO" reset --hard --quiet origin/main

# Die laufende Version steht in der Instanz selbst, nicht in einer Merkdatei:
# Was dort liegt, IST der Stand — eine Notiz daneben koennte falsch sein.
HIER_F="$(fassung "$ORDNER")"
NEU_F="$(git -C "$REPO" show origin/main:VERSION 2>/dev/null | tr -d " \t\n\r" || echo "")"
LISTE="$(git -C "$REPO" show origin/main:CHANGELOG.md 2>/dev/null \
         | awk '/^## /{n++; if(n==1){next}} n==1 && NF' | head -12 || true)"

if [[ "$MODUS" == "pruefen" ]]; then
    if [[ -n "$NEU_F" && "$NEU_F" == "$HIER_F" ]]; then
        melden aktuell "Version $HIER_F ist die neueste." "$NEU" "" ""
    elif [[ -n "$NEU_F" ]]; then
        melden verfuegbar "Version $NEU_F liegt bereit — hier läuft ${HIER_F:-eine ältere}." \
               "$NEU" "$NEU_F" "$LISTE"
    else
        melden verfuegbar "Ein neuer Stand liegt bereit ($NEU)." "$NEU" "" ""
    fi
    exit 0
fi

melden laeuft "Prüfe den neuen Code …"
if ! python3 -m compileall -q "$REPO/app" >/dev/null 2>&1; then
    melden fehler "Der neue Stand hat einen Syntaxfehler — nichts geändert."
    exit 1
fi

# Sicherung: nur Programmdateien. `.env` und `data/` sind nicht dabei — sie
# werden auch nicht ueberschrieben, also gibt es nichts zurueckzuholen.
ZEIT="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$SICHERUNGEN/$ZEIT"
melden laeuft "Lege eine Sicherung des laufenden Stands an …"
rsync -a --exclude '.env' --exclude 'data/' --exclude '.vorher/' \
      "$ORDNER/" "$SICHERUNGEN/$ZEIT/"

melden laeuft "Spiele Version ${NEU_F:-$NEU} auf …"
rsync -a --delete \
    --exclude '__pycache__' --exclude '*.pyc' \
    --exclude '.env' --exclude 'data/' --exclude '.vorher/' \
    --exclude 'deploy/' --exclude 'docs/' --exclude 'README.md' \
    --exclude 'zugang-anlegen.sh' \
    "$REPO/" "$ORDNER/"
# Gehoert auf den Server, liegt aber in deploy/ und ist deshalb vom Abgleich
# ausgenommen — ohne diese Zeile waere es nach dem ersten Update weg.
install -m 755 "$REPO/deploy/zugang-anlegen.sh" "$ORDNER/zugang-anlegen.sh"

melden laeuft "Baue den Container neu …"
if ! (cd "$ORDNER" && docker compose up -d --build --remove-orphans) >/tmp/smg-update-bau.log 2>&1; then
    melden laeuft "Bau fehlgeschlagen — spiele den vorherigen Stand zurück …"
    rsync -a --delete --exclude '.env' --exclude 'data/' --exclude '.vorher/' \
          "$SICHERUNGEN/$ZEIT/" "$ORDNER/"
    (cd "$ORDNER" && docker compose up -d --build) >/dev/null 2>&1 || true
    melden fehler "Neuer Stand ließ sich nicht bauen — alter Stand läuft weiter. $(tail -3 /tmp/smg-update-bau.log | tr '\n' ' ' | cut -c1-200)"
    exit 1
fi

HOST="$(grep -m1 '^HOST=' "$ORDNER/.env" | cut -d= -f2- | tr -d '\r' || true)"
melden laeuft "Warte darauf, dass die Seite antwortet …"
GESUND=""
for _ in $(seq 1 20); do
    if curl -fsS --max-time 8 "https://$HOST/healthz" 2>/dev/null | grep -q '"status":"ok"'; then
        GESUND="ja"; break
    fi
    sleep 3
done

if [[ -z "$GESUND" ]]; then
    melden laeuft "Seite antwortet nicht — spiele den vorherigen Stand zurück …"
    rsync -a --delete --exclude '.env' --exclude 'data/' --exclude '.vorher/' \
          "$SICHERUNGEN/$ZEIT/" "$ORDNER/"
    (cd "$ORDNER" && docker compose up -d --build) >/dev/null 2>&1 || true
    melden fehler "Nach dem Update antwortete die Seite nicht — der vorherige Stand ist zurück."
    exit 1
fi

# Alte Sicherungen ausduennen: die letzten fuenf bleiben. Das sind eigene
# Kopien, keine Daten der Instanz.
ls -1dt "$SICHERUNGEN"/*/ 2>/dev/null | tail -n +$((BEHALTEN + 1)) | xargs -r rm -rf

melden fertig "Auf Version $(fassung "$ORDNER") gebracht." "$NEU" "" ""
