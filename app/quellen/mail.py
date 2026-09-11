"""Posteingang — beliebig viele Postfaecher, gemischt.

Jedes Postfach traegt seinen eigenen **Weg**: entweder die
**Hostinger-Mail-API** (Bearer-Token, kein Passwort noetig, kennt aber nur
Postfaecher, die dort gefuehrt werden) oder **IMAP** (Passwort noetig, geht
dafuer mit jedem Anbieter — genau daran scheiterte es im Sommer 2026, siehe
der Anbieter-Doku).

**Warum der Weg am Postfach haengt und nicht mehr am Dashboard:** Bis zum
10.09.2026 gab es einen einzigen Schalter fuer alle. Wer die API benutzte,
hatte genau ein Postfach und kam an kein zweites; wer auf IMAP stellte, verlor
das erste aus dem Blick. Ein Haus mit zwei Tueren braucht keinen Schalter,
welche Tuer benutzt wird — es braucht pro Tuer einen Schluessel.

Gelesen wird ausschliesslich lesend: die API macht nur `GET` und ruehrt das
`\\Seen`-Flag nicht an, IMAP holt Koepfe nur mit `BODY.PEEK`. Ein gewoehnliches
`FETCH BODY[]` wuerde das Postfach beim blossen Hinsehen als gelesen
markieren.

**Ein defektes Postfach darf die Karte nicht leeren.** Faellt eines aus, kommen
die uebrigen trotzdem, und die Karte nennt im Hinweis, welches klemmt und
warum. Alles-oder-nichts waere hier die falsche Wahl: Wer drei Postfaecher hat,
verliert sonst wegen eines abgelaufenen Passworts den Blick auf die anderen
beiden.

Vor api.mail.hostinger.com sitzt Cloudflare und weist die Vorgabe-Kennung
"Python-urllib/3.x" mit 403 ab. Deshalb die eigene User-Agent-Zeile.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from .. import profil
from ..posten import posten, sortieren

NAME = "mail"
TITEL = "Posteingang"
ICON = "✉️"
TTL = 180
ANLAUF = 2
# Kein fester Link an der Karte: Der Fuss zeigte sonst „Webmail öffnen“ nach
# Hostinger, auch wenn dort ein IMAP-Postfach eines ganz anderen Anbieters
# hinterlegt ist. Wohin er zeigt, entscheidet `_kartenlink()` aus den
# tatsaechlich hinterlegten Postfaechern.
LINK = None
LINK_TEXT = "Webmail"
# Vorgabe fuer die Zahl oben: (grosse Zahl, Warnzahl, Warntext)
KOPFZAHL = ("Ungelesen", "Ungelesen", "ungelesen")
# Nur fuer den API-Weg: Der laeuft ueber Hostinger, also ist das dort die
# richtige Webmail-Adresse — aber eben nur dort.
HOSTINGER_WEBMAIL = "https://mail.hostinger.com/"

API = "https://api.mail.hostinger.com/api/v1"
USER_AGENT = (f"Mozilla/5.0 (compatible; smg-{profil.INSTANZ}/1.0; "
              f"+https://{profil.HOST})")
TIMEOUT = 25
TAGE = 14
MAX = 40            # so viele Zeilen zeigt die Karte je Postfach
# Fuer die Erkennung im Tagesfortschritt muss das Modul ALLE Nachrichten im
# Fenster kennen, nicht nur die 40 angezeigten — sonst saehe eine Mail, die aus
# den 40 rutscht, aus wie eine, die wegsortiert wurde. Kopfzeilen sind billig.
MAX_BESTAND = 300
# Werbung ist kein Vorgang. Was hier passt, wird angezeigt, aber nie rot.
# Absender, die nie rot werden. Die Vorgabe sind allgemeine Muster; eigene
# Lieferanten und Newsletter kommen ueber MAIL_WERBUNG dazu (kommagetrennt).
# Firmennamen gehoeren nicht in den Quelltext, sondern in die Einstellungen.
WERBUNG_VORGABE = ("noreply@", "no-reply@", "newsletter@", "news@",
                   "mailer-daemon@", "notifications@")


def _werbung(env: dict) -> tuple:
    eigene = [w.strip().lower() for w in
              (env.get("MAIL_WERBUNG") or "").split(",") if w.strip()]
    return tuple(WERBUNG_VORGABE) + tuple(eigene)


def _hole(pfad: str, token: str, params: dict | None = None):
    url = f"{API}{pfad}" + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as antwort:
            return json.loads(antwort.read().decode())
    except urllib.error.HTTPError as err:
        koerper = err.read().decode(errors="replace")[:200]
        raise RuntimeError(f"HTTP {err.code} bei {pfad}: {koerper}") from err


def _postfach_id(token: str, adresse: str) -> str:
    """Die Ressourcen-Kennung des Postfachs. Es gibt keinen eigenen Endpunkt
    dafuer — sie steht in /me unter data.mailboxes[]."""
    daten = _hole("/me", token)
    for fach in ((daten.get("data") or {}).get("mailboxes") or []):
        if (fach.get("address") or "").lower() == adresse.lower():
            return fach.get("resourceId") or ""
    return ""


def _alle(env: dict) -> dict:
    """Alle aktiven Postfaecher lesen und zusammenfuehren."""
    from .. import db

    konten = [k for k in db.mailkonten(mit_passwort=True) if k.get("aktiv")]
    if not konten:
        return {"posten": [], "kennzahlen": {},
                "hinweis": "Noch kein Postfach hinterlegt — unter Settings "
                           "eines anlegen."}

    liste, bestand, gelesen, ungelesen_gesamt, probleme = [], [], [], 0, []
    abgeschnitten = []
    for konto in konten:
        try:
            teil = _ein_postfach(konto, _werbung(env))
        except Exception as fehler:                               # noqa: BLE001
            name = konto.get("bezeichnung") or konto.get("benutzer") or "Postfach"
            probleme.append(f"{name}: {fehler}")
            continue
        liste.extend(teil["posten"])
        bestand.extend(teil.get("bestand") or [])
        ungelesen_gesamt += teil["ungelesen"]
        # Nur Postfaecher, die wirklich gelesen wurden, gelten als Gruppe.
        # Faellt eines aus, fehlen seine Mails — sie sind nicht erledigt.
        gelesen.append(str(konto.get("id")))
        if teil.get("abgeschnitten"):
            abgeschnitten.append(konto.get("bezeichnung") or konto.get("benutzer") or "?")

    kennzahlen = {"Ungelesen": ungelesen_gesamt, "Im Blick": len(liste)}
    if len(konten) > 1:
        kennzahlen["Postfächer"] = len(konten) - len(probleme)
    return {"posten": sortieren(liste),
            "kennzahlen": kennzahlen,
            "link": _kartenlink(konten),
            "bestand": bestand,
            "gruppen": gelesen,
            "fenster_tage": TAGE,
            "diff_sperre": (f"Postfach über {MAX_BESTAND} Nachrichten im Fenster: "
                            + ", ".join(abgeschnitten)) if abgeschnitten else None,
            "hinweis": ("Nicht erreichbar — " + " · ".join(probleme)) if probleme else None}


def _webadresse(wert) -> str | None:
    """Nur echte Web-Adressen werden zu einem Link.

    Im Feld „Webmail-Adresse“ landet leicht die **E-Mail**-Adresse — genau das
    ist am 10.09.2026 passiert. Als `href` waere das ein relativer Pfad: Der
    Knopf sieht aus wie ein Link und fuehrt ins Nichts. Lieber gar kein Link
    als einer, der nirgends hinfuehrt.
    """
    ziel = (wert or "").strip()
    if ziel[:7].lower() == "http://" or ziel[:8].lower() == "https://":
        return ziel
    return None


def _kartenlink(konten: list) -> str | None:
    """Wohin „Webmail öffnen“ im Fuss der Karte zeigt.

    **Nur wenn es eine eindeutige Antwort gibt.** Bei einem Postfach ist das
    dessen Webmail-Adresse. Bei mehreren mit derselben Adresse ebenfalls. Bei
    mehreren mit verschiedenen Adressen gibt es keinen richtigen Link mehr —
    dann bleibt der Fuss leer, und man geht ueber die einzelne Zeile, die ihr
    eigenes Postfach kennt. Ein Link, der fuer die Haelfte der Zeilen zum
    falschen Anbieter fuehrt, ist schlechter als keiner.
    """
    adressen = []
    for konto in konten:
        ziel = _webadresse(konto.get("webmail"))
        if not ziel and (konto.get("weg") or "imap").lower() == "api":
            ziel = HOSTINGER_WEBMAIL
        if ziel and ziel not in adressen:
            adressen.append(ziel)
    return adressen[0] if len(adressen) == 1 else None


def _ein_postfach(konto: dict, werbung=None) -> dict:
    """Ein einzelnes Postfach lesen — auf dem Weg, den es selbst nennt."""
    werbung = werbung or WERBUNG_VORGABE
    if (konto.get("weg") or "imap").strip().lower() == "api":
        return _ein_postfach_api(konto, werbung)
    return _ein_postfach_imap(konto, werbung)


def _ein_postfach_imap(konto: dict, werbung=WERBUNG_VORGABE) -> dict:
    """Ein Postfach per IMAP lesen."""
    import email.header
    import email.utils
    import imaplib

    # Keine Vorgabe fuer den Server: Der haengt am Anbieter, und ein
    # eingebauter Standard waere entweder falsch oder eine stille Wette auf
    # einen bestimmten Anbieter. Port 993 und INBOX sind dagegen echte
    # Standards.
    host = (konto.get("host") or "").strip()
    port = int(konto.get("port") or 993)
    benutzer = (konto.get("benutzer") or "").strip()
    passwort = konto.get("passwort") or ""
    ordner = (konto.get("ordner") or "").strip() or "INBOX"
    # Ohne eigene Webmail-Adresse lieber gar kein Link als einer, der zum
    # falschen Anbieter fuehrt.
    webmail = _webadresse(konto.get("webmail"))
    kennung_konto = konto.get("id")
    name = (konto.get("bezeichnung") or benutzer or "Postfach").strip()

    fehlt = [f for f, wert in (("Server", host), ("Benutzer", benutzer),
                               ("Passwort", passwort)) if not wert]
    if fehlt:
        raise RuntimeError(f"unvollständig ({', '.join(fehlt)} fehlt)")

    def kopf_text(roh) -> str:
        """Umlaute lesbar machen — sie stehen dort als =?utf-8?Q?…?=."""
        if roh is None:
            return ""
        stuecke = email.header.decode_header(roh)
        ergebnis = []
        for wert, kodierung in stuecke:
            if isinstance(wert, bytes):
                try:
                    ergebnis.append(wert.decode(kodierung or "utf-8", "replace"))
                except LookupError:
                    ergebnis.append(wert.decode("utf-8", "replace"))
            else:
                ergebnis.append(wert)
        return "".join(ergebnis).strip()

    seit = (datetime.now() - timedelta(days=TAGE)).strftime("%d-%b-%Y")
    # Verbindung je Abruf neu: Hostinger trennt untaetige Sitzungen, und ein
    # Takt alle 30 Minuten haelt ohnehin nichts warm.
    try:
        verbindung = imaplib.IMAP4_SSL(host, port, timeout=30)
    except OSError as fehler:
        raise RuntimeError(f"{host}:{port} nicht erreichbar — {fehler}") from fehler

    liste, bestand, ungelesen_zahl = [], [], 0
    try:
        try:
            verbindung.login(benutzer, passwort)
        except imaplib.IMAP4.error as fehler:
            # Die Rohmeldung ist ein bytes-Objekt und steht sonst als
            # b'[AUTHENTICATIONFAILED] …' in der Karte. Wer das liest, sucht
            # den Fehler im Dashboard statt im Passwort.
            roh = str(fehler)
            if "AUTHENTICATIONFAILED" in roh.upper():
                raise RuntimeError(
                    f"Anmeldung am Postfach {benutzer} abgelehnt — "
                    f"Benutzer oder Passwort stimmen nicht.") from fehler
            raise RuntimeError(f"IMAP-Anmeldung fehlgeschlagen: {roh[:150]}") from fehler
        # readonly: schon das Auswaehlen darf nichts veraendern.
        verbindung.select(ordner, readonly=True)
        _, roh_ungelesen = verbindung.search(None, "UNSEEN")
        ungelesen = set(roh_ungelesen[0].split())
        _, roh_jung = verbindung.search(None, f'(SINCE "{seit}")')
        # Beantwortet = erledigt (entschieden am 10.09.2026). Eine SEARCH statt
        # FLAGS je Nachricht: gleiches Muster wie UNSEEN, nichts zu parsen.
        _, roh_beantwortet = verbindung.search(None, "ANSWERED")
        beantwortet = set(roh_beantwortet[0].split())
        # Nach Laufnummer sortiert liegen die neuesten hinten — vorher kam die
        # Reihenfolge aus einem set und war Zufall.
        kennungen = sorted(set(list(ungelesen) + roh_jung[0].split()), key=int)
        abgeschnitten = len(kennungen) > MAX_BESTAND
        kennungen = kennungen[-MAX_BESTAND:]

        # EIN Abruf fuer alle Kopfzeilen statt einer je Nachricht. In der
        # Antwort steht die Laufnummer vorn im ersten Teil jedes Tupels; die
        # Reihenfolge ist nicht garantiert, deshalb wird sie ausgelesen.
        koepfe = {}
        for i in range(0, len(kennungen), 100):
            stueck = kennungen[i:i + 100]
            _, daten = verbindung.fetch(
                ",".join(k.decode() for k in stueck),
                "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])")
            for teil in daten:
                if isinstance(teil, tuple) and len(teil) >= 2:
                    nummer = teil[0].split()[0] if teil[0] else b""
                    koepfe[nummer] = teil[1]

        for kennung in reversed(kennungen):
            nachricht = email.message_from_bytes(koepfe.get(kennung, b""))
            betreff = kopf_text(nachricht.get("Subject")) or "(kein Betreff)"
            wann = None
            try:
                wann = email.utils.parsedate_to_datetime(nachricht.get("Date"))
            except (TypeError, ValueError):
                pass
            absender_name, adresse = email.utils.parseaddr(
                kopf_text(nachricht.get("From")))
            roh_id = (nachricht.get("Message-ID") or kennung.decode()).strip("<> ")
            schluessel = f"{kennung_konto}:{roh_id}"
            datum = wann.date().isoformat() if wann else None
            ist_beantwortet = kennung in beantwortet
            neu_da = kennung in ungelesen

            # Der Bestand kennt alles, auch Beantwortetes — daran erkennt der
            # Tagesfortschritt den Uebergang „offen -> beantwortet".
            bestand.append({"kennung": schluessel, "titel": betreff[:120],
                            "datum": datum, "gruppe": str(kennung_konto),
                            "erledigt": ist_beantwortet})
            if ist_beantwortet:
                # Beantwortet heisst erledigt, und Erledigtes steht nicht mehr
                # auf der eigenen Liste — wie ein abgeschlossenes Todo.
                continue
            if neu_da:
                ungelesen_zahl += 1
            if len(liste) >= MAX:
                continue
            ist_werbung = any(w in (adresse or "").lower() for w in werbung)
            if neu_da and not ist_werbung:
                ampel, marke = "rot", "Ungelesen"
            elif neu_da:
                ampel, marke = "blau", "Newsletter"
            else:
                ampel, marke = "blau", (wann.strftime("%H:%M") if wann else "")
            liste.append(posten(
                # Kontokennung mit hinein: Dieselbe Nachricht kann in zwei
                # Postfaechern liegen (Weiterleitung), und zwei Haken auf
                # denselben Schluessel waeren nicht auseinanderzuhalten.
                kennung=schluessel,
                titel=(absender_name or adresse or "Absender")[:80],
                ampel=ampel,
                datum=datum,
                text=betreff[:160],
                marke=marke,
                link=webmail,
                # Volle Uhrzeit nur zum Sortieren: `datum` bleibt der Tag,
                # weil die Anzeige daraus „gestern“ macht. Ohne diesen Wert
                # waere die Reihenfolge mehrerer Mails desselben Tages
                # zufaellig — und das ist im Posteingang der Normalfall.
                # Dasselbe Muster wie in kalender.py.
                zusatz={"absender": adresse, "weg": "imap", "postfach": name,
                        "sortier": wann.isoformat() if wann else ""},
            ))
    finally:
        try:
            verbindung.logout()
        except Exception:                                         # noqa: BLE001
            pass

    return {"posten": liste, "ungelesen": ungelesen_zahl,
            "bestand": bestand, "abgeschnitten": abgeschnitten}


def _ein_postfach_api(konto: dict, werbung=WERBUNG_VORGABE) -> dict:
    """Ein Postfach ueber die Hostinger-Mail-API lesen.

    Token und Adresse stehen am Postfach selbst, nicht mehr global — deshalb
    laesst sich ein zweites API-Postfach mit eigenem Token danebenstellen.
    """
    token = (konto.get("passwort") or "").strip()
    adresse = (konto.get("benutzer") or "").strip()
    name = (konto.get("bezeichnung") or adresse or "Postfach").strip()
    webmail = _webadresse(konto.get("webmail")) or HOSTINGER_WEBMAIL
    kennung_konto = konto.get("id")

    if not token:
        raise RuntimeError("kein Token hinterlegt")
    if not adresse:
        raise RuntimeError("keine Adresse hinterlegt")

    fach_id = (konto.get("postfach_id") or "").strip() or _postfach_id(token, adresse)
    if not fach_id:
        raise RuntimeError(f"{adresse} ist in der Hostinger-Mail-API nicht gelistet")

    grenze = datetime.now(timezone.utc) - timedelta(days=TAGE)

    # Seitenweise, bis das Fenster durch ist oder der Bestand voll: Vorher
    # gab es nur die erste Seite mit 40 — fuer die Erkennung muss das Modul
    # aber alles im Fenster kennen. Sehr alte ungelesene Mails jenseits der
    # Seiten, die das Fenster braucht, bleiben aussen vor; das ist die
    # bewusste Grenze dieses Wegs.
    nachrichten, seite, abgeschnitten = [], 1, False
    while True:
        antwort = _hole(f"/mailboxes/{fach_id}/folders/INBOX/messages", token,
                        {"perPage": 100, "page": seite})
        blatt = antwort.get("data") or []
        nachrichten.extend(blatt)
        if len(nachrichten) >= MAX_BESTAND:
            abgeschnitten = len(blatt) >= 100
            nachrichten = nachrichten[:MAX_BESTAND]
            break
        if len(blatt) < 100:
            break
        aelteste = None
        try:
            aelteste = datetime.fromisoformat(
                str(blatt[-1].get("date")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            pass
        if aelteste and aelteste < grenze:
            break
        seite += 1

    liste, bestand, ungelesen = [], [], 0
    for n in nachrichten:
        absender = n.get("from") or {}
        adresse_von = (absender.get("address") or "").lower()
        wann = None
        try:
            wann = datetime.fromisoformat(str(n.get("date")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            pass
        if wann and wann < grenze and not n.get("unseen"):
            continue
        roh_id = str(n.get("messageId") or n.get("uid")).strip("<> ")
        schluessel = f"{kennung_konto}:{roh_id}"
        datum = wann.date().isoformat() if wann else None
        # Ob die API ein Antwort-Merkmal liefert, ist nicht dokumentiert —
        # falls ja, wird es genutzt, sonst zaehlt hier nur das Verschwinden.
        ist_beantwortet = bool(n.get("answered") or n.get("isAnswered"))
        bestand.append({"kennung": schluessel,
                        "titel": (n.get("subject") or "(kein Betreff)")[:120],
                        "datum": datum, "gruppe": str(kennung_konto),
                        "erledigt": ist_beantwortet})
        if ist_beantwortet:
            continue
        ist_werbung = any(w in adresse_von for w in werbung)
        neu = bool(n.get("unseen"))
        if neu:
            ungelesen += 1
        if len(liste) >= MAX:
            continue
        if neu and not ist_werbung:
            ampel, marke = "rot", "Ungelesen"
        elif neu:
            ampel, marke = "blau", "Newsletter"
        else:
            ampel, marke = "blau", (wann.strftime("%H:%M") if wann else "")
        liste.append(posten(
            # Kontokennung mit hinein: Dieselbe Nachricht kann in zwei
            # Postfaechern liegen (Weiterleitung), und zwei Haken auf denselben
            # Schluessel waeren nicht auseinanderzuhalten.
            kennung=schluessel,
            titel=(absender.get("name") or adresse_von or "Absender")[:80],
            ampel=ampel,
            datum=datum,
            text=(n.get("subject") or "(kein Betreff)")[:160],
            marke=marke,
            link=webmail,
            zusatz={"absender": adresse_von, "weg": "api", "postfach": name,
                    "anhaenge": len(n.get("attachments") or []),
                    # Siehe IMAP-Zweig: die Uhrzeit nur fuer die Sortierung.
                    "sortier": wann.isoformat() if wann else ""},
        ))

    return {"posten": liste, "ungelesen": ungelesen,
            "bestand": bestand, "abgeschnitten": abgeschnitten}


def eingerichtet(env: dict) -> bool:
    """Die Karte braucht keine Einstellung, sondern ein angelegtes Postfach.

    Postfaecher stehen in der Datenbank, nicht in der .env — deshalb reicht
    hier keine Schluesselliste."""
    from .. import db
    try:
        return any(k.get("aktiv") for k in db.mailkonten())
    except Exception:                                             # noqa: BLE001
        return True

def fetch(env: dict) -> dict:
    return _alle(env)
