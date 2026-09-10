"""Winziger MCP-Client fuer Todomaster (Streamable HTTP).

Uebernommen aus einem aelteren Werkzeug, angepasst auf Umgebungsvariablen
statt config.env. Bewusst eine eigene Kopie: so haengt dieses Dashboard nicht
davon ab, dass ein fremdes Werkzeug auf dem Server installiert bleibt.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

TIMEOUT = 30


def _rpc(methode: str, params: dict, _id: int = 1):
    url = os.environ.get("TODOMASTER_URL")
    token = os.environ.get("TODOMASTER_TOKEN")
    if not url or not token:
        raise RuntimeError("TODOMASTER_URL/TODOMASTER_TOKEN fehlen in der .env")
    body = json.dumps({"jsonrpc": "2.0", "id": _id, "method": methode,
                       "params": params}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            antwort = _entpacke(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: "
                           f"{e.read()[:200].decode('utf-8', 'replace')}") from e
    if "error" in antwort:
        raise RuntimeError(f"Todomaster: {antwort['error']}")
    return antwort.get("result", {})


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


def tool_call(name: str, argumente: dict):
    ergebnis = _rpc("tools/call", {"name": name, "arguments": argumente})
    if ergebnis.get("isError"):
        # Den Klartext herausziehen statt die Roh-Liste zu zeigen. Sonst stuende
        # in der Karte "[{'type': 'text', 'text': 'Aufgabe ... nicht
        # gefunden.'}]" — technisch korrekt und trotzdem unlesbar.
        texte = [b.get("text", "") for b in (ergebnis.get("content") or [])
                 if isinstance(b, dict) and b.get("type") == "text"]
        raise RuntimeError(" ".join(t for t in texte if t)
                           or f"{name}: unbekannter Fehler")
    for block in ergebnis.get("content", []):
        if block.get("type") == "text":
            try:
                return json.loads(block["text"])
            except (json.JSONDecodeError, TypeError):
                return block["text"]
    return ergebnis


def kategorien() -> list:
    daten = tool_call("list_categories", {})
    if not isinstance(daten, list):
        raise RuntimeError(f"Todomaster liefert keine Kategorienliste: {str(daten)[:120]}")
    return [k for k in daten if isinstance(k, dict)]


def todos(kategorie: str) -> list:
    daten = tool_call("list_todos", {"category": kategorie})
    # Ein Fehlertext statt einer Liste hiess frueher „keine Aufgaben" — und
    # seit der Tagesfortschritt Verschwinden als Erledigen liest, hiesse es
    # „alle Aufgaben erledigt". Ein Fehler muss ein Fehler bleiben.
    if not isinstance(daten, list):
        raise RuntimeError(f"Todomaster liefert keine Aufgabenliste: {str(daten)[:120]}")
    return [t for t in daten if isinstance(t, dict)]


# --------------------------------------------------------------- schreibend

def erledigen(kennung: str, von: str) -> None:
    """Aufgabe in Todomaster abhaken. Wirft bei Misserfolg."""
    tool_call("complete_todo", {"id": kennung, "completed_by": von or "Dashboard"})


def wieder_oeffnen(kennung: str) -> None:
    tool_call("reopen_todo", {"id": kennung})
