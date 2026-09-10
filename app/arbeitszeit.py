"""Wann soll das Dashboard ueberhaupt Daten holen?

Vorher lief jeder Takt rund um die Uhr — auch nachts um drei, wenn niemand
hinsieht. Die Superchat-Karte allein sind 246 Aufrufe je Lauf; bei zehn
Minuten waren das rund 35.000 Aufrufe am Tag fuer eine Seite, die jemand ein
paar Stunden am Tag benutzt.

Entscheidung des Betreibers, 09.09.2026: **Nur waehrend der Arbeitszeit, alle
halbe Stunde** — und immer dann, wenn tatsaechlich jemand die Seite offen hat.
Der zweite Teil ist wichtig: Sonst saehe man abends um elf die Zahlen vom
Nachmittag, ohne zu merken, dass sie alt sind.

Die Zeiten stehen hier und nicht im Kalender. Das ist Absicht: Wenn die Takte
ruhen, laeuft auch die Kalender-Karte nicht — sie koennte also gar nicht
melden, dass die Person wieder da ist. Ein Henne-Ei-Problem, das eine feste Tabelle
nicht hat. Urlaub kommt trotzdem aus dem Kalender, aber aus dem **zuletzt
geholten** Stand.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from . import db, profil

log = logging.getLogger("buchhaltung.arbeitszeit")

ZONE = ZoneInfo("Europe/Berlin")

# Format "Mo 8:00-15:15, Di 13:20-18:00, ..." — ohne Eintrag gibt es kein
# Mi 8 Std, Do frei, Fr nach Absprache ab 14:30. Jede Instanz setzt ihre
# eigenen per ARBEITSZEITEN in der .env,
# Format "Mo 8:00-15:15, Di 13:20-18:00, ..." — damit eine geaenderte
# Arbeitszeit kein Deploy braucht.
# Keine Vorgabe: Die Arbeitszeit eines Menschen gehoert nicht in den
# Quelltext. Ohne ARBEITSZEITEN gibt es kein Zeitfenster — dann holen die
# Takte rund um die Uhr, was hoechstens etwas Verkehr kostet. Ein
# erfundener Plan waere schlimmer: Er wuerde Abrufe verhindern, ohne dass
# jemand ahnt, warum die Zahlen alt sind.
STANDARD = ""
TAGE = {"mo": 0, "di": 1, "mi": 2, "do": 3, "fr": 4, "sa": 5, "so": 6}

# Etwas vor Schichtbeginn anfangen, damit die Zahlen stehen, wenn jemand die
# Seite aufmacht — und nicht erst eine halbe Stunde spaeter.
VORLAUF = timedelta(minutes=30)

# So lange nach dem letzten Seitenaufruf gilt "jemand schaut hin".
BESUCH_GILT = timedelta(minutes=10)


def _uhrzeit(roh: str) -> time:
    """"8:00" lesen koennen, nicht nur "08:00".

    `time.fromisoformat` besteht auf zwei Stellen. Ohne diese Zeile fielen am
    09.09.2026 Montag und Mittwoch stillschweigend aus dem Plan — ausgerechnet
    volle Tage, und das Dashboard haette an ihnen nie abgerufen. Es stand
    nur eine WARN-Zeile im Log.
    """
    roh = roh.strip()
    stunde, _, rest = roh.partition(":")
    return time.fromisoformat(f"{int(stunde):02d}:{(rest or '00').strip()}")


def _plan() -> dict:
    plan: dict[int, list] = {}
    roh = os.environ.get("ARBEITSZEITEN", "").strip() or STANDARD
    for stueck in roh.split(","):
        stueck = stueck.strip()
        if not stueck:
            continue
        try:
            tag, spanne = stueck.split(None, 1)
            von, bis = spanne.split("-")
            nummer = TAGE[tag.strip().lower()[:2]]
            plan.setdefault(nummer, []).append((_uhrzeit(von), _uhrzeit(bis)))
        except (ValueError, KeyError):
            log.warning("WARN Arbeitszeit unlesbar: %r — wird übersprungen", stueck)
    return plan


PLAN = _plan()


def _urlaub_bis():
    """Letzter bekannter Abwesenheitstag aus dem zuletzt geholten Kalender."""
    try:
        daten = db.cache_lesen("kalender")["daten"] or {}
        stand = daten.get("person") or {}
        bis = stand.get("abwesend_bis")
        return datetime.fromisoformat(bis).date() if bis else None
    except (ValueError, TypeError, KeyError):
        return None


def arbeitet(jetzt: datetime | None = None) -> bool:
    jetzt = jetzt or datetime.now(ZONE)
    urlaub = _urlaub_bis()
    if urlaub and jetzt.date() <= urlaub:
        return False
    for von, bis in PLAN.get(jetzt.weekday(), []):
        beginn = (datetime.combine(jetzt.date(), von, tzinfo=ZONE) - VORLAUF).time()
        if beginn <= jetzt.time() <= bis:
            return True
    return False


def besuch_merken() -> None:
    db.kv_schreiben("letzter_besuch", datetime.now(ZONE).isoformat(timespec="seconds"))


def wird_geschaut(jetzt: datetime | None = None) -> bool:
    roh = db.kv_lesen("letzter_besuch", "")
    if not roh:
        return False
    try:
        letzter = datetime.fromisoformat(roh)
    except ValueError:
        return False
    return (jetzt or datetime.now(ZONE)) - letzter < BESUCH_GILT


def soll_holen() -> tuple[bool, str]:
    """(darf abrufen, Begruendung fuers Log und die Seite)"""
    # Ohne hinterlegten Plan gibt es kein Zeitfenster, das man verpassen
    # koennte — dann wird immer geholt. Ein leerer Plan darf nicht als
    # „nie arbeiten“ gelesen werden, sonst stuenden die Karten still und
    # niemand fände den Grund.
    if not PLAN:
        return True, "keine Arbeitszeit hinterlegt — es wird immer geholt"
    if wird_geschaut():
        return True, "jemand schaut auf die Seite"
    if arbeitet():
        return True, ("Arbeitszeit von " + profil.NAME) if profil.NAME else "Arbeitszeit"
    return False, "außerhalb der Arbeitszeit, niemand auf der Seite"
