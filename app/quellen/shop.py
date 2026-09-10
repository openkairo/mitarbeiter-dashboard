"""Offene Shop-Bestellungen.

Die nackte Zahl sagt wenig — erst das Alter trennt echte Vorgaenge von
Altlasten. Deshalb steht in der Karte neben der Anzahl immer, wie alt der
Stapel ist, und alles ueber einer Woche wird rot.
"""

from __future__ import annotations

from .. import wooshop
from ..posten import bestand_aus, posten, tage_alt

NAME = "shop"
TITEL = "Offene Bestellungen"
ICON = "🛒"
TTL = 300
ANLAUF = 12
# Ohne diese Einstellungen kann die Karte nichts holen — dann erscheint
# sie gar nicht erst, statt „nichts zu tun“ zu behaupten.
BRAUCHT = ("WP_URL", "WC_KEY", "WC_SECRET")

LINK_TEXT = "Shop"

STATUS = "on-hold,processing,pending"
STATUS_TEXT = {"on-hold": "Wartet auf Zahlung", "processing": "In Arbeit",
               "pending": "Unbezahlt"}
ANZEIGE = 20
# Mehr offene Bestellungen holt wooshop nicht — ab hier waere Fehlen kein
# Erledigen mehr, sondern ein Loch in der Liste.
GRENZE = 300
ALTLAST_AB = 30
KOPFZAHL = ("Offen", f"Älter als {ALTLAST_AB} Tage", f"älter als {ALTLAST_AB} Tage")


def fetch(env: dict) -> dict:
    basis = env.get("WP_URL") or ""
    bestellungen = wooshop.nach_status(basis, env.get("WC_KEY"), env.get("WC_SECRET"),
                                       STATUS, grenze=GRENZE)
    liste, summe, altlast = [], 0.0, 0

    for b in bestellungen:
        try:
            betrag = float(b.get("total") or 0)
        except (TypeError, ValueError):
            betrag = 0.0
        summe += betrag
        datum = (b.get("date_created") or "")[:10]
        alter = tage_alt(datum) or 0
        if alter > ALTLAST_AB:
            altlast += 1
        if alter <= 3:
            ampel = "blau"
        elif alter <= 14:
            ampel = "gelb"
        else:
            ampel = "rot"
        status = b.get("status") or ""
        liste.append(posten(
            kennung=str(b.get("id")),
            titel=wooshop.name_aus(b),
            ampel=ampel,
            betrag=betrag,
            datum=datum or None,
            text=f"#{b.get('number') or b.get('id')} · {b.get('payment_method_title') or ''}".strip(" ·"),
            marke=STATUS_TEXT.get(status, status),
            link=f"{basis.rstrip('/')}/wp-admin/post.php?post={b.get('id')}&action=edit",
            zusatz={"status": status, "alter": alter},
        ))

    # Wie bei den Rechnungen: die Neuesten sind die Arbeit, der alte Stapel ist
    # eine Zahl. Am 09.09.2026 waren 109 von 129 Bestellungen aelter als 30 Tage —
    # als Liste haetten sie alles Aktuelle zugedeckt.
    liste.sort(key=lambda p: p["datum"] or "", reverse=True)
    return {
        "posten": liste[:ANZEIGE],
        # Volle Liste fuer die Erkennung — die zwanzig oben sind nur Anzeige.
        "bestand": bestand_aus(liste),
        "diff_sperre": (f"Bestellliste bei {GRENZE} abgeschnitten"
                        if len(bestellungen) >= GRENZE else None),
        "kennzahlen": {"Offen": len(liste), "Summe": summe,
                       f"Älter als {ALTLAST_AB} Tage": altlast},
        "hinweis": (f"Angezeigt sind die {ANZEIGE} neuesten von {len(liste)}. "
                    f"{altlast} liegen länger als {ALTLAST_AB} Tage."
                    if len(liste) > ANZEIGE else None),
    }
