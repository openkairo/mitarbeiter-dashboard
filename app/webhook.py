"""Ausgehender Webhook: meldet sofort, wenn die Person auf eine Nachricht antwortet.

Ohne ihn müsste die KI regelmässig `antworten_lesen` aufrufen und wüsste erst
beim naechsten Versuch Bescheid. Mit ihm kommt die Rueckmeldung in dem Moment
an, in dem die Person auf „Antwort senden" tippt.

**Drei Regeln, die hier gelten:**

  * **Die Antwort wartet nie auf den Webhook.** Der Versand laeuft in einem
    eigenen Faden. Waere er synchron, haenge die Oberflaeche an der Laune eines
    fremden Servers — und ein langsamer Empfaenger sähe für die Person aus wie ein
    kaputtes Dashboard.
  * **Der Webhook ist Zusatz, nicht Zustellung.** Er darf ausfallen; die
    Antwort bleibt in der Datenbank und ist ueber `antworten_lesen` weiter
    abholbar. Deshalb wird hier auch nichts als „zugestellt" markiert.
**Zwei getrennte Geheimnisse, die man nicht verwechseln darf:**

  * **Bearer** (`ANTWORT_WEBHOOK_BEARER`) geht als
    `Authorization: Bearer <key>` mit. **Cursor verlangt das zwingend** — ohne
    diesen Kopf antwortet es mit 401 „Missing Authorization header", und die
    Routine laeuft nie an. Der Wert steht in der Grok-Routine unter
    „Webhook key" und beginnt mit `crsr_`.
  * **HMAC** (`ANTWORT_WEBHOOK_SECRET`) unterschreibt den Rumpf per
    HMAC-SHA256, Kopfzeile `X-SMG-Signatur: sha256=…`. Das ist fuer andere
    Empfaenger gedacht und **kein Ersatz** fuer den Bearer.

Beide sind unabhaengig: keines, eines oder beide. Wer den Cursor-Schluessel ins
HMAC-Feld schreibt, bekommt weiterhin 401 — genau diese Verwechslung hat den
Webhook am 10.09.2026 stillgelegt.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
import urllib.error
import urllib.request

from . import db
from . import profil

log = logging.getLogger("buchhaltung.webhook")

TIMEOUT = 15
VERSUCHE = 3
PAUSEN = [2, 8]          # Sekunden zwischen den Versuchen
STAND = "webhook_stand"


def _stand_schreiben(ok: bool, meldung: str, ziel: str, hinweis: str = "") -> None:
    from datetime import datetime
    eintrag = {"zuletzt": datetime.now().isoformat(timespec="seconds"),
               "ok": ok, "meldung": meldung[:250], "ziel": ziel[:120],
               "hinweis": hinweis}
    db.kv_schreiben(STAND, json.dumps(eintrag, ensure_ascii=False))


def stand() -> dict:
    try:
        return json.loads(db.kv_lesen(STAND, "{}") or "{}")
    except json.JSONDecodeError:
        return {}


HINWEIS_401 = ("Bearer fehlt oder ist falsch — den „Webhook key“ aus der "
               "Grok-Routine kopieren und in den Settings unter „Cursor "
               "Authorization (Bearer)“ eintragen, nicht ins HMAC-Feld.")


def _senden(url: str, bearer: str, geheimnis: str, nutzlast: dict) -> None:
    rumpf = json.dumps(nutzlast, ensure_ascii=False).encode("utf-8")
    kopf = {"Content-Type": "application/json",
            "User-Agent": f"smg-{profil.INSTANZ}/1.0"}
    if bearer:
        kopf["Authorization"] = "Bearer " + bearer
    if geheimnis:
        marke = hmac.new(geheimnis.encode("utf-8"), rumpf, hashlib.sha256).hexdigest()
        kopf["X-SMG-Signatur"] = "sha256=" + marke

    letzter, hinweis = "", ""
    for versuch in range(VERSUCHE):
        try:
            req = urllib.request.Request(url, data=rumpf, headers=kopf, method="POST")
            with urllib.request.urlopen(req, timeout=TIMEOUT) as antwort:
                _stand_schreiben(True, f"HTTP {antwort.status}", url)
                log.info("Webhook zugestellt: HTTP %s an %s", antwort.status, url)
                return
        except urllib.error.HTTPError as fehler:
            # Den Rumpf mitnehmen: „HTTP 401“ allein sagt nicht, WAS fehlt.
            # Cursor schreibt den Grund hinein, und ohne ihn sucht man lange.
            try:
                text = fehler.read().decode(errors="replace").strip()[:200]
            except Exception:                                     # noqa: BLE001
                text = ""
            letzter = f"HTTP {fehler.code}" + (f" — {text}" if text else "")
            if fehler.code == 401:
                hinweis = HINWEIS_401
            # 4xx wiederholt sich beliebig oft gleich — nur bei 5xx und
            # Netzfehlern lohnt ein zweiter Versuch.
            if fehler.code < 500:
                break
        except Exception as fehler:                               # noqa: BLE001
            letzter = f"{type(fehler).__name__}: {fehler}"
        if versuch < len(PAUSEN):
            time.sleep(PAUSEN[versuch])

    _stand_schreiben(False, letzter, url, hinweis)
    # WARN, damit der Watchdog eine stille Verschlechterung sieht.
    log.warning("WARN Webhook nicht zugestellt (%s) an %s%s — die Antwort bleibt "
                "über antworten_lesen abrufbar", letzter, url,
                f" | {hinweis}" if hinweis else "")


def melden(umgebung: dict, nutzlast: dict) -> bool:
    """Im Hintergrund verschicken. Gibt zurueck, ob ueberhaupt einer eingerichtet ist."""
    url = (umgebung.get("ANTWORT_WEBHOOK_URL") or "").strip()
    if not url:
        return False
    bearer = (umgebung.get("ANTWORT_WEBHOOK_BEARER") or "").strip()
    geheimnis = umgebung.get("ANTWORT_WEBHOOK_SECRET") or ""
    threading.Thread(target=_senden, args=(url, bearer, geheimnis, nutzlast),
                     daemon=True, name="webhook").start()
    return True
