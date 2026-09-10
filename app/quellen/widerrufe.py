"""Widerrufe aus dem Shop und Shop-Rechnungen, die Lexware abgelehnt hat.

Zwei Themen in einer Karte, weil beide dieselbe Handlung verlangen: die Person muss
in Lexware etwas von Hand nachziehen.

  * **Widerruf** — `state.json` im gemounteten Ordner fuehrt nur Bestellnummer und
    gemeldeten Status. Name und Betrag holt diese Quelle deshalb aus dem Shop
    nach; faellt der Shop aus, bleibt die Nummer stehen (besser knapp als leer).
  * **Lexware-Rueckstand** — `lexware_gruende.json` im Watchdog-Ordner sind Shop-
    Rechnungen, die der Sync nicht anlegen konnte (fehlender PV-Haken am
    Artikel). Ein erneuter Sync hilft nicht, sie muessen von Hand entstehen.
    Absichtlich aus der Gruende-Datei und nicht aus dem Watchdog-Status: der
    schaut nur 45 Tage zurueck und meldet irgendwann "alles gut", waehrend der
    Stapel liegen bleibt.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .. import wooshop
from ..posten import bestand_aus, posten, sortieren, tage_alt

NAME = "widerrufe"
TITEL = "Widerrufe & Lexware-Rückstand"
ICON = "↩️"
TTL = 300
ANLAUF = 4
# Der Link in die Shop-Verwaltung entsteht aus WP_URL — eine feste Adresse
# hier waere die eines fremden Shops.
LINK = None
LINK_TEXT = "Shop"
KOPFZAHL = ("Widerrufe", "Rückstand", "Lexware-Rückstand")

WIDERRUF = Path(os.environ.get("WIDERRUF_ORDNER", "/daten/widerruf"))
WATCHDOG = Path(os.environ.get("WATCHDOG_ORDNER", "/daten/watchdog"))

STATUS_TEXT = {"pending-wdraw": ("Widerruf angemeldet", "rot"),
               "withdrawn": ("Widerrufen", "gelb")}


def _json(pfad: Path, standard):
    """Liest eine Datei — und sagt, ob das geklappt hat.

    Gibt `(inhalt, gelesen)` zurueck. Der zweite Wert zaehlt fuer die
    Erkennung: Eine Datei, die im Moment des `os.replace` gerade nicht
    lesbar ist, ist nicht leer, sondern abwesend. Waere das nicht
    unterscheidbar, gaelten alle Widerrufe fuer einen Takt als erledigt.
    """
    try:
        return json.loads(pfad.read_text(encoding="utf-8")), True
    except (OSError, json.JSONDecodeError):
        return standard, False


def eingerichtet(env: dict) -> bool:
    """Beide Haelften kommen aus gemounteten Dateien. Fehlt beides, gibt es
    hier nichts zu zeigen."""
    try:
        return (WIDERRUF / "state.json").exists() or (WATCHDOG / "lexware_gruende.json").exists()
    except OSError:
        return False

def fetch(env: dict) -> dict:
    liste = []
    hinweise = []

    # ------------------------------------------------------------ Widerrufe
    zustand, widerruf_gelesen = _json(WIDERRUF / "state.json", {})
    gemeldet = (zustand or {}).get("reported") or {}
    nummern = list(gemeldet.keys())
    details = {}
    if nummern:
        try:
            details = wooshop.nach_nummern(env.get("WP_URL"), env.get("WC_KEY"),
                                           env.get("WC_SECRET"), nummern)
        except Exception as fehler:                               # noqa: BLE001
            hinweise.append(f"Shop-Details nicht erreichbar ({fehler}).")

    for nummer in nummern:
        status_liste = gemeldet.get(nummer) or []
        letzter = status_liste[-1] if status_liste else ""
        marke, ampel = STATUS_TEXT.get(letzter, (letzter or "Widerruf", "gelb"))
        b = details.get(str(nummer)) or {}
        betrag = None
        try:
            betrag = float(b.get("total")) if b.get("total") is not None else None
        except (TypeError, ValueError):
            betrag = None
        liste.append(posten(
            kennung=f"widerruf-{nummer}-{letzter}",
            titel=(wooshop.name_aus(b) if b else f"Bestellung {nummer}"),
            ampel=ampel,
            betrag=betrag,
            datum=(b.get("date_created") or "")[:10] or None,
            text=f"Bestellung {nummer} · prüfen, erstatten, Gutschrift in Lexware",
            marke=marke,
            link=f"{env.get('WP_URL', '').rstrip('/')}/wp-admin/post.php?post={nummer}&action=edit",
            zusatz={"thema": "widerruf", "bestellung": nummer},
        ))

    # ------------------------------------------------------ Lexware-Rueckstand
    gruende, lexware_gelesen = _json(WATCHDOG / "lexware_gruende.json", {})
    gruende = gruende or {}
    for beleg, g in gruende.items():
        if not isinstance(g, dict):
            continue
        alter = tage_alt(g.get("datum"))
        liste.append(posten(
            kennung=f"lexgrund-{beleg}",
            titel=f"{beleg} nicht in Lexware",
            ampel="rot" if (alter or 0) > 30 else "gelb",
            betrag=g.get("betrag"),
            datum=g.get("datum"),
            text="Von Hand in Lexware anlegen — ein erneuter Sync hilft nicht.",
            marke="Rückstand",
            link=(f"{env.get('WP_URL', '').rstrip('/')}/wp-admin/post.php"
                  f"?post={g.get('bestellung')}&action=edit" if g.get("bestellung") else None),
            zusatz={"thema": "lexware", "grund": (g.get("grund") or "")[:200],
                    "bestellung": g.get("bestellung")},
        ))

    summe_rueckstand = sum(float(g.get("betrag") or 0) for g in gruende.values()
                           if isinstance(g, dict))
    def stamm(p):
        # Der Status steckt im Schluessel; ein Statuswechsel ist kein
        # Erledigen. Fuer den Vergleich zaehlt nur die Bestellnummer.
        if p["zusatz"].get("thema") == "widerruf":
            return f"widerruf-{p['zusatz'].get('bestellung')}"
        return p["id"]

    gruppen = [name for name, ok in (("widerruf", widerruf_gelesen),
                                     ("lexware", lexware_gelesen)) if ok]
    basis = (env.get("WP_URL") or "").rstrip("/")
    return {
        "posten": sortieren(liste),
        # Der Fusslink entsteht aus der eigenen Shop-Adresse.
        "link": f"{basis}/wp-admin/edit.php?post_type=shop_order" if basis else None,
        "bestand": bestand_aus(liste, stamm=stamm,
                               gruppe=lambda p: p["zusatz"].get("thema") or ""),
        "gruppen": gruppen,
        "kennzahlen": {
            "Widerrufe": len(nummern),
            "Rückstand": len(gruende),
            "Summe Rückstand": summe_rueckstand,
        },
        "hinweis": " ".join(hinweise) or None,
    }
