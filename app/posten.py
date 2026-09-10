"""Ein Posten ist die kleinste Einheit auf dem Dashboard.

Jede Quelle liefert dieselbe Form, damit die Oberflaeche nur EINE Zeile
zeichnen muss — egal ob dahinter eine Bank, ein Postfach oder der Kalender
steckt. Was quellenspezifisch ist, wandert nach `zusatz` und wird dort
allenfalls als Beiwerk angezeigt.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime

# Ampel: was die Farbe bedeutet
#   rot     — liegen lassen kostet Geld oder Ruf (ueberfaellig, dringend, neu&offen)
#   gelb    — heute anschauen
#   blau    — zur Kenntnis, kein Handlungsbedarf
#   gruen   — erledigt / stimmt
RANG = {"rot": 3, "gelb": 2, "blau": 1, "gruen": 0, "": 0}


def posten(kennung, titel, ampel="blau", betrag=None, datum=None,
           text="", marke="", link=None, zusatz=None) -> dict:
    """Baut einen Posten. `kennung` muss innerhalb der Quelle stabil sein —
    aus ihr entsteht der Schluessel fuer "erledigt" und die Notiz."""
    return {
        "id": str(kennung),
        "titel": (titel or "").strip()[:200],
        "text": (text or "").strip()[:300],
        "marke": marke,          # Pille rechts: "Dringend", "Heute", "Offen" …
        "ampel": ampel,
        "betrag": betrag,
        "datum": datum,          # ISO (YYYY-MM-DD oder voll) — fuer Sortierung
        "link": link,
        "zusatz": zusatz or {},
    }


def hash_id(*teile) -> str:
    """Stabile Kennung fuer Posten, die von sich aus keine haben.

    Der Bank-Abgleich etwa liefert nur art/beleg/datum/betrag. Aendert eine
    dieser vier Angaben, gilt der Posten als neu und taucht wieder auf — das
    ist gewollt: es ist dann ein anderer Sachverhalt.
    """
    roh = "|".join("" if t is None else str(t) for t in teile)
    return hashlib.sha1(roh.encode("utf-8")).hexdigest()[:16]


def schlimmste(posten_liste) -> str:
    """Die schlechteste Ampel einer Liste — faerbt den Punkt am Kartenkopf."""
    schlecht = ""
    for p in posten_liste:
        if RANG.get(p.get("ampel", ""), 0) > RANG.get(schlecht, 0):
            schlecht = p.get("ampel", "")
    return schlecht or "gruen"


def als_datum(wert):
    """Nimmt ISO-Text oder date/datetime und gibt ein `date` zurueck (oder None)."""
    if not wert:
        return None
    if isinstance(wert, datetime):
        return wert.date()
    if isinstance(wert, date):
        return wert
    text = str(wert)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def tage_alt(wert, heute=None) -> int | None:
    """Wie viele Tage liegt das zurueck? Negativ = liegt in der Zukunft."""
    d = als_datum(wert)
    if d is None:
        return None
    return ((heute or date.today()) - d).days


def sortieren(posten_liste) -> list:
    """Dringendstes zuerst, danach das Aelteste — so liest die Person von oben nach
    unten ab, ohne selbst zu sortieren."""
    def schluessel(p):
        datum = p.get("datum") or "9999-99-99"
        return (-RANG.get(p.get("ampel", ""), 0), str(datum))
    return sorted(posten_liste, key=schluessel)


def bestand_aus(posten_liste, stamm=None, gruppe=None) -> list:
    """Der Bestand einer Quelle fuer die Erkennung im Tagesfortschritt.

    Ein Posten, der offen war und beim naechsten Abruf fehlt, gilt als
    erledigt — dafuer braucht die Erkennung die **ganze** offene Menge, nicht
    nur die zwanzig, die auf der Karte stehen. Quellen mit Anzeigeschnitt
    (Rechnungen, Shop) rufen das hier deshalb mit ihrer vollen Liste auf.

    `stamm` liefert die Kennung ohne Zustandsanteil: Beim Widerruf steckt der
    Status im Schluessel, und ein Statuswechsel ist kein Erledigen. `gruppe`
    ordnet den Eintrag einer Teilmenge zu (Postfach, Datei), damit ein
    ausgefallener Teil nicht als „alles erledigt" durchgeht.
    """
    ergebnis = []
    for p in posten_liste:
        ergebnis.append({
            "kennung": p["id"],
            "stamm": str(stamm(p)) if stamm else p["id"],
            "titel": p.get("titel") or "",
            "datum": p.get("datum"),
            "gruppe": str(gruppe(p)) if gruppe else "",
            "erledigt": False,
        })
    return ergebnis
