"""Offene Ausgangsrechnungen aus Lexware.

**Warum hier nicht alles rot ist, obwohl Lexware das sagt.** Shop-Rechnungen
sind sofort faellig: `dueDate` = `voucherDate`. Lexware fuehrt sie deshalb noch
am Ausstellungstag als `overdue` — am 09.09.2026 waren das 142 von 142 offenen
Belegen. Eine Karte, auf der alles rot leuchtet, sagt genau so viel wie eine,
auf der nichts rot leuchtet. Die Ampel richtet sich hier deshalb danach, **wie
lange** etwas ueberfaellig ist.

Aus demselben Grund gibt es nur EINEN Abruf: `voucherStatus=overdue` liefert
dieselben 143 Belege wie `open` (nachgemessen 09.09.2026) und waere reine
Verschwendung am 2-Anfragen-Limit.

Angezeigt werden die **20 neuesten** — dieselbe Regel wie im 12-Uhr-Post: nie
den ganzen Stapel. Der Rest steht als Zahl darueber; das Mahnwesen der alten
Posten ist keine Tagesarbeit.

Positivliste ueber die Belegnummer: Unter `salesinvoice` liegen auch
Umsatzsteuervoranmeldungen und Finanzamtsbelege. `voucherType` allein trennt
Verkauf nicht von Verwaltung — die Belegnummer tut es (RE- und SG-).
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from ..lexware import Lexware
from ..posten import bestand_aus, posten, tage_alt

NAME = "rechnungen"
TITEL = "Offene Ausgangsrechnungen"
ICON = "🧾"
TTL = 900
ANLAUF = 8
# Ohne diese Einstellungen kann die Karte nichts holen — dann erscheint
# sie gar nicht erst, statt „nichts zu tun“ zu behaupten.
BRAUCHT = ("LEXWARE_API_KEY",)

LINK = "https://app.lexoffice.de/permanent/vouchers"
LINK_TEXT = "Lexware"

VERKAUF = re.compile(r"^(RE|SG)-", re.IGNORECASE)
FENSTER_TAGE = 400
MAX_SEITEN = 12
ANZEIGE = 20
ALT_AB_TAGEN = 30
KOPFZAHL = ("Offen", f"Über {ALT_AB_TAGEN} Tage", f"über {ALT_AB_TAGEN} Tage")


def fetch(env: dict) -> dict:
    schluessel = env.get("LEXWARE_API_KEY") or ""
    if not schluessel:
        return {"posten": [], "kennzahlen": {},
                "hinweis": "LEXWARE_API_KEY fehlt in der .env."}

    lex = Lexware(schluessel)
    von = (date.today() - timedelta(days=FENSTER_TAGE)).isoformat()
    belege, seite = [], 0
    while seite < MAX_SEITEN:
        antwort = lex.belegliste(seite=seite, datum_von=von, status="open")
        inhalt = antwort.get("content") or []
        belege.extend(inhalt)
        if antwort.get("last") or not inhalt:
            break
        seite += 1
    # Bricht die Schleife am Seitenlimit ab, fehlt ein Teil der offenen
    # Belege — und Fehlen darf dann nicht als Bezahlen gelten.
    abgeschnitten = seite >= MAX_SEITEN

    liste, offen_summe, alt = [], 0.0, 0
    for b in belege:
        nummer = str(b.get("voucherNumber") or "")
        if not VERKAUF.match(nummer):
            continue
        # Was wirklich aussteht — nicht der Rechnungsbetrag. Bei Teilzahlungen
        # sind das zwei verschiedene Zahlen.
        rest = float(b.get("openAmount") or b.get("totalAmount") or 0)
        offen_summe += rest
        faellig = (b.get("dueDate") or b.get("voucherDate") or "")[:10]
        ueberfaellig_seit = tage_alt(faellig) or 0
        if ueberfaellig_seit > ALT_AB_TAGEN:
            ampel, marke = "rot", f"seit {ueberfaellig_seit} Tagen fällig"
            alt += 1
        elif ueberfaellig_seit > 0:
            ampel, marke = "gelb", f"seit {ueberfaellig_seit} Tagen fällig"
        else:
            ampel, marke = "blau", "fällig"
        liste.append(posten(
            kennung=nummer,
            titel=(b.get("contactName") or "Kunde")[:80],
            ampel=ampel,
            betrag=rest,
            datum=(b.get("voucherDate") or "")[:10] or None,
            text=nummer,
            marke=marke,
            link=f"https://app.lexoffice.de/permanent/voucher/{b.get('id')}",
            zusatz={"faellig": faellig, "tage": ueberfaellig_seit,
                    "brutto": b.get("totalAmount")},
        ))

    # Neueste zuerst — die sind die Tagesarbeit. Alte Posten sind Mahnwesen
    # und stehen als Zahl oben, nicht als 122 Zeilen.
    liste.sort(key=lambda p: p["datum"] or "", reverse=True)
    return {
        "posten": liste[:ANZEIGE],
        # Fuer die Erkennung im Tagesfortschritt zaehlt die VOLLE Liste: Eine
        # Rechnung, die aus den zwanzig angezeigten rutscht, ist nicht bezahlt.
        "bestand": bestand_aus(liste),
        # Wie viele es insgesamt waeren. Die Oberflaeche braucht das,
        # um beim Umsortieren ehrlich zu bleiben: „aelteste zuerst" kann
        # hier nur die aeltesten der angezeigten meinen.
        "gekuerzt": len(liste) if len(liste) > ANZEIGE else 0,
        "fenster_tage": FENSTER_TAGE,
        "diff_sperre": (f"Belegliste am Seitenlimit ({MAX_SEITEN}) abgeschnitten"
                        if abgeschnitten else None),
        "kennzahlen": {
            "Offen": len(liste),
            "Offene Summe": offen_summe,
            f"Über {ALT_AB_TAGEN} Tage": alt,
        },
        "hinweis": (f"Angezeigt sind die {ANZEIGE} neuesten von {len(liste)}. "
                    f"{alt} liegen länger als {ALT_AB_TAGEN} Tage — das ist Mahnwesen, "
                    f"keine Tagesarbeit." if len(liste) > ANZEIGE else None),
    }
