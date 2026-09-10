"""SQLite fuer das, was NUR dem Dashboard gehoert.

Absichtlich wenig: Fremdsysteme bleiben die Wahrheit. Hier liegen
  * erledigt — was die Person abgehakt hat (Schluessel = "quelle:id")
  * verlauf  — was heute erledigt wurde, von Hand oder von der Quelle erkannt;
               daraus speist sich der Tagesfortschritt
  * notiz    — ihre Randbemerkung zu einem Posten
  * cache    — der letzte erfolgreiche Abruf je Quelle (damit die Seite sofort
               antwortet und ein Ausfall der Fremd-API nichts leert)
  * kv       — Kleinkram, den eine Quelle sich merken muss (Superchat-Cursor)
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

PFAD = Path(os.environ.get("BUCHHALTUNG_DB", "/data/buchhaltung.sqlite3"))
_sperre = threading.Lock()

# Abgehakte Posten, die seit Monaten nicht mehr auftauchen, sind Geschichte.
ERLEDIGT_MAX_TAGE = 120
# Der Ring braucht nur den heutigen Tag; 30 Tage bleiben zum Nachsehen.
VERLAUF_MAX_TAGE = 30


def verbindung():
    PFAD.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(PFAD, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=8000")
    return con


def _spalte_ergaenzen(con, tabelle: str, spalte: str, definition: str) -> None:
    """Fehlende Spalte nachruesten, ohne bestehende Daten anzufassen.

    `CREATE TABLE IF NOT EXISTS` legt nur an, was fehlt — eine bestehende
    Tabelle laesst es unveraendert. Ohne dieses Nachruesten haette die
    Antwortfunktion auf dem laufenden Server gefehlt, waehrend sie in einer
    frisch angelegten Datenbank da gewesen waere.
    """
    vorhanden = {z["name"] for z in con.execute(f"PRAGMA table_info({tabelle})")}
    if spalte not in vorhanden:
        con.execute(f"ALTER TABLE {tabelle} ADD COLUMN {spalte} {definition}")


def init() -> None:
    with _sperre, verbindung() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS erledigt (
            schluessel TEXT PRIMARY KEY,
            quelle     TEXT NOT NULL,
            von        TEXT NOT NULL DEFAULT '',
            am         TEXT NOT NULL,
            gesehen_am TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS verlauf (
            schluessel  TEXT PRIMARY KEY,
            quelle      TEXT NOT NULL,
            titel       TEXT NOT NULL DEFAULT '',
            art         TEXT NOT NULL,
            von         TEXT NOT NULL DEFAULT '',
            erledigt_am TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS verlauf_am ON verlauf (erledigt_am);
        CREATE TABLE IF NOT EXISTS notiz (
            schluessel TEXT PRIMARY KEY,
            quelle     TEXT NOT NULL,
            text       TEXT NOT NULL,
            von        TEXT NOT NULL DEFAULT '',
            am         TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS cache (
            quelle   TEXT PRIMARY KEY,
            stand    TEXT NOT NULL DEFAULT '',
            daten    TEXT NOT NULL DEFAULT '',
            fehler   TEXT NOT NULL DEFAULT '',
            dauer_ms INTEGER NOT NULL DEFAULT 0,
            versuch  TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS einstellung (
            schluessel TEXT PRIMARY KEY,
            wert       TEXT NOT NULL DEFAULT '',
            von        TEXT NOT NULL DEFAULT '',
            am         TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS nachricht (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            text         TEXT NOT NULL,
            von          TEXT NOT NULL DEFAULT 'Claude',
            dringlichkeit TEXT NOT NULL DEFAULT 'info',
            karte        TEXT NOT NULL DEFAULT '',
            am           TEXT NOT NULL,
            erledigt_am  TEXT NOT NULL DEFAULT '',
            erledigt_von TEXT NOT NULL DEFAULT '',
            antwort      TEXT NOT NULL DEFAULT '',
            antwort_am   TEXT NOT NULL DEFAULT '',
            antwort_von  TEXT NOT NULL DEFAULT '',
            antwort_abgeholt TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS mailkonto (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            bezeichnung TEXT NOT NULL DEFAULT '',
            weg        TEXT NOT NULL DEFAULT 'imap',
            postfach_id TEXT NOT NULL DEFAULT '',
            host       TEXT NOT NULL DEFAULT '',
            port       INTEGER NOT NULL DEFAULT 993,
            benutzer   TEXT NOT NULL DEFAULT '',
            passwort   TEXT NOT NULL DEFAULT '',
            ordner     TEXT NOT NULL DEFAULT 'INBOX',
            webmail    TEXT NOT NULL DEFAULT '',
            aktiv      INTEGER NOT NULL DEFAULT 1,
            von        TEXT NOT NULL DEFAULT '',
            am         TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS kv (
            k TEXT PRIMARY KEY,
            v TEXT NOT NULL DEFAULT ''
        );
        """)
        for spalte in ("antwort", "antwort_am", "antwort_von", "antwort_abgeholt"):
            _spalte_ergaenzen(con, "nachricht", spalte, "TEXT NOT NULL DEFAULT ''")
        # Seit 10.09.2026 kann ein Postfach auch ueber die Anbieter-API gelesen
        # werden statt per IMAP. Bestehende Zeilen sind IMAP — daher der
        # Vorgabewert, der die vorhandenen Postfaecher unveraendert laesst.
        _spalte_ergaenzen(con, "mailkonto", "weg", "TEXT NOT NULL DEFAULT 'imap'")
        _spalte_ergaenzen(con, "mailkonto", "postfach_id", "TEXT NOT NULL DEFAULT ''")
    # Nach dem Block: `_verlauf_umziehen` nimmt die Sperre selbst, und die
    # ist nicht wiedereintrittsfaehig.
    _verlauf_umziehen()


def _verlauf_umziehen() -> None:
    """Einmalig: bestehende Haken in den Verlauf uebernehmen.

    Der Tagesfortschritt liest seit dem 10.09.2026 aus `verlauf`, nicht mehr
    aus `erledigt`. Ohne diesen Umzug staende der Ring nach dem Deploy bei
    null, obwohl die Person heute schon abgehakt hat. Alte Haken kommen mit ihrem
    Datum herein, zaehlen also nicht fuer heute und fallen nach 30 Tagen weg.
    """
    if kv_lesen("verlauf_umzug"):
        return
    with _sperre, verbindung() as con:
        con.execute(
            "INSERT OR IGNORE INTO verlauf (schluessel, quelle, titel, art, von, erledigt_am) "
            "SELECT schluessel, quelle, '', 'haken', von, am FROM erledigt")
    kv_schreiben("verlauf_umzug", _jetzt())


def _jetzt() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------------ erledigt

def erledigt_setzen(schluessel: str, quelle: str, an: bool, von: str,
                    titel: str = "") -> None:
    """Haken setzen oder nehmen — und den Verlauf in derselben Transaktion
    nachziehen. So sind alle drei Wege (Oberflaeche, MCP, Selbstheilung der
    Todos) abgedeckt, ohne dass einer davon an den Verlauf denken muss."""
    with _sperre, verbindung() as con:
        if an:
            con.execute(
                "INSERT INTO erledigt (schluessel, quelle, von, am, gesehen_am) "
                "VALUES (?,?,?,?,?) ON CONFLICT(schluessel) DO UPDATE SET "
                "von=excluded.von, am=excluded.am, gesehen_am=excluded.gesehen_am",
                (schluessel, quelle, von, _jetzt(), _jetzt()))
            _verlauf_eintragen(con, schluessel, quelle, "haken", titel, von)
        else:
            con.execute("DELETE FROM erledigt WHERE schluessel=?", (schluessel,))
            con.execute("DELETE FROM verlauf WHERE schluessel=?", (schluessel,))


def erledigte(quelle: str) -> dict:
    with verbindung() as con:
        zeilen = con.execute(
            "SELECT schluessel, von, am FROM erledigt WHERE quelle=?", (quelle,)
        ).fetchall()
    return {z["schluessel"]: {"von": z["von"], "am": z["am"]} for z in zeilen}


def erledigt_gesehen(quelle: str, schluessel_liste) -> None:
    """Merkt sich, dass diese Posten heute noch existieren.

    Ohne das wuesste das Aufraeumen nicht, was Geschichte ist und was nur
    gerade abgehakt in der Liste steht.
    """
    if not schluessel_liste:
        return
    with _sperre, verbindung() as con:
        con.executemany(
            "UPDATE erledigt SET gesehen_am=? WHERE schluessel=?",
            [(_jetzt(), s) for s in schluessel_liste])


def aufraeumen() -> int:
    grenze = (datetime.now() - timedelta(days=ERLEDIGT_MAX_TAGE)).isoformat(timespec="seconds")
    verlauf_grenze = (datetime.now() - timedelta(days=VERLAUF_MAX_TAGE)).isoformat(timespec="seconds")
    with _sperre, verbindung() as con:
        weg = con.execute(
            "DELETE FROM erledigt WHERE gesehen_am < ? AND am < ?", (grenze, grenze)
        ).rowcount
        con.execute("DELETE FROM notiz WHERE schluessel NOT IN "
                    "(SELECT schluessel FROM erledigt) AND am < ?", (grenze,))
        con.execute("DELETE FROM verlauf WHERE erledigt_am < ?", (verlauf_grenze,))
    return weg or 0


# ------------------------------------------------------------------- Verlauf

def _verlauf_eintragen(con, schluessel: str, quelle: str, art: str,
                       titel: str, von: str) -> bool:
    """Eine Verlaufszeile schreiben. Gibt zurueck, ob sie neu ist.

    **Ein Haken gewinnt, eine Erkennung weicht.** Der Haken ist eine bewusste
    Handlung und darf eine aeltere Erkennung ueberschreiben. Die Erkennung
    dagegen darf einen Haken nicht anfassen — sonst stuende „von selbst"
    dort, wo die Person gerade selbst geklickt hat. Und weil der Schluessel der
    Primaerschluessel ist, zaehlt ein Posten in jedem Fall genau einmal.
    """
    if art == "haken":
        con.execute(
            "INSERT INTO verlauf (schluessel, quelle, titel, art, von, erledigt_am) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(schluessel) DO UPDATE SET "
            "art=excluded.art, von=excluded.von, erledigt_am=excluded.erledigt_am, "
            "titel=CASE WHEN excluded.titel='' THEN verlauf.titel ELSE excluded.titel END",
            (schluessel, quelle, titel[:120], art, von, _jetzt()))
        return True
    z = con.execute(
        "INSERT INTO verlauf (schluessel, quelle, titel, art, von, erledigt_am) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(schluessel) DO NOTHING",
        (schluessel, quelle, titel[:120], art, von, _jetzt()))
    return bool(z.rowcount)


def verlauf_setzen(schluessel: str, quelle: str, art: str, titel: str = "",
                   von: str = "") -> bool:
    with _sperre, verbindung() as con:
        return _verlauf_eintragen(con, schluessel, quelle, art, titel, von)


def verlauf_entfernen(schluessel_liste) -> int:
    """Posten, die wieder offen sind, zaehlen nicht mehr als erledigt."""
    schluessel_liste = list(schluessel_liste)
    if not schluessel_liste:
        return 0
    with _sperre, verbindung() as con:
        weg = con.executemany("DELETE FROM verlauf WHERE schluessel=?",
                              [(s,) for s in schluessel_liste]).rowcount
    return weg or 0


def verlauf_heute() -> list:
    """Alles, was seit heute 00:00 als erledigt vermerkt ist.

    „Heute“ ist der Kalendertag der Serverzeit — im Container Europe/Berlin,
    dieselbe Zeit, in der auch `_jetzt()` schreibt. Eine zweite Zeitzone an
    dieser Stelle waere ein Widerspruch, den niemand bemerkt, bis der Ring
    um Mitternacht springt.
    """
    ab = datetime.now().date().isoformat() + "T00:00:00"
    with verbindung() as con:
        zeilen = con.execute(
            "SELECT schluessel, quelle, titel, art, von, erledigt_am FROM verlauf "
            "WHERE erledigt_am >= ? ORDER BY erledigt_am", (ab,)).fetchall()
    return [dict(z) for z in zeilen]


# --------------------------------------------------------------------- Notiz

def notiz_setzen(schluessel: str, quelle: str, text: str, von: str) -> None:
    text = (text or "").strip()[:2000]
    with _sperre, verbindung() as con:
        if text:
            con.execute(
                "INSERT INTO notiz (schluessel, quelle, text, von, am) VALUES (?,?,?,?,?) "
                "ON CONFLICT(schluessel) DO UPDATE SET text=excluded.text, "
                "von=excluded.von, am=excluded.am",
                (schluessel, quelle, text, von, _jetzt()))
        else:
            con.execute("DELETE FROM notiz WHERE schluessel=?", (schluessel,))


def notizen(quelle: str) -> dict:
    with verbindung() as con:
        zeilen = con.execute(
            "SELECT schluessel, text, von, am FROM notiz WHERE quelle=?", (quelle,)
        ).fetchall()
    return {z["schluessel"]: {"text": z["text"], "von": z["von"], "am": z["am"]}
            for z in zeilen}


# --------------------------------------------------------------------- Cache

def cache_schreiben(quelle: str, daten: dict | None, fehler: str,
                    dauer_ms: int) -> tuple:
    """Bei Fehler bleiben die alten Daten stehen — eine Karte wird nie leer,
    nur aelter. Sie sagt dann selbst, dass ihr Stand nicht frisch ist.

    Gibt `(alte_daten, alter_stand)` zurueck — bei Erfolg der Stand, der
    gerade ueberschrieben wurde, sonst `(None, "")`. Der Vergleich alt gegen
    neu ist die Grundlage der Erkennung im Tagesfortschritt, und hier liegt
    der alte Stand ohnehin schon in der Hand.
    """
    with _sperre, verbindung() as con:
        vorher = con.execute("SELECT daten, stand FROM cache WHERE quelle=?",
                             (quelle,)).fetchone()
        if daten is None:
            con.execute(
                "INSERT INTO cache (quelle, stand, daten, fehler, dauer_ms, versuch) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(quelle) DO UPDATE SET "
                "fehler=excluded.fehler, dauer_ms=excluded.dauer_ms, versuch=excluded.versuch",
                (quelle, vorher["stand"] if vorher else "",
                 vorher["daten"] if vorher else "", fehler[:400], dauer_ms, _jetzt()))
        else:
            con.execute(
                "INSERT INTO cache (quelle, stand, daten, fehler, dauer_ms, versuch) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(quelle) DO UPDATE SET "
                "stand=excluded.stand, daten=excluded.daten, fehler='', "
                "dauer_ms=excluded.dauer_ms, versuch=excluded.versuch",
                (quelle, _jetzt(), json.dumps(daten, ensure_ascii=False), "",
                 dauer_ms, _jetzt()))
    if daten is None or not vorher or not vorher["daten"]:
        return None, ""
    try:
        return json.loads(vorher["daten"]), vorher["stand"] or ""
    except (TypeError, ValueError):
        return None, ""


def cache_lesen(quelle: str) -> dict:
    with verbindung() as con:
        z = con.execute("SELECT * FROM cache WHERE quelle=?", (quelle,)).fetchone()
    if not z:
        return {"stand": "", "daten": None, "fehler": "", "versuch": ""}
    try:
        daten = json.loads(z["daten"]) if z["daten"] else None
    except json.JSONDecodeError:
        daten = None
    return {"stand": z["stand"], "daten": daten, "fehler": z["fehler"],
            "versuch": z["versuch"], "dauer_ms": z["dauer_ms"]}


def cache_alle() -> dict:
    with verbindung() as con:
        zeilen = con.execute("SELECT quelle, stand, fehler FROM cache").fetchall()
    return {z["quelle"]: {"stand": z["stand"], "fehler": z["fehler"]} for z in zeilen}


# --------------------------------------------------------------- Einstellungen

def einstellungen() -> dict:
    """{Schluessel: Wert} — nur was hier gesetzt wurde, ohne .env."""
    with verbindung() as con:
        zeilen = con.execute("SELECT schluessel, wert FROM einstellung").fetchall()
    return {z["schluessel"]: z["wert"] for z in zeilen}


def einstellung_herkunft() -> dict:
    """{Schluessel: (von, am)} — wer hat wann gesetzt.

    Seit die Seite allen offensteht, ist das keine Nebensache mehr: Wenn ein
    Schluessel plötzlich nicht mehr traegt, muss nachvollziehbar sein, wer ihn
    zuletzt angefasst hat.
    """
    with verbindung() as con:
        zeilen = con.execute(
            "SELECT schluessel, von, am FROM einstellung").fetchall()
    return {z["schluessel"]: (z["von"], z["am"]) for z in zeilen}


def einstellung_setzen(schluessel: str, wert: str, von: str) -> None:
    """Leerer Wert loescht den Eintrag — dann gilt wieder die .env."""
    with _sperre, verbindung() as con:
        if wert:
            con.execute(
                "INSERT INTO einstellung (schluessel, wert, von, am) VALUES (?,?,?,?) "
                "ON CONFLICT(schluessel) DO UPDATE SET wert=excluded.wert, "
                "von=excluded.von, am=excluded.am",
                (schluessel, wert, von, _jetzt()))
        else:
            con.execute("DELETE FROM einstellung WHERE schluessel=?", (schluessel,))


# --------------------------------------------------------------- Nachrichten

NACHRICHT_MAX = 2000
NACHRICHT_AUFHEBEN_TAGE = 14


def nachricht_anlegen(text: str, von: str, dringlichkeit: str = "info",
                      karte: str = "") -> int:
    """Eine Nachricht an die Person. Kommt von der KI ueber den MCP-Zugang."""
    text = (text or "").strip()[:NACHRICHT_MAX]
    if not text:
        raise ValueError("Leere Nachricht")
    if dringlichkeit not in ("info", "wichtig"):
        dringlichkeit = "info"
    with _sperre, verbindung() as con:
        z = con.execute(
            "INSERT INTO nachricht (text, von, dringlichkeit, karte, am) "
            "VALUES (?,?,?,?,?)",
            (text, (von or "Claude")[:40], dringlichkeit, (karte or "")[:40], _jetzt()))
        return int(z.lastrowid)


def nachrichten(offen_nur: bool = True, grenze: int = 20) -> list:
    bedingung = "WHERE erledigt_am = ''" if offen_nur else ""
    with verbindung() as con:
        zeilen = con.execute(
            f"SELECT * FROM nachricht {bedingung} ORDER BY id DESC LIMIT ?",
            (int(grenze),)).fetchall()
    return [{"id": z["id"], "text": z["text"], "von": z["von"],
             "dringlichkeit": z["dringlichkeit"], "karte": z["karte"],
             "am": z["am"], "erledigt_am": z["erledigt_am"],
             "erledigt_von": z["erledigt_von"], "antwort": z["antwort"],
             "antwort_am": z["antwort_am"]} for z in zeilen]


def nachricht_antworten(kennung: int, text: str, von: str) -> None:
    """Die Antwort. Schliesst die Nachricht zugleich ab — wer antwortet, hat
    sich damit befasst, und die Box soll leer bleiben."""
    text = (text or "").strip()[:NACHRICHT_MAX]
    if not text:
        raise ValueError("Leere Antwort")
    with _sperre, verbindung() as con:
        con.execute(
            "UPDATE nachricht SET antwort=?, antwort_am=?, antwort_von=?, "
            "erledigt_am=?, erledigt_von=? WHERE id=?",
            (text, _jetzt(), (von or "")[:40], _jetzt(), (von or "")[:40],
             int(kennung)))


def antworten(nur_neue: bool = True, grenze: int = 20) -> list:
    """Antworten fuer die KI.

    `nur_neue` liefert, was noch nicht abgeholt wurde. Abgeholte Antworten
    bleiben abrufbar (`nur_neue=False`) — sonst waere eine Rueckmeldung
    verloren, sobald die KI zwischendurch den Faden verliert.
    """
    bedingung = "antwort != ''"
    if nur_neue:
        bedingung += " AND antwort_abgeholt = ''"
    with verbindung() as con:
        zeilen = con.execute(
            f"SELECT * FROM nachricht WHERE {bedingung} ORDER BY id DESC LIMIT ?",
            (int(grenze),)).fetchall()
    return [{"id": z["id"], "frage": z["text"], "antwort": z["antwort"],
             "von": z["antwort_von"], "am": z["antwort_am"],
             "karte": z["karte"], "dringlichkeit": z["dringlichkeit"],
             "schon_abgeholt": bool(z["antwort_abgeholt"])} for z in zeilen]


def antworten_abhaken(kennungen) -> None:
    if not kennungen:
        return
    with _sperre, verbindung() as con:
        con.executemany("UPDATE nachricht SET antwort_abgeholt=? WHERE id=?",
                        [(_jetzt(), int(k)) for k in kennungen])


def _schliessen(con, kennung: int, von: str) -> dict:
    """Eine offene Nachricht abschliessen — ohne Antwort.

    Wirft, statt still nichts zu tun: Eine KI, die eine falsche Nummer
    schickt und `{ok: true}` zurueckbekommt, glaubt aufgeraeumt zu haben,
    waehrend die Box unveraendert dasteht.
    """
    zeile = con.execute("SELECT id, erledigt_am FROM nachricht WHERE id=?",
                        (int(kennung),)).fetchone()
    if zeile is None:
        raise LookupError(f"Nachricht {kennung} gibt es nicht.")
    if zeile["erledigt_am"]:
        raise ValueError(f"Nachricht {kennung} ist schon seit "
                         f"{zeile['erledigt_am']} erledigt.")
    jetzt, wer = _jetzt(), (von or "")[:40]
    con.execute("UPDATE nachricht SET erledigt_am=?, erledigt_von=? WHERE id=?",
                (jetzt, wer, int(kennung)))
    return {"id": int(kennung), "erledigt_am": jetzt, "erledigt_von": wer}


def nachricht_erledigen(kennung: int, von: str, streng: bool = False) -> dict:
    """`streng=True` meldet unbekannte oder bereits erledigte Nummern.

    Der Knopf auf dem Dashboard bleibt nachsichtig: Wer zweimal tippt, weil
    die Seite hakte, soll keine Fehlermeldung sehen — das Ergebnis ist ja
    dasselbe. Die KI dagegen soll es erfahren.
    """
    with _sperre, verbindung() as con:
        try:
            return _schliessen(con, kennung, von)
        except (LookupError, ValueError):
            if streng:
                raise
            return {}


def nachricht_ersetzen(text: str, von: str, dringlichkeit: str = "info",
                       karte: str = "", kennung: int | None = None) -> dict:
    """Die offene Nachricht durch eine neue ersetzen — in einem Zug.

    **Warum das ein eigener Schritt ist und kein Erledigen plus Senden:**
    Zwischen zwei Aufrufen kann alles Moegliche passieren — die Verbindung
    bricht ab, und auf dem Dashboard steht gar nichts mehr oder es stehen
    zwei Zurufe uebereinander. Beides in einer Transaktion heisst: entweder
    beides oder nichts.

    Ohne `kennung` wird die **neueste offene** Nachricht ersetzt. Gibt es
    keine, entsteht einfach eine neue (`ersetzt: False`) — fuer einen Agenten,
    der vor jedem Zuruf ersetzt, ist das der normale erste Lauf und kein
    Fehler. Eine ausdrueckliche `kennung`, die nicht passt, ist dagegen ein
    Fehler: Dann war eine bestimmte Nachricht gemeint.
    """
    text = (text or "").strip()[:NACHRICHT_MAX]
    if not text:
        raise ValueError("Leere Nachricht")
    if dringlichkeit not in ("info", "wichtig"):
        dringlichkeit = "info"
    wer = (von or "Claude")[:40]
    with _sperre, verbindung() as con:
        alt = None
        if kennung is not None:
            alt = _schliessen(con, int(kennung), wer)
        else:
            zeile = con.execute(
                "SELECT id FROM nachricht WHERE erledigt_am = '' "
                "ORDER BY id DESC LIMIT 1").fetchone()
            if zeile is not None:
                alt = _schliessen(con, zeile["id"], wer)
        z = con.execute(
            "INSERT INTO nachricht (text, von, dringlichkeit, karte, am) "
            "VALUES (?,?,?,?,?)",
            (text, wer, dringlichkeit, (karte or "")[:40], _jetzt()))
        return {"id": int(z.lastrowid),
                "ersetzt": alt is not None,
                "alte_id": alt["id"] if alt else None}


def nachrichten_aufraeumen() -> int:
    """Erledigte Nachrichten verfallen nach zwei Wochen — sie sind Zuruf,
    kein Archiv."""
    from datetime import timedelta as _td
    grenze = (datetime.now() - _td(days=NACHRICHT_AUFHEBEN_TAGE)).isoformat(timespec="seconds")
    with _sperre, verbindung() as con:
        # Eine Antwort, die noch niemand abgeholt hat, wird NICHT geloescht —
        # sonst verschwindet die Rueckmeldung, bevor sie jemanden erreicht.
        return con.execute(
            "DELETE FROM nachricht WHERE erledigt_am != '' AND erledigt_am < ? "
            "AND (antwort = '' OR antwort_abgeholt != '')",
            (grenze,)).rowcount or 0


# ------------------------------------------------------------ Mail-Postfaecher

def mailkonten(mit_passwort: bool = False) -> list:
    """Alle hinterlegten Postfaecher, gleich welchen Wegs.

    `mit_passwort` nur fuer den Abruf selbst — die Oberflaeche bekommt es nie,
    weder das IMAP-Passwort noch den API-Token. Zurueck geht nur die Tatsache,
    dass etwas hinterlegt ist, und die letzten vier Zeichen.
    """
    with verbindung() as con:
        zeilen = con.execute(
            "SELECT * FROM mailkonto ORDER BY id").fetchall()
    ergebnis = []
    for z in zeilen:
        k = {"id": z["id"], "bezeichnung": z["bezeichnung"],
             "weg": z["weg"] or "imap", "postfach_id": z["postfach_id"],
             "host": z["host"],
             "port": z["port"], "benutzer": z["benutzer"], "ordner": z["ordner"],
             "webmail": z["webmail"], "aktiv": bool(z["aktiv"]),
             "von": z["von"], "am": z["am"],
             "passwort_gesetzt": bool(z["passwort"]),
             "spur": ("…" + z["passwort"][-4:]) if len(z["passwort"] or "") > 4 else ""}
        if mit_passwort:
            k["passwort"] = z["passwort"]
        ergebnis.append(k)
    return ergebnis


def mailkonto_speichern(daten: dict, von: str) -> int:
    """Anlegen oder aendern. Ein leeres Passwort laesst das alte stehen —
    sonst wuerde jedes Speichern der uebrigen Felder den Zugang loeschen."""
    kennung = daten.get("id")
    weg = str(daten.get("weg") or "imap").strip().lower()
    if weg not in ("imap", "api"):
        weg = "imap"
    felder = {
        "bezeichnung": str(daten.get("bezeichnung") or "").strip()[:60],
        "weg": weg,
        "postfach_id": str(daten.get("postfach_id") or "").strip()[:80],
        "host": str(daten.get("host") or "").strip()[:120],
        "port": int(daten.get("port") or 993),
        "benutzer": str(daten.get("benutzer") or "").strip()[:120],
        "ordner": str(daten.get("ordner") or "").strip()[:80] or "INBOX",
        "webmail": str(daten.get("webmail") or "").strip()[:200],
        "aktiv": 1 if daten.get("aktiv", True) else 0,
        "von": von, "am": _jetzt(),
    }
    passwort = daten.get("passwort")
    with _sperre, verbindung() as con:
        if kennung:
            satz = ", ".join(f"{k}=?" for k in felder)
            werte = list(felder.values()) + [int(kennung)]
            con.execute(f"UPDATE mailkonto SET {satz} WHERE id=?", werte)
            if passwort:
                con.execute("UPDATE mailkonto SET passwort=? WHERE id=?",
                            (passwort, int(kennung)))
            return int(kennung)
        felder["passwort"] = passwort or ""
        spalten = ", ".join(felder)
        platz = ", ".join("?" * len(felder))
        z = con.execute(f"INSERT INTO mailkonto ({spalten}) VALUES ({platz})",
                        list(felder.values()))
        return int(z.lastrowid)


def mailkonto_loeschen(kennung: int) -> None:
    with _sperre, verbindung() as con:
        con.execute("DELETE FROM mailkonto WHERE id=?", (int(kennung),))


# ------------------------------------------------------------------------ kv

def kv_lesen(k: str, standard: str = "") -> str:
    with verbindung() as con:
        z = con.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return z["v"] if z else standard


def kv_schreiben(k: str, v: str) -> None:
    with _sperre, verbindung() as con:
        con.execute("INSERT INTO kv (k,v) VALUES (?,?) "
                    "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))
