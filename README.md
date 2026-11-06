# Stream Cinema CZ/SK (fork)

Fork aneb jailbreak který znovu dovoluje stahovat ze Stream Cinema CZ/SK na Kodi.

> **Pozor:** Pro provoz je potřeba registrace na kra.sk s aktivním předplatným.

## Funkce

- Přehrávání filmů a seriálů z kra.sk
- Automatický i manuální výběr streamu (jazyk, kvalita, bitrate, filtry HDR/Dolby Vision)
- Synchronizace s Trakt.tv (scrobbling, historie, hodnocení)
- Rodičovská kontrola
- **Stahování souborů s frontou** (viz níže)

## Požadavky

- Kodi 19 (Matrix) a novější
- Registrace na [kra.sk](https://kra.sk) s aktivním předplatným

## Instalace

1. Nainstalujte doplněk z ZIP archívu (nebo z repozitáře, ze kterého fork pochází).
2. Otevřete nastavení doplňku a přihlaste se údaji kra.sk (kategorie **Účet**).
3. V kategorii **Složky** nastavte **Složku pro stahování**.

## Stahování s frontou

### Jak na to

1. V nastavení doplňku (kategorie **Složky**) nastavte **Složku pro stahování**.
   Bez nastavené složky se položka **Stáhnout** v kontextové nabídce nezobrazí.
2. Nad filmem nebo epizodou otevřete kontextovou nabídku a zvolte **Stáhnout**.
3. Soubor se zařadí do fronty a stahuje se na pozadí — můžete pokračovat v
   prohlížení nebo doplněk úplně zavřít.

### Jak fronta funguje

- Frontu zpracovává **služba doplňku** na pozadí, takže stahování pokračuje,
  i když zavřete seznamy doplňku.
- Současně stahuje **maximálně 3 soubory**, další čekají ve frontě (max 50 položek).
- Přerušená stahování (restart Kodi, výpadek sítě) se **obnoví od poslední pozice**
  a při chybě se automaticky **opakují až 3krát** s minutovým odstupem.
- Tentýž soubor nelze zařadit do fronty dvakrát.
- Po dokončení nebo selhání přijde notifikace.

### Přehled fronty

V nastavení doplňku (kategorie **Složky**) otevřete **Fronta stahování**:

- seznam všech stahování včetně stavu (Ve frontě / Stahuje se / Hotovo / Chyba)
  a počtu opakování,
- **Smazat dokončené** — vyčistí hotové a selhané položky,
- **Smazat celou frontu** — zruší vše (běžící stahování se přeruší),
- u konkrétní položky ji lze **Odebrat z fronty**.

## Struktura projektu

```
plugin.video.stream-cinema/
├── addon.xml                 # manifest doplňku
├── main.py                   # vstupní bod pluginu
├── service.py                # vstupní bod služby (background loop)
└── resources/
    ├── settings.xml          # nastavení doplňku
    ├── language/             # lokalizace (sk, cs, en)
    └── lib/
        ├── streamcinema.py   # hlavní logika + router akcí
        ├── kodiutils.py      # Kodi helpery (včetně download())
        ├── services/
        │   ├── service.py    # hlavní služba — zpracovává fronty na pozadí
        │   └── download_queue.py  # fronta stahování
        └── ...
```

## Licence

GNU GENERAL PUBLIC LICENSE, Version 3 — viz [LICENSE](plugin.video.stream-cinema/LICENSE).

## Disclaimer

Autor tohoto doplňku neposkytuje žádný obsah a není nijako propojen s
poskytovateli obsahu. Doplněk pouze vyhledává zpřístupněný obsah na kra.sk.
Použití na vlastní odpovědnost!
