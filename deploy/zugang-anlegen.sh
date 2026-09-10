#!/usr/bin/env bash
# Legt einen Basic-Auth-Zugang fuer das Buchhaltungs-Dashboard an — oder aendert das Passwort
# eines bestehenden. Laeuft auf dem Server.
#
#   ./zugang-anlegen.sh team            → fragt das Passwort verdeckt ab
#   echo 'geheim' | ./zugang-anlegen.sh team -   → Passwort ueber stdin
#   ./zugang-anlegen.sh team 'geheim'            → als Argument; steht dann in
#                                                   Prozessliste und History
#   ./zugang-anlegen.sh --liste         → zeigt, welche Benutzer es gibt
#
# Nimmt drei Fallen ab:
#   1. Docker Compose frisst einzelne "$" — der Hash wird verdoppelt abgelegt.
#   2. Ein zweiter Eintrag mit gleichem Namen wuerde still gewinnen oder
#      verlieren — ein vorhandener Benutzer wird ersetzt statt angehaengt.
#   3. Am Ende wird die Anmeldung wirklich ausprobiert. Ohne diese Probe
#      merkt man einen kaputten Hash erst, wenn sich das Team nicht einloggen
#      kann.

set -euo pipefail

# Welche Instanz gemeint ist, kommt als Umgebungsvariable — das Skript
# laeuft auf dem Server und weiss nichts von den Ordnernamen hier.
INSTANZ="${INSTANZ:-dashboard}"
ORDNER="${ORDNER:-/docker/smg-$INSTANZ}"
ENV_DATEI="$ORDNER/.env"
# Die Adresse fuer die Anmeldeprobe steht in der .env der Instanz.
ADRESSE="https://$(grep -m1 '^HOST=' "$ENV_DATEI" 2>/dev/null | cut -d= -f2- | tr -d '\r')"

if [[ ! -f "$ENV_DATEI" ]]; then
    echo "✗ $ENV_DATEI fehlt. Erst das Dashboard einrichten (siehe README)." >&2
    exit 1
fi

benutzer_liste() {
    local zeile
    zeile="$(grep '^BASIC_AUTH_USERS=' "$ENV_DATEI" | head -1 || true)"
    zeile="${zeile#BASIC_AUTH_USERS=}"
    local IFS=','
    for eintrag in $zeile; do
        [[ -n "$eintrag" ]] && echo "  · ${eintrag%%:*}"
    done
}

if [[ "${1:-}" == "--liste" ]]; then
    echo "Zugänge für $ADRESSE:"
    benutzer_liste
    exit 0
fi

BENUTZER="${1:-}"
if [[ -z "$BENUTZER" ]]; then
    echo "Aufruf: $0 <benutzername> [passwort]" >&2
    echo "        $0 --liste" >&2
    exit 1
fi
if [[ ! "$BENUTZER" =~ ^[a-zA-Z0-9._-]+$ ]]; then
    echo "✗ Benutzername darf nur Buchstaben, Ziffern, Punkt, Strich enthalten." >&2
    exit 1
fi

PASSWORT="${2:-}"
if [[ "$PASSWORT" == "-" ]]; then
    # Aus der Standardeingabe lesen. Als Argument uebergeben stuende das
    # Passwort waehrend des Laufs in der Prozessliste (`ps aux`) und in der
    # Shell-History — ueber stdin nicht.
    read -r PASSWORT
elif [[ -z "$PASSWORT" ]]; then
    read -rsp "Passwort für „$BENUTZER“: " PASSWORT; echo
    read -rsp "Zur Sicherheit noch einmal: " PASSWORT2; echo
    if [[ "$PASSWORT" != "$PASSWORT2" ]]; then
        echo "✗ Die beiden Eingaben sind nicht gleich. Nichts geändert." >&2
        exit 1
    fi
fi
if [[ ${#PASSWORT} -lt 8 ]]; then
    echo "✗ Bitte mindestens 8 Zeichen. Nichts geändert." >&2
    exit 1
fi

# --- Hash bauen -----------------------------------------------------------
# apache2-utils (htpasswd) ist nicht installiert; openssl kann denselben
# APR1-Hash, den Traefik versteht.
HASH="$(openssl passwd -apr1 "$PASSWORT")"
HASH_FUER_ENV="${HASH//\$/\$\$}"   # Dollarzeichen verdoppeln, siehe Falle 1

# --- Bestehende Benutzer einsammeln, den gleichnamigen ersetzen -----------
ALT="$(grep '^BASIC_AUTH_USERS=' "$ENV_DATEI" | head -1 || true)"
ALT="${ALT#BASIC_AUTH_USERS=}"

NEU=""
ERSETZT="nein"
IFS=',' read -ra EINTRAEGE <<< "$ALT"
for eintrag in "${EINTRAEGE[@]}"; do
    [[ -z "$eintrag" ]] && continue
    if [[ "${eintrag%%:*}" == "$BENUTZER" ]]; then
        ERSETZT="ja"
        continue
    fi
    NEU="${NEU:+$NEU,}$eintrag"
done
NEU="${NEU:+$NEU,}${BENUTZER}:${HASH_FUER_ENV}"

# --- Schreiben, mit Sicherung --------------------------------------------
cp -p "$ENV_DATEI" "$ENV_DATEI.bak"
TEMP="$(mktemp)"
grep -v '^BASIC_AUTH_USERS=' "$ENV_DATEI" > "$TEMP" || true
echo "BASIC_AUTH_USERS=$NEU" >> "$TEMP"
cat "$TEMP" > "$ENV_DATEI"
rm -f "$TEMP"
chmod 600 "$ENV_DATEI"

if [[ "$ERSETZT" == "ja" ]]; then
    echo "▸ Passwort für „$BENUTZER“ geändert."
else
    echo "▸ Zugang „$BENUTZER“ angelegt."
fi

# --- Traefik die neue Middleware geben ------------------------------------
echo "▸ Container neu starten, damit Traefik die Zugänge neu liest"
(cd "$ORDNER" && docker compose up -d) 2>&1 | sed 's/^/  /'

# --- Probe aufs Exempel ---------------------------------------------------
echo "▸ Anmeldung ausprobieren"
for versuch in $(seq 1 10); do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 \
            -u "$BENUTZER:$PASSWORT" "$ADRESSE/" || true)"
    if [[ "$code" == "200" ]]; then
        echo "  ✓ „$BENUTZER“ kommt rein. Fertig."
        echo
        echo "Zugänge auf $ADRESSE:"
        benutzer_liste
        echo
        echo "Passwort ins mSecure und an die Person weitergeben — nicht in den Vault."
        exit 0
    fi
    sleep 2
done

echo "✗ Anmeldung schlägt fehl (HTTP $code). Alte Datei liegt unter $ENV_DATEI.bak." >&2
echo "  Zurückholen:  cp $ENV_DATEI.bak $ENV_DATEI && cd $ORDNER && docker compose up -d" >&2
exit 1
