"""Mitarbeiter-Dashboard — alles, was heute ansteht, auf einer Seite.

Dasselbe Programm laeuft mehrfach: je Person eine Instanz mit eigenen
Karten und eigenen Zugaengen. Was sich unterscheidet, steht in `app/profil.py`
und der `.env` der Instanz — nicht hier.

Bisher verteilt sich ihre Arbeit auf vier Kanaele: der Bank-Abgleich um 10:15,
der Lexoffice-Stapel um 12:00 und die Widerruf-Alarme im Superchat-Teamchat,
dazu Todos, Kalender, Shop und Mail. Keiner davon zeigt die Gesamtlage, und
abhaken kann man in einem Chat auch nichts.

Die Seite selbst holt nichts: Sie liest den Cache, den die Takte in app/cache.py
im Hintergrund fuellen. Deshalb antwortet sie in Millisekunden, auch wenn
Lexware gerade drosselt oder Superchat blaettert.

Angemeldet wird ueber Traefik (Basic-Auth); die App liest den Benutzernamen nur
mit, um festzuhalten, wer etwas abgehakt hat.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import hashlib
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import (arbeitszeit, cache, db, einstellungen, mcp, profil, quellen,
               webhook)
from .posten import schlimmste

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("buchhaltung")

BASIS = Path(__file__).parent

# Was die Quellen brauchen, kommt aus app/einstellungen.py: Datenbank schlaegt
# .env. Frueher stand hier ein beim Start eingesammeltes Woerterbuch — dann
# wirkte eine geaenderte Einstellung erst nach einem Neustart.

# Die Seite "Zugaenge" steht **allen** angemeldeten Nutzern offen
# (Entscheidung des Betreibers, 09.09.2026). Vorher durfte nur ein einzelner Zugang hinein.
#
# Was das heisst, damit es niemanden spaeter ueberrascht: Wer sich am
# Dashboard anmelden kann, kann die Schluessel fuer Lexware, den Shop,
# Superchat, clockin und das Postfach **ersetzen**. Was NICHT geht — und das
# ist die eigentliche Schutzlinie — ist sie **auslesen**: Geheimnisse gehen
# nie an den Browser zurueck, nur ihre letzten vier Zeichen.
#
# Dafuer merkt sich jede Einstellung, wer sie zuletzt gesetzt hat; die
# Oberflaeche zeigt es an, und jede Aenderung steht im Log.

# Eine Karte gilt als veraltet, wenn sie das Dreifache ihres Taktes nicht mehr
# frisch wurde. Erst dann meldet /healthz einen Fehler — ein einzelner
# misslungener Abruf ist Alltag und soll niemanden wecken.
VERALTET_FAKTOR = 3


def _webhook_schluessel_umziehen() -> None:
    """Einmalige Umschichtung: bisher gab es nur EIN Feld „Geheimnis“, und dort
    stand meist der Cursor-Schluessel — der aber als `Authorization: Bearer`
    gehoert, nicht in die HMAC-Signatur. Genau diese Verwechslung hat den
    Webhook stillgelegt (Cursor antwortete mit 401).

    Der Wert wird deshalb **verschoben**, nicht geloescht: ins Bearer-Feld,
    HMAC bleibt leer, bis jemand es bewusst setzt. Laeuft nur, solange das
    Bearer-Feld leer ist — danach nie wieder.
    """
    gespeichert = db.einstellungen()
    alt = (gespeichert.get("ANTWORT_WEBHOOK_SECRET") or "").strip()
    if alt and not (gespeichert.get("ANTWORT_WEBHOOK_BEARER") or "").strip():
        db.einstellung_setzen("ANTWORT_WEBHOOK_BEARER", alt, "Umzug")
        db.einstellung_setzen("ANTWORT_WEBHOOK_SECRET", "", "Umzug")
        log.info("Webhook-Geheimnis nach Bearer verschoben — HMAC bleibt leer, "
                 "bis es jemand bewusst setzt.")


def _postfaecher_umziehen() -> None:
    """Einmalige Umschichtung: aus den vier festen Mail-Feldern wird ein
    Postfach in der Liste.

    Bis zum 10.09.2026 stand das Hostinger-Postfach in den Einstellungen
    (`MAIL_QUELLE`, `HOSTINGER_EMAIL_TOKEN`, `MAIL_ADRESSE`,
    `MAIL_POSTFACH_ID`) und liess sich weder loeschen noch vervielfaeltigen.
    Es wandert hier in die Tabelle `mailkonto` — mit denselben Werten, damit
    sich am Ergebnis nichts aendert.

    **Genau einmal, gemerkt in `kv`.** Ohne diesen Merker wuerde ein geloeschtes
    Postfach beim naechsten Neustart wieder auftauchen, solange die alten Werte
    noch in der `.env` stehen — was ein Loeschen unmoeglich machte.

    **Der bisherige Weg wird respektiert.** Stand der Schalter auf `imap`, war
    das API-Postfach nicht in Gebrauch: dann kommt es inaktiv herein. Stand er
    auf `api`, waren umgekehrt die IMAP-Zeilen ungenutzt und werden inaktiv
    gesetzt. So liest die Karte nach dem Umbau genau das, was sie vorher las.
    """
    if db.kv_lesen("postfach_umzug"):
        return

    gespeichert = db.einstellungen()

    def wert(schluessel: str) -> str:
        return (gespeichert.get(schluessel) or os.environ.get(schluessel, "")).strip()

    token = wert("HOSTINGER_EMAIL_TOKEN")
    adresse = wert("MAIL_ADRESSE")
    weg_alt = (wert("MAIL_QUELLE") or "api").lower()
    db.kv_schreiben("postfach_umzug", datetime.now().isoformat(timespec="seconds"))

    if not token and not adresse:
        return
    if any((k.get("weg") or "imap") == "api" for k in db.mailkonten()):
        return

    db.mailkonto_speichern({
        "bezeichnung": adresse or "Hostinger-Postfach",
        "weg": "api",
        "benutzer": adresse,
        "passwort": token,
        "postfach_id": wert("MAIL_POSTFACH_ID"),
        "webmail": "https://mail.hostinger.com/",
        "aktiv": weg_alt != "imap",
    }, "Umzug")
    if weg_alt != "imap":
        for konto in db.mailkonten():
            if (konto.get("weg") or "imap") != "api" and konto.get("aktiv"):
                konto["aktiv"] = False
                db.mailkonto_speichern(konto, "Umzug")
    log.info("Mail-Einstellungen als Postfach übernommen (Weg %s) — "
             "ab jetzt in der Liste löschbar.", weg_alt)


@contextlib.asynccontextmanager
async def lebenszyklus(app: FastAPI):
    db.init()
    _webhook_schluessel_umziehen()
    _postfaecher_umziehen()
    cache.starten(quellen.REGISTRY, {})   # die Werte holt jeder Lauf selbst
    yield


app = FastAPI(title=f"SMG {profil.TITEL}", docs_url=None, redoc_url=None,
              lifespan=lebenszyklus)
# MCP-Endpunkt fuer eine KI: /mcp/<token>, ohne Basic-Auth (Traefik laesst ihn
# durch, der Token im Pfad traegt allein). Siehe app/mcp.py.
app.include_router(mcp.mcp_router)
app.mount("/static", StaticFiles(directory=BASIS / "static"), name="static")
templates = Jinja2Templates(directory=str(BASIS / "templates"))


def _statik_version() -> str:
    """Kurzer Hash ueber CSS und JS, haengt als ?v=… an den Dateien.

    Ohne das liefert der Browser nach einem Deploy weiter das alte Stylesheet.
    """
    h = hashlib.sha256()
    for name in ("style.css", "app.js"):
        pfad = BASIS / "static" / name
        if pfad.exists():
            h.update(pfad.read_bytes())
    return h.hexdigest()[:8]


STATIK_VERSION = _statik_version()


def benutzer(request: Request) -> str:
    """Benutzername aus dem Basic-Auth-Kopf, den Traefik durchreicht.

    Kein Sicherheitsmerkmal — die Anmeldung macht Traefik. Hier geht es nur um
    die Zeile "abgehakt von …".
    """
    kopf = request.headers.get("authorization", "")
    if not kopf.lower().startswith("basic "):
        return "Team"
    try:
        roh = base64.b64decode(kopf.split(" ", 1)[1], validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, IndexError):
        return "Team"
    name = roh.split(":", 1)[0].strip()
    return name[:40] if name else "Team"


def _veraltet() -> list:
    alt = []
    stand = db.cache_alle()
    jetzt = datetime.now()
    for modul in quellen.REGISTRY:
        eintrag = stand.get(modul.NAME)
        if not eintrag or not eintrag["stand"]:
            alt.append(modul.NAME)
            continue
        try:
            alter = (jetzt - datetime.fromisoformat(eintrag["stand"])).total_seconds()
        except ValueError:
            alt.append(modul.NAME)
            continue
        # Gegen den TATSAECHLICHEN Takt messen, nicht gegen die TTL des Moduls.
        # Seit der Umstellung auf 30 Minuten (09.09.2026) ist die TTL nur noch
        # ein Richtwert fuer den Browser; wer weiter gegen sie prueft, meldet
        # jede Karte als veraltet, sobald sie aelter als neun Minuten ist.
        if alter > cache.TAKT * VERALTET_FAKTOR:
            alt.append(modul.NAME)
    return alt


# ------------------------------------------------------------------- Auskunft

@app.get("/healthz")
def healthz():
    try:
        db.cache_alle()
    except Exception as fehler:                                   # noqa: BLE001
        return JSONResponse({"status": "fehler", "grund": str(fehler)[:200]},
                            status_code=500)
    alt = _veraltet()
    darf, grund = arbeitszeit.soll_holen()
    # Ausserhalb der Arbeitszeit wird bewusst nicht geholt — alte Daten
    # sind dann der gewollte Zustand und kein Grund, jemanden zu wecken.
    if alt and not darf:
        return {"status": "ok", "karten": len(quellen.REGISTRY),
                "veraltet": alt, "pause": grund}
    # Beim Start sind noch nicht alle Takte durch — das ist auch kein Fehler.
    if alt and len(alt) < len(quellen.REGISTRY):
        return {"status": "ok", "karten": len(quellen.REGISTRY), "veraltet": alt}
    if alt:
        # Eine frisch ausgerollte Instanz hat noch gar nichts geholt. Das sieht
        # aus wie "alles veraltet", ist aber Anlauf — und ein 500 in den ersten
        # Sekunden nach dem Deploy weckt sonst den Watchdog fuer nichts.
        stand = db.cache_alle()
        if not any((stand.get(m.NAME) or {}).get("stand") for m in quellen.REGISTRY):
            return {"status": "ok", "karten": len(quellen.REGISTRY),
                    "veraltet": alt, "anlauf": "erster Abruf läuft noch"}
        return JSONResponse({"status": "fehler", "grund": "keine Karte ist frisch",
                             "veraltet": alt}, status_code=500)
    return {"status": "ok", "karten": len(quellen.REGISTRY), "veraltet": []}


def _karte(name: str) -> dict:
    modul = quellen.NACH_NAME[name]
    eintrag = db.cache_lesen(name)
    daten = eintrag["daten"] or {}
    posten_liste = list(daten.get("posten") or [])
    erledigt = db.erledigte(name)
    notizen = db.notizen(name)

    # Bei Karten, die zurueckschreiben, gehoert die Wahrheit dem Fremdsystem.
    # Steht ein Posten noch in der frisch geholten Liste, ist er dort OFFEN —
    # ein lokaler Haken darauf ist dann veraltet und wird weggeraeumt.
    #
    # Ohne das entsteht genau die Doppelwahrheit, die der Rueckweg verhindern
    # soll: Am 09.09.2026 wurde eine Aufgabe direkt in Todomaster wieder
    # geoeffnet — auf dem Dashboard blieb sie durchgestrichen stehen. Der
    # Fehlerfall war abgesichert, der Fall "woanders geaendert" nicht.
    schreibt_zurueck = hasattr(modul, "erledigt_setzen")

    offen = 0
    for p in posten_liste:
        schluessel = f"{name}:{p['id']}"
        p["schluessel"] = schluessel
        haken = erledigt.get(schluessel)
        if (haken and schreibt_zurueck and eintrag["stand"]
                and eintrag["stand"] > haken["am"]):
            # Der Abruf ist juenger als der Haken und der Posten ist immer noch
            # da — also hat ihn jemand drueben wieder geoeffnet.
            db.erledigt_setzen(schluessel, name, False, "")
            haken = None
        p["erledigt"] = haken is not None
        p["notiz"] = (notizen.get(schluessel) or {}).get("text", "")
        if not p["erledigt"]:
            offen += 1

    db.erledigt_gesehen(name, [p["schluessel"] for p in posten_liste if p["erledigt"]])
    nicht_erledigt = [p for p in posten_liste if not p["erledigt"]]

    return {
        "name": name,
        "titel": modul.TITEL,
        # Ohne Zugangsdaten zeigt die Oberflaeche die Karte nicht im
        # Raster, sondern unten als "noch einzurichten". Eine leere Karte
        # sähe aus wie Feierabend.
        "eingerichtet": quellen.ist_eingerichtet(modul, einstellungen.umgebung()),
        # Karten ohne Haken (z. B. der Kalender) zeigen nur an; dort gibt es
        # nichts zu erledigen.
        "abhakbar": getattr(modul, "ABHAKBAR", True),
        "icon": modul.ICON,
        # Der Abruf darf den Link bestimmen: Beim Posteingang haengt er an den
        # hinterlegten Postfaechern, nicht am Modul — sonst zeigte der Fuss
        # „Webmail öffnen“ nach Hostinger, auch bei einem IMAP-Postfach eines
        # anderen Anbieters.
        "link": daten.get("link") or getattr(modul, "LINK", None)
                or daten.get("teamchat"),
        # Auch die Beschriftung darf aus dem Abruf kommen: Bei Superchat haengt
        # sie am Postfach, und „Postfach Buchhaltung“ waere auf einer anderen
        # Dashboard schlicht falsch.
        "link_text": daten.get("link_text") or getattr(modul, "LINK_TEXT", ""),
        "ttl": modul.TTL,
        "stand": eintrag["stand"],
        "fehler": eintrag["fehler"],
        "hinweis": daten.get("hinweis"),
        "kennzahlen": daten.get("kennzahlen") or {},
        "ampel": schlimmste(nicht_erledigt),
        "offen": offen,
        "gesamt": len(posten_liste),
        "posten": posten_liste,
        "extra": {k: v for k, v in daten.items()
                  if k in ("person", "zeit", "teamchat", "stand_datei",
                           "postfaecher", "postfach_farben", "gekuerzt")},
    }


@app.get("/api/karten")
def api_karten():
    """Kurzfassung aller Karten — fuer die Zahlenreihe oben und die Badges."""
    # Jemand schaut hin — das erlaubt den Takten zu holen, auch ausserhalb
    # von der Arbeitszeit. Ohne das saehe man abends die Zahlen vom
    # Nachmittag, ohne zu merken, dass sie alt sind.
    arbeitszeit.besuch_merken()
    karten = [_karte(m.NAME) for m in quellen.REGISTRY]
    knapp = [{k: v for k, v in karte.items() if k != "posten"} for karte in karten]
    kopf = []
    for quelle, gross, warn, text, unterteil in quellen.KOPFZAHLEN:
        karte = next((k for k in karten if k["name"] == quelle), None)
        # Eine Kachel fuer eine Karte ohne Zugang zeigte eine Null, die
        # wie „nichts zu tun“ aussieht statt wie „nicht angeschlossen“.
        if not karte or not karte.get("eingerichtet", True):
            continue
        kopf.append({
            "quelle": quelle,
            # Ein Ausschnitt (etwa ein zweites Postfach) traegt seinen Namen
            # im Titel — sonst staenden zwei Kacheln „Superchat“ nebeneinander.
            "titel": (f"{karte['titel']} · {unterteil}" if unterteil
                      else karte["titel"]),
            "icon": karte["icon"],
            # Bei einem Ausschnitt zaehlt NUR die genannte Kennzahl. Der
            # Rueckfall auf die Gesamtzahl waere hier eine Falschaussage:
            # Wird ein Postfach in Superchat umbenannt, gibt es die Kennzahl
            # nicht mehr — die Kachel „Superchat · BEZAHLEN“ zeigte dann
            # klaglos die Summe aller Postfaecher.
            "zahl": (karte["kennzahlen"].get(gross, 0) if unterteil
                     else karte["kennzahlen"].get(gross, karte["offen"])),
            "warnung": karte["kennzahlen"].get(warn, 0) if warn else 0,
            "warntext": text,
            # Sagt es, statt still eine Null zu zeigen.
            "fehlt": bool(unterteil and gross not in karte["kennzahlen"]),
        })
    # Nur zaehlen, was sich abhaken laesst — sonst misst der Ring Termine mit,
    # die nie erledigt werden koennen.
    zaehlbar = [k for k in karten if k["abhakbar"] and k.get("eingerichtet", True)]
    namen = {k["name"] for k in zaehlbar}
    # „Heute erledigt“ kommt aus dem Verlauf, nicht aus den Haken in der
    # Liste. Frueher zaehlte der Ring nur abgehakte Posten, die noch da
    # standen — ein in Todomaster erledigtes Todo verschwand und riss seinen
    # Haken aus Zaehler UND Nenner, der Ring sprang zurueck. Jetzt zaehlt,
    # was heute erledigt wurde: von Hand oder von der Quelle erkannt.
    # Und was gerade offen ist, ist nicht erledigt — egal, was der Verlauf
    # sagt. Das deckt Wiederoeffnen in jeder Quelle ab.
    offen_schluessel = {p["schluessel"] for karte in zaehlbar
                        for p in karte["posten"] if not p["erledigt"]}
    heute = [v for v in db.verlauf_heute()
             if v["quelle"] in namen and v["schluessel"] not in offen_schluessel]
    erledigt_heute = len(heute)
    von_selbst = sum(1 for v in heute if v["art"] == "quelle")
    offen_gesamt = sum(karte["offen"] for karte in zaehlbar)
    person = next((k["extra"].get("person") for k in karten
                   if k["extra"].get("person")), None)
    zeit = next((k["extra"].get("zeit") for k in karten if k["extra"].get("zeit")), None)
    darf, grund = arbeitszeit.soll_holen()
    return {"karten": knapp, "kopf": kopf,
            # Ob eine neue Fassung bereitliegt. Kommt hier mit, weil die
            # Uebersicht ohnehin jede Minute geholt wird — eine eigene Abfrage
            # nur fuer einen kleinen Punkt waere Verkehr ohne Gegenwert.
            "update": _update_hinweis(),
            # Die Fassung der ausgelieferten Dateien. Eine Seite, die seit
            # Stunden offen steht, laeuft sonst still mit altem JavaScript
            # weiter: Knoepfe, die es serverseitig laengst anders gibt, tun
            # dann scheinbar nichts. Genau das ist am 10.09.2026 passiert —
            # ein Loeschklick kam nie am Server an.
            "fassung": _statik_version(),
            "fortschritt": {"erledigt": erledigt_heute,
                            "offen": offen_gesamt,
                            "gesamt": erledigt_heute + offen_gesamt,
                            "von_selbst": von_selbst,
                            "von_hand": erledigt_heute - von_selbst},
            "person": person, "zeit": zeit, "veraltet": _veraltet(),
            "takt": {"holt": darf, "grund": grund, "sekunden": cache.TAKT}}


@app.get("/api/karten/{name}")
def api_karte(name: str):
    if name not in quellen.NACH_NAME:
        return JSONResponse({"fehler": f"Karte „{name}“ gibt es nicht."},
                            status_code=404)
    return _karte(name)


@app.post("/api/karten/{name}/refresh")
def api_refresh(name: str):
    if name not in quellen.NACH_NAME:
        return JSONResponse({"fehler": f"Karte „{name}“ gibt es nicht."},
                            status_code=404)
    cache.sofort(name)
    return JSONResponse({"status": "angestossen"}, status_code=202)


# ------------------------------------------------------------------ Handlungen

def _quelle_aus(schluessel: str) -> str | None:
    quelle = (schluessel or "").split(":", 1)[0]
    return quelle if quelle in quellen.NACH_NAME else None


@app.post("/api/erledigt")
async def api_erledigt(request: Request):
    daten = await request.json()
    schluessel = str(daten.get("schluessel") or "")
    quelle = _quelle_aus(schluessel)
    if not quelle:
        return JSONResponse({"fehler": "Unbekannter Posten."}, status_code=400)
    an = bool(daten.get("erledigt"))
    wer = benutzer(request)
    # Der Titel ist Beiwerk fuer den Verlauf — die Oberflaeche schickt ihn
    # mit, damit im Log steht, WAS abgehakt wurde, nicht nur ein Schluessel.
    titel = str(daten.get("titel") or "")[:120]

    # Manche Karten schreiben zurueck — bei den Aufgaben wandert der Haken nach
    # Todomaster. Das passiert ZUERST: Klappt es nicht, wird hier auch nichts
    # gemerkt. Sonst stuende die Aufgabe auf dem Dashboard als erledigt und im
    # Todomaster weiter offen, und niemand wuesste welche der beiden stimmt.
    modul = quellen.NACH_NAME[quelle]
    rueckweg = getattr(modul, "erledigt_setzen", None)
    if rueckweg is not None:
        kennung = schluessel.split(":", 1)[1] if ":" in schluessel else ""
        try:
            rueckweg(kennung, an, wer, einstellungen.umgebung())
        except Exception as fehler:                               # noqa: BLE001
            log.warning("WARN Rueckweg %s: %s", quelle, fehler)
            grund = str(fehler).strip().rstrip(".")
            return JSONResponse(
                {"fehler": f"In Todomaster ließ sich das nicht ändern: {grund}. "
                           f"Der Haken wurde deshalb nicht gesetzt."},
                status_code=502)
    # Erst merken, dann die Liste nachziehen: Der Sofort-Abruf vergleicht alt
    # gegen neu, und der Haken soll vor diesem Vergleich stehen — sonst
    # stuende „von selbst“ dort, wo die Person gerade selbst geklickt hat.
    db.erledigt_setzen(schluessel, quelle, an, wer, titel)
    if rueckweg is not None:
        # Todomaster ist jetzt die Wahrheit — die Liste sofort nachziehen,
        # damit die erledigte Aufgabe nicht bis zum naechsten Takt herumsteht.
        cache.sofort(quelle)
    return _karte(quelle)


@app.post("/api/notiz")
async def api_notiz(request: Request):
    daten = await request.json()
    schluessel = str(daten.get("schluessel") or "")
    quelle = _quelle_aus(schluessel)
    if not quelle:
        return JSONResponse({"fehler": "Unbekannter Posten."}, status_code=400)
    db.notiz_setzen(schluessel, quelle, str(daten.get("text") or ""),
                    benutzer(request))
    return _karte(quelle)


# -------------------------------------------------------------- Einstellungen

@app.get("/api/einstellungen")
def api_einstellungen(request: Request):
    return {"felder": einstellungen.uebersicht(),
            "gruppen_karte": einstellungen.GRUPPE_KARTE}


@app.post("/api/einstellungen")
async def api_einstellungen_setzen(request: Request):
    daten = await request.json()
    werte = daten.get("werte") or {}
    loeschen = daten.get("loeschen") or []
    if not isinstance(werte, dict) or not isinstance(loeschen, list):
        return JSONResponse({"fehler": "Ungültige Daten."}, status_code=400)
    geaendert = einstellungen.setzen(werte, benutzer(request), loeschen)
    # Betroffene Karten sofort neu holen, damit man gleich sieht, ob es traegt.
    for gruppe, karte in einstellungen.GRUPPE_KARTE.items():
        if any(f[0] in geaendert for f in einstellungen.FELDER if f[2] == gruppe):
            cache.sofort(karte)
    log.info("Einstellungen geändert von %s: %s", benutzer(request),
             ", ".join(geaendert) or "nichts")
    return {"geaendert": geaendert, "felder": einstellungen.uebersicht()}


def _mcp_adresse(request: Request) -> str:
    token = mcp.MCP_TOKEN
    if not token:
        return ""
    # Dieselbe Adresse, unter der die Seite gerade laeuft — dann stimmt sie
    # auch beim Blick durch einen Tunnel oder unter einem anderen Namen.
    basis = str(request.base_url).rstrip("/")
    return f"{basis}/mcp/{token}"


@app.get("/api/mcp")
def api_mcp(request: Request):
    """Auskunft ueber den KI-Zugang — die Adresse aber nur maskiert.

    Der Token ist selbst ein Geheimnis: Wer ihn hat, kann alles, was das
    Dashboard kann, und zwar ohne Passwort. Er steht deshalb nicht einfach auf
    der Seite, wo ihn jedes Bildschirmfoto mitnehmen wuerde. Zum Einrichten
    holt man ihn ueber /api/mcp/adresse — eine bewusste Handlung.
    """
    token = mcp.MCP_TOKEN
    adresse = _mcp_adresse(request)
    maskiert = ""
    if adresse and token:
        maskiert = adresse.replace(token, "·" * 12 + token[-4:])
    return {
        "vorhanden": bool(token),
        "adresse_maskiert": maskiert,
        "werkzeuge": [{"name": w["name"], "beschreibung": w["description"]}
                      for w in mcp.TOOLS],
    }


@app.get("/api/mcp/adresse")
def api_mcp_adresse(request: Request):
    """Die volle Adresse — nur auf ausdrueckliche Anforderung."""
    adresse = _mcp_adresse(request)
    if not adresse:
        return JSONResponse({"fehler": "Es ist kein MCP_TOKEN hinterlegt."},
                            status_code=404)
    log.info("MCP-Adresse abgerufen von %s", benutzer(request))
    return {"adresse": adresse}


# ---------------------------------------------------------------- Nachrichten

@app.get("/api/nachrichten")
def api_nachrichten():
    """Offene Zurufe der KI. Wird haeufiger abgefragt als die Karten — die
    Daten liegen in der eigenen Datenbank und kosten nichts."""
    return {"nachrichten": db.nachrichten(offen_nur=True)}


@app.post("/api/nachrichten/{kennung}/antwort")
async def api_nachricht_antwort(kennung: int, request: Request):
    """Die Antwort an die KI. Schliesst die Nachricht zugleich ab."""
    daten = await request.json()
    text = str((daten or {}).get("text") or "").strip()
    if not text:
        return JSONResponse({"fehler": "Die Antwort ist leer."}, status_code=400)
    wer = benutzer(request)
    db.nachricht_antworten(kennung, text, wer)
    log.info("Antwort auf Nachricht %s von %s", kennung, wer)

    # Sofort melden, falls ein Webhook eingerichtet ist. Laeuft im Hintergrund —
    # Die Antwort wartet nicht auf einen fremden Server.
    ursprung = next((n for n in db.nachrichten(offen_nur=False, grenze=50)
                     if n["id"] == kennung), {})
    webhook.melden(einstellungen.umgebung(), {
        "ereignis": "antwort",
        "nachricht_id": kennung,
        "frage": ursprung.get("text", ""),
        "antwort": text,
        "von": wer,
        "am": ursprung.get("antwort_am", ""),
        "karte": ursprung.get("karte", ""),
        "dringlichkeit": ursprung.get("dringlichkeit", ""),
        "dashboard": str(request.base_url).rstrip("/"),
    })
    return {"nachrichten": db.nachrichten(offen_nur=True)}


@app.post("/api/nachrichten/{kennung}/erledigt")
def api_nachricht_erledigt(kennung: int, request: Request):
    # Nachsichtig: ein zweiter Klick auf denselben Knopf ist kein Fehler.
    db.nachricht_erledigen(kennung, benutzer(request))
    return {"nachrichten": db.nachrichten(offen_nur=True)}


# ------------------------------------------------------------ Mail-Postfaecher

@app.get("/api/mailkonten")
def api_mailkonten():
    """Alle Postfaecher — **ohne** Passwoerter, nur die Angabe ob eines da ist."""
    return {"konten": db.mailkonten()}


@app.post("/api/mailkonten")
async def api_mailkonto_speichern(request: Request):
    daten = await request.json()
    if not isinstance(daten, dict):
        return JSONResponse({"fehler": "Ungültige Daten."}, status_code=400)
    weg = str(daten.get("weg") or "imap").strip().lower()
    if not (daten.get("benutzer") or "").strip():
        return JSONResponse({"fehler": "Die Adresse ist Pflicht."}, status_code=400)
    # Beim API-Weg gibt es keinen Server einzutragen — der steht fest. Die
    # gleiche Pflichtangabe fuer beide Wege zu verlangen, haette den einen Weg
    # unbenutzbar gemacht.
    if weg != "api" and not (daten.get("host") or "").strip():
        return JSONResponse({"fehler": "Server ist beim Weg IMAP Pflicht."},
                            status_code=400)
    # Ins Feld „Webmail-Adresse“ rutscht leicht die E-Mail-Adresse. Als Link
    # waere das ein relativer Pfad: Der Knopf saehe aus wie ein Link und
    # fuehrte ins Nichts. Ein fehlendes „https://“ ist dagegen ein Vertipper,
    # kein Denkfehler — das wird ergaenzt statt bemaengelt.
    web = (daten.get("webmail") or "").strip()
    if web and web[:7].lower() != "http://" and web[:8].lower() != "https://":
        if "@" in web.split("/")[0]:
            return JSONResponse(
                {"fehler": "Das sieht nach einer E-Mail-Adresse aus. Hier "
                           "gehört die Web-Adresse der Webmail hin, z. B. "
                           "https://webmail.anbieter.de — oder das Feld bleibt leer."},
                status_code=400)
        web = "https://" + web
    daten["webmail"] = web
    kennung = db.mailkonto_speichern(daten, benutzer(request))
    cache.sofort("mail")
    log.info("Mail-Postfach %s gespeichert von %s", kennung, benutzer(request))
    return {"id": kennung, "konten": db.mailkonten()}


@app.delete("/api/mailkonten/{kennung}")
def api_mailkonto_loeschen(kennung: int, request: Request):
    db.mailkonto_loeschen(kennung)
    cache.sofort("mail")
    log.info("Mail-Postfach %s gelöscht von %s", kennung, benutzer(request))
    return {"konten": db.mailkonten()}


@app.post("/api/mailkonten/{kennung}/pruefen")
def api_mailkonto_pruefen(kennung: int):
    """Nur dieses eine Postfach anfassen — sonst weiss man bei drei Konten
    nicht, welches klemmt."""
    from .quellen import mail as mail_quelle
    konto = next((k for k in db.mailkonten(mit_passwort=True)
                  if k["id"] == kennung), None)
    if konto is None:
        return JSONResponse({"fehler": "Postfach nicht gefunden."}, status_code=404)
    try:
        ergebnis = mail_quelle._ein_postfach(konto)
    except Exception as fehler:                                   # noqa: BLE001
        return {"ok": False, "meldung": str(fehler)[:250]}
    return {"ok": True,
            "meldung": f"{len(ergebnis['posten'])} Nachrichten, "
                       f"{ergebnis['ungelesen']} ungelesen."}


@app.get("/api/superchat/postfaecher")
def api_superchat_postfaecher():
    """Die Postfaecher zur Auswahl in den Einstellungen."""
    from .quellen import superchat as superchat_quelle
    try:
        return {"postfaecher": superchat_quelle.postfaecher(einstellungen.umgebung())}
    except Exception as fehler:                                   # noqa: BLE001
        # 409 statt 500: Es ist kein Fehler des Servers, sondern eine fehlende
        # oder falsche Angabe — und die Oberflaeche soll das unterscheiden
        # koennen, um den richtigen Satz anzuzeigen.
        return JSONResponse({"fehler": str(fehler)[:200]}, status_code=409)


# ------------------------------------------------- Anmeldung bei Google

# Der zweite Weg zum Kalender: sich normal bei Google anmelden, statt eine
# Dienstkonto-Datei auf den Server zu legen. Was das Dashboard dabei behaelt,
# ist ein Auffrisch-Token — ein Wert, kein Dateimount, und damit etwas, das
# der Einrichtungsassistent selbst besorgen kann.
#
# Absichtlich ohne fremde Bibliothek: Der Tausch von Code gegen Token ist ein
# einziger POST. `google-auth` liegt ohnehin im Abbild und erneuert danach von
# selbst; `google-auth-oauthlib` waere eine Abhaengigkeit fuer eine Handvoll
# Zeilen.
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
# Wie lange ein begonnener Anmeldevorgang gilt. Kurz, weil er nur die paar
# Sekunden ueberdauern muss, die Googles Zustimmungsseite braucht.
STATE_GUELTIG_SEK = 600


def _google_rueckweg(request: Request) -> str:
    """Die Adresse, die in der Google-Konsole eingetragen sein muss.

    Aus der laufenden Anfrage gebildet, nicht aus der Konfiguration: Dann
    stimmt sie auch bei einer zweiten Instanz oder unter einem neuen Namen,
    ohne dass jemand daran denken muss.
    """
    return str(request.base_url).rstrip("/") + "/oauth/google/zurueck"


@app.get("/api/google/anmeldung")
def api_google_stand(request: Request):
    from .quellen import kalender as kalender_quelle
    umg = einstellungen.umgebung()
    steht = kalender_quelle.angemeldet(umg)
    # Wer angemeldet ist, aendert sich nicht von selbst — deshalb einmal bei
    # Google nachfragen und den Namen merken. Ohne das ginge waehrend des
    # Wartens auf die Zustimmung alle drei Sekunden ein Aufruf hinaus.
    wer = db.kv_lesen("google_konto", "") if steht else ""
    fehler = ""
    if steht and not wer:
        try:
            wer = kalender_quelle.konto(umg)
            if wer:
                db.kv_schreiben("google_konto", wer)
        except Exception as f:                                    # noqa: BLE001
            fehler = kalender_quelle._lesbar(f)
    return {
        "angemeldet": steht,
        "konto": wer,
        "fehler": fehler,
        "client_da": bool((umg.get("GOOGLE_CLIENT_ID") or "").strip()
                          and (umg.get("GOOGLE_CLIENT_SECRET") or "").strip()),
        "rueckweg": _google_rueckweg(request),
        # Damit die Oberflaeche sagen kann, dass die Karte auch ohne Anmeldung
        # laeuft — sonst wirkt ein Dienstkonto wie ein Fehler.
        "dienstkonto": bool(kalender_quelle._schluesseldatei(umg)),
    }


@app.post("/api/google/anmeldung")
def api_google_start(request: Request):
    import secrets
    from urllib.parse import urlencode
    from .quellen import kalender as kalender_quelle

    umg = einstellungen.umgebung()
    client = (umg.get("GOOGLE_CLIENT_ID") or "").strip()
    if not client or not (umg.get("GOOGLE_CLIENT_SECRET") or "").strip():
        return JSONResponse(
            {"fehler": "Erst Client-ID und Client-Geheimnis eintragen und speichern."},
            status_code=409)
    state = secrets.token_urlsafe(32)
    db.kv_schreiben("google_state", f"{state}|{datetime.now().isoformat(timespec='seconds')}")
    frage = urlencode({
        "client_id": client,
        "redirect_uri": _google_rueckweg(request),
        "response_type": "code",
        "scope": kalender_quelle.SCOPE,
        # Der state kommt unveraendert zurueck und ist der einzige Beleg, dass
        # die Rueckmeldung zu einem Vorgang dieses Dashboards gehoert.
        "state": state,
        # offline + consent: Nur so kommt ueberhaupt ein Auffrisch-Token
        # zurueck. Ohne "consent" laesst Google es beim zweiten Mal weg, und
        # dann steht man mit einem Zugang da, der in einer Stunde endet.
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    })
    log.info("Google-Anmeldung begonnen von %s", benutzer(request))
    return {"adresse": f"{GOOGLE_AUTH_URL}?{frage}"}


@app.post("/api/google/abmelden")
def api_google_abmelden(request: Request):
    einstellungen.setzen({}, benutzer(request), ["GOOGLE_REFRESH_TOKEN"])
    db.kv_schreiben("google_state", "")
    db.kv_schreiben("google_konto", "")
    cache.sofort("kalender")
    log.info("Google-Anmeldung geloest von %s", benutzer(request))
    return {"angemeldet": False}


@app.get("/api/google/kalender")
def api_google_kalender():
    """Die Kalender zur Auswahl — dasselbe Muster wie bei den Postfaechern."""
    from .quellen import kalender as kalender_quelle
    try:
        return {"kalender": kalender_quelle.kalenderliste(einstellungen.umgebung())}
    except Exception as fehler:                                   # noqa: BLE001
        return JSONResponse({"fehler": kalender_quelle._lesbar(fehler)},
                            status_code=409)


def _google_seite(titel: str, text: str, gut: bool) -> HTMLResponse:
    """Die Seite, auf der Google den Browser abliefert.

    Bewusst eine eigene, winzige Seite statt einer Weiterleitung ins
    Dashboard: Der Vorgang laeuft in einem zweiten Tab, und der soll sich
    schliessen lassen, ohne dass man den ersten verliert.
    """
    farbe = "#1f9d61" if gut else "#dc3b3b"
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8>"
        f"<title>{titel}</title>"
        "<style>body{font:16px/1.5 system-ui,sans-serif;margin:3rem auto;max-width:34rem;"
        "padding:0 1rem;color:#16202b}h1{font-size:1.3rem}"
        f"h1{{color:{farbe}}}</style>"
        f"<h1>{titel}</h1><p>{text}</p>"
        "<p><button onclick=\"window.close()\">Fenster schließen</button></p>",
        status_code=200 if gut else 400)


@app.get("/oauth/google/zurueck", response_class=HTMLResponse)
def oauth_google_zurueck(request: Request):
    import json as _json
    import urllib.error
    import urllib.parse
    import urllib.request
    from .quellen import kalender as kalender_quelle

    fehler = request.query_params.get("error")
    if fehler:
        return _google_seite("Nicht angemeldet",
                             f"Google hat abgelehnt: {fehler}. Du kannst das "
                             "Fenster schließen und es erneut versuchen.", False)

    code = request.query_params.get("code") or ""
    state = request.query_params.get("state") or ""
    gemerkt = db.kv_lesen("google_state", "")
    # Der state ist einmalig und wird sofort verbraucht — ein zweiter Aufruf
    # mit demselben Wert darf nichts mehr bewirken.
    db.kv_schreiben("google_state", "")
    if not code or not state or "|" not in gemerkt or state != gemerkt.split("|", 1)[0]:
        return _google_seite("Abgelehnt",
                             "Diese Rückmeldung gehört zu keinem Anmeldevorgang "
                             "dieses Dashboards. Bitte in den Einstellungen neu "
                             "beginnen.", False)
    try:
        begonnen = datetime.fromisoformat(gemerkt.split("|", 1)[1])
    except ValueError:
        begonnen = datetime.now()
    if (datetime.now() - begonnen).total_seconds() > STATE_GUELTIG_SEK:
        return _google_seite("Zu spät",
                             "Der Anmeldevorgang ist älter als zehn Minuten. "
                             "Bitte in den Einstellungen neu beginnen.", False)

    umg = einstellungen.umgebung()
    rumpf = urllib.parse.urlencode({
        "code": code,
        "client_id": (umg.get("GOOGLE_CLIENT_ID") or "").strip(),
        "client_secret": (umg.get("GOOGLE_CLIENT_SECRET") or "").strip(),
        "redirect_uri": _google_rueckweg(request),
        "grant_type": "authorization_code",
    }).encode()
    anfrage = urllib.request.Request(
        kalender_quelle.TOKEN_URL, data=rumpf,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(anfrage, timeout=20) as antwort:
            daten = _json.loads(antwort.read().decode("utf-8"))
    except urllib.error.HTTPError as f:
        roh = f.read().decode("utf-8", "replace")[:300]
        log.warning("Google-Tausch fehlgeschlagen: %s", roh)
        return _google_seite("Fehlgeschlagen", kalender_quelle._lesbar(
            Exception(roh)), False)
    except Exception as f:                                        # noqa: BLE001
        return _google_seite("Fehlgeschlagen", kalender_quelle._lesbar(f), False)

    token = (daten.get("refresh_token") or "").strip()
    if not token:
        # Kommt vor, wenn dieselbe Zustimmung schon einmal erteilt wurde und
        # Google sie stillschweigend wiederverwendet. Der Zugang waere dann
        # nach einer Stunde tot — deshalb hier abbrechen statt speichern.
        return _google_seite(
            "Kein dauerhafter Zugang",
            "Google hat keine dauerhafte Anmeldung mitgeschickt. Entziehe dem "
            "Dashboard den Zugriff unter myaccount.google.com/permissions und "
            "melde dich danach neu an.", False)

    einstellungen.setzen({"GOOGLE_REFRESH_TOKEN": token}, benutzer(request))
    # Der gemerkte Name gehoert zur alten Anmeldung — sonst stuende nach einem
    # Kontowechsel der falsche Name da.
    db.kv_schreiben("google_konto", "")
    cache.sofort("kalender")
    log.info("Google-Anmeldung abgeschlossen von %s", benutzer(request))
    return _google_seite("Angemeldet",
                         "Das Dashboard darf deinen Kalender jetzt lesen. Du "
                         "kannst dieses Fenster schließen — die Einstellungen "
                         "im anderen Tab holen den Stand von selbst nach.", True)


# ------------------------------------------------------------------- Update

# Die Anforderung ist eine Datei im eigenen Datenordner, keine Docker-Aktion.
#
# Der Container koennte sich nicht selbst neu bauen, ohne den Docker-Socket zu
# bekommen — und das waere Root auf einem Server mit zwei Dutzend fremder
# Dienste, erreichbar fuer jeden, der sich hier anmelden kann. Stattdessen legt
# das Dashboard eine Anforderung ab; ausgefuehrt wird sie draussen von
# /opt/smg-update/update-wache.sh, die jede Minute nachsieht. Sie fasst
# ausschliesslich den Ordner DIESER Instanz an, nie `.env`, nie `data/`, und
# spielt bei einem Fehlschlag den vorherigen Stand zurueck.
UPDATE_ANFORDERUNG = Path(os.environ.get("BUCHHALTUNG_DB",
                                         "/data/buchhaltung.sqlite3")).parent / "update-angefordert"
UPDATE_STAND = UPDATE_ANFORDERUNG.parent / "update-stand.json"


def _fassung() -> str:
    """Die laufende Version — aus der Datei neben dem Programm.

    Was im Ordner liegt, IST der Stand. Eine Merkdatei daneben koennte nach
    einem misslungenen Update das Falsche behaupten.
    """
    try:
        return (BASIS.parent / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _punkte(zeilen, nummer: str = "") -> list:
    """Die Stichpunkte eines Abschnitts der Änderungsliste.

    Ohne `nummer` der erste Abschnitt mit einer Zahl — ganz oben steht die
    Sammelstelle „Unveröffentlicht“, die noch keine Fassung ist. Mit `nummer`
    genau der Abschnitt dieser Version.
    """
    raus, drin = [], False
    for zeile in zeilen:
        if zeile.startswith("## "):
            if drin:
                break
            kopf = zeile[3:].strip()
            if nummer:
                # „## 1.3.1 — 12.09.2026“: die Nummer steht vorn.
                if not (kopf == nummer or kopf.startswith(nummer + " ")):
                    continue
            elif not kopf[:1].isdigit():
                continue
            drin = True
            continue
        if not drin or not zeile.strip():
            continue
        zeile = zeile.strip()
        # Ein Punkt bricht in der Datei ueber mehrere Zeilen um. Ohne das
        # Zusammenziehen stuenden auf der Seite Satzfetzen.
        # Ein Aufzaehlungszeichen ist "-" oder "*" MIT Leerzeichen dahinter.
        # Ohne diese Bedingung faengt eine Folgezeile, die mit **fett**
        # beginnt, einen neuen Punkt an und zerreisst den Satz.
        if zeile[:2] in ("- ", "* "):
            raus.append(zeile[2:].strip())
        elif raus:
            raus[-1] += " " + zeile
    return [z.replace("**", "") for z in raus][:12]


def _aenderungen_hier() -> list:
    """Was die LAUFENDE Version gebracht hat — der oberste Abschnitt der
    Änderungsliste, die neben dem Programm liegt."""
    try:
        zeilen = (BASIS.parent / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return _punkte(zeilen)


# --------------------------------------------- Gibt es eine neuere Version?

# Frueher wusste das nur der Server: Eine Wache auf dem Host holte per `git
# fetch` den Stand und schrieb ihn in eine Datei. Das dauerte im besten Fall
# eine Minute und im Normalfall bis zum naechsten Tag — denn ausgeloest wurde
# es nur von Hand oder einmal taeglich.
#
# Zum ERKENNEN reicht ein Blick auf eine Datei mit sechs Zeichen. Der Container
# holt sie selbst; gemessen 0,03 Sekunden. Das AUFSPIELEN bleibt bei der Wache
# — dafuer braucht es Rechte, die im Container nichts zu suchen haben.
UPDATE_REPO = (os.environ.get("UPDATE_REPO")
               or "openkairo/mitarbeiter-dashboard").strip().strip("/")
# Als Konstante, damit die Pruefung im Test auf einen eigenen Mini-Server
# zeigen kann — sonst liesse sie sich nur mit echtem GitHub pruefen.
UPDATE_ROH = (os.environ.get("UPDATE_ROH_URL")
              or "https://raw.githubusercontent.com").rstrip("/")
# So lange gilt ein geholter Stand. Ein offener Tab fragt die Uebersicht im
# Minutentakt ab; ohne Sperre waeren das sechzig Abrufe in der Stunde fuer
# eine Zahl, die sich selten aendert. „Nachsehen" umgeht die Sperre.
UPDATE_SPERRE_SEK = 600


def _nummer(text: str):
    """„1.3.10“ als Zahlentupel. Leer, wenn es keine Versionsnummer ist.

    Als Text verglichen waere „1.3.9“ groesser als „1.3.10“ — der Fehler
    faellt erst bei der zehnten Korrektur auf und dann als „kein Update da“.
    """
    teile = (text or "").strip().split(".")
    if not teile or not all(t.isdigit() for t in teile):
        return ()
    return tuple(int(t) for t in teile)


def _roh_holen(datei: str, zeit: int = 5, frisch: str = "") -> str:
    """Eine Datei aus dem Repo. `frisch` haengt als Fragezeichen-Anhang an.

    Der Auslieferdienst von GitHub gibt eine Datei einige Minuten lang aus
    seinem Zwischenspeicher heraus — am 12.09.2026 kam die Aenderungsliste
    noch mit dem Stand der Vorversion zurueck, obwohl die Nummer daneben
    schon die neue war. Ein Anhang, der sich aendert, umgeht den Speicher.
    """
    url = f"{UPDATE_ROH}/{UPDATE_REPO}/main/{datei}"
    if frisch:
        url += "?v=" + urllib.parse.quote(frisch, safe="")
    anfrage = urllib.request.Request(url, headers={
        # GitHub weist Anfragen ohne Kennung ab; ausserdem soll im Zweifel
        # nachvollziehbar sein, wer da fragt.
        "User-Agent": f"smg-dashboard/{_fassung() or 'unbekannt'}"})
    with urllib.request.urlopen(anfrage, timeout=zeit) as antwort:
        return antwort.read().decode("utf-8", "replace")


def _fernstand(frisch: bool = False) -> dict:
    """Was auf GitHub liegt — gemerkt, damit nicht jede Anfrage hinausgeht.

    Gibt IMMER etwas zurueck. Ist GitHub nicht erreichbar, gilt der zuletzt
    bekannte Stand: Ein Netzfehler ist kein Grund, die Seite mit einer
    Fehlermeldung zu behelligen, die niemand beheben kann.
    """
    gemerkt = {}
    try:
        gemerkt = json.loads(db.kv_lesen("update_fern", "") or "{}")
    except ValueError:
        gemerkt = {}
    if not frisch and gemerkt.get("am"):
        try:
            alter = (datetime.now() - datetime.fromisoformat(gemerkt["am"])).total_seconds()
            if 0 <= alter < UPDATE_SPERRE_SEK:
                return gemerkt
        except ValueError:
            pass

    ergebnis = dict(gemerkt)
    try:
        # Die Nummer MUSS aktuell sein — deshalb der Zeitstempel als Anhang.
        # Sechs Zeichen alle zehn Minuten; am Zwischenspeicher vorbei kostet
        # das nichts und erspart den Fall "die Nummer ist von vorgestern".
        fern = _roh_holen("VERSION", frisch=str(int(time.time()))).strip()
        ergebnis["fassung"] = fern
        ergebnis["fehler"] = ""
        # Die Aenderungsliste kostet das Vierzigfache und interessiert nur,
        # wenn es ueberhaupt etwas Neues gibt.
        if _nummer(fern) > _nummer(_fassung()):
            try:
                ergebnis["aenderungen"] = _punkte(
                    _roh_holen("CHANGELOG.md", 8, frisch=fern).splitlines(), fern)
            except Exception as fehler:                           # noqa: BLE001
                log.info("Änderungsliste nicht geholt: %s", fehler)
                ergebnis["aenderungen"] = []
        else:
            ergebnis["aenderungen"] = []
        ergebnis["am"] = datetime.now().isoformat(timespec="seconds")
    except Exception as fehler:                                   # noqa: BLE001
        # Kein Netz, GitHub weg, Zeitueberschreitung: Der alte Stand bleibt
        # stehen, und `am` bleibt alt — damit wird beim naechsten Mal wieder
        # nachgesehen statt zehn Minuten zu warten.
        log.info("Versionsabgleich nicht möglich: %s", fehler)
        ergebnis["fehler"] = str(fehler)[:160]
    db.kv_schreiben("update_fern", json.dumps(ergebnis, ensure_ascii=False))
    return ergebnis


def _update_lage(frisch: bool = False) -> dict:
    """Die eine Wahrheit: Liegt eine neuere Version bereit?

    Der Nummernvergleich schlaegt die Zustandsdatei der Wache. Nach einem
    Aufspielen steht dort noch „verfuegbar“, obwohl die Nummern laengst gleich
    sind — die Datei weiss nur, was beim letzten Lauf war.
    """
    hier, fern = _fassung(), _fernstand(frisch)
    neu = fern.get("fassung") or ""
    if _nummer(neu) and _nummer(hier):
        verfuegbar = _nummer(neu) > _nummer(hier)
        meldung = (f"Version {neu} liegt bereit — hier läuft {hier}."
                   if verfuegbar else f"Version {hier} ist die neueste.")
        return {"verfuegbar": verfuegbar, "meldung": meldung,
                "neue_fassung": neu if verfuegbar else "",
                "aenderungen": fern.get("aenderungen") or [] if verfuegbar else [],
                "am": fern.get("am") or "", "fehler": fern.get("fehler") or ""}
    # Ohne brauchbare Nummern bleibt nur, was die Wache zuletzt vermerkt hat.
    stand = _update_stand()
    return {"verfuegbar": stand.get("zustand") == "verfuegbar",
            "meldung": stand.get("meldung") or "",
            "neue_fassung": stand.get("neue_fassung") or "",
            "aenderungen": stand.get("aenderungen") or [],
            "am": stand.get("am") or "", "fehler": fern.get("fehler") or ""}


def _update_hinweis() -> dict:
    """Nur das, was die Seitenleiste braucht: liegt etwas bereit?"""
    lage = _update_lage()
    return {"verfuegbar": lage["verfuegbar"], "meldung": lage["meldung"]}


def _update_stand() -> dict:
    try:
        return json.loads(UPDATE_STAND.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------ Einrichtungsassistent

# Ein frisch installiertes Dashboard ist leer — richtig so, aber ohne Fuehrung
# steht man davor und weiss nicht, wo man anfaengt. Der Assistent fragt zuerst
# den Namen und geht danach die Karten durch: je Karte die Felder, die sie
# braucht, und ein Knopf zum Pruefen. Er zeigt sich nur, solange nichts
# eingerichtet ist, und laesst sich in den Einstellungen wieder oeffnen.

def _einrichtung() -> dict:
    umg = einstellungen.umgebung()
    felder = einstellungen.uebersicht()
    karte_je_gruppe = einstellungen.GRUPPE_KARTE

    schritte = []
    for modul in list(quellen.REGISTRY) + list(quellen.WERKZEUGE):
        gruppen = [g for g, k in karte_je_gruppe.items() if k == modul.NAME]
        eigene = [f for f in felder if f["gruppe"] in gruppen]
        # Karten ohne eigene Felder (Bank, Widerrufe) haengen an gemounteten
        # Ordnern — dafuer gibt es im Assistenten nichts einzutragen.
        if not eigene:
            continue
        schritte.append({
            "karte": modul.NAME,
            "titel": modul.TITEL,
            "icon": modul.ICON,
            "eingerichtet": quellen.ist_eingerichtet(modul, umg),
            "braucht": list(getattr(modul, "BRAUCHT", ())),
            "felder": eigene,
        })

    # Der Posteingang hat keine Einstellungsfelder — er haengt an angelegten
    # Postfaechern. Ohne eigenen Schritt fehlte er im Assistenten ganz.
    mail_modul = quellen.BEKANNT.get("mail")
    if mail_modul is not None:
        schritte.append({
            "karte": "mail", "titel": mail_modul.TITEL, "icon": mail_modul.ICON,
            "eingerichtet": quellen.ist_eingerichtet(mail_modul, umg),
            "braucht": [], "felder": [],
            "postfaecher": True,
        })

    fertig = bool(db.kv_lesen("einrichtung_erledigt"))
    irgendwas_da = any(s["eingerichtet"] for s in schritte)
    return {
        "noetig": not fertig and not irgendwas_da,
        "erledigt": fertig,
        "person": {
            "PERSON_NAME": (umg.get("PERSON_NAME") or "").strip(),
            "TITEL": (umg.get("TITEL") or "").strip(),
            "FIRMA": (umg.get("FIRMA") or "").strip(),
            "ANSPRECHPARTNER": (umg.get("ANSPRECHPARTNER") or "").strip(),
        },
        "schritte": schritte,
    }


@app.get("/api/einrichtung")
def api_einrichtung():
    return _einrichtung()


@app.post("/api/einrichtung/fertig")
def api_einrichtung_fertig(request: Request):
    """Der Assistent ist durch — er meldet sich nicht mehr von selbst.

    Bewusst ein eigener Merker und nicht „irgendeine Karte ist eingerichtet":
    Wer bewusst nur mit zwei Karten arbeitet, soll nicht bei jedem Laden
    gefragt werden, ob er nicht doch noch etwas einrichten will.
    """
    db.kv_schreiben("einrichtung_erledigt", datetime.now().isoformat(timespec="seconds"))
    log.info("Einrichtungsassistent abgeschlossen von %s", benutzer(request))
    return {"erledigt": True}


@app.post("/api/einrichtung/erneut")
def api_einrichtung_erneut():
    db.kv_schreiben("einrichtung_erledigt", "")
    return _einrichtung()


@app.get("/api/update")
def api_update_stand(request: Request):
    # ?frisch=1 kommt vom Knopf „Nachsehen“ und umgeht die Sperrzeit. Das
    # Nachsehen geht seitdem direkt hinaus, statt eine Markerdatei abzulegen,
    # auf die eine Wache erst in der naechsten Minute stoesst.
    frisch = request.query_params.get("frisch") in ("1", "ja", "true")
    lage = _update_lage(frisch)
    stand = _update_stand()
    return {"stand": stand,
            # Was die Wache zuletzt TAT (laeuft, fehlgeschlagen, aufgespielt)
            # steht in `stand`; ob etwas BEREITLIEGT, sagt `lage` — das ist
            # frisch verglichen und hat darum Vorrang.
            "lage": lage,
            "fassung": _fassung(),
            "aenderungen_hier": _aenderungen_hier(),
            "angefordert": UPDATE_ANFORDERUNG.exists(),
            # Ohne Wache passiert nach dem Knopfdruck nichts — dann muss die
            # Seite das sagen und nicht ewig „läuft“ anzeigen.
            "eingerichtet": bool(stand) or UPDATE_ANFORDERUNG.parent.is_dir(),
            "instanz": profil.INSTANZ}


@app.post("/api/update")
async def api_update_anfordern(request: Request):
    daten = {}
    try:
        daten = await request.json()
    except Exception:                                             # noqa: BLE001
        pass
    modus = "pruefen" if (daten or {}).get("nur_pruefen") else "aufspielen"
    if UPDATE_ANFORDERUNG.exists():
        return JSONResponse({"fehler": "Es läuft schon eine Anforderung."},
                            status_code=409)
    try:
        UPDATE_ANFORDERUNG.parent.mkdir(parents=True, exist_ok=True)
        UPDATE_ANFORDERUNG.write_text(modus, encoding="utf-8")
    except OSError as fehler:
        return JSONResponse({"fehler": f"Anforderung ließ sich nicht ablegen: {fehler}"},
                            status_code=500)
    log.info("Update (%s) angefordert von %s", modus, benutzer(request))
    return {"angefordert": True, "modus": modus,
            "hinweis": ("Der Server sieht jede Minute nach. "
                        + ("Das Prüfen dauert ein paar Sekunden."
                           if modus == "pruefen" else
                           "Das Aufspielen dauert ein bis zwei Minuten; "
                           "die Seite ist dabei kurz nicht erreichbar."))}


@app.get("/api/webhook")
def api_webhook_stand():
    """Ist ein Webhook eingerichtet, und hat die letzte Meldung geklappt?"""
    umgebung = einstellungen.umgebung()
    url = (umgebung.get("ANTWORT_WEBHOOK_URL") or "").strip()
    return {"eingerichtet": bool(url),
            "bearer": bool((umgebung.get("ANTWORT_WEBHOOK_BEARER") or "").strip()),
            "signiert": bool(umgebung.get("ANTWORT_WEBHOOK_SECRET")),
            "stand": webhook.stand()}


@app.post("/api/webhook/test")
def api_webhook_test(request: Request):
    """Eine Probemeldung schicken — mit `ereignis: probe`, damit der Empfaenger
    sie nicht fuer eine echte Antwort haelt."""
    umgebung = einstellungen.umgebung()
    losgeschickt = webhook.melden(umgebung, {
        "ereignis": "probe",
        "nachricht_id": 0,
        "frage": "Probemeldung aus den Settings",
        "antwort": "Wenn du das liest, kommt der Webhook an.",
        "von": benutzer(request),
        "am": datetime.now().isoformat(timespec="seconds"),
        "karte": "", "dringlichkeit": "info",
        "dashboard": str(request.base_url).rstrip("/"),
    })
    if not losgeschickt:
        return JSONResponse({"fehler": "Es ist keine Webhook-Adresse hinterlegt."},
                            status_code=400)
    return {"status": "losgeschickt",
            "hinweis": "Läuft im Hintergrund. In ein paar Sekunden den Stand ansehen."}


@app.post("/api/einstellungen/pruefen/{karte}")
def api_einstellungen_pruefen(karte: str, request: Request):
    """Einen echten Abruf machen und sagen, ob er klappt.

    Bewusst der **echte** Abruf des Moduls und kein eigener Test-Aufruf: Sonst
    prueft man am Ende etwas anderes, als die Karte spaeter tut.
    """
    if karte not in quellen.BEKANNT:
        return JSONResponse({"fehler": f"Karte „{karte}“ gibt es hier nicht."},
                            status_code=404)
    ok, meldung, hinweis = quellen.pruefen(karte, einstellungen.umgebung())
    return {"ok": ok, "meldung": (meldung + (f" {hinweis}" if hinweis else ""))[:300]}


# ------------------------------------------------------------------- Werkzeug

@app.post("/api/faq")
async def api_faq(request: Request):
    """Eine Kundenfrage in der Wissensbasis nachschlagen.

    Kein Cache und kein Takt: Es gibt nichts, was veralten koennte, und eine
    Frage entsteht erst, wenn jemand sie stellt.
    """
    from .quellen import faq as faq_quelle
    if "faq" not in quellen.WERKZEUG_NACH_NAME:
        return JSONResponse({"fehler": "Diese Karte gibt es hier nicht."},
                            status_code=404)
    daten = await request.json()
    frage = str(daten.get("frage") or "").strip()[:500]
    if not frage:
        return JSONResponse({"fehler": "Keine Frage eingegeben."}, status_code=400)
    umgebung = einstellungen.umgebung()
    if not (umgebung.get("FAQ_MCP_URL") or "").strip():
        return JSONResponse(
            {"fehler": "Kein FAQ-Zugang hinterlegt — Settings → FAQ."},
            status_code=409)
    try:
        ergebnis = faq_quelle.antwort(umgebung, frage)
    except Exception as fehler:                                   # noqa: BLE001
        log.warning("WARN FAQ: %s", fehler)
        return JSONResponse({"fehler": f"{fehler}"[:250]}, status_code=502)
    # Die Frage selbst gehoert nicht ins Log — sie kann Kundendaten enthalten.
    log.info("FAQ nachgeschlagen von %s (%d Zeichen), gefunden: %s",
             benutzer(request), len(frage), ergebnis["gefunden"])
    return ergebnis


# --------------------------------------------------------------------- Seiten

@app.get("/", response_class=HTMLResponse)
def start(request: Request):
    arbeitszeit.besuch_merken()
    # Die Seite selbst darf NICHT im Browser-Cache liegen bleiben.
    #
    # CSS und JS tragen ein ?v=<Hash> und duerfen deshalb ewig gecacht werden.
    # Das nuetzt aber nichts, wenn der Browser die HTML-Seite von gestern
    # ausliefert: Die verweist dann auf das alte ?v= und laedt hartnaeckig die
    # alte Fassung. Genau das ist am 09.09.2026 passiert — die Seite lief mit
    # `app.js?v=d5fcc3c2`, waehrend der Server schon `3b8c30f5` auslieferte,
    # und eine Aenderung schien wirkungslos zu sein.
    umg = einstellungen.umgebung()
    antwort = templates.TemplateResponse("index.html", {
        "request": request,
        "v": STATIK_VERSION,
        "benutzer": benutzer(request),
        "karten": [{"name": m.NAME, "titel": m.TITEL, "icon": m.ICON,
                    "link_text": getattr(m, "LINK_TEXT", "")}
                   for m in quellen.REGISTRY],
        "werkzeuge": [{"name": m.NAME, "titel": m.TITEL, "icon": m.ICON,
                       "link": getattr(m, "LINK", ""),
                       "link_text": getattr(m, "LINK_TEXT", ""),
                       "eingerichtet": quellen.ist_eingerichtet(m, umg)}
                      for m in quellen.WERKZEUGE],
        "kopfzahlen": quellen.KOPFZAHLEN,
        # Nicht das Modul selbst, sondern die GELTENDEN Werte: Was jemand im
        # Assistenten eintraegt, soll beim naechsten Laden dastehen und nicht
        # erst nach einem Neustart.
        "profil": {
            "NAME": (umg.get("PERSON_NAME") or profil.NAME).strip(),
            "TITEL": (umg.get("TITEL") or profil.TITEL).strip(),
            "FIRMA": (umg.get("FIRMA") or profil.FIRMA).strip(),
            "ANSPRECHPARTNER": (umg.get("ANSPRECHPARTNER")
                                or profil.ANSPRECHPARTNER).strip(),
            "INSTANZ": profil.INSTANZ,
            "MARKE": ((umg.get("TITEL") or profil.TITEL).strip()[:1] or "D").upper(),
        },
        "heute": date.today().strftime("%d.%m.%Y"),
    })
    antwort.headers["Cache-Control"] = "no-cache, must-revalidate"
    return antwort


@app.get("/abgemeldet", response_class=HTMLResponse)
def abgemeldet():
    """Basic-Auth kennt kein Abmelden. Der Umweg: eine Anfrage mit absichtlich
    falschen Daten, danach landet der Browser hier — auf einem Router ohne
    Anmeldung, sonst fragte Traefik sofort wieder nach dem Passwort."""
    return HTMLResponse(
        "<!doctype html><html lang=de><meta charset=utf-8>"
        "<title>Abgemeldet</title>"
        "<style>body{font:17px/1.6 system-ui;background:#eef2f8;color:#16202b;"
        "display:grid;place-items:center;height:100vh;margin:0}"
        "div{background:#fff;padding:2.5rem 3rem;border-radius:16px;text-align:center;"
        "box-shadow:0 8px 30px rgba(20,40,80,.10)}a{color:#2f6fed}</style>"
        f"<div><h1>Abgemeldet</h1><p>Du bist aus dem {profil.TITEL}-Dashboard "
        "abgemeldet.</p><p><a href='/'>Wieder anmelden</a></p></div>")
