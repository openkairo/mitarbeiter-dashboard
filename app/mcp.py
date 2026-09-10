"""MCP-Server (Streamable HTTP) unter /mcp/<token> — damit eine KI das
Buchhaltungs-Dashboard lesen und bedienen kann.

Aufbau wie bei den uebrigen Werkzeugen dieses Hauses: Der Token im
Pfad ist die Anmeldung, Antworten kommen als reines JSON zurueck, kein SSE.
Traefik laesst /mcp/ ohne Basic-Auth durch — der Token traegt allein.

> Wer den Token hat, kann alles, was das Dashboard kann, einschliesslich
> Schreiben und Aendern der Zugangsdaten (Entscheidung des Betreibers, 09.09.2026).
> Ein geleakter Token ist ein vollwertiger Schluessel: neu wuerfeln
> (`openssl rand -hex 24`), in der .env der Instanz tauschen,
> Container neu starten, Connector neu eintragen.

**Eine Ausnahme, und die bleibt:** Geheimnisse werden auch hier **nie**
ausgegeben — `zugang_lesen` liefert nur, ob etwas gesetzt ist, woher es kommt
und die letzten vier Zeichen. Ein Token, der API-Schluessel im Klartext
herausgibt, waere ein Generalschluessel fuer Lexware, den Shop und das
Postfach zugleich.

Die Werkzeuge rufen dieselben Kernfunktionen wie die Oberflaeche. Es gibt
keinen zweiten Weg in die Daten — was hier passiert, passiert exakt so, als
haette jemand im Dashboard geklickt, inklusive Rueckweg nach Todomaster.
"""

from __future__ import annotations

import json
import os

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

# Auf Modulebene, weil die Werkzeugbeschreibungen und die Einweisung schon
# beim Import entstehen. Kein Kreis: `quellen` kennt `main` nicht, und `main`
# holt sich `mcp` erst danach.
from . import profil, quellen

mcp_router = APIRouter()

PROTOKOLL = "2025-06-18"
MCP_TOKEN = os.environ.get("MCP_TOKEN", "")

WER = {"type": "string",
       "description": "Wer das veranlasst hat (z. B. der eigene Name). Steht danach als "
                      "Urheber am Posten. Ohne Angabe: 'KI'."}

TOOLS = [
    {
        "name": "uebersicht",
        "description": (
            "Der Stand aller Karten auf einen Blick: je Karte Anzahl offener "
            "Posten, Ampel, Kennzahlen und Stand des letzten Abrufs. Dazu die "
            "Kopfzahlen, der Tagesfortschritt (`erledigt`, `offen`, `von_selbst` "
            "= von der Quelle erkannt, ohne Haken), die Zeiterfassung von heute "
            "und ob gerade abgerufen oder pausiert wird. Immer hiermit anfangen."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "karte",
        "description": (
            "Eine Karte im Detail, mit allen Posten: Titel, Betrag, Datum, Ampel, "
            "Beschriftung, Link, ob abgehakt, und die Notiz. Der `schluessel` jedes "
            "Postens ist das, was `abhaken` und `notieren` brauchen."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string",
                                    "description": "bank, rechnungen, widerrufe, todos, "
                                                   "kalender, shop, superchat oder mail"}},
            "required": ["name"],
        },
    },
    {
        "name": "abhaken",
        "description": (
            "Einen Posten abhaken oder den Haken wieder entfernen. **Bei der Karte "
            "`todos` wirkt das bis nach Todomaster** — die Aufgabe ist danach dort "
            "wirklich erledigt. Bei allen anderen Karten ist der Haken nur eine Notiz "
            "des Dashboards; in Lexware, im Shop oder im Postfach ändert sich nichts. "
            "Nur auf ausdrückliche Anweisung benutzen."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "schluessel": {"type": "string",
                               "description": "Aus `karte`, Form 'quelle:kennung'."},
                "erledigt": {"type": "boolean", "description": "true = abhaken, false = öffnen."},
                "wer": WER,
            },
            "required": ["schluessel"],
        },
    },
    {
        "name": "notieren",
        "description": ("Eine Notiz an einen Posten schreiben; leerer Text löscht sie. "
                        "Die Notiz steht danach in der Karte unter dem Posten."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "schluessel": {"type": "string"},
                "text": {"type": "string"},
                "wer": WER,
            },
            "required": ["schluessel", "text"],
        },
    },
    {
        "name": "auffrischen",
        "description": (
            "Eine Karte sofort neu holen, statt auf den nächsten Takt zu warten. "
            "Kommt sofort zurück; der Abruf läuft im Hintergrund und dauert je nach "
            "Quelle 2 bis 20 Sekunden. Danach `karte` erneut aufrufen."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "nachricht_senden",
        "description": (
            f"{profil.NAME} eine kurze Nachricht auf das Dashboard schreiben. Sie "
            "steht ganz oben, bis dort auf „Erledigt“ getippt wird. **Für Zurufe, "
            "die die Arbeit leichter machen** — etwa: welcher Posten heute zuerst "
            "dran ist, dass eine Zahlung zu einer Rechnung passt, oder dass "
            "eine Frist näher rückt. Kurz halten, ein bis drei Sätze, und "
            "nur schicken, wenn es wirklich hilft: Eine Box, in der ständig "
            "etwas steht, wird nach zwei Tagen nicht mehr gelesen."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Der Text, höchstens 2000 Zeichen."},
                "dringlichkeit": {"type": "string", "enum": ["info", "wichtig"],
                                  "description": "„wichtig“ färbt die Box rot. Sparsam benutzen."},
                "karte": {"type": "string",
                          "description": "Optional: Kartenname, auf den sich das bezieht "
                                         "(bank, rechnungen, todos …). Die Box verlinkt dorthin."},
                "wer": WER,
            },
            "required": ["text"],
        },
    },
    {
        "name": "nachricht_ersetzen",
        "description": (
            f"Den Zuruf oben auf {profil.NAME}s Dashboard **austauschen** statt "
            "einen zweiten danebenzustellen. Der bevorzugte Weg, wenn dieselbe "
            "Sache noch einmal angemahnt wird: Die alte Nachricht wird "
            "abgeschlossen und die neue tritt an ihre Stelle — in einem Zug, "
            "also nie beides und nie nichts. Steht gerade nichts da, entsteht "
            "einfach eine neue Nachricht; das ist kein Fehler. So bleibt es bei "
            "**einer** Box, auch wenn dreimal nachgehakt wird — drei "
            "übereinandergestapelte Zurufe liest niemand mehr."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Der neue Text, höchstens 2000 Zeichen."},
                "dringlichkeit": {"type": "string", "enum": ["info", "wichtig"],
                                  "description": "„wichtig“ färbt die Box rot. Sparsam benutzen."},
                "karte": {"type": "string",
                          "description": "Optional: Kartenname (bank, rechnungen, todos …)."},
                "id": {"type": "number",
                       "description": "Optional: genau diese Nachricht ersetzen. Ohne "
                                      "Angabe die neueste offene. Eine Nummer, die es "
                                      "nicht gibt oder die schon erledigt ist, wird "
                                      "gemeldet — dann bleibt alles, wie es war."},
                "wer": WER,
            },
            "required": ["text"],
        },
    },
    {
        "name": "nachricht_erledigen",
        "description": (
            "Eine offene Nachricht abschließen, ohne dass jemand geantwortet "
            f"hat — als hätte {profil.NAME} auf „Erledigt“ getippt. Für Zurufe, "
            "die sich von selbst erledigt haben: Die Rechnung ist bezahlt, die "
            "Frist ist durch. **Zum Nachhaken ist `nachricht_ersetzen` der "
            "bessere Weg** — erledigen und neu senden sind zwei Schritte, "
            "zwischen denen etwas schiefgehen kann."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "number", "description": "Nummer aus `nachrichten_offen`."},
                "wer": WER,
            },
            "required": ["id"],
        },
    },
    {
        "name": "nachrichten_offen",
        "description": ("Welche Nachrichten stehen noch auf dem Dashboard? "
                        "Vor dem Schreiben prüfen, damit dasselbe nicht zweimal "
                        "dasteht."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "antworten_lesen",
        "description": (
            f"**Rückmeldungen abholen.** Antwortet {profil.NAME} auf eine Nachricht, "
            "landet die Antwort hier — mit der ursprünglichen Nachricht daneben, "
            "damit der Zusammenhang klar ist. Standardmäßig kommen nur neue "
            "Antworten; abgeholte bleiben mit `nur_neue: false` abrufbar. "
            "Nach jeder eigenen Nachricht später einmal hier nachsehen: Ohne "
            "das schreibt man ins Leere und lernt nie, was hilft und was nervt."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "nur_neue": {"type": "boolean",
                             "description": "Vorgabe true. false zeigt auch schon abgeholte."},
            },
        },
    },
    {
        "name": "zugang_lesen",
        "description": (
            "Welche Zugangsdaten sind hinterlegt und woher stammen sie? Zeigt je Feld "
            "nur, **ob** etwas gesetzt ist, die Herkunft und bei Geheimnissen die "
            "letzten vier Zeichen — nie den Wert selbst. Gut, um zu klären, warum eine "
            "Karte nichts liefert."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "zugang_setzen",
        "description": (
            "Zugangsdaten oder Kennungen ändern, wie in den Settings. Ein leerer Wert "
            "setzt das Feld zurück auf die .env des Servers. **Nur auf ausdrückliche "
            "Anweisung** — ein falscher Schlüssel legt die betroffene Karte still."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "werte": {"type": "object",
                          "description": "{FELD: Wert}, Feldnamen aus `zugang_lesen`."},
                "loeschen": {"type": "array", "items": {"type": "string"},
                             "description": "Feldnamen, die hier entfernt werden sollen. "
                                            "Danach gilt wieder der Wert aus der .env, "
                                            "sofern es dort einen gibt."},
                "wer": WER,
            },
            "required": ["werte"],
        },
    },
    {
        "name": "verbindung_pruefen",
        "description": (
            "Macht den echten Abruf einer Karte und sagt, ob er klappt — genau das, "
            "was der Knopf in den Settings tut. Antwortet mit ok=true/false und der "
            "Meldung im Klartext."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
]


def run_tool(name: str, args: dict):
    # Spaet importieren: main importiert mcp, mcp braucht main — sonst dreht
    # sich der Import im Kreis.
    from . import cache, db, einstellungen
    from .main import _karte

    wer = (args.get("wer") or "").strip() or "KI"

    if name == "uebersicht":
        from .main import api_karten
        return api_karten()

    if name == "karte":
        kartenname = (args.get("name") or "").strip()
        if kartenname not in quellen.NACH_NAME:
            return {"fehler": f"Karte „{kartenname}“ gibt es nicht.",
                    "moeglich": list(quellen.NACH_NAME)}
        return _karte(kartenname)

    if name in ("abhaken", "notieren"):
        schluessel = (args.get("schluessel") or "").strip()
        quelle = schluessel.split(":", 1)[0]
        if quelle not in quellen.NACH_NAME:
            return {"fehler": "Unbekannter Posten. Schlüssel kommt aus `karte`."}
        if name == "abhaken":
            an = args.get("erledigt")
            an = True if an is None else bool(an)
            modul = quellen.NACH_NAME[quelle]
            rueckweg = getattr(modul, "erledigt_setzen", None)
            if rueckweg is not None:
                kennung = schluessel.split(":", 1)[1] if ":" in schluessel else ""
                try:
                    rueckweg(kennung, an, wer, einstellungen.umgebung())
                except Exception as fehler:                       # noqa: BLE001
                    return {"fehler": f"Im Fremdsystem ließ sich das nicht ändern: "
                                      f"{fehler}. Der Haken wurde nicht gesetzt."}
            # Erst merken, dann nachziehen — der Sofort-Abruf soll den Haken
            # schon vorfinden (siehe api_erledigt in main.py).
            db.erledigt_setzen(schluessel, quelle, an, wer)
            if rueckweg is not None:
                cache.sofort(quelle)
        else:
            db.notiz_setzen(schluessel, quelle, str(args.get("text") or ""), wer)
        return _karte(quelle)

    if name == "auffrischen":
        kartenname = (args.get("name") or "").strip()
        if kartenname not in quellen.NACH_NAME:
            return {"fehler": f"Karte „{kartenname}“ gibt es nicht."}
        cache.sofort(kartenname)
        return {"status": "angestoßen",
                "hinweis": "Läuft im Hintergrund. In ein paar Sekunden `karte` aufrufen."}

    if name == "nachricht_senden":
        text = (args.get("text") or "").strip()
        if not text:
            return {"fehler": "`text` fehlt."}
        karte = (args.get("karte") or "").strip()
        if karte and karte not in quellen.NACH_NAME:
            return {"fehler": f"Karte „{karte}“ gibt es nicht.",
                    "moeglich": list(quellen.NACH_NAME)}
        kennung = db.nachricht_anlegen(
            text, wer, (args.get("dringlichkeit") or "info"), karte)
        return {"id": kennung, "gesendet": True,
                "hinweis": f"Steht jetzt oben auf {profil.NAME}s Dashboard, "
                           f"bis es abgehakt wird.",
                "offen": db.nachrichten(offen_nur=True)}

    if name in ("nachricht_ersetzen", "nachricht_erledigen"):
        kennung = args.get("id")
        if kennung is not None:
            try:
                kennung = int(kennung)
            except (TypeError, ValueError):
                return {"fehler": "`id` muss eine Nummer sein."}

        if name == "nachricht_erledigen":
            if kennung is None:
                return {"fehler": "`id` fehlt — die Nummer steht in `nachrichten_offen`."}
            try:
                stand = db.nachricht_erledigen(kennung, wer, streng=True)
            except (LookupError, ValueError) as fehler:
                return {"fehler": str(fehler), "offen": db.nachrichten(offen_nur=True)}
            return {"ok": True, "id": stand["id"],
                    "erledigt_am": stand["erledigt_am"],
                    "erledigt_von": stand["erledigt_von"],
                    "offen": db.nachrichten(offen_nur=True)}

        text = (args.get("text") or "").strip()
        if not text:
            return {"fehler": "`text` fehlt."}
        karte = (args.get("karte") or "").strip()
        if karte and karte not in quellen.NACH_NAME:
            return {"fehler": f"Karte „{karte}“ gibt es nicht.",
                    "moeglich": list(quellen.NACH_NAME)}
        try:
            stand = db.nachricht_ersetzen(
                text, wer, (args.get("dringlichkeit") or "info"), karte, kennung)
        except (LookupError, ValueError) as fehler:
            # Nichts geschrieben: Die Transaktion ist zurueckgerollt, die alte
            # Nachricht steht unveraendert da.
            return {"fehler": str(fehler), "offen": db.nachrichten(offen_nur=True)}
        return {"ok": True, "ersetzt": stand["ersetzt"], "alte_id": stand["alte_id"],
                "id": stand["id"],
                "hinweis": (f"Ersetzt Nachricht {stand['alte_id']} — es steht "
                            f"weiterhin genau eine Box oben."
                            if stand["ersetzt"] else
                            f"Es stand nichts offen; die Nachricht ist neu."),
                "offen": db.nachrichten(offen_nur=True)}

    if name == "nachrichten_offen":
        return {"nachrichten": db.nachrichten(offen_nur=True)}

    if name == "antworten_lesen":
        nur_neue = args.get("nur_neue")
        nur_neue = True if nur_neue is None else bool(nur_neue)
        liste = db.antworten(nur_neue=nur_neue)
        if nur_neue and liste:
            # Als abgeholt vermerken, aber nicht loeschen: Mit
            # `nur_neue: false` sind sie weiter da, falls der Faden reisst.
            db.antworten_abhaken([a["id"] for a in liste])
        return {"antworten": liste,
                "hinweis": ("Nichts Neues." if not liste else
                            f"{len(liste)} Rückmeldung(en) von {profil.NAME}.")}

    if name == "zugang_lesen":
        return {"felder": einstellungen.uebersicht(),
                "hinweis": "Geheimnisse werden nie ausgegeben, nur ihre letzten vier Zeichen."}

    if name == "zugang_setzen":
        werte = args.get("werte") or {}
        if not isinstance(werte, dict) or (not werte and not args.get("loeschen")):
            return {"fehler": "`werte` muss ein Objekt {FELD: Wert} sein "
                              "(oder `loeschen` eine Liste von Feldnamen)."}
        unbekannt = [k for k in werte if k not in einstellungen.SCHLUESSEL]
        if unbekannt:
            return {"fehler": f"Unbekannte Felder: {', '.join(unbekannt)}",
                    "moeglich": einstellungen.SCHLUESSEL}
        geaendert = einstellungen.setzen(werte, wer, args.get("loeschen") or [])
        for gruppe, karte in einstellungen.GRUPPE_KARTE.items():
            if any(f[0] in geaendert for f in einstellungen.FELDER if f[2] == gruppe):
                cache.sofort(karte)
        return {"geaendert": geaendert, "felder": einstellungen.uebersicht()}

    if name == "verbindung_pruefen":
        kartenname = (args.get("name") or "").strip()
        if kartenname not in quellen.BEKANNT:
            return {"fehler": f"Karte „{kartenname}“ gibt es hier nicht. "
                              f"Vorhanden: {', '.join(quellen.BEKANNT)}."}
        ok, meldung, hinweis = quellen.pruefen(kartenname, einstellungen.umgebung())
        return {"ok": ok, "meldung": meldung, "hinweis": hinweis}

    return {"fehler": f"Unbekanntes Werkzeug: {name}"}


def _anleitung() -> str:
    """Die Einweisung fuer die KI — aus den Karten gebaut, nicht getippt.

    Stand sie fest im Text, erzaehlte ein Zugang von Bank-Abgleich und
    Widerrufen, die es dort gar nicht gibt. Eine Anleitung, die etwas
    verspricht, was fehlt, ist schlimmer als keine.
    """
    titel = [m.TITEL for m in quellen.REGISTRY]
    teile = [
        f"{profil.TITEL}"
        + (f" von {profil.FIRMA}" if profil.FIRMA else "")
        + (f" — Tagesübersicht von {profil.NAME}" if profil.NAME
           else " — Tagesübersicht")
        + f" aus {len(titel)} Quellen: " + ", ".join(titel) + ".",
        "Mit `uebersicht` anfangen, dann `karte` für Einzelheiten. "
        "Schreiben (`abhaken`, `notieren`, `zugang_setzen`) nur auf "
        "ausdrückliche Anweisung.",
    ]
    if "todos" in quellen.NACH_NAME:
        teile.append(
            "Wichtig: Ein Haken auf der Karte `todos` wirkt bis nach Todomaster — "
            "die Aufgabe ist danach dort wirklich erledigt. Bei allen anderen "
            "Karten bleibt der Haken eine Notiz des Dashboards; die Fremdsysteme "
            "bleiben unberührt.")
    teile.append(
        f"Mit `nachricht_senden` kannst du {profil.NAME} einen kurzen Zuruf oben "
        "aufs Dashboard schreiben — sparsam und nur, wenn es die Arbeit "
        "erleichtert; vorher `nachrichten_offen` prüfen. **Hakst du bei derselben "
        "Sache noch einmal nach, nimm `nachricht_ersetzen`**: Der alte Zuruf wird "
        "abgelöst statt gestapelt, und es bleibt bei einer Box. Was sich von "
        "selbst erledigt hat, schließt `nachricht_erledigen`. Die Antwort holst "
        "du mit `antworten_lesen` ab. Tu das nach jeder eigenen Nachricht "
        "einmal — sonst schreibst du ins Leere und lernst nie, was hilft.")
    teile.append(
        "Liefert eine Karte nichts, hilft `verbindung_pruefen` und danach "
        "`zugang_lesen` — Geheimnisse gibt auch dieser Zugang nie heraus.")
    return "\n\n".join(teile)


# ------------------------------------------------------------------ Transport

def _antwort(rid, ergebnis=None, fehler=None):
    if fehler is not None:
        return {"jsonrpc": "2.0", "id": rid, "error": fehler}
    return {"jsonrpc": "2.0", "id": rid, "result": ergebnis}


def _token_ok(token: str) -> bool:
    return bool(MCP_TOKEN) and token == MCP_TOKEN


@mcp_router.get("/mcp/{token}")
def mcp_get(token: str):
    # 404 statt 401, damit ein falscher Token nichts ueber die Existenz verraet.
    return Response(status_code=405 if _token_ok(token) else 404)


@mcp_router.delete("/mcp/{token}")
def mcp_delete(token: str):
    return Response(status_code=204 if _token_ok(token) else 404)


@mcp_router.post("/mcp/{token}")
async def mcp_post(token: str, request: Request):
    if not _token_ok(token):
        return Response(status_code=404)
    try:
        nachricht = await request.json()
    except Exception:                                             # noqa: BLE001
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None,
             "error": {"code": -32700, "message": "Kein gültiges JSON"}},
            status_code=400)

    if isinstance(nachricht, list):
        antworten = [a for a in (_verarbeite(n) for n in nachricht) if a]
        return JSONResponse(antworten) if antworten else Response(status_code=202)

    antwort = _verarbeite(nachricht)
    if antwort is None:
        return Response(status_code=202)
    return JSONResponse(antwort)


def _verarbeite(n: dict):
    method = n.get("method")
    rid = n.get("id")
    params = n.get("params") or {}

    if method == "initialize":
        return _antwort(rid, {
            "protocolVersion": PROTOKOLL,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": f"smg-{profil.INSTANZ}", "version": "1.0.0"},
            "instructions": _anleitung(),
        })

    if method in ("notifications/initialized", "notifications/cancelled"):
        return None

    if method == "ping":
        return _antwort(rid, {})

    if method == "tools/list":
        return _antwort(rid, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        try:
            ergebnis = run_tool(name, args)
        except Exception as e:      # defensiv: als Werkzeugfehler, nicht als 500
            return _antwort(rid, {
                "content": [{"type": "text", "text": f"Fehler: {e}"}],
                "isError": True,
            })
        # Auf den INHALT pruefen, nicht auf das Vorhandensein des Feldes: Eine
        # Karte fuehrt immer ein "fehler"-Feld mit, meist leer. Wer nur auf den
        # Schluessel prueft, meldet jede erfolgreiche Antwort als Fehler —
        # genau das ist beim ersten Test von `abhaken` passiert.
        fehlerhaft = isinstance(ergebnis, dict) and bool(ergebnis.get("fehler"))
        return _antwort(rid, {
            "content": [{"type": "text",
                         "text": json.dumps(ergebnis, ensure_ascii=False, indent=2,
                                            default=str)}],
            "isError": fehlerhaft,
        })

    if rid is None:
        return None
    return _antwort(rid, fehler={"code": -32601,
                                 "message": f"Unbekannte Methode: {method}"})
