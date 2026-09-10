#!/usr/bin/env bash
# Laeuft per Cron jede Minute und fuehrt angeforderte Updates aus.
#
# Warum ueber eine Datei und nicht direkt aus dem Dashboard: Der Container
# muesste dafuer den Docker-Socket haben — das waere Root auf einem Server mit
# zwei Dutzend fremder Dienste, erreichbar fuer jeden, der sich am Dashboard
# anmelden kann. Die Instanz legt stattdessen eine Anforderung in ihren eigenen
# Datenordner; ausgefuehrt wird sie hier draussen.

set -euo pipefail
BASIS="${DEPLOY_ORDNER:-/docker}"
REPO="/opt/smg-update/repo"

# Einmal am Tag von selbst nachsehen, ob es etwas Neues gibt. Das Ergebnis
# steht danach in update-stand.json, und das Dashboard setzt daraufhin einen
# kleinen Punkt an den Settings-Eintrag. Aufgespielt wird NICHTS von allein —
# wann ein Dashboard fuer eine Minute weg ist, entscheidet ein Mensch.
# Unter /docker liegen auch fremde Projekte, die mit smg- anfangen. Nur was
# nachweislich diese Anwendung ist, wird ueberhaupt betrachtet.
unser() { [[ -f "$1/app/profil.py" && -f "$1/app/quellen/superchat.py" ]]; }

if [[ "${1:-}" == "--taeglich" ]]; then
    for ordner in "$BASIS"/smg-*/; do
        unser "$ordner" || continue
        mkdir -p "$ordner/data"
        echo pruefen > "$ordner/data/update-angefordert"
    done
    exit 0
fi

for datei in "$BASIS"/smg-*/data/update-angefordert; do
    [[ -e "$datei" ]] || continue
    ordner="$(dirname "$(dirname "$datei")")"
    instanz="$(basename "$ordner")"; instanz="${instanz#smg-}"
    if ! unser "$ordner"; then
        # Anforderung in einem fremden Projekt: wegnehmen und nichts tun.
        rm -f "$datei"
        echo "[$instanz] uebergangen — kein Ordner dieses Dashboards" >> /var/log/smg-update.log
        continue
    fi
    modus="$(head -c 20 "$datei" | tr -d '\n\r ' || true)"
    [[ "$modus" == "pruefen" ]] || modus="aufspielen"
    rm -f "$datei"     # zuerst weg, damit ein Fehlschlag nicht ewig wiederholt

    # Das Skript aus dem Repo in eine Kopie legen und DIE ausfuehren: Sonst
    # tauscht das Update die gerade laufende Datei unter sich selbst aus.
    lauf="$(mktemp /tmp/smg-update-XXXX.sh)"
    cp "$REPO/deploy/update.sh" "$lauf" 2>/dev/null || cp /opt/smg-update/update.sh "$lauf"
    chmod +x "$lauf"
    flock -w 600 /var/lock/smg-update.lock "$lauf" "$instanz" "$modus" \
        >> /var/log/smg-update.log 2>&1 || true
    rm -f "$lauf"
done
