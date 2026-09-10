"""Lesender Zugriff auf den WooCommerce-Shop.

Uebernommen aus einem aelteren Werkzeug und um die Statusabfrage erweitert.
Zugangsdaten sind **nicht neu**: `WP_URL`/`WC_KEY`/`WC_SECRET` gehoeren der
Blog-Automation unter /opt/yt-automation/app/.env und werden hier mitbenutzt.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 45
BUENDEL = 100          # WooCommerce laesst hoechstens 100 Datensaetze je Seite zu


class ShopFehler(Exception):
    pass


def _abrufen(basis: str, key: str, secret: str, pfad: str, params: dict):
    if not (basis and key and secret):
        raise ShopFehler("WP_URL, WC_KEY oder WC_SECRET fehlen in der .env")
    url = (basis.rstrip("/") + "/wp-json/wc/v3" + pfad
           + "?" + urllib.parse.urlencode(params, doseq=True))
    req = urllib.request.Request(url)
    # Basic-Auth statt Parameter in der Adresse: sonst stuenden die
    # Zugangsdaten in jedem Server- und Proxy-Protokoll.
    marke = base64.b64encode(f"{key}:{secret}".encode()).decode()
    req.add_header("Authorization", "Basic " + marke)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as antwort:
            return json.loads(antwort.read().decode())
    except urllib.error.HTTPError as err:
        text = err.read().decode(errors="replace")[:300]
        raise ShopFehler(f"HTTP {err.code} bei {pfad}: {text}") from err
    except urllib.error.URLError as err:
        raise ShopFehler(f"Netzwerkfehler bei {pfad}: {err}") from err


FELDER = "id,number,status,date_created,total,currency,billing,payment_method_title"


def nach_status(basis, key, secret, status: str, grenze: int = 300) -> list:
    """Alle Bestellungen in den genannten Status (kommagetrennt), neueste zuerst."""
    alle: list = []
    for seite in range(1, (grenze // BUENDEL) + 2):
        teil = _abrufen(basis, key, secret, "/orders", {
            "status": status, "per_page": BUENDEL, "page": seite,
            "orderby": "date", "order": "desc", "_fields": FELDER,
        })
        if not isinstance(teil, list) or not teil:
            break
        alle.extend(teil)
        if len(teil) < BUENDEL or len(alle) >= grenze:
            break
    return alle


def nach_nummern(basis, key, secret, nummern) -> dict:
    """{Bestellnummer: Bestellung} — gebuendelt, nicht einzeln.

    Eine Einzelabfrage braucht rund 1,4 Sekunden, weil urllib die Verbindung
    nicht offen haelt. Mit `include=` gehen 100 auf einmal.
    """
    ergebnis: dict = {}
    sauber = [str(n).strip() for n in nummern if str(n).strip().isdigit()]
    for anfang in range(0, len(sauber), BUENDEL):
        teil = sauber[anfang:anfang + BUENDEL]
        daten = _abrufen(basis, key, secret, "/orders", {
            "include": ",".join(teil), "per_page": BUENDEL,
            "status": "any", "_fields": FELDER,
        })
        for b in daten if isinstance(daten, list) else []:
            ergebnis[str(b.get("id"))] = b
    return ergebnis


def name_aus(bestellung: dict) -> str:
    rechnung = bestellung.get("billing") or {}
    name = " ".join(t for t in ((rechnung.get("first_name") or "").strip(),
                                (rechnung.get("last_name") or "").strip()) if t)
    return (name or (rechnung.get("company") or "").strip() or "Kunde")[:80]
