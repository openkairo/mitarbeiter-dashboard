"""Lesender Zugriff auf die Lexware-/Lexoffice-API.

Drosselung und Retry sind bewusst identisch zu
einem aelteren Werkzeug desselben Hauses — dort haben sie sich
bewaehrt. Reine stdlib, kein pip-Paket noetig.

Zwei Belegwelten, die man nicht verwechseln darf:

    RE-…   voucherType=invoice        Theke/Abholung, von Hand geschrieben
           -> GET /invoices/{id}      mit address, lineItems[], introduction
    SG-…   voucherType=salesinvoice   Shop, ueber StoreaBill synchronisiert
           -> GET /vouchers/{id}      nur contactId, voucherItems[] ohne Namen

Der falsche Endpunkt liefert stumm 404. `beleg_detail()` waehlt ihn anhand der
Belegnummer, damit sich der Fehler gar nicht erst machen laesst.
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

BASIS_URL = "https://api.lexoffice.io/v1"
MIN_ABSTAND = 0.55       # die API erlaubt 2 Anfragen/s -> konservativ drosseln
SEITENGROESSE = 250      # Maximum der API

# Die Suche liefert hoechstens 10.000 Treffer; ab `page * size >= 10000`
# antwortet sie mit 400 "Maximum search window size exceeded". Bei rund 15.000
# Belegen kommt man ohne Zeitfenster also nie ans Ende der Historie.
SUCHFENSTER = 10_000

_letzter_aufruf = 0.0


class LexwareFehler(Exception):
    pass


def _ssl_kontext():
    """CA-Zertifikate finden.

    Auf dem Linux-VPS reicht der Systemspeicher. Ein macOS-Framework-Python
    bringt dagegen keine CAs mit — dort springt certifi ein. Nie ungeprueft
    verbinden: hier gehen Kundendaten und ein API-Key ueber die Leitung.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL_KONTEXT = _ssl_kontext()


class Lexware:
    def __init__(self, api_key: str, basis_url: str = BASIS_URL):
        if not api_key:
            raise LexwareFehler("LEXWARE_API_KEY fehlt in der .env")
        self.api_key = api_key
        self.basis_url = basis_url.rstrip("/")

    # ---------------------------------------------------------------- Transport

    def _get(self, pfad: str, params: dict | None = None,
             accept: str = "application/json", versuche: int = 4):
        """GET gegen die API. Gibt geparstes JSON zurueck — oder rohe Bytes,
        wenn `accept` kein JSON ist (fuer die PDF-Rechnungen)."""
        global _letzter_aufruf
        url = self.basis_url + "/" + pfad.lstrip("/")
        if params:
            url += "?" + urllib.parse.urlencode(params)

        for versuch in range(versuche):
            wartezeit = MIN_ABSTAND - (time.monotonic() - _letzter_aufruf)
            if wartezeit > 0:
                time.sleep(wartezeit)
            req = urllib.request.Request(url, method="GET")
            req.add_header("Authorization", "Bearer " + self.api_key)
            req.add_header("Accept", accept)
            try:
                with urllib.request.urlopen(req, timeout=45, context=SSL_KONTEXT) as resp:
                    _letzter_aufruf = time.monotonic()
                    roh = resp.read()
                    if accept != "application/json":
                        return roh
                    return json.loads(roh.decode()) if roh else {}
            except urllib.error.HTTPError as err:
                _letzter_aufruf = time.monotonic()
                text = err.read().decode(errors="replace")[:400]
                # 429 = zu schnell, 5xx = Lexware hat gerade ein Problem. Beides
                # geht von allein vorbei. Ein 4xx wiederholt sich dagegen
                # beliebig oft gleich — da hilft nur melden.
                if (err.code == 429 or 500 <= err.code < 600) and versuch < versuche - 1:
                    time.sleep(2 ** versuch)
                    continue
                raise LexwareFehler(f"HTTP {err.code} bei {pfad}: {text}")
            except urllib.error.URLError as err:
                _letzter_aufruf = time.monotonic()
                if versuch < versuche - 1:
                    time.sleep(2 ** versuch)
                    continue
                raise LexwareFehler(f"Netzwerkfehler bei {pfad}: {err}")

    # ------------------------------------------------------------------ Abrufe

    def profil(self) -> dict:
        """Prueft, ob der Key ueberhaupt zieht — kostet nichts."""
        return self._get("profile")

    def belegliste(self, seite: int = 0, aktualisiert_ab: str | None = None,
                   datum_von: str | None = None, datum_bis: str | None = None,
                   groesse: int = SEITENGROESSE, status: str = "open,paid") -> dict:
        """Eine Seite der Belegliste.

        `voucherStatus=overdue` laesst sich **nicht** mit anderen Status
        kombinieren — die API antwortet dann mit 400. Deshalb nur open,paid:
        Entwuerfe und stornierte Belege will hier ohnehin niemand anrufen.
        """
        params = {
            "voucherType": "invoice,salesinvoice",
            "voucherStatus": status,
            "archived": "false",
            "size": groesse,
            "page": seite,
            "sort": "voucherDate,DESC",
        }
        if aktualisiert_ab:
            params["updatedDateFrom"] = aktualisiert_ab
        if datum_von:
            params["voucherDateFrom"] = datum_von
        if datum_bis:
            params["voucherDateTo"] = datum_bis
        return self._get("voucherlist", params)

    def beleg_detail(self, lex_id: str, beleg_nr: str) -> dict:
        """Detail eines Belegs — mit dem Endpunkt, der zur Belegnummer passt."""
        if beleg_nr.upper().startswith("RE-"):
            return self._get(f"invoices/{lex_id}")
        return self._get(f"vouchers/{lex_id}")

    def kontakt(self, kontakt_id: str) -> dict:
        return self._get(f"contacts/{kontakt_id}")

    def datei(self, datei_id: str) -> bytes:
        """Die fertige PDF-Rechnung."""
        return self._get(f"files/{datei_id}", accept="application/pdf")


def datei_id_aus_detail(detail: dict) -> str:
    """Die Datei-ID der PDF-Rechnung — die beiden Belegwelten legen sie
    unterschiedlich ab.

        RE-  "files": {"documentFileId": "…"}
        SG-  "files": ["…"]
    """
    dateien = detail.get("files")
    if isinstance(dateien, dict):
        return dateien.get("documentFileId") or ""
    if isinstance(dateien, list) and dateien:
        erste = dateien[0]
        # Je nach Beleg steht dort die nackte ID oder ein Objekt darum herum.
        return erste if isinstance(erste, str) else (erste or {}).get("id", "")
    return ""
