"""Kalender — der Arbeitszeiten, Abwesenheiten und die Abholer von heute.

Zwei Dinge in einer Karte: was heute im Haus passiert (Abholungen betreffen die
Rechnungen an der Theke) und ob die Person selbst da ist.

Die Falle, die den Bank-Abgleich im August blamiert hat: Wer nur `DTSTART` im
Fenster "ab jetzt" prueft, sieht einen **laufenden** Urlaub nicht — er hat in
der Vergangenheit begonnen. Hier gilt deshalb: ein Termin ist heute aktiv, wenn
`beginn < morgen` UND `ende > heute 00:00`. Bei ganztaegigen Terminen ist das
Ende exklusiv (14.-18.09. endet mit end.date = 19.09.).
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .. import clockin as clockin_api
from .. import profil
from ..posten import posten

NAME = "kalender"
TITEL = "Heute im Kalender"
ICON = "📅"
TTL = 300
ANLAUF = 10
# Ohne diese Einstellungen kann die Karte nichts holen — dann erscheint
# sie gar nicht erst, statt „nichts zu tun“ zu behaupten.
BRAUCHT = ("KALENDER_ID",)

LINK = "https://calendar.google.com/"
LINK_TEXT = "Kalender"
KOPFZAHL = ("Heute", "Abholungen", "Abholungen heute")
# Einen Termin kann man nicht "erledigen" — er findet statt oder nicht.
# Deshalb hier keine Haken, und die Termine zaehlen auch nicht in den
# Tagesfortschritt: Sonst stuenden im Ring acht Punkte, die niemand je
# abhaken wird, und die Zahl waere dauerhaft unerreichbar.
ABHAKBAR = False

ZONE = ZoneInfo("Europe/Berlin")
VORAUS_TAGE = 14
# Wessen Kalender das hier ist, sagt das Profil.
RE_PERSON = profil.RE_PERSON
# Termine aus der Terminbuchungsseite tragen "Mitarbeiter: <name>" in der
# Beschreibung. Das heisst "von dieser Person gebucht" — fuer die
# Beratungen ist das der einzige Bezug, den der Titel nicht hergibt.
RE_MITARBEITER = re.compile(r"Mitarbeiter:\s*" + re.escape(profil.NAME) + r"\b",
                            re.IGNORECASE)
RE_ABGESAGT = re.compile(r"^abgesagt", re.IGNORECASE)
FREI = ("nicht da", "frei", "urlaub", "krank", "fehlt", "nicht im")
# Was gelb auffaellt und oben mitgezaehlt wird. Der Schluessel ist das Wort im
# Titel, der Wert die Beschriftung der Kennzahl.
HERVORHEBEN_ALLE = {"abhol": "Abholungen", "beratung": "Beratungen",
                    "montage": "Montagen", "liefer": "Lieferungen"}
HERVORHEBEN = {wort: HERVORHEBEN_ALLE.get(wort, wort.capitalize())
               for wort in profil.KALENDER_HERVORHEBEN}
RE_HERVOR = {wort: re.compile(wort, re.IGNORECASE) for wort in HERVORHEBEN}


def _dienst(key_pfad: str):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    zugang = service_account.Credentials.from_service_account_file(
        key_pfad, scopes=["https://www.googleapis.com/auth/calendar.readonly"])
    return build("calendar", "v3", credentials=zugang, cache_discovery=False)


def _spanne(termin: dict):
    """(beginn, ende, ganztags) — beide als aware datetime in Europe/Berlin."""
    start, ende = termin.get("start") or {}, termin.get("end") or {}
    if "date" in start:
        a = datetime.combine(date.fromisoformat(start["date"]), time.min, tzinfo=ZONE)
        roh_ende = ende.get("date") or start["date"]
        b = datetime.combine(date.fromisoformat(roh_ende), time.min, tzinfo=ZONE)
        return a, b, True                      # Ende ist exklusiv — so gewollt
    a = datetime.fromisoformat(start["dateTime"]).astimezone(ZONE)
    b = (datetime.fromisoformat(ende["dateTime"]).astimezone(ZONE)
         if ende.get("dateTime") else a + timedelta(hours=1))
    return a, b, False


def fetch(env: dict) -> dict:
    key = env.get("GOOGLE_KEY") or "/daten/google-key.json"
    # Ohne Kennung kein Kalender: Eine fremde Adresse als Vorgabe waere
    # ein Zugriffsversuch auf einen Kalender, der uns nicht gehoert.
    kalender_id = (env.get("KALENDER_ID") or "").strip()
    if not kalender_id:
        return {"posten": [], "kennzahlen": {},
                "hinweis": "Kalender-Kennung fehlt — unter Settings eintragen."}
    if not os.path.exists(key):
        return {"posten": [], "kennzahlen": {},
                "hinweis": f"Google-Schluessel {key} nicht gefunden."}

    heute = datetime.now(ZONE).date()
    von = datetime.combine(heute, time.min, tzinfo=ZONE)
    bis = von + timedelta(days=VORAUS_TAGE)
    antwort = _dienst(key).events().list(
        calendarId=kalender_id, timeMin=von.isoformat(), timeMax=bis.isoformat(),
        singleEvents=True, orderBy="startTime", maxResults=250).execute()

    morgen = von + timedelta(days=1)
    liste = []
    hervor_heute = {wort: 0 for wort in HERVORHEBEN}
    person_heute, person_abwesend_bis = None, None

    for t in antwort.get("items", []):
        if t.get("status") == "cancelled":
            continue
        titel = (t.get("summary") or "").strip()
        if not titel or RE_ABGESAGT.match(titel):
            continue
        try:
            beginn, ende, ganztags = _spanne(t)
        except (KeyError, ValueError):
            continue
        laeuft_heute = beginn < morgen and ende > von
        unten = titel.lower()
        beschreibung = t.get("description") or ""
        # Ein Kundentermin ist nie eine Anwesenheitsmeldung. Ohne diese
        # Unterscheidung machte "Beratung vor Ort (Kundenname)" aus einem
        # Kundennamen einen Arbeitstag.
        ist_kundentermin = ("kunde:" in beschreibung.lower()
                            or bool(t.get("attendees")))

        # --- Was sagt der Kalender ueber die Person dieses Dashboards?
        if RE_PERSON.search(titel) and not ist_kundentermin:
            abwesend = any(w in unten for w in FREI)
            if laeuft_heute and person_heute is None:
                person_heute = not abwesend
            # NUR eine laufende Abwesenheit zaehlt hier. Ein Urlaub naechste
            # Woche darf nicht dazu fuehren, dass die Seite heute schon
            # "du bist nicht da" behauptet.
            if abwesend and laeuft_heute:
                letzter_tag = (ende - timedelta(days=1)).date() if ganztags else ende.date()
                if person_abwesend_bis is None or letzter_tag > person_abwesend_bis:
                    person_abwesend_bis = letzter_tag

        hervor = ""
        for wort, muster in RE_HERVOR.items():
            if muster.search(titel) or muster.search(beschreibung):
                hervor = wort
                break
        if hervor and laeuft_heute:
            hervor_heute[hervor] += 1

        # In die Karte kommt: heute alles, spaeter nur, was diese Person
        # angeht — im Titel oder als Mitarbeiter der Buchung.
        eigener_bezug = (bool(RE_PERSON.search(titel)) and not ist_kundentermin) \
            or bool(RE_MITARBEITER.search(beschreibung))
        if not laeuft_heute and not eigener_bezug:
            continue

        wann = "ganztägig" if ganztags else beginn.strftime("%H:%M")
        if laeuft_heute:
            # Eine Abholung ist Tagesgeschaeft, kein Alarm. Sie faellt auf
            # (gelb), aber Rot bleibt dem vorbehalten, was wirklich brennt —
            # sonst gewoehnt man sich an Rot und uebersieht es.
            ampel = "gelb" if hervor else "blau"
            marke = wann
        else:
            ampel, marke = "blau", beginn.strftime("%d.%m.")
        liste.append(posten(
            kennung=str(t.get("id") or titel)[:60],
            titel=titel,
            ampel=ampel,
            datum=beginn.date().isoformat(),
            text=(t.get("location") or "")[:80],
            marke=marke,
            link=t.get("htmlLink"),
            zusatz={"zeit": wann, "heute": laeuft_heute,
                    "abholung": hervor == "abhol", "art": hervor,
                    "sortier": beginn.isoformat()},
        ))

    liste.sort(key=lambda p: (not p["zusatz"]["heute"], p["zusatz"]["sortier"]))
    kennzahlen = {"Heute": sum(1 for p in liste if p["zusatz"]["heute"])}
    for wort, beschriftung in HERVORHEBEN.items():
        kennzahlen[beschriftung] = hervor_heute[wort]
    return {
        "posten": liste,
        "kennzahlen": kennzahlen,
        "hinweis": None,
        "person": {"heute_da": person_heute,
                   "abwesend_bis": (person_abwesend_bis.isoformat()
                                    if person_abwesend_bis else None)},
        "zeit": _zeit_heute(env),
    }


def _zeit_heute(env: dict) -> dict | None:
    """Die Zeiterfassung aus clockin — der heutige Tag und die Monatssumme.

    Bewusst **nichts Gerechnetes**: Was hier steht, liest clockin selbst so
    aus. Stundenkonto und Saldo haengen an Arbeitsplan, Tagessoll und der
    Berechnungsgrundlage der Abwesenheiten (siehe [[clockin Abwesenheiten und
    Stundenkonto]]) — eine falsch hergeleitete Zahl waere schlimmer als keine.

    **Warum die Monatssumme ohne Soll dasteht:** Waehrend eines Urlaubs laeuft
    das Tagessoll weiter, die gearbeitete Zeit bleibt bei null, und clockin
    schreibt die Abwesenheit an anderer Stelle gut. Ein Vergleich
    "gearbeitet gegen Soll" saehe dann nach einem grossen Minus aus, das es
    nicht gibt. Deshalb steht dort die reine Summe.

    Ein Abruf fuer beides: der Monat bis heute enthaelt den heutigen Tag.
    Faellt clockin aus, gibt es die Zeile nicht — der Kalender bleibt heil.
    """
    kennung = env.get("CLOCKIN_PERSON_ID") or ""
    if not (env.get("CLOCKIN_TOKEN") and kennung):
        return None
    try:
        heute = datetime.now(ZONE).date()
        daten = clockin_api.arbeitstage([int(kennung)], heute.replace(day=1), heute)
        tage = (daten[0].get("workdays") if daten else []) or []

        monat_sekunden = sum(int(w.get("work_seconds") or 0) for w in tage)
        monat_tage = sum(1 for w in tage if (w.get("work_seconds") or 0) > 0)
        monat = {"erfasst": monat_sekunden, "tage": monat_tage}

        tag = next((w for w in tage if w.get("date") == heute.isoformat()), None)
        if not tag:
            return {"erfasst": 0, "soll": 0, "laeuft": False, "seit": None,
                    "bis": None, "monat": monat}

        def uhr(wert):
            if not wert:
                return None
            return (datetime.fromisoformat(str(wert).replace("Z", "+00:00"))
                    .astimezone(ZONE).strftime("%H:%M"))

        # Laeuft die Stempeluhr gerade? Dann hat die letzte Buchung kein Ende.
        buchungen = tag.get("activities") or []
        laeuft = bool(buchungen) and not (buchungen[-1] or {}).get("ends_at")
        return {"erfasst": int(tag.get("work_seconds") or 0),
                "soll": int(tag.get("target_seconds") or 0),
                "pause": int(tag.get("break_seconds") or 0),
                "laeuft": laeuft,
                "seit": uhr(tag.get("starts_at")),
                "bis": None if laeuft else uhr(tag.get("ends_at")),
                "monat": monat}
    except Exception:                                             # noqa: BLE001
        return None
