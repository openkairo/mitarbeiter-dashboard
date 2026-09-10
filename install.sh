#!/usr/bin/env bash
# Richtet eine Instanz dieses Dashboards auf DIESEM Server ein.
#
#   ./install.sh --host buchhaltung.example.org --instanz buchhaltung \
#                --person Alex --titel Buchhaltung --benutzer alex
#
#   ./install.sh --pruefen --host buchhaltung.example.org
#       prueft nur die Voraussetzungen und aendert nichts.
#
# Das Skript bricht ab, BEVOR es etwas anlegt, wenn eine Voraussetzung fehlt.
# Ein halb eingerichtetes Dashboard ist schlimmer als gar keines: Es sieht aus
# wie ein Fehler im Programm, obwohl nur die Umgebung nicht passt.

set -euo pipefail

HOST=""; INSTANZ=""; PERSON=""; TITEL="Dashboard"; FIRMA=""; BENUTZER=""
PASSWORT=""; NETZ="traefik"; AUFLOESER="letsencrypt"; ORDNER=""
NUR_PRUEFEN=""; ANSPRECHPARTNER=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)     HOST="$2"; shift 2 ;;
        --instanz)  INSTANZ="$2"; shift 2 ;;
        --person)   PERSON="$2"; shift 2 ;;
        --titel)    TITEL="$2"; shift 2 ;;
        --firma)    FIRMA="$2"; shift 2 ;;
        --hilfe-von) ANSPRECHPARTNER="$2"; shift 2 ;;
        --benutzer) BENUTZER="$2"; shift 2 ;;
        --passwort) PASSWORT="$2"; shift 2 ;;
        --netz)     NETZ="$2"; shift 2 ;;
        --aufloeser) AUFLOESER="$2"; shift 2 ;;
        --ordner)   ORDNER="$2"; shift 2 ;;
        --pruefen)  NUR_PRUEFEN="ja"; shift ;;
        -h|--help)  sed -n '2,14p' "$0"; exit 0 ;;
        *) echo "✗ Unbekannte Angabe: $1" >&2; exit 2 ;;
    esac
done

FEHLT=()
melde() { printf '  %s %s\n' "$1" "$2"; }
gut()   { melde "✓" "$1"; }
schlecht() { melde "✗" "$1"; FEHLT+=("$1"); }
hinweis()  { melde "•" "$1"; }

echo "▸ 1/6  Werkzeuge auf diesem Server"
command -v docker >/dev/null && gut "docker ist da" || schlecht "docker fehlt"
docker compose version >/dev/null 2>&1 && gut "docker compose (v2) ist da" \
    || schlecht "docker compose fehlt — das alte docker-compose reicht nicht"
command -v openssl >/dev/null && gut "openssl ist da (für das Anmelde-Passwort)" \
    || schlecht "openssl fehlt"
command -v curl >/dev/null && gut "curl ist da" || schlecht "curl fehlt"
[[ "$(id -u)" == "0" ]] && gut "läuft als root" || hinweis "läuft nicht als root — docker muss ohne sudo gehen"

echo "▸ 2/6  Traefik"
if docker network inspect "$NETZ" >/dev/null 2>&1; then
    gut "Docker-Netz „$NETZ“ ist da"
else
    schlecht "Docker-Netz „$NETZ“ fehlt — Traefik muss laufen und dieses Netz anbieten"
fi
if docker ps --format '{{.Image}}' | grep -qi traefik; then
    gut "ein Traefik-Container läuft"
    if docker ps -q --filter ancestor=traefik >/dev/null 2>&1 && \
       docker inspect $(docker ps -q --filter name=traefik | head -1) 2>/dev/null \
       | grep -q "certificatesresolvers\.$AUFLOESER"; then
        gut "Zertifikatsauflöser „$AUFLOESER“ gefunden"
    else
        hinweis "Auflöser „$AUFLOESER“ nicht nachweisbar — bitte selbst prüfen; ohne ihn gibt es kein Zertifikat"
    fi
else
    schlecht "kein Traefik-Container sichtbar"
fi

echo "▸ 3/6  Adresse und DNS"
if [[ -z "$HOST" ]]; then
    schlecht "--host fehlt"
else
    EIGENE="$(curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null || true)"
    [[ -n "$EIGENE" ]] && gut "eigene Adresse: $EIGENE" || hinweis "eigene Adresse nicht ermittelbar"
    # Drei Faelle, die auseinandergehalten werden muessen. Keine Antwort ist
    # KEIN „nicht pruefbar“, sondern ein fehlender A-Eintrag — und damit der
    # haeufigste Grund, warum das Zertifikat spaeter scheitert.
    if ! command -v dig >/dev/null; then
        hinweis "dig fehlt — DNS nicht prüfbar; bitte selbst sicherstellen, dass $HOST hierher zeigt"
    else
        TREFFER=0; ANTWORTEN=0; GESEHEN=""
        for r in 1.1.1.1 8.8.8.8 9.9.9.9; do
            ANTWORT="$(dig +short @"$r" "$HOST" A 2>/dev/null | tail -1 || true)"
            [[ -z "$ANTWORT" ]] && continue
            ANTWORTEN=$((ANTWORTEN + 1))
            GESEHEN="$GESEHEN $ANTWORT"
            [[ "$ANTWORT" == "$EIGENE" ]] && TREFFER=$((TREFFER + 1))
        done
        if [[ "$ANTWORTEN" -eq 0 ]]; then
            schlecht "$HOST hat keinen A-Eintrag — erst im DNS anlegen, sonst scheitert das Zertifikat"
        elif [[ "$ANTWORTEN" -lt 3 ]]; then
            schlecht "$HOST kennt erst $ANTWORTEN von 3 Resolvern — noch warten, der Eintrag verteilt sich"
        elif [[ "$TREFFER" -eq "$ANTWORTEN" ]]; then
            gut "$HOST zeigt bei allen drei Resolvern hierher"
        else
            schlecht "$HOST zeigt auf$GESEHEN statt auf $EIGENE — erst den A-Eintrag korrigieren"
        fi
    fi
fi

echo "▸ 4/6  Angaben"
[[ -n "$INSTANZ" ]] || INSTANZ="$(echo "${HOST%%.*}" | tr -cd 'a-z0-9-')"
[[ -n "$INSTANZ" ]] && gut "Instanz: $INSTANZ" || schlecht "--instanz fehlt und lässt sich nicht ableiten"
ORDNER="${ORDNER:-/docker/smg-$INSTANZ}"
if [[ -z "$INSTANZ" ]]; then
    :   # ohne Instanznamen ist der Ordner sinnlos — der Fehler steht schon oben
elif [[ -e "$ORDNER" ]]; then
    schlecht "$ORDNER gibt es schon — hier wird nichts überschrieben"
else
    gut "Zielordner frei: $ORDNER"
fi
[[ -n "$BENUTZER" ]] && gut "Anmeldename: $BENUTZER" \
    || schlecht "--benutzer fehlt — ohne Zugang käme niemand auf die Seite"
QUELLE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$QUELLE/docker-compose.yml" && -f "$QUELLE/app/main.py" ]] \
    && gut "Quelltext liegt in $QUELLE" || schlecht "in $QUELLE fehlt der Quelltext"

echo
if [[ ${#FEHLT[@]} -gt 0 ]]; then
    echo "✗ ${#FEHLT[@]} Voraussetzung(en) fehlen — es wurde nichts angelegt:"
    printf '    %s\n' "${FEHLT[@]}"
    exit 1
fi
echo "✓ Alle Voraussetzungen erfüllt."
if [[ -n "$NUR_PRUEFEN" ]]; then
    echo "  (--pruefen: es wurde nichts angelegt)"
    exit 0
fi

echo "▸ 5/6  Einrichten"
mkdir -p "$ORDNER"
# Quelltext kopieren, aber nichts Persoenliches: .env und data/ entstehen hier neu.
rsync -a --exclude '.git' --exclude '.env' --exclude 'data/' --exclude '__pycache__' \
      "$QUELLE/" "$ORDNER/"
mkdir -p "$ORDNER/data"

[[ -n "$PASSWORT" ]] || PASSWORT="$(openssl rand -base64 12)"
HASH="$(openssl passwd -apr1 "$PASSWORT")"
# Compose frisst einzelne "$" — im .env muss jedes verdoppelt sein.
HASH_ENV="${HASH//$/$$}"

install -m 600 /dev/null "$ORDNER/.env"
cat > "$ORDNER/.env" <<ENDE
INSTANZ=$INSTANZ
HOST=$HOST
HOST_REGEL=Host(\`$HOST\`)
PERSON_NAME=$PERSON
TITEL=$TITEL
FIRMA=$FIRMA
ANSPRECHPARTNER=$ANSPRECHPARTNER
KARTEN=
KOPFZAHLEN=
BASIC_AUTH_USERS=$BENUTZER:$HASH_ENV
ENDE
# Alles Weitere aus der Vorlage anhaengen, ohne die Zeilen von oben zu doppeln.
grep -vE '^(INSTANZ|HOST|HOST_REGEL|PERSON_NAME|TITEL|FIRMA|ANSPRECHPARTNER|KARTEN|KOPFZAHLEN|BASIC_AUTH_USERS)=' \
     "$QUELLE/.env.beispiel" >> "$ORDNER/.env"
chmod 600 "$ORDNER/.env"
gut ".env angelegt (Rechte 600)"

echo "▸ 6/6  Bauen und starten"
(cd "$ORDNER" && docker compose up -d --build) 2>&1 | tail -3 | sed 's/^/  /'
for _ in $(seq 1 20); do
    if curl -fsS --max-time 8 "https://$HOST/healthz" 2>/dev/null | grep -q '"status":"ok"'; then
        echo
        echo "Fertig. Dashboard: https://$HOST"
        echo "  Anmeldung: $BENUTZER / $PASSWORT"
        echo "  Zugangsdaten für die Karten trägst du dort unter „Settings“ ein;"
        echo "  jede Karte erscheint, sobald ihr Zugang steht."
        exit 0
    fi
    sleep 3
done
echo "✗ Die Seite antwortet nach 60 Sekunden nicht." >&2
echo "  Logs:  cd $ORDNER && docker compose logs --tail 50" >&2
exit 1
