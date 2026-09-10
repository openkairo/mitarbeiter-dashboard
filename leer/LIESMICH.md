# Absichtlich leer

Dieser Ordner wird eingehängt, wenn eine Instanz keine Zulieferungen von außen
hat — Bank-Abgleich, Widerruf-Wache, Watchdog, Google-Schlüssel. Ohne ihn
legte Docker für jeden fehlenden Pfad stillschweigend ein Verzeichnis an, und
beim Google-Schlüssel entstünde ein Verzeichnis namens `google-key.json`, gegen
das der Kalender läuft, ohne dass jemand den Grund findet.

Wer diese Quellen hat, trägt die Pfade in der `.env` ein:

    BANK_ORDNER_HOST=/pfad/zur/bank-abgleich-automation
    WIDERRUF_ORDNER_HOST=/pfad/zur/widerruf-wache
    WATCHDOG_ORDNER_HOST=/pfad/zum/watchdog
    GOOGLE_ORDNER_HOST=/pfad/zum/ordner-mit-dem-google-schluessel
