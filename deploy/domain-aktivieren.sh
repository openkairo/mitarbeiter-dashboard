#!/usr/bin/env bash
# Haengt einen weiteren Hostnamen an das Buchhaltungs-Dashboard — aber erst, wenn er
# wirklich auf den VPS zeigt.
#
#   ./deploy/domain-aktivieren.sh dashboard.example.org
#   ./deploy/domain-aktivieren.sh --pruefen dashboard.example.org   (nur nachsehen)
#
# Warum die Pruefung sein muss: Traefik packt alle Hostnamen einer Regel in
# EIN Zertifikat. Steht ein Name drin, der noch woandershin zeigt, scheitert
# die Let's-Encrypt-Pruefung fuer das ganze Zertifikat — und damit irgendwann
# auch die Erneuerung fuer die bereits laufenden Namen. Das Dashboard wuerde Wochen
# spaeter ohne erkennbaren Zusammenhang ausfallen.
#
# Zweite Lehre, aus dem Delegationswechsel vom 12.08.2026: Eine DNS-Abfrage
# von einem Ort beweist nichts. Deshalb fragt das Skript mehrere oeffentliche
# Resolver UND den VPS selbst.

set -euo pipefail

# Server und Schluessel gehoeren zur Installation, nicht zum Programm —
# siehe deploy/ziel.beispiel.env.
ZIEL_ENV="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ziel.env"
# shellcheck disable=SC1090
[[ -f "$ZIEL_ENV" ]] && source "$ZIEL_ENV"
VPS_IP="${DEPLOY_VPS_IP:-}"
SERVER="${DEPLOY_SERVER:-root@$VPS_IP}"
SSH_KEY="${DEPLOY_SSH_KEY:-$HOME/.ssh/id_ed25519}"
if [[ -z "$VPS_IP" ]]; then
    echo "✗ DEPLOY_VPS_IP fehlt — deploy/ziel.env anlegen (Vorlage: ziel.beispiel.env)." >&2
    exit 1
fi
PROJEKT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="$PROJEKT/docker-compose.yml"
RESOLVER=(1.1.1.1 8.8.8.8 9.9.9.9)

NUR_PRUEFEN=""
if [[ "${1:-}" == "--pruefen" ]]; then
    NUR_PRUEFEN="ja"
    shift
fi

NEUER_HOST="${1:-}"
if [[ -z "$NEUER_HOST" ]]; then
    echo "Aufruf: $0 [--pruefen] <hostname>" >&2
    exit 1
fi

echo "▸ 1/4  Zeigt $NEUER_HOST auf den VPS ($VPS_IP)?"

alle_gut="ja"
for resolver in "${RESOLVER[@]}"; do
    antwort="$(dig +short A "$NEUER_HOST" "@$resolver" 2>/dev/null | grep -E '^[0-9.]+$' | tail -1 || true)"
    if [[ "$antwort" == "$VPS_IP" ]]; then
        echo "  ✓ $resolver sagt $antwort"
    else
        echo "  ✗ $resolver sagt ${antwort:-(nichts)} — erwartet $VPS_IP"
        alle_gut="nein"
    fi
done

# Der VPS selbst sieht das Netz manchmal anders als der Mac — genau daran ist
# der Delegationswechsel im August aufgefallen.
vom_vps="$(ssh -i "$SSH_KEY" -o ConnectTimeout=10 "$SERVER" \
    "getent hosts $NEUER_HOST | awk '{print \$1}' | head -1" 2>/dev/null || true)"
if [[ "$vom_vps" == "$VPS_IP" ]]; then
    echo "  ✓ der VPS selbst sagt $vom_vps"
else
    echo "  ✗ der VPS selbst sagt ${vom_vps:-(nichts)} — erwartet $VPS_IP"
    alle_gut="nein"
fi

if [[ "$alle_gut" != "ja" ]]; then
    cat <<HINWEIS

✗ Noch nicht so weit — es wurde nichts geändert.

  Der Name zeigt noch nicht auf diesen Server. Beim zustaendigen
  DNS-Anbieter anzulegen (dort, wo die Nameserver der Domain stehen —
  nicht zwingend beim Hoster des Servers):

      Name: ${NEUER_HOST%%.*}    Typ: A    Wert: $VPS_IP

  Achtung bei Wildcards in der Zone (* CNAME oder * A): Der Name antwortet
  dann schon jetzt, nur mit der falschen Adresse. Ein eigener A-Eintrag ist
  spezifischer und gewinnt.

  Danach dieses Skript erneut aufrufen. Bis dahin bleibt alles, wie es ist.

HINWEIS
    exit 1
fi

echo "  ✓ überall gleich"

if [[ -n "$NUR_PRUEFEN" ]]; then
    echo "▸ Nur nachgesehen — nichts geändert."
    exit 0
fi

echo "▸ 2/4  Hostnamen in die Traefik-Regeln aufnehmen"

if grep -q "$NEUER_HOST" "$COMPOSE"; then
    echo "  · steht schon drin"
else
    cp -p "$COMPOSE" "$COMPOSE.bak"
    python3 - "$COMPOSE" "$NEUER_HOST" <<'PY'
import re
import sys

pfad, neuer_host = sys.argv[1], sys.argv[2]
zeilen = open(pfad, encoding="utf-8").read().splitlines(keepends=True)

# Die vorhandenen Hostnamen aus der Hauptregel lesen, statt auf feste Namen zu
# vergleichen: Sonst greift das Skript nicht mehr, sobald eine Domain
# umbenannt oder entfernt wurde — und zwar lautlos.
HAUPT = "traefik.http.routers.buchhaltung.rule="
HEALTH = "traefik.http.routers.buchhaltung-health.rule="

hosts = []
for zeile in zeilen:
    if HAUPT in zeile:
        hosts = re.findall(r"Host\(`([^`]+)`\)", zeile)
        break

if not hosts:
    sys.exit("Keine Host()-Regel in docker-compose.yml gefunden")
if neuer_host not in hosts:
    hosts.append(neuer_host)

ausdruck = " || ".join(f"Host(`{h}`)" for h in hosts)
# Klammern sind Pflicht, sobald mehr als ein Host da ist: && bindet staerker
# als ||, ohne Klammern bedeutet die Health-Regel etwas ganz anderes.
geklammert = f"({ausdruck})" if len(hosts) > 1 else ausdruck

neu = []
for zeile in zeilen:
    einzug = zeile[: len(zeile) - len(zeile.lstrip())]
    if HAUPT in zeile:
        neu.append(f"{einzug}- {HAUPT}{ausdruck}\n")
    elif HEALTH in zeile:
        neu.append(f"{einzug}- {HEALTH}{geklammert} && Path(`/healthz`)\n")
    else:
        neu.append(zeile)

open(pfad, "w", encoding="utf-8").writelines(neu)
PY
    grep -c "$NEUER_HOST" "$COMPOSE" > /dev/null && echo "  ✓ eingetragen (Sicherung: docker-compose.yml.bak)"
fi

echo "▸ 3/4  Ausrollen"
"$PROJEKT/deploy/deploy.sh" | tail -3

echo "▸ 4/4  Auf das Zertifikat warten (Let's Encrypt braucht einen Moment)"
for versuch in $(seq 1 20); do
    if curl -fsS --max-time 8 "https://$NEUER_HOST/healthz" >/dev/null 2>&1; then
        echo "  ✓ https://$NEUER_HOST antwortet mit gültigem Zertifikat"
        echo
        echo "Fertig. Das Dashboard ist unter diesen Adressen erreichbar:"
        grep -oE 'routers\.buchhaltung\.rule=.*' "$COMPOSE" \
            | grep -oE '`[^`]+`' | tr -d '`' | sed 's|^|  · https://|'
        exit 0
    fi
    sleep 6
done

echo "✗ Nach zwei Minuten noch kein gültiges Zertifikat." >&2
echo "  Traefik-Log ansehen:" >&2
echo "  ssh -i $SSH_KEY $SERVER 'docker logs \$(docker ps -qf name=traefik) --tail 40'" >&2
exit 1
