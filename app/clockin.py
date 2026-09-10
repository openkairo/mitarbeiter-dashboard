#!/usr/bin/env python3
"""Lesender Zugriff auf die clockin Customer-API v3.

Zeiterfassung, Abwesenheiten und Stundenkonto.
Angelegt 09.09.2026. Doku: https://docs.clockin.de/customer-api/v3
(Die Swagger-Seite laedt ihre Daten aus `openapi.yaml` — wer nachschlagen
will, holt sich besser gleich die Datei.)

Reine Standardbibliothek, kein pip-Paket noetig — dasselbe Muster wie
`lexware.py` und `todomaster.py`.

    Basis:      https://customerapi.clockin.de
    Anmeldung:  Authorization: Bearer <Token>
    Token:      aus CLOCKIN_CONFIG oder der Umgebung (Rechte 600)

Selbsttest:  python3 clockin.py
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

# Im Container gibt es die config.env nicht — der Token kommt aus der Umgebung
# (.env des Dashboards). Die Datei bleibt als Rueckfallebene fuer den
# Aufruf von Hand auf dem Server.
CONFIG = Path(os.environ.get("CLOCKIN_CONFIG", "/daten/clockin/config.env"))
ZONE = ZoneInfo("Europe/Berlin")
BASIS = "https://customerapi.clockin.de"
TIMEOUT = 30


class ClockinFehler(Exception):
    pass


def _ssl_kontext():
    """Auf dem Linux-VPS reicht der Systemspeicher; ein macOS-Framework-Python
    bringt keine CAs mit — dort springt certifi ein. Nie ungeprueft verbinden:
    hier gehen Personaldaten und ein Token ueber die Leitung."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL_KONTEXT = _ssl_kontext()


def _config() -> dict:
    werte = {}
    if CONFIG.exists():
        for zeile in CONFIG.read_text().splitlines():
            if "=" in zeile and not zeile.strip().startswith("#"):
                k, v = zeile.split("=", 1)
                werte[k.strip()] = v.strip()
    return werte


def _token() -> tuple[str, str]:
    cfg = _config()
    token = os.environ.get("CLOCKIN_TOKEN") or cfg.get("CLOCKIN_TOKEN", "")
    basis = os.environ.get("CLOCKIN_BASIS") or cfg.get("CLOCKIN_BASIS") or BASIS
    if not token:
        raise ClockinFehler(f"CLOCKIN_TOKEN fehlt — weder in der Umgebung noch in {CONFIG}")
    return token, basis.rstrip("/")


def ruf(pfad: str, methode: str = "GET", koerper: dict | None = None,
        params: dict | None = None):
    token, basis = _token()
    url = basis + "/" + pfad.lstrip("/")
    if params:
        url += "?" + urllib.parse.urlencode(params)
    daten = json.dumps(koerper).encode() if koerper is not None else None
    req = urllib.request.Request(url, data=daten, method=methode)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/json")
    if daten is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=SSL_KONTEXT) as antwort:
            roh = antwort.read()
            return json.loads(roh.decode()) if roh else {}
    except urllib.error.HTTPError as err:
        text = err.read().decode(errors="replace")[:300]
        raise ClockinFehler(f"HTTP {err.code} bei {pfad}: {text}") from err
    except urllib.error.URLError as err:
        raise ClockinFehler(f"Netzwerkfehler bei {pfad}: {err.reason}") from err


def _seiten(pfad: str, params: dict | None = None) -> list:
    """Alle Seiten einer Liste einsammeln (`data` + `meta.last_page`)."""
    alles, seite = [], 1
    while seite < 50:
        antwort = ruf(pfad, params={**(params or {}), "page": seite})
        alles.extend(antwort.get("data") or [])
        meta = antwort.get("meta") or {}
        if seite >= int(meta.get("last_page") or 1):
            break
        seite += 1
    return alles


# ------------------------------------------------------------------ Abrufe

def mitarbeiter() -> list:
    return _seiten("/v3/employees")


def name(m: dict) -> str:
    teile = [(m.get("firstName") or m.get("first_name") or "").strip(),
             (m.get("lastName") or m.get("last_name") or "").strip()]
    return " ".join(t for t in teile if t) or str(m.get("id"))


def arbeitstage(employee_ids: list, von: date, bis: date) -> list:
    """Arbeitstage samt Buchungen. `employee_ids` ist Pflicht — ohne die
    Liste antwortet die API mit 422, nicht mit "alle"."""
    return (ruf("/v3/workdays/search", "POST", {
        "employee_ids": [int(i) for i in employee_ids],
        "start_date": von.isoformat(),
        "end_date": bis.isoformat(),
    }) or {}).get("data") or []


def abwesenheiten(von: date, bis: date, nur_genehmigt: bool = True) -> list:
    """Urlaub, Krankheit und Ähnliches im Zeitraum.

    Gefiltert wird ueber `scopes` — `byEndsAt >= von` und `byStartsAt <= bis`
    fangen auch die Abwesenheiten mit ein, die in den Zeitraum hineinragen.
    """
    # Voller Zeitstempel, nicht nur das Datum: Ein blosses "2026-09-09" lehnt
    # die API mit 422 ab ("must be a valid ISO8601 string").
    scopes = [
        {"name": "byEndsAt", "parameters": [">=", f"{von.isoformat()}T00:00:00Z"]},
        {"name": "byStartsAt", "parameters": ["<=", f"{bis.isoformat()}T23:59:59Z"]},
    ]
    if nur_genehmigt:
        scopes.append({"name": "byApprovals", "parameters": ["granted"]})
    return (ruf("/v3/absences/search", "POST", {"scopes": scopes}) or {}).get("data") or []


def zeitraum(a: dict) -> tuple:
    """(erster Tag, letzter Tag) einer Abwesenheit als `date` in Berliner Zeit.

    **Ohne Umrechnung ist jedes Datum einen Tag daneben.** clockin speichert in
    UTC: Ein ganzer Tag am 03.10. steht als `2026-10-02T22:00:00Z` bis
    `2026-10-03T21:59:59Z`. Wer die ersten zehn Zeichen abschneidet, liest den
    2. Oktober — dieselbe Falle wie bei ganztaegigen Google-Kalender-Terminen.
    """
    def tag(wert, ende=False):
        if not wert:
            return None
        roh = str(wert).replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(roh).astimezone(ZONE).date()
        except ValueError:
            return None
    return tag(a.get("starts_at")), tag(a.get("ends_at"), True)


def wer_fehlt(tag: date | None = None) -> list:
    """[(Name, Kategorie, Notiz)] — wer an dem Tag genehmigt abwesend ist."""
    tag = tag or date.today()
    namen = {m.get("id"): name(m) for m in mitarbeiter()}
    ergebnis = []
    for a in abwesenheiten(tag, tag):
        von, bis = zeitraum(a)
        if von and bis and von <= tag <= bis:
            ergebnis.append((namen.get(a.get("employee_id"), str(a.get("employee_id"))),
                             a.get("absencecategory_name") or "", a.get("note") or ""))
    return ergebnis


if __name__ == "__main__":       # Verbindungstest: python3 clockin.py
    leute = mitarbeiter()
    print(f"Verbindung steht — {len(leute)} Mitarbeiter:")
    for m in leute:
        print(f"  {m.get('id')}  {name(m)}")
    namen = {m.get("id"): name(m) for m in leute}
    heute = date.today()
    ab = abwesenheiten(heute, heute + timedelta(days=45))
    print(f"\nGenehmigte Abwesenheiten der nächsten 45 Tage: {len(ab)}")
    for a in sorted(ab, key=lambda x: str(x.get("starts_at"))):
        von, bis = zeitraum(a)
        spanne = von.strftime("%d.%m.") if von == bis else \
            f"{von.strftime('%d.%m.')}–{bis.strftime('%d.%m.')}"
        print(f"  {spanne:14} {namen.get(a.get('employee_id'), '?'):18} "
              f"{a.get('absencecategory_name'):10} {a.get('note') or ''}")
    fehlt = wer_fehlt()
    print(f"\nHeute abwesend: {', '.join(n for n, _, _ in fehlt) or 'niemand'}")
