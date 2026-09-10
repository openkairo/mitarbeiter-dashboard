"""Ein Hintergrund-Takt je Quelle.

Warum ueberhaupt: Lexware ist auf 2 Anfragen/s gedrosselt, Superchat blaettert
im Erstlauf ueber 200 Seiten, IMAP baut jedes Mal eine TLS-Verbindung auf. Wenn
das am Seitenaufruf haengt, wartet die Person Sekunden auf eine Seite, die sie
zwanzigmal am Tag oeffnet. Deshalb holt ein Thread die Daten in Ruhe, und die
Oberflaeche liest nur noch aus SQLite.

Ein Fehler leert nie eine Karte: die alten Daten bleiben stehen und bekommen
einen Hinweis. Eine leere Karte sieht aus wie "nichts zu tun" — das waere die
gefaehrlichste aller Falschaussagen.
"""

from __future__ import annotations

import logging
import os
import threading
import time

from . import arbeitszeit, db, einstellungen, verlauf

log = logging.getLogger("buchhaltung.cache")

# Ein Takt fuer alle Karten. Entscheidung des Betreibers, 09.09.2026: alle halbe
# Stunde, und nur wenn die Person arbeitet oder jemand die Seite offen hat.
# Die TTL der Module bleibt als Untergrenze fuer den Client-Takt stehen.
TAKT = int(os.environ.get("TAKT_SEKUNDEN", "1800"))

# So oft wird nachgesehen, ob wieder abgerufen werden darf. Kurz genug, dass
# ein Seitenaufruf sich sofort auswirkt, lang genug um nichts zu kosten.
PRUEFTAKT = 30

# Ein Ereignis je Quelle: setzt es jemand, laeuft der Abruf sofort statt beim
# naechsten Takt (Knopf "jetzt aktualisieren").
_wecker: dict[str, threading.Event] = {}


def sofort(name: str) -> bool:
    ereignis = _wecker.get(name)
    if ereignis is None:
        return False
    ereignis.set()
    return True


def _einmal(modul, umgebung: dict) -> None:
    beginn = time.monotonic()
    try:
        # Die Werte werden hier neu geholt, nicht beim Start eingefroren:
        # Sonst wirkte ein in den Einstellungen geaenderter Schluessel erst
        # nach einem Neustart, und niemand wuesste warum.
        ergebnis = modul.fetch(einstellungen.umgebung())
        dauer = int((time.monotonic() - beginn) * 1000)
        alt_daten, alt_stand = db.cache_schreiben(modul.NAME, ergebnis, "", dauer)
        log.info("%s aktualisiert: %d Posten in %d ms",
                 modul.NAME, len(ergebnis.get("posten") or []), dauer)
        # Erst schreiben, dann vergleichen — und der Vergleich darf den
        # Abruf nie mitreissen. Ein Fehler in der Erkennung ist ein Eintrag
        # im Log, kein leerer Cache.
        if getattr(modul, "ABHAKBAR", True) and getattr(modul, "ERKENNUNG", True):
            try:
                verlauf.nach_abruf(modul.NAME, alt_daten, alt_stand, ergebnis)
            except Exception as fehler:                           # noqa: BLE001
                log.warning("WARN Erkennung %s: %s", modul.NAME, fehler)
    except Exception as fehler:                                   # noqa: BLE001
        dauer = int((time.monotonic() - beginn) * 1000)
        db.cache_schreiben(modul.NAME, None, f"{type(fehler).__name__}: {fehler}", dauer)
        # WARN im Log, damit der Watchdog eine stille Verschlechterung sieht —
        # dieselbe Lehre wie beim Bank-Abgleich am 23.08.2026.
        log.warning("WARN %s: %s", modul.NAME, fehler)


def _takt(modul, umgebung: dict) -> None:
    ereignis = _wecker[modul.NAME]
    # Beim Start versetzt anlaufen, damit nicht acht Quellen gleichzeitig
    # losrennen und sich TLS-Handshakes und Drosselung in die Quere kommen.
    ereignis.wait(modul.ANLAUF)
    ereignis.clear()
    _einmal(modul, umgebung)          # einmal beim Start, sonst startet die
    faellig = time.monotonic() + TAKT  # Seite leer

    letzte_absage = ""
    while True:
        # In kleinen Schritten schlafen statt einmal lang: So wirkt ein
        # Seitenaufruf oder der Schichtbeginn sofort, ohne dass ein halbe
        # Stunde langer Schlaf abgewartet werden muss.
        von_hand = ereignis.wait(PRUEFTAKT)
        ereignis.clear()

        if von_hand:                   # Knopf "jetzt auffrischen" — immer holen
            _einmal(modul, umgebung)
            faellig = time.monotonic() + TAKT
            continue

        if time.monotonic() < faellig:
            continue

        darf, grund = arbeitszeit.soll_holen()
        if not darf:
            # Nicht faellig weiterschieben: Sobald jemand hinsieht oder die
            # Schicht beginnt, wird beim naechsten Durchgang sofort geholt.
            if grund != letzte_absage:
                log.info("%s pausiert — %s", modul.NAME, grund)
                letzte_absage = grund
            continue

        letzte_absage = ""
        _einmal(modul, umgebung)
        faellig = time.monotonic() + TAKT


def starten(module, umgebung: dict) -> None:
    for modul in module:
        _wecker[modul.NAME] = threading.Event()
        threading.Thread(target=_takt, args=(modul, umgebung),
                         daemon=True, name=f"takt-{modul.NAME}").start()
    threading.Thread(target=_aufraeum_takt, daemon=True, name="aufraeumen").start()
    log.info("%d Takte gestartet", len(module))


def _aufraeum_takt() -> None:
    while True:
        time.sleep(24 * 3600)
        try:
            weg = db.aufraeumen()
            if weg:
                log.info("aufgeraeumt: %d alte Haken entfernt", weg)
            alt = db.nachrichten_aufraeumen()
            if alt:
                log.info("aufgeraeumt: %d erledigte Nachrichten entfernt", alt)
        except Exception as fehler:                               # noqa: BLE001
            log.warning("WARN Aufraeumen: %s", fehler)
