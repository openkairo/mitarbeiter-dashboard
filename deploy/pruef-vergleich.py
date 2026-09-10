import json, sys
a = json.load(open(sys.argv[1])); b = json.load(open(sys.argv[2]))
fehler = []

def gleich(name, x, y, weich=False):
    if x == y:
        print(f"  ✓ {name}")
    elif weich:
        print(f"  ~ {name}: {x}  →  {y}   (darf sich ändern)")
    else:
        print(f"  ✗ {name}\n      vorher : {x}\n      nachher: {y}")
        fehler.append(name)

print("── Einstellungen und Zugänge")
gleich("Einstellungsfelder (Schlüssel, Gruppe, gesetzt, Spur, Herkunft)",
       a["einstellungen"], b["einstellungen"])
gleich("Postfächer inkl. hinterlegter Zugänge", a["postfaecher"], b["postfaecher"])
gleich("Webhook", a["webhook"], b["webhook"])
gleich("KI-Zugang eingerichtet", a["mcp_eingerichtet"], b["mcp_eingerichtet"])
gleich("Version", a["version"], b["version"])

print("── Karten")
gleich("Kartenliste", sorted(a["karten"]), sorted(b["karten"]))
for name in sorted(a["karten"]):
    ka, kb = a["karten"][name], b["karten"].get(name, {})
    for feld in ("titel", "eingerichtet", "abhakbar", "link"):
        gleich(f"{name}: {feld}", ka.get(feld), kb.get(feld))
    gleich(f"{name}: Fehler", ka["fehler"], kb.get("fehler"))
    gleich(f"{name}: Haken", ka["haken"], kb.get("haken"))
    gleich(f"{name}: Notizen", ka["notizen"], kb.get("notizen"))
    gleich(f"{name}: Extras (Postfächer, Farben …)", ka.get("extra"), kb.get("extra"))
    gleich(f"{name}: offen/gesamt", (ka["offen"], ka["gesamt"]),
           (kb.get("offen"), kb.get("gesamt")), weich=True)

print("── Nachrichten und Fortschritt")
gleich("offene Nachrichten", a["nachrichten"], b["nachrichten"])
gleich("Kopfzahlen", a["kopfzahlen"], b["kopfzahlen"], weich=True)
gleich("Tagesfortschritt", a["fortschritt"], b["fortschritt"], weich=True)

print()
print("  ERGEBNIS:", "alles erhalten" if not fehler else f"{len(fehler)} Abweichung(en): {fehler}")
sys.exit(1 if fehler else 0)
