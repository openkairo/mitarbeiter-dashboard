"""Vollstaendiger Abzug von Karten, Einstellungen und Daten einer Instanz.

Fuer die Probe, ob ein Update etwas verliert:

    python3 deploy/pruef-abzug.py vorher.json      # vor dem Aufspielen
    …Update aufspielen…
    python3 deploy/pruef-abzug.py nachher.json
    python3 deploy/pruef-vergleich.py vorher.json nachher.json

Setzt einen Tunnel auf 127.0.0.1:8899 zur Instanz voraus (siehe README).
Zahlen, die sich zwischendurch aendern duerfen — offene Posten, Kopfzahlen,
Tagesfortschritt — meldet der Vergleich als „~", nicht als Fehler.
"""
import json, sys, urllib.request, base64

BASIS = "http://127.0.0.1:8899"
def hole(pfad):
    req = urllib.request.Request(BASIS + pfad)
    req.add_header("Authorization", "Basic " + base64.b64encode(b"benutzer:passwort").decode())
    with urllib.request.urlopen(req, timeout=25) as a:
        return json.loads(a.read().decode())

ab = {}
u = hole("/api/karten")
ab["version"] = hole("/api/update").get("fassung")
ab["fortschritt"] = u["fortschritt"]
ab["kopfzahlen"] = [(k["titel"], k["zahl"], k["warnung"]) for k in u["kopf"]]
ab["karten"] = {}
for k in u["karten"]:
    voll = hole("/api/karten/" + k["name"])
    ab["karten"][k["name"]] = {
        "titel": voll["titel"], "eingerichtet": voll.get("eingerichtet"),
        "abhakbar": voll["abhakbar"], "offen": voll["offen"], "gesamt": voll["gesamt"],
        "ampel": voll["ampel"], "kennzahlen": voll["kennzahlen"],
        "fehler": voll["fehler"], "hinweis": voll["hinweis"], "link": voll.get("link"),
        "extra": voll.get("extra"),
        "haken": sorted(p["schluessel"] for p in voll["posten"] if p["erledigt"]),
        "notizen": sorted((p["schluessel"], p["notiz"]) for p in voll["posten"] if p.get("notiz")),
    }
e = hole("/api/einstellungen")
ab["einstellungen"] = sorted(
    (f["schluessel"], f["gruppe"], bool(f["gesetzt"]), f.get("wert") or "", f["herkunft"])
    for f in e["felder"])
ab["postfaecher"] = [(k["id"], k["bezeichnung"], k["weg"], k["benutzer"], k["postfach_id"],
                      k["webmail"], k["aktiv"], k["passwort_gesetzt"], k["spur"])
                     for k in hole("/api/mailkonten")["konten"]]
ab["nachrichten"] = [(n["id"], n["text"], n["von"], n["dringlichkeit"], n["karte"])
                     for n in hole("/api/nachrichten")["nachrichten"]]
w = hole("/api/webhook")
ab["webhook"] = {k: w[k] for k in ("eingerichtet", "bearer", "signiert")}
m = hole("/api/mcp")
ab["mcp_eingerichtet"] = bool(m.get("adresse") or m.get("eingerichtet"))
json.dump(ab, open(sys.argv[1], "w"), ensure_ascii=False, indent=1, sort_keys=True)
print("  Abzug:", sys.argv[1], "|", len(ab["karten"]), "Karten,",
      len(ab["einstellungen"]), "Einstellungsfelder,", len(ab["postfaecher"]), "Postfächer")
