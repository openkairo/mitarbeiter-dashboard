"""Bank-Abgleich — Zahlungseingaenge, zu denen noch Arbeit ansteht.

Liest den Tagesbericht einer Bank-Abgleich-Automation aus dem gemounteten
Ordner (BANK_ORDNER),
der um 10:00 entsteht. Kein eigener Bankzugriff: PSD2 erlaubt nur rund vier
Abrufe am Tag, die verbraucht der Abgleich selbst.

Drei Arten, so wie sie das Skript vergibt:
    fehlt       Geld da, aber nur ein Angebot/eine AB — Rechnung erzeugen
    zuordnen    Rechnung da, Zahlung noch nicht zugeordnet
    kein_beleg  Geld da, in Lexware nichts dazu gefunden
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..posten import hash_id, posten, sortieren

NAME = "bank"
TITEL = "Bank-Abgleich"
ICON = "🏦"
TTL = 300
ANLAUF = 0
LINK = "https://app.lexoffice.de/permanent/vouchers"
LINK_TEXT = "Lexware"
KOPFZAHL = ("Posten", "Rechnung fehlt", "ohne Rechnung")
# Keine Erkennung im Tagesfortschritt. Der Bericht entsteht einmal am Tag um
# 10:15 — was die Person gestern Nachmittag zugeordnet hat, verschwindet erst mit
# dem heutigen Bericht und stuende dann als heutige Arbeit im Ring, bevor sie
# angefangen hat. Hier bleibt der Haken der Weg. (entschieden am 10.09.2026)
ERKENNUNG = False

ORDNER = Path(os.environ.get("BANK_ORDNER", "/daten/bank"))

BESCHRIFTUNG = {
    "fehlt": ("Rechnung fehlt", "rot"),
    "zuordnen": ("Zahlung zuordnen", "gelb"),
    "kein_beleg": ("Kein Treffer", "gelb"),
}


def _neuester_bericht() -> Path | None:
    """Der juengste Tagesbericht. Nach Dateiname, nicht nach mtime — die
    Berichte heissen YYYY-MM-DD.json und sortieren sich damit selbst."""
    berichte = sorted(ORDNER.glob("reports/*.json"))
    return berichte[-1] if berichte else None


def eingerichtet(env: dict) -> bool:
    """Der Abgleich kommt aus einem gemounteten Ordner, nicht aus einem
    Schluessel. Ohne Berichte gibt es die Karte nicht."""
    try:
        return (ORDNER / "reports").is_dir() and any((ORDNER / "reports").glob("*.json"))
    except OSError:
        return False

def fetch(env: dict) -> dict:
    datei = _neuester_bericht()
    if datei is None:
        return {"posten": [], "kennzahlen": {},
                "hinweis": f"Noch kein Bericht in {ORDNER}/reports — laeuft der "
                           f"Bank-Abgleich auf diesem Server?"}

    roh = json.loads(datei.read_text(encoding="utf-8") or "[]")
    liste = []
    summe = 0.0
    for p in roh:
        art = p.get("art") or "kein_beleg"
        marke, ampel = BESCHRIFTUNG.get(art, (art, "gelb"))
        tage = p.get("tage")
        # Was eine Woche liegt, ist kein Tagesgeschaeft mehr.
        if isinstance(tage, int) and tage >= 7 and ampel == "gelb":
            ampel = "rot"
        betrag = float(p.get("betrag") or 0)
        summe += betrag
        kunde = (p.get("kunde") or "").strip()
        beleg = (p.get("beleg") or "").strip()
        liste.append(posten(
            kennung=hash_id(art, p.get("datum"), betrag, beleg, kunde),
            titel=kunde if kunde and kunde != "?" else (beleg or "Zahlungseingang"),
            ampel=ampel,
            betrag=betrag,
            datum=p.get("datum"),
            text=beleg if kunde and kunde != "?" else "",
            marke=marke,
            link=LINK,
            zusatz={"art": art, "tage": tage, "typ": p.get("typ") or ""},
        ))

    zaehler = {}
    for p in roh:
        art = p.get("art") or "kein_beleg"
        zaehler[art] = zaehler.get(art, 0) + 1

    return {
        "posten": sortieren(liste),
        "kennzahlen": {
            "Posten": len(liste),
            "Summe": summe,
            "Rechnung fehlt": zaehler.get("fehlt", 0),
        },
        "hinweis": None,
        "stand_datei": datei.stem,
    }
