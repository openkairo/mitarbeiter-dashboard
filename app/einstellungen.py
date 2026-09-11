"""Zugangsdaten und Kennungen der Karten — pflegbar über die Oberfläche.

**Sie standen nie im Quellcode.** Der Code liest ausschliesslich
Umgebungsvariablen; die Werte liegen in der `.env` der Instanz. Was
fehlte, war ein Weg, sie ohne SSH zu aendern — etwa wenn ein Lexware-Schluessel
neu gewuerfelt wird.

Rangfolge: **Datenbank schlaegt .env.** Die .env bleibt damit die
Erstausstattung; was ueber die Oberflaeche gesetzt wird, gilt danach. Ein
geleertes Feld faellt auf die .env zurueck.

Zwei Regeln, die diese Datei durchsetzt:

  * **Geheimnisse gehen nie zurueck an den Browser.** Die Oberflaeche erfaehrt
    nur, ob etwas gesetzt ist, woher es kommt und die letzten vier Zeichen.
    Ein Feld, das den Schluessel im Klartext anzeigt, steht sonst offen in
    jedem Bildschirmfoto und in jedem ueber die Schulter geworfenen Blick.
  * **Nur Verwalter duerfen hier hinein.** Wer die Karten benutzt, braucht
    keine API-Schluessel;
    sie braucht die Karten. Wer verwalten darf, steht in ADMINS.
"""

from __future__ import annotations

import os

from . import db, profil

# (Schluessel, Beschriftung, Gruppe, geheim?, Hilfetext, Auswahl|None, optional?)
# Die Auswahl zeichnet ein Klappfeld statt eines Textfelds; "optional" heisst,
# dass ein leeres Feld kein Fehler ist. Beide Angaben duerfen fehlen.
FELDER = [
    # Wer das Dashboard benutzt. Steht auch in der .env, laesst sich aber hier
    # aendern — der Einrichtungsassistent fragt genau danach, und ein Name,
    # fuer den man einen Neustart braucht, ist kein Name, den man eintraegt.
    ("PERSON_NAME", "Name", "Person", False,
     "Steht in der Begrüßung oben. Leer lassen heißt: Begrüßung ohne Namen.",
     None, True),
    ("TITEL", "Rolle", "Person", False,
     "Die Überschrift in der Seitenleiste — etwa „Buchhaltung“ oder „Support“.",
     None, True),
    ("FIRMA", "Firma", "Person", False,
     "Die kleine Zeile darunter. Leer lassen, wenn dort nichts stehen soll.",
     None, True),
    ("ANSPRECHPARTNER", "Hilfe von", "Person", False,
     "Wer hilft, wenn etwas unklar ist. Steht im Fuß der Seite und bei einer "
     "Abwesenheit im Kalender.", None, True),

    ("LEXWARE_API_KEY", "API-Schlüssel", "Lexware", True,
     "Steuert die Karte „Offene Ausgangsrechnungen“. In Lexware unter "
     "Einstellungen → Öffentliche API."),

    ("TODOMASTER_URL", "MCP-Adresse", "Todomaster", False,
     "Der MCP-Endpunkt von Todomaster."),
    ("TODOMASTER_TOKEN", "Token", "Todomaster", True, ""),
    ("TODO_KATEGORIEN", "Kategorien", "Todomaster", False,
     "Kommagetrennt, z. B. buchhaltung,einkauf"),

    ("WP_URL", "Shop-Adresse", "Webshop", False,
     "Wurzeladresse des Shops, ohne /wp-json."),
    ("WC_KEY", "WooCommerce-Schlüssel", "Webshop", True,
     "Steuert „Offene Bestellungen“ und die Kundendaten bei Widerrufen."),
    ("WC_SECRET", "WooCommerce-Geheimnis", "Webshop", True, ""),

    ("SUPERCHAT_API_KEY", "API-Schlüssel", "Superchat", True, ""),
    ("SUPERCHAT_FARBEN", "Farben je Postfach", "Superchat", False,
     "Optional, nur bei mehreren Postfächern. Form „Postfach:Farbe“, mehrere "
     "durch Komma — z. B. „BEZAHLEN:rot, Buchhaltung:violett“. Möglich sind "
     "rot, orange, violett, türkis, magenta, bernstein, indigo, oliv. Was hier "
     "nicht steht, bekommt eine Farbe nach seinem Platz in der Liste. "
     "**Rot bedeutet auf den Karten sonst „dringend“** — nimm es nur für ein "
     "Postfach, das wirklich Vorrang hat.", None, True),
    ("SUPERCHAT_INBOX_ID", "Postfach-Kennung(en)", "Superchat", False,
     "Aus der Liste wählen — sie kommt aus Superchat, sobald der API-Schlüssel "
     "steht. Mehrere sind möglich; die Karte führt sie zusammen und schreibt "
     "an jede Zeile, aus welchem Postfach sie kommt."),

    # Der Posteingang steht NICHT mehr hier. Bis zum 10.09.2026 gab es einen
    # globalen Weg (API oder IMAP) und genau ein API-Postfach, fest in vier
    # Feldern verdrahtet — es liess sich weder loeschen noch ein zweites
    # danebenstellen. Jetzt ist jedes Postfach eine Zeile in `mailkonto` mit
    # eigenem Weg, eigenem Zugang und eigenem Loeschknopf; gepflegt wird die
    # Liste in den Settings unter „Postfächer“. Ein flaches Feld je Angabe
    # haette bei drei Postfaechern zwanzig Felder bedeutet, die niemand mehr
    # auseinanderhaelt.

    ("ANTWORT_WEBHOOK_URL", "Webhook-Adresse", "Rückmeldungen", False,
     f"Wohin gemeldet wird, sobald {profil.NAME} auf eine Nachricht antwortet. "
     "Leer lassen, wenn die KI stattdessen selbst nachfragt.", None, True),
    ("ANTWORT_WEBHOOK_BEARER", "Cursor Authorization (Bearer)", "Rückmeldungen", True,
     "Der „Webhook key“ aus der Grok-Routine, beginnt mit crsr_. Wird als "
     "Authorization: Bearer … gesendet. Cursor verlangt ihn zwingend — ohne "
     "ihn kommt 401 zurück und die Routine läuft nie an.", None, True),
    ("ANTWORT_WEBHOOK_SECRET", "SMG-HMAC (optional)", "Rückmeldungen", True,
     "Unterschreibt den Rumpf (HMAC-SHA256, Kopfzeile X-SMG-Signatur) — für "
     "andere Empfänger. **Kein Ersatz für den Bearer**: Der Cursor-Schlüssel "
     "gehört ins Feld darüber, nicht hierher.", None, True),

    ("KALENDER_ID", "Kalender", "Kalender", False,
     "Kennung des Google-Kalenders, meist die Adresse des Kontos. Nach der "
     "Anmeldung oben kannst du ihn stattdessen aus einer Liste wählen."),
    # Der zweite Weg zum Kalender: die normale Google-Anmeldung statt einer
    # Schluesseldatei auf dem Server. Alles optional — wer ein Dienstkonto
    # gemountet hat, soll hier nicht rot angemahnt werden.
    ("GOOGLE_CLIENT_ID", "Client-ID", "Kalender", False,
     "Aus der Google-Konsole, OAuth-Client vom Typ „Webanwendung“. Eine "
     "Client-ID ist kein Geheimnis — sie steht offen, damit du sie mit der "
     "Konsole vergleichen kannst.", None, True),
    ("GOOGLE_CLIENT_SECRET", "Client-Geheimnis", "Kalender", True,
     "Steht neben der Client-ID in der Google-Konsole.", None, True),
    ("GOOGLE_REFRESH_TOKEN", "Anmeldung", "Kalender", True,
     "Setzt der Knopf „Mit Google anmelden“ von selbst. Von Hand nur nötig, "
     "wenn du die Anmeldung woanders erzeugt hast.", None, True),

    ("CLOCKIN_TOKEN", "API-Token", "clockin", True,
     "Für die Zeitzeile im Kopf. Ohne ihn fällt nur diese Zeile weg."),
    ("CLOCKIN_PERSON_ID", f"Mitarbeiter-Nummer {profil.NAME}", "clockin", False,
     "Wessen Zeiten im Kopf stehen. Nummern zeigt clockin unter Mitarbeiter."),

    ("FAQ_MCP_URL", "FAQ-Adresse", "FAQ", True,
     "Volle MCP-Adresse der Wissensbasis, der Zugangsschlüssel steckt darin "
     "im Pfad. Steuert die Karte „FAQ-Nachschlag“ — ohne sie sagt die Karte "
     "das und schlägt nichts nach.", None, True),
]

# Alle Zeilen auf dieselbe Laenge bringen: (…, Auswahl, optional?). "Optional"
# heisst: wird nur in einer bestimmten Betriebsart gebraucht und darf deshalb
# leer sein, ohne dass die Seite Alarm schlaegt.
FELDER = [f + (None,) * (7 - len(f)) for f in FELDER]

SCHLUESSEL = [f[0] for f in FELDER]
GEHEIM = {f[0] for f in FELDER if f[3]}

# Welche Karte an welcher Gruppe haengt — fuer den Knopf „Verbindung prüfen“.
GRUPPE_KARTE = {
    "Lexware": "rechnungen",
    "Todomaster": "todos",
    "Webshop": "shop",
    "Superchat": "superchat",
    "Posteingang": "mail",
    "Kalender": "kalender",
    "clockin": "kalender",       # die Zeitzeile haengt am Kalender-Abruf
    "FAQ": "faq",
}


def umgebung() -> dict:
    """Die geltenden Werte: Datenbank schlaegt .env.

    Wird bei **jedem** Abruf neu gebildet, nicht einmal beim Start — sonst
    wirkte eine geaenderte Einstellung erst nach einem Neustart, und niemand
    wuesste warum.
    """
    werte = {s: os.environ.get(s, "") for s in SCHLUESSEL}
    # Ein paar Werte kommen nur aus der Umgebung (Pfade im Container).
    for s in ("GOOGLE_KEY", "CLOCKIN_BASIS"):
        werte[s] = os.environ.get(s, "")
    for schluessel, wert in db.einstellungen().items():
        if wert:
            werte[schluessel] = wert
    # Bis zum 10.09.2026 hiess die clockin-Nummer CLOCKIN_LISA_ID. Der alte
    # Name gilt weiter, solange der neue leer ist — sonst haette der Umbau auf
    # zwei Instanzen die Zeitzeile abgeschaltet, ohne dass jemand etwas
    # falsch gemacht haette.
    if not werte.get("CLOCKIN_PERSON_ID"):
        werte["CLOCKIN_PERSON_ID"] = (os.environ.get("CLOCKIN_LISA_ID", "")
                                      or db.einstellungen().get("CLOCKIN_LISA_ID", ""))
    return werte


def _herkunft(schluessel: str, aus_db: dict, wer: dict, wert: str) -> str:
    if aus_db.get(schluessel):
        von, am = wer.get(schluessel, ("", ""))
        # Wer zuletzt gespeichert hat, gehoert sichtbar dazu — seit die Seite
        # allen offensteht, ist das der einzige Weg, eine Aenderung zuzuordnen.
        wann = (am or "")[:16].replace("T", " ")
        return f"hier eingetragen von {von or 'jemandem'}" + (f", {wann}" if wann else "")
    return ".env auf dem Server" if wert else "fehlt"


def _spur(wert: str) -> str:
    """Was von einem Geheimnis gezeigt werden darf: die letzten vier Zeichen."""
    wert = wert or ""
    if len(wert) <= 4:
        return "····"
    return "····" + wert[-4:]


def uebersicht() -> list:
    """Fuer die Oberflaeche — ohne Klartext-Geheimnisse."""
    aus_db = db.einstellungen()
    wer = db.einstellung_herkunft()
    jetzt = umgebung()
    zeilen = []
    for schluessel, titel, gruppe, geheim, hilfe, auswahl, optional in FELDER:
        wert = jetzt.get(schluessel, "")
        zeilen.append({
            "schluessel": schluessel,
            "titel": titel,
            "gruppe": gruppe,
            "geheim": geheim,
            "hilfe": hilfe,
            "auswahl": [{"wert": w, "titel": b} for w, b in (auswahl or [])],
            "optional": bool(optional),
            "gesetzt": bool(wert),
            "herkunft": _herkunft(schluessel, aus_db, wer, wert),
            # Geheimnisse nur als Spur, alles andere im Klartext — eine
            # Postfach-Kennung zu verstecken hilft niemandem.
            "wert": _spur(wert) if geheim else wert,
        })
    return zeilen


def setzen(werte: dict, von: str, loeschen=None) -> list:
    """Speichert die uebergebenen Felder. Leerer Wert = zurueck auf .env.

    `loeschen` ist der **ausdrueckliche** Weg, einen hier eingetragenen Wert
    wieder loszuwerden. Noetig, weil ein leeres Geheimnis-Feld beim Speichern
    „unveraendert lassen" bedeutet — sonst wuerde jedes Speichern der uebrigen
    Felder die Schluessel mitloeschen. Ohne diesen zweiten Weg gaebe es gar
    keine Moeglichkeit, ein Geheimnis wieder zu entfernen.
    """
    geaendert = []
    for schluessel in (loeschen or []):
        if schluessel in SCHLUESSEL:
            db.einstellung_setzen(schluessel, "", von)
            geaendert.append(schluessel)
    for schluessel, wert in werte.items():
        if schluessel not in SCHLUESSEL or schluessel in (loeschen or []):
            continue
        db.einstellung_setzen(schluessel, (wert or "").strip(), von)
        geaendert.append(schluessel)
    return geaendert
