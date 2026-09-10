"""Wer dieses Dashboard benutzt und woraus es besteht.

Dasselbe Programm laeuft mehrfach — je Person eine Instanz mit eigener
`.env`, eigener Datenbank und eigenen Zugaengen. Was die Instanzen
unterscheidet, steht nicht im Code: der Name in der Begruessung, die
Kartenliste, die Zahlen oben, die Adresse.

**Warum aus der `.env` und nicht aus den Einstellungen:** Karten und ihre
Hintergrund-Takte entstehen beim Start. Ein Umschalter in der Oberflaeche
braeuchte also ohnehin einen Neustart — und er wuerde einladen, die
Instanz einer Person versehentlich auf eine andere zu stellen. Das Profil
gehoert zum Ausrollen, nicht zur Bedienung.

**Die Vorgaben sind neutral.** Wer nichts setzt, bekommt ein Dashboard ohne
Namen, mit allen Karten, die eingerichtet sind — und sonst nichts.
"""

from __future__ import annotations

import os
import re

# Leer erlaubt: Dann gruesst die Seite ohne Namen. Einen fremden Namen als
# Vorgabe einzubauen waere schlimmer als gar keiner.
NAME = (os.environ.get("PERSON_NAME") or "").strip()
TITEL = (os.environ.get("TITEL") or "Dashboard").strip()
# Das Zeichen in der Seitenleiste ist kein eigener Schalter: Ein zweites Feld
# fuer einen einzelnen Buchstaben waere eine Einstellung, die man vergisst.
MARKE = (TITEL[:1] or "D").upper()
INSTANZ = (os.environ.get("INSTANZ") or "dashboard").strip()
HOST = (os.environ.get("HOST") or "").strip()
# An wen sich die Person wendet, wenn etwas unklar ist. Ohne Eintrag
# stehen dort allgemeine Saetze statt eines erfundenen Namens.
ANSPRECHPARTNER = (os.environ.get("ANSPRECHPARTNER") or "").strip()
# Der Zusatz unter dem Markenzeichen. Ohne Eintrag bleibt die Zeile leer,
# statt einen fremden Firmennamen zu behaupten.
FIRMA = (os.environ.get("FIRMA") or "").strip()

# Der Name als eigenes Wort. `\b` verhindert, dass ein laengerer Name mit
# demselben Anfang mitzaehlt (ein laengerer Name mit demselben Anfang).
# Ohne Namen darf das Muster NIE greifen — `(?!)` schlaegt immer fehl.
RE_PERSON = (re.compile(r"\b" + re.escape(NAME) + r"\b", re.IGNORECASE)
             if NAME else re.compile(r"(?!)"))


def _liste(schluessel: str, vorgabe: str) -> list:
    roh = (os.environ.get(schluessel) or "").strip() or vorgabe
    return [s.strip() for s in roh.split(",") if s.strip()]


# Welche Karten diese Instanz zeigt — und in welcher Reihenfolge. Die Vorgabe
# ist die bisherige REGISTRY.
# Vorgabe: alle. Welche davon wirklich erscheinen, entscheiden die
# hinterlegten Zugangsdaten — eine Karte ohne Zugang zeigt nichts an.
KARTEN = _liste(
    "KARTEN",
    "todos,mail,kalender,bank,superchat,rechnungen,widerrufe,shop,faq")

# Die Zahlen ganz oben. Eintrag "quelle" nimmt die Vorgabezahl des Moduls,
# "quelle:Kennzahl" eine bestimmte — so bekommt ein zweites Superchat-Postfach
# eine eigene Kachel, ohne dass es eine zweite Karte braucht.
KOPFZAHLEN = _liste("KOPFZAHLEN", "mail,superchat,todos,bank")

# Welche Termine im Kalender gelb hervorgehoben und gezaehlt werden.
KALENDER_HERVORHEBEN = _liste("KALENDER_HERVORHEBEN", "abhol")
