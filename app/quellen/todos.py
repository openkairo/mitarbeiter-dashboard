"""Aufgaben aus Todomaster.

**Mehrere Kategorien sind moeglich, nicht nur eine:** typisch das eigene
Fach (geteilt mit dem Team) und eine persoenliche Liste. Ohne die zweite
wuerde ein Todo, das jemand dort einstellt, auf dem eigenen Dashboard nie
auftauchen.

Alle anderen Kategorien sind fremde Arbeit und bleiben draussen. Welche
gelten, steht in `TODO_KATEGORIEN` — nichts davon im Quelltext.

Die Kategorien werden beim Abruf gegen `list_categories` geprueft. Eine falsche
Kennung filtert sonst still auf null Treffer, und die Karte behauptet "nichts zu
tun" — die gefaehrlichste Falschaussage auf diesem Dashboard.
"""

from __future__ import annotations

import os
from datetime import date

from .. import todomaster
from ..posten import als_datum, posten, sortieren

NAME = "todos"
TITEL = "Aufgaben"
ICON = "✅"
TTL = 180
ANLAUF = 6
# Wohin der Fusslink zeigt. Ohne Eintrag kein Link — eine fremde Adresse
# waere geraten. Gesetzt wird sie ueber TODOMASTER_WEB in der .env.
# Ohne diese Einstellungen kann die Karte nichts holen — dann erscheint
# sie gar nicht erst, statt „nichts zu tun“ zu behaupten.
BRAUCHT = ("TODOMASTER_URL", "TODOMASTER_TOKEN", "TODO_KATEGORIEN")

LINK = (os.environ.get("TODOMASTER_WEB") or "").strip() or None
LINK_TEXT = "Todomaster"
KOPFZAHL = ("Offen", "Überfällig", "überfällig")

# Keine Vorgabe: Welche Listen auf dieses Dashboard gehoeren, weiss nur,
# wer es einrichtet. Ohne Angabe bleibt die Karte leer und sagt das.
VORGABE_KATEGORIEN = ""


def _kategorien(env: dict) -> list:
    """Welche Listen diese Instanz zeigt.

    **Bei jedem Abruf neu aus der Umgebung**, nicht einmal beim Import: Sonst
    wirkte das Feld in den Einstellungen nie, und wer die Kategorie dort
    aenderte, saehe bis zum naechsten Neustart die alte Liste — ohne einen
    Hinweis, warum.
    """
    roh = (env.get("TODO_KATEGORIEN") or "").strip() or VORGABE_KATEGORIEN
    return [k.strip() for k in roh.split(",") if k.strip()]


def _pruefen(kategorien: list) -> tuple[list, str | None]:
    """(vorhandene der gewuenschten Kategorien, Warnung)"""
    try:
        bekannt = {k.get("id") for k in todomaster.kategorien()}
    except Exception:                                             # noqa: BLE001
        return kategorien, None        # kein Urteil moeglich — dann ungeprueft
    if not bekannt:
        return kategorien, None
    fehlend = [k for k in kategorien if k not in bekannt]
    gibt_es = [k for k in kategorien if k in bekannt]
    if fehlend:
        return gibt_es, (f"Kategorie „{', '.join(fehlend)}“ gibt es in Todomaster "
                         f"nicht (mehr) — wird übersprungen.")
    return gibt_es, None


def fetch(env: dict) -> dict:
    kategorien, warnung = _pruefen(_kategorien(env))
    heute = date.today()
    liste, faellig_heute, ueberfaellig = [], 0, 0
    gesehen = set()

    for kategorie in kategorien:
        for t in todomaster.todos(kategorie):
            if t.get("completed") or t.get("done") or t.get("status") == "completed":
                continue
            kennung = str(t.get("id") or t.get("title"))
            if kennung in gesehen:        # dieselbe Aufgabe in beiden Listen
                continue
            gesehen.add(kennung)

            frist = als_datum(t.get("dueDate") or t.get("due_date"))
            if frist and frist < heute:
                ampel, marke = "rot", f"seit {(heute - frist).days} Tagen fällig"
                ueberfaellig += 1
            elif frist and frist == heute:
                ampel, marke = "rot", "heute fällig"
                faellig_heute += 1
            elif frist and (frist - heute).days <= 7:
                ampel, marke = "gelb", f"fällig {frist.strftime('%d.%m.')}"
            elif frist:
                ampel, marke = "blau", f"fällig {frist.strftime('%d.%m.')}"
            else:
                ampel, marke = "blau", "ohne Frist"

            zusatz = {"kategorie": kategorie,
                      "von": t.get("createdBy") or t.get("created_by") or ""}
            if t.get("isRecurring"):
                zusatz["wiederkehrend"] = t.get("recurringInterval") or "ja"

            liste.append(posten(
                kennung=kennung,
                titel=str(t.get("title") or "Aufgabe"),
                ampel=ampel,
                # Sortiert wird nach Frist; ohne Frist zaehlt das Anlegedatum.
                datum=(frist.isoformat() if frist
                       else (t.get("createdAt") or t.get("created_at") or "")[:10] or None),
                text=str(t.get("description") or "")[:200],
                marke=marke,
                link=LINK,
                zusatz=zusatz,
            ))

    return {
        "posten": sortieren(liste),
        "kennzahlen": {"Offen": len(liste), "Heute fällig": faellig_heute,
                       "Überfällig": ueberfaellig},
        "hinweis": warnung,
        # Fehlt eine Kategorie, fehlen ihre Aufgaben — und die sind dann nicht
        # erledigt, sondern unsichtbar.
        "diff_sperre": warnung,
    }


# --------------------------------------------------------------- Rueckweg

def erledigt_setzen(kennung: str, an: bool, von: str, env: dict) -> None:
    """Der Haken auf dem Dashboard schreibt nach Todomaster zurueck.

    Das ist die einzige Karte, die das tut — bei allen anderen bleibt der Haken
    eine reine Notiz des Dashboards, weil es in Lexware und im Shop nichts zu
    "erledigen" gibt.

    **Wirft bei Misserfolg, und das ist Absicht.** Ginge der Aufruf still
    daneben, stuende die Aufgabe hier als erledigt und in Todomaster weiter
    offen — zwei Wahrheiten, und es faellt erst auf, wenn jemand nachfragt.
    Lieber bleibt der Haken aus und die Karte sagt, warum.

    `von` ist der Anmeldename aus der Basic-Auth; in Todomaster steht dann
    "erledigt von <Name>" statt "Dashboard".
    """
    if an:
        todomaster.erledigen(kennung, (von or "").capitalize())
    else:
        todomaster.wieder_oeffnen(kennung)
