"""Erledigtes erkennen, ohne dass jemand einen Haken setzt.

Der Tagesfortschritt fragt nicht mehr „was hat die Person abgehakt", sondern „was
war heute offen und ist es jetzt nicht mehr". Ein Todo, das in Todomaster
erledigt wurde, ein geschlossener Superchat, eine bezahlte Rechnung, eine
beantwortete oder wegsortierte Mail — all das verschwindet aus seiner Quelle,
und genau dieses Verschwinden ist das Signal.

**Der Vergleich laeuft beim Abruf, nicht beim Seitenaufruf.** Nur dort liegt
der alte Stand noch neben dem neuen. `erkennen()` ist eine reine Funktion
ueber zwei Abruf-Ergebnisse; `nach_abruf()` schreibt das Ergebnis weg.

**Die Regeln gegen Fehlalarme sind der eigentliche Inhalt dieses Moduls.**
Verschwinden hat viele Gruende, die nichts mit Erledigen zu tun haben: ein
geloeschtes Postfach, ein Seitenlimit, eine Mail, die aus dem 14-Tage-Fenster
faellt, ein Widerruf, der nur seinen Status wechselt. Jede dieser Faellen
hat unten eine eigene Regel. Lieber einen Treffer verpassen als einen
erfinden — ein verpasster Treffer ist ein Haken, den die Person noch setzen kann;
ein erfundener ist eine Zahl, der niemand mehr traut.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from . import db

log = logging.getLogger("buchhaltung")

# Ab wann ein Massenverschwinden nach Quellen-Reset aussieht statt nach Arbeit.
# So gewaehlt, dass 15 von 25 archivierte Mails noch zaehlen — das ist ein
# normaler Vormittag —, eine still verkuerzte Liste mit 90 fehlenden Zeilen
# aber nicht.
RESET_AB_ANZAHL = 20
RESET_AB_ANTEIL = 0.5
# Eine ploetzlich leere Liste ist verdaechtig, sobald vorher mehr als ein
# paar Posten drin standen. Zwei letzte Mails darf die Person wegsortieren.
LEER_VERDAECHTIG_AB = 3


def bestand(daten: dict) -> list:
    """Den Bestand eines Abruf-Ergebnisses normalisieren.

    Liefert die Quelle keinen eigenen `bestand`, gelten die angezeigten
    Posten als Bestand — das ist fuer vollstaendig gelesene Quellen (Todos,
    Superchat, Widerrufe) richtig und fuer alle anderen die konservative
    Wahl.
    """
    roh = daten.get("bestand")
    if roh is None:
        roh = [{"kennung": p.get("id"), "titel": p.get("titel"),
                "datum": p.get("datum")} for p in (daten.get("posten") or [])]
    ergebnis = []
    for e in roh:
        kennung = str(e.get("kennung") or "")
        if not kennung:
            continue
        ergebnis.append({
            "kennung": kennung,
            "stamm": str(e.get("stamm") or kennung),
            "titel": (e.get("titel") or "")[:120],
            "datum": (e.get("datum") or None),
            "gruppe": str(e.get("gruppe") or ""),
            "erledigt": bool(e.get("erledigt")),
        })
    return ergebnis


def erkennen(quelle: str, alt: dict | None, alt_stand: str, neu: dict,
             heute: date | None = None) -> tuple:
    """Vergleicht zwei Abrufe. Gibt `(erledigt, wieder_offen, grund)` zurueck.

    `erledigt` sind Bestandseintraege, `wieder_offen` Kennungen, `grund` ist
    gesetzt, wenn bewusst NICHT verglichen wurde — dann sind die Listen leer.
    """
    heute = heute or date.today()
    if alt is None:
        return [], [], "keine Grundlinie"
    # Der erste Abruf des Tages vergleicht gegen gestern Abend. Alles, was
    # ueber Nacht oder uebers Wochenende verschwand, wuerde sonst als heutige
    # Arbeit gezaehlt, bevor die Person angefangen hat.
    if (alt_stand or "")[:10] != heute.isoformat():
        return [], [], "Grundlinie nicht von heute"
    sperre = neu.get("diff_sperre")
    if sperre:
        return [], [], str(sperre)

    neu_b = bestand(neu)
    alt_b = bestand(alt)
    if not neu_b and neu.get("hinweis"):
        return [], [], "leer mit Hinweis"

    alt_offen = [e for e in alt_b if not e["erledigt"]]
    neu_staemme = {e["stamm"] for e in neu_b}
    neu_gruppen = neu.get("gruppen")
    alt_gruppen = alt.get("gruppen")
    fenster = neu.get("fenster_tage")
    kante = None
    if fenster:
        # Was am Rand des Fensters liegt, faellt beim naechsten Abruf von
        # allein heraus — das ist Kalender, nicht Arbeit.
        kante = (heute - timedelta(days=int(fenster) - 1)).isoformat()

    verschwunden = []
    for e in alt_offen:
        if e["stamm"] in neu_staemme:
            continue
        if neu_gruppen is not None and e["gruppe"] not in neu_gruppen:
            continue
        if kante and e["datum"] and str(e["datum"])[:10] <= kante:
            continue
        verschwunden.append(e)

    if not neu_b and len(alt_offen) >= LEER_VERDAECHTIG_AB:
        return [], [], f"Liste ploetzlich leer ({len(alt_offen)} vorher) — Reset?"
    if (len(verschwunden) >= RESET_AB_ANZAHL
            and len(verschwunden) > RESET_AB_ANTEIL * len(alt_offen)):
        return [], [], (f"{len(verschwunden)} von {len(alt_offen)} auf einmal "
                        f"weg — Reset?")

    alt_kennungen = {e["kennung"] for e in alt_b}
    alt_offen_kennungen = {e["kennung"] for e in alt_offen}
    beantwortet = []
    for e in neu_b:
        if not e["erledigt"]:
            continue
        if e["kennung"] in alt_offen_kennungen:
            beantwortet.append(e)
        elif (e["kennung"] not in alt_kennungen
              and (alt_gruppen is None or e["gruppe"] in alt_gruppen)):
            # Kam heute an und wurde gleich beantwortet. Aber nur, wenn das
            # Postfach schon beim letzten Mal gelesen wurde — ein frisch
            # angelegtes Postfach bringt alte beantwortete Mails mit, und
            # die hat heute niemand bearbeitet.
            beantwortet.append(e)

    wieder_offen = [e["kennung"] for e in neu_b
                    if not e["erledigt"] and e["kennung"] not in alt_kennungen]
    return verschwunden + beantwortet, wieder_offen, None


def nach_abruf(quelle: str, alt: dict | None, alt_stand: str, neu: dict) -> int:
    """Nach einem erfolgreichen Abruf: vergleichen, wegschreiben, loggen.
    Gibt die Zahl neu erkannter Erledigungen zurueck."""
    erledigt, wieder_offen, grund = erkennen(quelle, alt, alt_stand, neu)
    if grund:
        log.info("%s: keine Erkennung — %s", quelle, grund)
        return 0
    if wieder_offen:
        weg = db.verlauf_entfernen(f"{quelle}:{k}" for k in wieder_offen)
        if weg:
            log.info("%s: %d wieder offen, aus dem Verlauf genommen", quelle, weg)
    neu_gezaehlt = []
    for e in erledigt:
        if db.verlauf_setzen(f"{quelle}:{e['kennung']}", quelle, "quelle", e["titel"]):
            neu_gezaehlt.append(e["titel"][:40] or e["kennung"])
    if neu_gezaehlt:
        log.info("%s: %d von selbst erledigt erkannt: %s",
                 quelle, len(neu_gezaehlt), "; ".join(neu_gezaehlt))
    return len(neu_gezaehlt)
