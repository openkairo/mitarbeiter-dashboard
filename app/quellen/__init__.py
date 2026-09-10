"""Alle Datenquellen des Dashboards — eine Kachel je Modul.

Jedes Modul haelt sich an dieselbe Form:

    NAME, TITEL, ICON, TTL, ANLAUF, LINK, LINK_TEXT, KOPFZAHL
    fetch(env) -> {"posten": [...], "kennzahlen": {...}, "hinweis": str|None}

Damit muss die Oberflaeche nichts ueber Lexware, IMAP oder Superchat wissen —
und eine neue Karte ist eine Datei plus eine Zeile in ALLE.

**Werkzeug-Karten** (`ART = "werkzeug"`, heute nur die FAQ) sind die Ausnahme:
Sie holen nichts von selbst, sondern antworten auf eine Frage. Sie stehen im
Raster wie die anderen, haben aber keinen Takt, keinen Cache und keinen Haken.
Die Trennung ist wichtig, weil sonst ein Hintergrund-Faden fuer eine Karte
liefe, die gar nichts zu holen hat.

**Welche Karten erscheinen, entscheiden die Zugangsdaten.** Jedes Modul
nennt in `BRAUCHT`, ohne welche Einstellungen es nichts holen kann; wo eine
Datei oder ein Postfach noetig ist, entscheidet stattdessen ein eigenes
`eingerichtet(env)`. Wer den Zugang unter „Settings“ eintraegt, bekommt die
Karte — ohne Neustart und ohne dass jemand etwas am Code aendert. Bis dahin
steht sie unten in einer Zeile „noch nicht eingerichtet“ statt im Raster.

Das ist der Unterschied zwischen „hier ist nichts zu tun“ und „hier weiss
niemand etwas“. Eine Karte ohne Zugang, die „Nichts offen“ zeigt, ist die
gefaehrlichste Falschaussage auf einem Dashboard.

`KARTEN` in der .env bleibt daneben moeglich — als Auswahl und Reihenfolge
fuer den, der bewusst weniger zeigen will als er eingerichtet hat.
"""

import logging

from .. import profil
from . import (bank, faq, kalender, mail, rechnungen, shop, superchat, todos,
               widerrufe)

log = logging.getLogger("buchhaltung.quellen")

ALLE = [todos, mail, kalender, bank, superchat, rechnungen, widerrufe, shop, faq]
NACH_KENNUNG = {m.NAME: m for m in ALLE}


def _auswahl() -> list:
    gewaehlt = []
    for name in profil.KARTEN:
        modul = NACH_KENNUNG.get(name)
        if modul is None:
            log.warning("WARN Unbekannte Karte %r in KARTEN — übersprungen.", name)
            continue
        if modul not in gewaehlt:
            gewaehlt.append(modul)
    if not gewaehlt:
        # Lieber gar nicht starten als eine leere Seite zeigen: Ein Dashboard
        # ohne Karten sieht aus wie ein erledigter Tag.
        raise RuntimeError(
            "KARTEN ergibt keine einzige gültige Karte — bekannt sind: "
            + ", ".join(NACH_KENNUNG))
    return gewaehlt


_GEWAEHLT = _auswahl()

# Karten, die Posten holen: Takte, Cache, Haken, MCP-Werkzeug `karte`.
REGISTRY = [m for m in _GEWAEHLT if getattr(m, "ART", "posten") != "werkzeug"]
# Karten, die auf Zuruf antworten. Kein Takt, kein Cache.
WERKZEUGE = [m for m in _GEWAEHLT if getattr(m, "ART", "posten") == "werkzeug"]

NACH_NAME = {m.NAME: m for m in REGISTRY}
WERKZEUG_NACH_NAME = {m.NAME: m for m in WERKZEUGE}
# Alles, was diese Instanz zeigt — fuer "gibt es die Karte hier ueberhaupt?".
BEKANNT = dict(NACH_NAME, **WERKZEUG_NACH_NAME)


def _kopfzahlen() -> list:
    """Die Zahlen ganz oben, aus dem Profil.

    Eintrag `quelle` nimmt die Vorgabezahl des Moduls, `quelle:Kennzahl` eine
    bestimmte — so bekommt ein zweites Superchat-Postfach eine eigene Kachel,
    ohne dass es eine zweite Karte braucht.
    """
    ergebnis = []
    for eintrag in profil.KOPFZAHLEN:
        name, _, kennzahl = eintrag.partition(":")
        modul = NACH_NAME.get(name.strip())
        if modul is None:
            log.warning("WARN Kopfzahl %r zeigt auf keine aktive Karte.", eintrag)
            continue
        gross, warn, text = getattr(modul, "KOPFZAHL", ("Offen", "", ""))
        if kennzahl.strip():
            # Eine bestimmte Kennzahl hat keine eigene Warnzeile — sie ist ein
            # Ausschnitt, kein Gesamtbild.
            ergebnis.append((modul.NAME, kennzahl.strip(), "", "", kennzahl.strip()))
        else:
            ergebnis.append((modul.NAME, gross, warn, text, None))
    return ergebnis


KOPFZAHLEN = _kopfzahlen()


def ist_eingerichtet(modul, umgebung: dict) -> bool:
    """Kann diese Karte ueberhaupt etwas holen?

    Vorgabe: alle Schluessel aus `BRAUCHT` sind gefuellt. Module, deren
    Voraussetzung keine Einstellung ist (ein gemounteter Ordner, ein
    angelegtes Postfach), bringen ihr eigenes `eingerichtet(env)` mit.
    """
    eigen = getattr(modul, "eingerichtet", None)
    if eigen is not None:
        try:
            return bool(eigen(umgebung))
        except Exception:                                      # noqa: BLE001
            # Im Zweifel anzeigen: Eine Karte zu verstecken, weil die
            # Pruefung stolpert, waere schlimmer als eine Karte zu viel.
            return True
    noetig = getattr(modul, "BRAUCHT", ())
    if not noetig:
        return True
    return all((umgebung.get(s) or "").strip() for s in noetig)


def pruefen(name: str, umgebung: dict) -> tuple:
    """Verbindung einer Karte testen — fuer Settings und den MCP-Zugang.

    Gibt `(ok, meldung, hinweis)` zurueck; der Name muss in BEKANNT stehen.
    Posten-Karten holen einmal ab,
    Werkzeug-Karten fragen ihr Werkzeug. Fehler werden hier gefangen: Ein
    Verbindungstest, der die Seite mitreisst, prueft nichts.
    """
    modul = BEKANNT[name]
    try:
        if hasattr(modul, "pruefen"):
            ok, meldung = modul.pruefen(umgebung)
            return ok, meldung, None
        # Bewusst der **echte** Abruf des Moduls und kein eigener Testaufruf:
        # Sonst prueft man am Ende etwas anderes, als die Karte spaeter tut.
        ergebnis = modul.fetch(umgebung)
    except Exception as fehler:                                   # noqa: BLE001
        return False, f"{type(fehler).__name__}: {fehler}"[:300], None
    anzahl = len(ergebnis.get("posten") or [])
    return True, f"{anzahl} Einträge geladen.", ergebnis.get("hinweis")
