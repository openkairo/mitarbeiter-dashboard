#!/usr/bin/env bash
# Prueft die Dollarzeichen-Falle: In einer .env, die Docker Compose liest, muss
# jedes "$" verdoppelt sein — und im Ersetzungstext einer Bash-Ersetzung muss
# jedes davon maskiert sein, weil "$$" sonst die Prozess-ID ist.
#
#   ./deploy/pruef-dollar.sh
#
# Der Test zeigt bewusst BEIDE Richtungen: Er weist zuerst nach, dass die alte
# Schreibweise den Fehler wirklich erzeugt. Ein Test, der nur den Gutfall
# vorfuehrt, beweist nichts — er wuerde auch dann gruen melden, wenn er die
# falsche Stelle prueft.
#
# Alle Hashes hier sind erfunden. Es gehoert kein echter Hash ins Repo.

set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.."

HASH='$apr1$Testsalz$ErfundenerHashOhneEchtenWert'
fehler=0
ok()  { echo "  ✓ $1"; }
bad() { echo "  ✗ $1"; fehler=1; }

echo "1) Gegenprobe — die alte Schreibweise muss den Fehler zeigen"
ALT="${HASH//$/$$}"
if [[ "$ALT" == *"$$"* && "$ALT" != *'$'* ]]; then
    ok "alte Fassung schreibt die PID statt der Dollarzeichen: $ALT"
else
    bad "Fehler nicht reproduziert — dieser Test taugt dann nichts: $ALT"
fi

echo "2) Die maskierte Schreibweise"
NEU="${HASH//\$/\$\$}"
if [[ "$NEU" == '$$apr1$$Testsalz$$ErfundenerHashOhneEchtenWert' ]]; then
    ok "verdoppelt korrekt: $NEU"
else
    bad "falsches Ergebnis: $NEU"
fi

echo "3) Was tatsaechlich in den Skripten steht"
for datei in install.sh deploy/zugang-anlegen.sh; do
    zeile="$(grep -n 'openssl passwd -apr1' -A 12 "$datei" | grep -m1 '//.*\$.*}' || true)"
    if [[ "$zeile" == *'//\$/\$\$'* ]]; then
        ok "$datei maskiert beide Dollarzeichen"
    else
        bad "$datei: ${zeile:-keine Ersetzung gefunden}"
    fi
done

echo "4) Keine weitere Stelle derselben Art im Repo"
# Gesucht ist nicht jedes "$$" — in Kommentaren und in Anfuehrungszeichen ist
# es harmlos —, sondern ein unmaskiertes "$$" im Ersetzungstext einer
# Bash-Ersetzung oder eines sed-Aufrufs. Genau dort wird daraus die Prozess-ID.
# git grep, weil grep hier je nach Rechner ugrep ist und dann uebergebene
# Dateilisten stillschweigend nicht durchsucht.
suche() {
    git grep -nE '\$\{[A-Za-z_][A-Za-z_0-9]*//[^}]*[^\\]\$\$|sed [^|]*[^\\]\$\$' \
        -- '*.sh' '*.yml' '*.py' "$@" | grep -v 'pruef-dollar.sh' || true
}
treffer="$(suche)"
if [[ -z "$treffer" ]]; then
    ok "keine unmaskierte Verdoppelung sonstwo"
else
    bad "nachsehen: $treffer"
fi

# Gegenprobe: Findet dieses Muster den bekannten Fehler ueberhaupt? Ohne diese
# Zeile hiesse "keine Treffer" vielleicht nur "falsches Muster".
probe="$(printf 'HASH_ENV="${HASH//$/$$}"\n' | grep -cE '\$\{[A-Za-z_][A-Za-z_0-9]*//[^}]*[^\\]\$\$')"
if [[ "$probe" == "1" ]]; then
    ok "das Suchmuster erkennt die alte Zeile — die Freimeldung oben zaehlt"
else
    bad "das Suchmuster findet nicht einmal den bekannten Fehler"
fi

echo "5) Erkennung bereits kaputter .env-Eintraege"
# Nur die Funktion herausschneiden, das Skript selbst wuerde eine .env wollen.
eval "$(sed -n '/^hash_befund() {/,/^}/p' deploy/zugang-anlegen.sh)"
hash_befund '$$apr1$$Salz$$Hash'      >/dev/null && ok "guter Hash gilt als gut"          || bad "guter Hash faelschlich bemaengelt"
hash_befund '4711apr14711Salz4711Ha'  >/dev/null && bad "PID-Schaden nicht erkannt"       || ok "PID-Schaden erkannt"
hash_befund '$apr1$Salz$Hash'         >/dev/null && bad "unverdoppelt nicht erkannt"      || ok "unverdoppelt erkannt"

echo
if [[ $fehler -eq 0 ]]; then echo "Alles gruen."; else echo "Fehlgeschlagen."; fi
exit $fehler
