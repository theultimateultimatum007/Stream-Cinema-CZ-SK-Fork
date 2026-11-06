# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals

import json
from resources.lib.common.logger import debug
from resources.lib.api.sc import Sc


class FilterAPI:
    """
    Filter API klient pre pokročilé filtrovanie obsahu

    Funkcie:
    - Filtrovanie filmov/seriálov podľa rôznych kritérií
    - Dynamické načítanie možných hodnôt (facets)
    - Podpora 20+ filter parametrov (kvalita, HDR, žánre, rok, hodnotenie, ...)
    """

    @staticmethod
    def _format_slug_to_name(slug):
        """
        Konvertuje URL slug na čitateľný názov

        Args:
            slug (str): URL slug (napr. "akcia-thriller")

        Returns:
            str: Formátovaný názov (napr. "Akcia Thriller")
        """
        if not slug:
            return slug

        # Nahraď pomlčky/podčiarkovníky medzerami
        name = slug.replace('-', ' ').replace('_', ' ')

        # Kapitalizuj každé slovo
        name = ' '.join(word.capitalize() for word in name.split())

        return name

    # Filter typy
    TYPE_MOVIE = 1
    TYPE_SERIES = 3
    TYPE_CONCERT = -1
    TYPE_ALL = 'all'

    # Kvalita options
    QUALITY_SD = 'SD'
    QUALITY_720P = '720p'
    QUALITY_1080P = '1080p'
    QUALITY_3D_SBS = '3D-SBS'
    QUALITY_4K = '4K'
    QUALITY_8K = '8K'

    # Jazyk options
    LANG_SK = 'SK'
    LANG_CZ = 'CZ'
    LANG_EN = 'EN'

    # HDR/DV options
    TECH_EXCLUDE = 0  # Bez technológie (filter out)
    TECH_INCLUDE = 1  # Aj s technológiou (zobrazí všetko)
    TECH_ONLY = 2     # Len s technológiou

    # Sorting fields
    SORT_DATE = 'datum'
    SORT_MINDATE = 'mindate'
    SORT_MAXDATE = 'maxdate'
    SORT_RATING = 'rating'
    SORT_YEAR = 'yyear'
    SORT_PLAY_COUNT = 'minfo.play'
    SORT_NAME_CS = 'name_cs'
    SORT_NAME_EN = 'name_en'
    SORT_NAME_SL = 'name_sl'
    SORT_BITRATE = 'bitrate'
    SORT_FILESIZE = 'filesize'
    SORT_RANDOM = 'random'
    SORT_QUALITY = 'quality'
    SORT_STREAM = 'stream'

    # Sorting direction
    ORDER_ASC = 'asc'
    ORDER_DESC = 'desc'

    @staticmethod
    def get_filtered(filter_params=None):
        """
        Získa filtrovaný obsah podľa zadaných parametrov

        Args:
            filter_params (dict): Dictionary s filter parametrami

        Príklad filter_params:
        {
            'typ': 1,              # Filmy
            'q': '4K',             # Kvalita 4K
            'HDR': 2,              # Len HDR videa
            'la': 'SK',            # Slovenský jazyk
            'mu': [123, 456],      # Universal IDs (žánre, TAGy, herci, krajiny)
            'r': '>70',            # Hodnotenie 70%+
            'y': '2020:2024',      # Rok 2020-2024
            'of': 'rating',        # Zoradiť podľa hodnotenia
            'od': 'desc',          # Zostupne
            'page': 1,             # Stránka 1
            'limit': 40            # 40 položiek na stránku
        }

        Returns:
            dict: API odpoveď s filtrovanými položkami
        """
        if filter_params is None:
            filter_params = {}

        # Priprav parametre pre Sc.get()
        # Array parametre (mu, co, ca, ge) sa posielajú ako list hodnôt
        # Sc.prepare() ich automaticky expandne na PHP array syntax
        # napr. ('mu', [123, 456]) → ('mu[]', 123), ('mu[]', 456) → URL: mu[]=123&mu[]=456
        params = []

        for key, value in filter_params.items():
            if isinstance(value, (list, tuple)) and value:  # Neprázdny list
                # VÝNIMKA: 'la' a 'q' by nemali byť lists (server nepodporuje multiselect)
                if key in ['la', 'q']:
                    # Použij prvú hodnotu z listu (fallback pre prípad chyby)
                    params.append((key, value[0]))
                    debug('FilterAPI: Warning - {} should be string, not list. Using first value: {}'.format(key, value[0]))
                elif key in ['mu', 'co', 'ca', 'ge']:
                    # Array parametre - musíme poslať ako list hodnôt
                    # Sc.prepare() automaticky pridá '[]' suffix pre každú hodnotu v liste
                    # Napr. ('mu', [70393, 69801]) → ('mu[]', 70393), ('mu[]', 69801)
                    int_values = []
                    for item_value in value:
                        try:
                            # Ensure integers for ID fields
                            item_int = int(item_value)
                            int_values.append(item_int)
                        except (ValueError, TypeError) as e:
                            debug('FilterAPI: Warning - {} contains non-integer value: {}. Error: {}'.format(key, item_value, e))

                    # Pridaj ako jeden parameter s listom hodnôt
                    # Sc.prepare() expandne list na mu[]=val1&mu[]=val2 pre PHP array syntax
                    if int_values:
                        params.append((key, int_values))
                        debug('FilterAPI: Added array parameter: {} = {}'.format(key, int_values))
                else:
                    # Iné array parametre (ak existujú) - pošli ako JSON
                    params.append((key, json.dumps(value, separators=(',', ':'))))
            elif isinstance(value, (list, tuple)):
                # Prázdny list - preskočiť (nepošli parameter)
                debug('FilterAPI: Skipping empty list parameter: {}'.format(key))
            else:
                # Skalárna hodnota
                # Preskočiť parametre s hodnotou 0, ktoré znamenajú "nepoužívať filter"
                # Výnimka: HDR=0 a DV=0 znamenajú "filter out", nie "ignoruj", tak ich pošleme
                # Ale dub=0, tit=0 znamenajú "ignoruj filter", tak ich preskočíme
                if value == 0 and key in ['dub', 'tit', 'atmos', 'hevc', 'ste']:
                    debug('FilterAPI: Skipping {} with value 0 (means no filter)'.format(key))
                    continue

                params.append((key, value))

        debug('FilterAPI.get_filtered: Calling /Filter with params: {}'.format(params))

        # Použij Sc.get() pre volanie API s cache support
        return Sc.get('/Filter', params=params)

    @staticmethod
    def get_facets():
        """
        Získa možné hodnoty pre filtre (facets) - dynamicky zo servera

        Returns:
            dict: Dictionary s možnými hodnotami pre každý filter

        Príklad odpovede:
        {
            "genres": [
                {"id": 123, "name": "Akcia"},
                {"id": 456, "name": "Thriller"},
                ...
            ],
            "countries": [
                {"id": 1, "name": "USA"},
                {"id": 2, "name": "UK"},
                ...
            ],
            "years": {
                "min": 1900,
                "max": 2024
            },
            "qualities": ["SD", "720p", "1080p", "4K", "8K"],
            ...
        }
        """
        debug('FilterAPI.get_facets: Calling /Filter/facet')

        # Volaj API s cache (TTL 1 deň - facets sa nemenia často)
        raw_facets = Sc.get('/Filter/facet', ttl=604800)

        # Transform flat array to structured dict
        # Server returns: [{'i': id, 't': 'genre'|'country', 'u': url}, ...]
        # We need: {'genres': [{'id': id, 'name': 'name'}], 'countries': [...]}

        if not isinstance(raw_facets, list):
            debug('FilterAPI.get_facets: Invalid facets format, expected list, got {}'.format(type(raw_facets)))
            return {}

        genres = []
        countries = []

        for item in raw_facets:
            if not isinstance(item, dict):
                continue

            item_id = item.get('i')
            item_type = item.get('t')
            # Preferuj 'n' (name) field, ale fallback na 'u' (url/slug) ak name neexistuje
            item_name_raw = item.get('n') or item.get('u')

            if not item_id or not item_type or not item_name_raw:
                continue

            # Ensure ID is integer (SphinxQL expects integers for murl field)
            try:
                item_id = int(item_id)
            except (ValueError, TypeError):
                debug('FilterAPI.get_facets: Invalid ID format: {}, skipping'.format(item_id))
                continue

            # Ak je item_name_raw URL slug (bez 'n' fieldu), formátuj ho na čitateľný názov
            if not item.get('n') and item.get('u'):
                item_name = FilterAPI._format_slug_to_name(item_name_raw)
            else:
                item_name = item_name_raw

            facet_entry = {'id': item_id, 'name': item_name}

            if item_type == 'genre':
                genres.append(facet_entry)
            elif item_type == 'country':
                countries.append(facet_entry)

        # Pridaj Anime TAG na prvé miesto (ID 70393)
        # Anime je TAG, nie žáner, ale zobrazujeme ho medzi žánrami
        genres.insert(0, {'id': 70393, 'name': 'Anime'})

        # Pridaj Koncert TAG (ID 69801)
        genres.insert(1, {'id': 69801, 'name': 'Koncert'})

        debug('FilterAPI.get_facets: Loaded {} genres (with Anime + Koncert TAGs), {} countries'.format(len(genres), len(countries)))

        return {
            'genres': genres,
            'countries': countries
        }

    @staticmethod
    def build_filter_url(filter_params):
        """
        Vytvorí filter URL string z parametrov

        Args:
            filter_params (dict): Dictionary s filter parametrami

        Returns:
            str: URL query string (napr. "typ=1&q=4K&HDR=2&r=>70")
        """
        from resources.lib.kodiutils import urlencode

        # Konvertuj list parametre na JSON
        params = {}
        for key, value in filter_params.items():
            if isinstance(value, (list, tuple)):
                params[key] = json.dumps(value)
            else:
                params[key] = value

        return urlencode(params)

    @staticmethod
    def parse_range_value(value_str):
        """
        Parsuje range hodnotu z textového vstupu

        Args:
            value_str (str): Range hodnota (napr. ">70", "60:80", "2020")

        Returns:
            str: Validovaný range string alebo None

        Príklady:
            "70" → "70" (presná hodnota)
            ">70" → ">70" (väčšie alebo rovné)
            "<70" → "<70" (menšie alebo rovné)
            "60:80" → "60:80" (od-do range)
        """
        if not value_str:
            return None

        value_str = str(value_str).strip()

        # Presná hodnota (číslo)
        if value_str.isdigit():
            return value_str

        # Operátor > alebo <
        if value_str.startswith('>') or value_str.startswith('<'):
            num = value_str[1:].strip()
            if num.isdigit():
                return value_str

        # Range (od:do)
        if ':' in value_str:
            parts = value_str.split(':')
            if len(parts) == 2 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
                return '{}:{}'.format(parts[0].strip(), parts[1].strip())

        # Nevalidný formát
        debug('FilterAPI.parse_range_value: Invalid range format: {}'.format(value_str))
        return None


# Singleton instance
filter_api = FilterAPI()
