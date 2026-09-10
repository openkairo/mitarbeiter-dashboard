"""Offene Kundengespraeche im Superchat-Postfach Buchhaltung.

**Jeder Lauf blaettert die ganze Liste durch.** Das klingt teuer und ist es
nicht: 246 Seiten mit 24.588 Gespraechen brauchen **18 Sekunden** (gemessen
09.09.2026). Dafuer stimmt das Ergebnis immer.

Der erste Entwurf merkte sich stattdessen den letzten Cursor und blaetterte nur
den Rest — und lag damit zweimal daneben:

  1. Die Liste wurde je Lauf neu aus dem Blaetterergebnis gebaut. Ab dem
     zweiten Lauf kam von dort fast nichts mehr, und vorher gefundene Vorgaenge
     fielen heraus. Die Karte zeigte einen von zwei.
  2. Ein Gespraech, das jemand **in** das Postfach verschiebt, entsteht nicht
     neu am Ende der Liste — es steht laengst irgendwo in der Mitte. Vorwaerts
     blaettern findet es nie. Genau das ist am 09.09.2026 aufgefallen.

Beides ist mit dem vollen Durchlauf konstruktionsbedingt erledigt: Was die
Liste sagt, gilt. Kein Cursor, kein Nachpflegen, keine zweite Wahrheit.

Filtern kann die API nicht — `inbox_id`, `status`, `sort` und `filter[...]`
werden stillschweigend ignoriert (durchprobiert am 09.09.2026, alle liefern
dieselben Ergebnisse). Auch `GET /conversations/{id}/messages` ist
Enterprise-Kunden vorbehalten.

Teamchats — auch die Gruppe Buchhaltung, in der die Bot-Meldungen landen — sind
ueber die API gar nicht erreichbar. Dafuer gibt es nur den Direktlink.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from .. import db
from ..posten import posten, sortieren, tage_alt

NAME = "superchat"
TITEL = "Superchat"
ICON = "💬"
TTL = 600
ANLAUF = 15
# Kein festes Postfach im Code: Welche ueberwacht werden, sagt
# SUPERCHAT_INBOX_ID — eine Kennung oder mehrere, kommagetrennt. Der Fusslink
# entsteht daraus (siehe fetch), damit er nie ins falsche Postfach zeigt.
# Ohne diese Einstellungen kann die Karte nichts holen — dann erscheint
# sie gar nicht erst, statt „nichts zu tun“ zu behaupten.
BRAUCHT = ("SUPERCHAT_API_KEY", "SUPERCHAT_INBOX_ID")

LINK = None
LINK_TEXT = "Superchat"
KOPFZAHL = ("Offen", "Älter als 3 Tage", "länger als 3 Tage")
# Keine Vorgabe: Eine fremde Postfach-Kennung im Code waere entweder
# falsch oder ein Datenleck. Ohne Eintrag sagt die Karte, was fehlt.
VORGABE_POSTFACH = ""

API = "https://api.superchat.com/v1.0"
TIMEOUT = 30
MAX_SEITEN = 500          # Notbremse; gebraucht werden rund 250
ALARM_AB_TAGEN = 3


def _hole(pfad: str, key: str):
    req = urllib.request.Request(f"{API}{pfad}",
                                 headers={"X-API-KEY": key, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as antwort:
        return json.loads(antwort.read().decode())


def _merker(schluessel: str) -> dict:
    try:
        return json.loads(db.kv_lesen(schluessel, "{}") or "{}")
    except json.JSONDecodeError:
        return {}


def _hat_nachrichten(kennung: str, key: str) -> bool:
    """Steht in dem Gespraech ueberhaupt etwas?

    Die API fuehrt Gespraeche ohne eine einzige Nachricht als `open`; die
    Oberflaeche zeigt sie zu Recht nicht an (am 31.08.2026 waren 10 von 14
    vermeintlich offenen Chats solche Huellen). Erkannt werden sie am Export:
    Bei einer Huelle lehnt er mit 400 ab, und zwar bevor ein Auftrag entsteht.
    """
    req = urllib.request.Request(
        f"{API}/conversations/{kennung}/export", method="POST",
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        data=json.dumps({"start": "2020-01-01T00:00:00Z"}).encode())
    try:
        urllib.request.urlopen(req, timeout=TIMEOUT).read()
        return True
    except urllib.error.HTTPError as fehler:
        return fehler.code != 400
    except Exception:                                             # noqa: BLE001
        return True            # im Zweifel anzeigen — lieber zu viel als verschluckt


def _name(kontakt_id: str, key: str, zwischen: dict) -> str:
    """Namen zum Kontakt holen; das Gespraech selbst fuehrt nur `{id, url}`."""
    if not kontakt_id:
        return "Kontakt"
    if kontakt_id in zwischen:
        return zwischen[kontakt_id]
    try:
        d = _hole(f"/contacts/{kontakt_id}", key)
    except Exception:                                             # noqa: BLE001
        return "Kontakt"
    teile = [(d.get("first_name") or "").strip(), (d.get("last_name") or "").strip()]
    name = " ".join(t for t in teile if t)
    if not name:
        for griff in (d.get("handles") or []):
            name = (griff.get("value") or griff.get("identifier") or "").strip()
            if name:
                break
    zwischen[kontakt_id] = (name or "Kontakt")[:80]
    return zwischen[kontakt_id]


def _letzte_aktivitaet(g: dict) -> str | None:
    """Wann hat der Kunde zuletzt geschrieben? Als ISO-Datum, sonst None.

    Die API nennt kein Datum fuer offene Gespraeche — aber bei WhatsApp das
    Ende des 24-Stunden-Servicefensters (`time_window.open_until`). Minus 24
    Stunden ist das die letzte Kundennachricht.

    Am 09.09.2026 gegen die Superchat-Oberflaeche geprueft, auf den Tag genau:
    open_until 05.09. 15:46 -> "Freitag" (04.09.), open_until 25.08. 13:23 ->
    "24.08."

    Nur fuer WhatsApp — andere Kanaele haben dieses Fenster nicht oder ein
    anderes, und ein falsch berechnetes Alter waere schlimmer als keines.
    """
    if (g.get("channel") or {}).get("type") != "whats_app":
        return None
    bis = (g.get("time_window") or {}).get("open_until")
    if not bis:
        return None
    try:
        ende = datetime.fromisoformat(str(bis).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (ende - timedelta(hours=24)).date().isoformat()


def _alle_offenen(key: str, postfaecher: set):
    """Voller Durchlauf. Liefert (offene Gespraeche der Postfaecher, Seitenzahl).

    **Ein Durchlauf fuer alle Postfaecher.** Die API filtert nicht nach
    Postfach, es muss ohnehin jede Seite durch — zwei Postfaecher kosten
    deshalb keinen zweiten Durchgang.
    """
    treffer, seiten, cursor = [], 0, None
    while seiten < MAX_SEITEN:
        pfad = "/conversations?limit=100" + (f"&after={cursor}" if cursor else "")
        daten = _hole(pfad, key)
        seiten += 1
        for g in daten.get("results", []):
            if (g.get("inbox") or {}).get("id") not in postfaecher:
                continue
            if g.get("status") != "open":
                continue
            treffer.append(g)
        cursor = (daten.get("pagination") or {}).get("next_cursor")
        if not cursor:
            break
    return treffer, seiten


# Farbnamen, die in SUPERCHAT_FARBEN erlaubt sind. Die Oberflaeche kennt
# dieselben Namen als CSS-Klasse.
FARBEN = ("rot", "orange", "violett", "tuerkis", "magenta", "bernstein",
          "indigo", "oliv")


def _farbwuensche(env: dict) -> dict:
    """`SUPERCHAT_FARBEN` lesen: "BEZAHLEN:rot, Buchhaltung:violett".

    Was nicht genannt ist, bekommt weiter eine Farbe nach seinem Platz in der
    Liste. Ein unbekannter Farbname wird uebergangen statt die ganze Angabe zu
    verwerfen — ein Tippfehler soll nicht die uebrigen Zuordnungen kosten.
    """
    wuensche = {}
    for stueck in (env.get("SUPERCHAT_FARBEN") or "").split(","):
        name, _, farbe = stueck.partition(":")
        name, farbe = name.strip(), farbe.strip().lower()
        if name and farbe in FARBEN:
            wuensche[name] = farbe
    return wuensche


def postfaecher(env: dict) -> list:
    """Alle Postfaecher des Arbeitsbereichs — Kennung und Name, sonst nichts.

    Fuer die Auswahl in den Einstellungen: Eine Kennung wie `ib_a1B2c3D4e…`
    tippt niemand fehlerfrei ab, und die Weboberflaeche zeigt an derselben
    Stelle mal die Postfach-, mal die Gespraechskennung. Wer die falsche
    erwischt, bekommt eine still leere Karte.

    **Bewusst nur `id` und `name`.** Die API liefert zu jedem Postfach auch
    die zugeteilten Nutzer samt Mailadresse; die hat in einer Auswahlliste
    nichts zu suchen und geht deshalb gar nicht erst an den Browser.
    """
    key = (env.get("SUPERCHAT_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("Kein Superchat-API-Schlüssel hinterlegt.")
    ergebnis, cursor, seiten = [], None, 0
    while seiten < 20:
        pfad = "/inboxes?limit=100" + (f"&after={cursor}" if cursor else "")
        daten = _hole(pfad, key)
        seiten += 1
        for fach in daten.get("results", []):
            if fach.get("id"):
                ergebnis.append({"id": fach["id"],
                                 "name": (fach.get("name") or "").strip()
                                         or fach["id"]})
        cursor = (daten.get("pagination") or {}).get("next_cursor")
        if not cursor:
            break
    ergebnis.sort(key=lambda f: f["name"].lower())
    # Die Namen gleich mitmerken: Dann muss der naechste Kartenabruf sie nicht
    # noch einmal holen.
    namen = _merker("superchat_postfach_namen")
    for f in ergebnis:
        namen[f["id"]] = f["name"]
    db.kv_schreiben("superchat_postfach_namen", json.dumps(namen, ensure_ascii=False))
    return ergebnis


def _postfach_namen(key: str, kennungen: list) -> dict:
    """Wie die Postfaecher heissen — einmal geholt, dann gemerkt.

    Der Name gehoert in jede Zeile, sobald mehr als ein Postfach ueberwacht
    wird: "offen im Postfach" ohne Angabe welches waere bei zwei Quellen eine
    halbe Auskunft. Gemerkt wird er, weil er sich praktisch nie aendert.
    """
    namen = _merker("superchat_postfach_namen")
    fehlend = [k for k in kennungen if k not in namen]
    if fehlend:
        try:
            cursor = None
            while True:
                pfad = "/inboxes?limit=100" + (f"&after={cursor}" if cursor else "")
                daten = _hole(pfad, key)
                for fach in daten.get("results", []):
                    if fach.get("id"):
                        namen[fach["id"]] = (fach.get("name") or "").strip()
                cursor = (daten.get("pagination") or {}).get("next_cursor")
                if not cursor:
                    break
            db.kv_schreiben("superchat_postfach_namen",
                            json.dumps(namen, ensure_ascii=False))
        except Exception:                                         # noqa: BLE001
            pass          # Ohne Namen geht es auch — dann steht die Kennung da.
    # Rueckfall: die letzten Zeichen der Kennung. Unschoen, aber eindeutig.
    return {k: (namen.get(k) or "…" + k[-4:]) for k in kennungen}


def fetch(env: dict) -> dict:
    key = env.get("SUPERCHAT_API_KEY") or ""
    roh = (env.get("SUPERCHAT_INBOX_ID") or "").strip() or VORGABE_POSTFACH
    postfaecher = [s.strip() for s in roh.split(",") if s.strip()]
    if not key:
        return {"posten": [], "kennzahlen": {},
                "hinweis": "SUPERCHAT_API_KEY fehlt in der .env."}

    gespraeche, seiten = _alle_offenen(key, set(postfaecher))
    fach_namen = _postfach_namen(key, postfaecher)
    je_fach = {name: 0 for name in fach_namen.values()}

    # Gemerkt wird nur, was sich nicht aendert: ob ein Gespraech ueberhaupt
    # Nachrichten hat, wie der Kontakt heisst, und wann wir es zuerst gesehen
    # haben. Was offen ist, sagt jedes Mal die Liste.
    huellen = _merker("superchat_huellen")
    namen = _merker("superchat_namen")
    erstsicht = _merker("superchat_erstsicht")
    heute = datetime.now().date().isoformat()

    liste = []
    for g in gespraeche:
        kennung = g.get("id")
        if huellen.get(kennung) is None:
            huellen[kennung] = _hat_nachrichten(kennung, key)
        if not huellen[kennung]:
            continue                       # leere Huelle, zeigt Superchat auch nicht

        kontakte = g.get("contacts") or []
        kontakt_id = (kontakte[0] or {}).get("id") if kontakte else ""
        erstsicht.setdefault(kennung, heute)

        aktiv = _letzte_aktivitaet(g)
        datum = aktiv or erstsicht[kennung]
        alter = tage_alt(datum) or 0
        if aktiv:
            marke = ("heute geschrieben" if alter == 0 else
                     ("gestern geschrieben" if alter == 1 else
                      f"seit {alter} Tagen ohne Antwort"))
        else:
            marke = ("seit heute bekannt" if alter == 0
                     else f"seit {alter} Tagen bekannt")
        kanal = (g.get("channel") or {}).get("type") or ""
        fach_id = (g.get("inbox") or {}).get("id") or ""
        fach_name = fach_namen.get(fach_id, fach_id)
        je_fach[fach_name] = je_fach.get(fach_name, 0) + 1

        liste.append(posten(
            kennung=kennung,
            titel=_name(kontakt_id, key, namen),
            ampel="rot" if alter >= ALARM_AB_TAGEN else "gelb",
            datum=datum,
            text=f"offen im Postfach {fach_name}"
                 + (f" · {kanal.replace('_', '')}" if kanal else ""),
            marke=marke,
            # Der Link traegt das Postfach des Gespraechs, nicht das erste der
            # Liste — sonst landet ein Klick im falschen Postfach.
            link=f"https://app.superchat.de/inbox/{fach_id}?conversationId={kennung}",
            zusatz={"alter": alter, "postfach": fach_name,
                    "gemessen": "letzte Nachricht" if aktiv else "erste Sichtung"},
        ))

    db.kv_schreiben("superchat_huellen", json.dumps(huellen, ensure_ascii=False))
    db.kv_schreiben("superchat_namen", json.dumps(namen, ensure_ascii=False))
    db.kv_schreiben("superchat_erstsicht", json.dumps(erstsicht, ensure_ascii=False))

    kennzahlen = {"Offen": len(liste),
                  f"Älter als {ALARM_AB_TAGEN} Tage":
                      sum(1 for p in liste if p["ampel"] == "rot")}
    if len(postfaecher) > 1:
        # Bei mehreren Postfaechern zaehlt jedes einzeln mit — sonst sieht man
        # nur die Summe und weiss nicht, wo die Arbeit liegt.
        for fach_name in fach_namen.values():
            kennzahlen[fach_name] = je_fach.get(fach_name, 0)
    return {
        "posten": sortieren(liste),
        "kennzahlen": kennzahlen,
        # Die Postfaecher in fester Reihenfolge. Die Oberflaeche faerbt danach
        # ein — nach Platz in dieser Liste, nicht nach einem Namens-Hash: So
        # liegen die Farben zweier Postfaecher immer weit auseinander, statt
        # sich zufaellig zu aehneln.
        "postfaecher": ([fach_namen[f] for f in postfaecher]
                        if len(postfaecher) > 1 else []),
        # Ausdrueckliche Farbwuensche je Postfach. Wer ein Postfach bevorzugt
        # behandelt, will es auch bevorzugt sehen — und das weiss nur, wer das
        # Dashboard einrichtet, nicht der Quelltext.
        "postfach_farben": _farbwuensche(env),
        # Fusslink nur, wenn es EIN Postfach gibt. Bei mehreren fuehrte er fuer
        # die Haelfte der Zeilen ins falsche — dann lieber keiner, die Zeilen
        # verlinken selbst.
        "link": (f"https://app.superchat.de/inbox/{postfaecher[0]}"
                 if len(postfaecher) == 1 else None),
        "link_text": (f"Postfach {fach_namen[postfaecher[0]]}"
                      if len(postfaecher) == 1 else None),
        # Kein Dauerhinweis mehr (entschieden am 09.09.2026): Ein Satz, der bei jedem
        # Laden gleich dasteht, wird nach dem zweiten Mal nicht mehr gelesen
        # und kostet nur Platz. Dass Teamchats über die API nicht erreichbar
        # sind, steht in der Vault-Notiz, wo man es sucht.
        "hinweis": None,
        "seiten": seiten,
        "diff_sperre": (f"Durchlauf bei {MAX_SEITEN} Seiten abgebrochen"
                        if seiten >= MAX_SEITEN else None),
    }
