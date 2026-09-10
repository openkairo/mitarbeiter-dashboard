#!/usr/bin/env bash
# Rollt ein Mitarbeiter-Dashboard auf VPS 1 aus.
#
#   ./deploy/deploy.sh                    — die Vorgabe-Instanz
#   ./deploy/deploy.sh <instanz>          — eine weitere Instanz
#   ./deploy/deploy.sh <instanz> --dry-run — nur zeigen, was sich aendern wuerde
#
# Derselbe Code, mehrere Instanzen: je Instanz ein Ordner /docker/smg-<name>
# mit eigener .env und eigener Datenbank. Uebertragen werden ausschliesslich
# Programmdateien; .env und data/ bleiben unberuehrt.

set -euo pipefail

# Wohin ausgerollt wird, steht NICHT im Quelltext: Server-Adresse und
# Schluesselpfad gehoeren zu einer bestimmten Installation, nicht zum Programm.
# Beides kommt aus deploy/ziel.env (nicht im Repo, Vorlage: ziel.beispiel.env)
# oder aus der Umgebung.
ZIEL_ENV="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ziel.env"
# shellcheck disable=SC1090
[[ -f "$ZIEL_ENV" ]] && source "$ZIEL_ENV"
SERVER="${DEPLOY_SERVER:-}"
SSH_KEY="${DEPLOY_SSH_KEY:-$HOME/.ssh/id_ed25519}"
if [[ -z "$SERVER" ]]; then
    echo "✗ DEPLOY_SERVER fehlt. deploy/ziel.beispiel.env nach deploy/ziel.env" >&2
    echo "  kopieren und ausfuellen (Server, Schluessel, VPS-IP)." >&2
    exit 1
fi
QUELLE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

INSTANZ="${DEPLOY_INSTANZ:-dashboard}"
TROCKEN=""
for arg in "$@"; do
    case "$arg" in
        --dry-run) TROCKEN="--dry-run" ;;
        -*)        echo "✗ Unbekannte Option: $arg" >&2; exit 1 ;;
        *)         INSTANZ="$arg" ;;
    esac
done
ZIEL="${DEPLOY_ORDNER:-/docker}/smg-$INSTANZ"

ssh_kurz() { ssh -i "$SSH_KEY" -o ConnectTimeout=15 "$SERVER" "$@"; }

# Die Adresse fuer die Abschlusspruefung kommt aus der .env der Instanz auf dem
# Server, nicht fest aus dem Skript: Beim Umbenennen einer Domain waere sie
# sonst still falsch, und das Deploy meldete einen Fehler, obwohl alles laeuft.
ERSTER_HOST="$(ssh_kurz "grep -m1 '^HOST=' $ZIEL/.env 2>/dev/null | cut -d= -f2-" | tr -d '\r' || true)"
[[ -z "$ERSTER_HOST" ]] && ERSTER_HOST="${DEPLOY_HOST:-}"
if [[ -z "$ERSTER_HOST" ]]; then
    echo "✗ Kein HOST in $ZIEL/.env und kein DEPLOY_HOST — Abschlusspruefung nicht moeglich." >&2
    exit 1
fi
ADRESSE="https://$ERSTER_HOST"

ssh_cmd() { ssh -i "$SSH_KEY" -o ConnectTimeout=15 "$SERVER" "$@"; }

echo "▸ Instanz: $INSTANZ  →  $ZIEL  ($ADRESSE)"
echo "▸ 1/5  Code lokal pruefen"
if command -v python3 >/dev/null; then
    python3 -m compileall -q "$QUELLE/app" >/dev/null || {
        echo "✗ Syntaxfehler im Python-Code — Abbruch, nichts uebertragen." >&2
        exit 1
    }
fi
# Kein Deploy, wenn versehentlich echte Zugangsdaten im Projekt liegen.
if [[ -f "$QUELLE/.env" ]]; then
    echo "✗ Es liegt eine .env im Projektordner. Die gehoert nur auf den Server." >&2
    exit 1
fi
echo "  ✓ Code in Ordnung"

echo "▸ 2/5  Verbindung und Zielordner pruefen"
ssh_cmd "mkdir -p $ZIEL/data"
if ! ssh_cmd "test -f $ZIEL/.env"; then
    echo "  ! Auf dem Server fehlt $ZIEL/.env."
    echo "    Einmalig anlegen — Vorlage ist .env.beispiel im Projekt. Mindestens"
    echo "    noetig: BASIC_AUTH_USERS (Zugaenge, jedes \$ verdoppelt) und bei einer"
    echo "    zweiten Instanz INSTANZ, HOST, HOST_REGEL, PERSON_NAME, TITEL, KARTEN."
    echo
    echo "      ssh -i $SSH_KEY $SERVER \\"
    echo "        'install -m 600 /dev/null $ZIEL/.env'"
    echo
    echo "    Danach Zugaenge mit ./zugang-anlegen.sh im Instanzordner ergaenzen."
    exit 1
fi
echo "  ✓ Zielordner und .env vorhanden"

echo "▸ 3/5  Dateien uebertragen${TROCKEN:+ (Probelauf)}"
rsync -az --delete $TROCKEN \
    -e "ssh -i $SSH_KEY" \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.env' \
    --exclude 'data/' \
    --exclude 'deploy/' \
    --exclude 'README.md' \
    "$QUELLE/" "$SERVER:$ZIEL/"

if [[ -n "$TROCKEN" ]]; then
    echo "▸ Probelauf beendet — auf dem Server wurde nichts geaendert."
    exit 0
fi

# Das Zugangs-Skript gehoert auf den Server, liegt aber in deploy/ — und das ist
# vom rsync ausgenommen. Ohne diese Zeile loescht `--delete` es beim naechsten
# Ausrollen wieder, weil es im Quellordner oben nicht vorkommt. Genau das ist
# am 09.09.2026 passiert, direkt nachdem der erste Zugang angelegt war.
scp -q -i "$SSH_KEY" "$QUELLE/deploy/zugang-anlegen.sh" "$SERVER:$ZIEL/zugang-anlegen.sh"
ssh_cmd "chmod +x $ZIEL/zugang-anlegen.sh"

echo "  ✓ uebertragen"

echo "▸ 4/5  Container neu bauen und starten"
ssh_cmd "cd $ZIEL && docker compose up -d --build --remove-orphans" 2>&1 | sed 's/^/  /'

echo "▸ 5/5  Nachsehen, ob die Seite antwortet"
for versuch in $(seq 1 20); do
    zustand="$(curl -fsS --max-time 8 "$ADRESSE/healthz" 2>/dev/null || true)"
    if [[ "$zustand" == *'"status":"ok"'* ]]; then
        echo "  ✓ $ADRESSE antwortet: $zustand"
        echo
        echo "Fertig. Dashboard: $ADRESSE"
        exit 0
    fi
    sleep 3
done

echo "✗ Die Seite antwortet nach 60 Sekunden nicht." >&2
echo "  Logs ansehen:  ssh -i $SSH_KEY $SERVER 'cd $ZIEL && docker compose logs --tail 50'" >&2
exit 1
