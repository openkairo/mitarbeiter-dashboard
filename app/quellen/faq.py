"""FAQ-Nachschlag — die Wissensbasis aus echten Kundengespraechen.

Anders als alle anderen Karten holt diese **nichts von selbst**. Sie ist ein
Werkzeug: Man tippt eine Kundenfrage ein und bekommt die Antwort, die im
dem FAQ-Tool steht — samt Fundstelle und der Angabe, wie sicher sie ist.

**Warum kein Takt und kein Cache:** Es gibt keinen Zustand, der veralten
koennte. Eine Frage ohne Antwort gibt es erst, wenn jemand fragt. Ein
Hintergrund-Faden haette hier nichts zu tun.

**Warum der Status mit angezeigt wird:** Das FAQ-Tool kennt `geprueft`,
`entwurf` und `unsicher`. Ein Entwurf ist ein Vorschlag, keine Auskunft — wer
ihn ungeprueft an einen Kunden weitergibt, gibt eine Vermutung als Zusage aus.
Deshalb steht der Status neben der Antwort und nicht im Kleingedruckten. Wird
gar nichts gefunden, sagt die Karte das ausdruecklich, statt eine plausible
Antwort zu erfinden.

Der Zugang ist die volle MCP-Adresse (`FAQ_MCP_URL`), der Token steckt darin
im Pfad — dasselbe Muster wie beim eigenen MCP-Endpunkt dieses Dashboards.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

NAME = "faq"
TITEL = "FAQ-Nachschlag"
ICON = "📖"
# Kein Takt, kein Cache, kein Haken — siehe quellen/__init__.py.
ART = "werkzeug"
# Der Fusslink zur eigenen Wissensbasis, falls es eine Weboberflaeche gibt.
# Ohne diese Einstellungen kann die Karte nichts holen — dann erscheint
# sie gar nicht erst, statt „nichts zu tun“ zu behaupten.
BRAUCHT = ("FAQ_MCP_URL",)

LINK = (os.environ.get("FAQ_WEB") or "").strip() or None
LINK_TEXT = "FAQ-Tool"

TIMEOUT = 30


def _rpc(url: str, methode: str, params: dict):
    rumpf = json.dumps({"jsonrpc": "2.0", "id": 1, "method": methode,
                        "params": params}).encode()
    req = urllib.request.Request(url, data=rumpf, headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as antwort:
            daten = _entpacke(antwort.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as fehler:
        if fehler.code == 404:
            # 404 heisst bei diesem Muster fast immer: falscher Token im Pfad.
            raise RuntimeError("FAQ-Adresse abgelehnt (404) — Token prüfen.") from fehler
        raise RuntimeError(
            f"HTTP {fehler.code}: "
            f"{fehler.read()[:200].decode('utf-8', 'replace')}") from fehler
    if "error" in daten:
        raise RuntimeError(f"FAQ-Tool: {daten['error']}")
    return daten.get("result", {})


def _entpacke(rohtext: str):
    """Der Server darf JSON oder SSE (event/data) schicken."""
    rohtext = rohtext.strip()
    if rohtext.startswith("{"):
        return json.loads(rohtext)
    for zeile in rohtext.splitlines():
        if zeile.startswith("data:"):
            block = zeile[5:].strip()
            if block and block != "[DONE]":
                return json.loads(block)
    raise RuntimeError(f"unlesbare Antwort: {rohtext[:200]}")


def _text_inhalt(ergebnis: dict):
    """Aus der MCP-Huelle den eigentlichen Inhalt holen."""
    for block in (ergebnis.get("content") or []):
        if block.get("type") == "text":
            roh = block.get("text") or ""
            try:
                return json.loads(roh)
            except (TypeError, ValueError):
                return {"antwort": roh}
    return {}


def _adresse(env: dict) -> str:
    url = (env.get("FAQ_MCP_URL") or "").strip()
    if not url:
        raise RuntimeError("Kein FAQ-Zugang hinterlegt.")
    return url


def antwort(env: dict, frage: str) -> dict:
    """Eine Kundenfrage nachschlagen."""
    ergebnis = _rpc(_adresse(env), "tools/call",
                    {"name": "faq_antwort", "arguments": {"frage": frage}})
    daten = _text_inhalt(ergebnis)
    quelle = daten.get("quelle") or {}
    weitere = []
    for t in (daten.get("weitere_treffer") or [])[:4]:
        if isinstance(t, dict):
            weitere.append({"titel": t.get("titel") or t.get("frage") or "",
                            "status": t.get("status") or ""})
    return {
        "gefunden": bool(daten.get("gefunden", bool(daten.get("antwort")))),
        "antwort": (daten.get("antwort") or "").strip(),
        "ausfuehrlich": (daten.get("ausfuehrlich") or "").strip(),
        "nicht_sagen": (daten.get("nicht_sagen") or "").strip(),
        "titel": (quelle.get("titel") or "").strip(),
        "kategorie": (quelle.get("kategorie") or "").strip(),
        "status": (quelle.get("status") or "").strip(),
        "warnung": (quelle.get("warnung") or "").strip(),
        "weitere": weitere,
    }


def pruefen(env: dict) -> tuple:
    """Antwortet das FAQ-Tool ueberhaupt?"""
    ergebnis = _rpc(_adresse(env), "tools/list", {})
    namen = [w.get("name") for w in (ergebnis.get("tools") or [])]
    if "faq_antwort" not in namen:
        return False, f"Verbunden, aber ohne faq_antwort ({len(namen)} Werkzeuge)."
    return True, f"Verbunden, {len(namen)} Werkzeuge."
