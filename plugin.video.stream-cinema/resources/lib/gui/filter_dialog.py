# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals

import re
import xbmcgui
from resources.lib.common.logger import debug
from resources.lib.api.filter import FilterAPI, filter_api
from resources.lib.constants import ADDON


def _convert_filesize_range_to_bytes(value_str):
    """
    Konvertuje filesize range z MB na B
    Podporuje formáty: >5000, <10000, 5000:10000

    Args:
        value_str (str): Range v MB (napr. "<50000")

    Returns:
        str: Range v B (napr. "<50000000000")
    """
    if not value_str:
        return value_str

    # Pattern pre range hodnoty
    if value_str.startswith('>'):
        # >5000 MB → >5000000000 B
        mb_value = value_str[1:].strip()
        try:
            bytes_value = int(float(mb_value) * 1000000)
            return '>{}'.format(bytes_value)
        except (ValueError, TypeError):
            return value_str
    elif value_str.startswith('<'):
        # <10000 MB → <10000000000 B
        mb_value = value_str[1:].strip()
        try:
            bytes_value = int(float(mb_value) * 1000000)
            return '<{}'.format(bytes_value)
        except (ValueError, TypeError):
            return value_str
    elif ':' in value_str:
        # 5000:10000 MB → 5000000000:10000000000 B
        parts = value_str.split(':')
        if len(parts) == 2:
            try:
                bytes_min = int(float(parts[0].strip()) * 1000000)
                bytes_max = int(float(parts[1].strip()) * 1000000)
                return '{}:{}'.format(bytes_min, bytes_max)
            except (ValueError, TypeError):
                return value_str

    return value_str


def _convert_filesize_range_from_bytes(value_str):
    """
    Konvertuje filesize range z B na MB
    Podporuje formáty: >5000000000, <10000000000, 5000000000:10000000000

    Args:
        value_str (str): Range v B (napr. "<50000000000")

    Returns:
        str: Range v MB (napr. "<50000")
    """
    if not value_str:
        return value_str

    # Konvertuj na string ak je to číslo
    value_str = str(value_str)

    # Pattern pre range hodnoty
    if value_str.startswith('>'):
        # >5000000000 B → >5000 MB
        bytes_value = value_str[1:].strip()
        try:
            mb_value = int(float(bytes_value) / 1000000)
            return '>{}'.format(mb_value)
        except (ValueError, TypeError):
            return value_str
    elif value_str.startswith('<'):
        # <10000000000 B → <10000 MB
        bytes_value = value_str[1:].strip()
        try:
            mb_value = int(float(bytes_value) / 1000000)
            return '<{}'.format(mb_value)
        except (ValueError, TypeError):
            return value_str
    elif ':' in value_str:
        # 5000000000:10000000000 B → 5000:10000 MB
        parts = value_str.split(':')
        if len(parts) == 2:
            try:
                mb_min = int(float(parts[0].strip()) / 1000000)
                mb_max = int(float(parts[1].strip()) / 1000000)
                return '{}:{}'.format(mb_min, mb_max)
            except (ValueError, TypeError):
                return value_str

    return value_str


def _convert_bitrate_range_to_kbps(value_str):
    """
    Konvertuje bitrate range z Mbps na kbps
    Podporuje formáty: >5, <10, 5:10

    Args:
        value_str (str): Range v Mbps (napr. "<10")

    Returns:
        str: Range v kbps (napr. "<10000")
    """
    if not value_str:
        return value_str

    # Pattern pre range hodnoty
    if value_str.startswith('>'):
        # >5 Mbps → >5000 kbps
        mbps_value = value_str[1:].strip()
        try:
            kbps_value = int(float(mbps_value) * 1000)
            return '>{}'.format(kbps_value)
        except (ValueError, TypeError):
            return value_str
    elif value_str.startswith('<'):
        # <10 Mbps → <10000 kbps
        mbps_value = value_str[1:].strip()
        try:
            kbps_value = int(float(mbps_value) * 1000)
            return '<{}'.format(kbps_value)
        except (ValueError, TypeError):
            return value_str
    elif ':' in value_str:
        # 5:10 Mbps → 5000:10000 kbps
        parts = value_str.split(':')
        if len(parts) == 2:
            try:
                kbps_min = int(float(parts[0].strip()) * 1000)
                kbps_max = int(float(parts[1].strip()) * 1000)
                return '{}:{}'.format(kbps_min, kbps_max)
            except (ValueError, TypeError):
                return value_str

    return value_str


def _convert_bitrate_range_from_kbps(value_str):
    """
    Konvertuje bitrate range z kbps na Mbps
    Podporuje formáty: >5000, <10000, 5000:10000

    Args:
        value_str (str): Range v kbps (napr. "<10000")

    Returns:
        str: Range v Mbps (napr. "<10")
    """
    if not value_str:
        return value_str

    # Konvertuj na string ak je to číslo
    value_str = str(value_str)

    # Pattern pre range hodnoty
    if value_str.startswith('>'):
        # >5000 kbps → >5 Mbps
        kbps_value = value_str[1:].strip()
        try:
            mbps_value = int(float(kbps_value) / 1000)
            return '>{}'.format(mbps_value)
        except (ValueError, TypeError):
            return value_str
    elif value_str.startswith('<'):
        # <10000 kbps → <10 Mbps
        kbps_value = value_str[1:].strip()
        try:
            mbps_value = int(float(kbps_value) / 1000)
            return '<{}'.format(mbps_value)
        except (ValueError, TypeError):
            return value_str
    elif ':' in value_str:
        # 5000:10000 kbps → 5:10 Mbps
        parts = value_str.split(':')
        if len(parts) == 2:
            try:
                mbps_min = int(float(parts[0].strip()) / 1000)
                mbps_max = int(float(parts[1].strip()) / 1000)
                return '{}:{}'.format(mbps_min, mbps_max)
            except (ValueError, TypeError):
                return value_str

    return value_str


def _get_default_facets():
    """Vráti default facets ak server API zlyhá"""
    return {
        'types': [
            {'id': FilterAPI.TYPE_MOVIE, 'name': ADDON.getLocalizedString(30219)},  # Filmy
            {'id': FilterAPI.TYPE_SERIES, 'name': ADDON.getLocalizedString(30220)},  # Seriály
            {'id': FilterAPI.TYPE_ALL, 'name': ADDON.getLocalizedString(30221)},  # Všetko
        ],
        'qualities': [
            FilterAPI.QUALITY_SD,
            FilterAPI.QUALITY_720P,
            FilterAPI.QUALITY_1080P,
            FilterAPI.QUALITY_4K,
            FilterAPI.QUALITY_8K,
        ],
        'languages': [
            'SK',
            'CZ',
            'EN',
            'DE',
            'JP',
            'HU',
        ],
        'sort_fields': [
            {'id': FilterAPI.SORT_MINDATE, 'name': ADDON.getLocalizedString(30264)},  # Prvé pridané
            {'id': FilterAPI.SORT_MAXDATE, 'name': ADDON.getLocalizedString(30265)},  # Posledne pridané
            {'id': FilterAPI.SORT_PLAY_COUNT, 'name': ADDON.getLocalizedString(30266)},  # Popularita
            {'id': FilterAPI.SORT_RATING, 'name': ADDON.getLocalizedString(30209)},  # Hodnotenie
            {'id': FilterAPI.SORT_YEAR, 'name': ADDON.getLocalizedString(30210)},  # Rok vydania
            {'id': FilterAPI.SORT_QUALITY, 'name': ADDON.getLocalizedString(30202)},  # Kvalita
        ],
        'sort_directions': [
            {'id': FilterAPI.ORDER_DESC, 'name': ADDON.getLocalizedString(30253)},  # Zostupne
            {'id': FilterAPI.ORDER_ASC, 'name': ADDON.getLocalizedString(30254)},  # Vzostupne
        ],
        'genres': [],  # Žánre sa načítajú zo servera (vrátane Anime TAGu)
        'countries': [],  # Krajiny sa načítajú zo servera
    }


def _get_selected_label(items, selected_id):
    """Vráti label pre vybraný item"""
    for item in items:
        if isinstance(item, dict):
            if str(item.get('id')) == str(selected_id):
                return item.get('name', str(selected_id))
        elif str(item) == str(selected_id):
            return str(item)
    return None


def _select_type(dialog, facets, filter_params):
    """Výber typu obsahu"""
    types = facets.get('types', [])
    if not types:
        dialog.ok(ADDON.getLocalizedString(30200), ADDON.getLocalizedString(30255))
        return

    labels = [item['name'] for item in types]

    # Pre-select aktuálnu hodnotu
    preselect = -1
    if 'typ' in filter_params:
        for idx, item in enumerate(types):
            if str(item['id']) == str(filter_params['typ']):
                preselect = idx
                break

    selected = dialog.select(ADDON.getLocalizedString(30201), labels, preselect=preselect)

    if selected >= 0:
        filter_params['typ'] = types[selected]['id']
        debug('FilterDialog: Selected type: {}'.format(types[selected]))


def _select_quality(dialog, facets, filter_params):
    """Výber kvality (single select - server nepodporuje multiselect)"""
    qualities_raw = facets.get('qualities', [])
    if not qualities_raw:
        dialog.ok(ADDON.getLocalizedString(30200), ADDON.getLocalizedString(30247))
        return

    qualities = [{'id': q, 'name': q} for q in qualities_raw if q]
    labels = [item['name'] for item in qualities]

    # Pre-select aktuálnu hodnotu
    preselect = -1
    if 'q' in filter_params:
        for idx, item in enumerate(qualities):
            if str(item['id']) == str(filter_params['q']):
                preselect = idx
                break

    selected = dialog.select(ADDON.getLocalizedString(30202), labels, preselect=preselect)

    if selected >= 0:
        filter_params['q'] = qualities[selected]['id']
        debug('FilterDialog: Selected quality: {}'.format(qualities[selected]))


def _select_language(dialog, facets, filter_params):
    """Výber jazyka (single select - server nepodporuje multiselect)"""
    languages_raw = facets.get('languages', [])
    if not languages_raw:
        dialog.ok(ADDON.getLocalizedString(30200), ADDON.getLocalizedString(30248))
        return

    languages = [{'id': l, 'name': l} for l in languages_raw if l]
    labels = [item['name'] for item in languages]

    # Pre-select aktuálnu hodnotu
    preselect = -1
    if 'la' in filter_params:
        for idx, item in enumerate(languages):
            if str(item['id']) == str(filter_params['la']):
                preselect = idx
                break

    selected = dialog.select(ADDON.getLocalizedString(30203), labels, preselect=preselect)

    if selected >= 0:
        filter_params['la'] = languages[selected]['id']
        debug('FilterDialog: Selected language: {}'.format(languages[selected]))


def _select_sort_field(dialog, facets, filter_params):
    """Výber zoradenia"""
    sort_fields = facets.get('sort_fields', [])
    if not sort_fields:
        dialog.ok(ADDON.getLocalizedString(30200), ADDON.getLocalizedString(30249))
        return

    labels = [item['name'] for item in sort_fields]

    # Pre-select aktuálnu hodnotu
    preselect = -1
    if 'of' in filter_params:
        for idx, item in enumerate(sort_fields):
            if str(item['id']) == str(filter_params['of']):
                preselect = idx
                break

    selected = dialog.select(ADDON.getLocalizedString(30213), labels, preselect=preselect)

    if selected >= 0:
        filter_params['of'] = sort_fields[selected]['id']
        debug('FilterDialog: Selected sort field: {}'.format(sort_fields[selected]))


def _select_sort_direction(dialog, facets, filter_params):
    """Výber smeru zoradenia"""
    sort_directions = facets.get('sort_directions', [])
    if not sort_directions:
        dialog.ok(ADDON.getLocalizedString(30200), ADDON.getLocalizedString(30256))
        return

    labels = [item['name'] for item in sort_directions]

    # Pre-select aktuálnu hodnotu
    preselect = -1
    if 'od' in filter_params:
        for idx, item in enumerate(sort_directions):
            if str(item['id']) == str(filter_params['od']):
                preselect = idx
                break

    selected = dialog.select(ADDON.getLocalizedString(30214), labels, preselect=preselect)

    if selected >= 0:
        filter_params['od'] = sort_directions[selected]['id']
        debug('FilterDialog: Selected sort direction: {}'.format(sort_directions[selected]))


def _select_hdr(dialog, filter_params):
    """Výber HDR"""
    options = [
        {'id': 1, 'name': ADDON.getLocalizedString(30222)},  # Zobraz aj HDR
        {'id': 2, 'name': ADDON.getLocalizedString(30223)},  # Len HDR
        {'id': 0, 'name': ADDON.getLocalizedString(30224)},  # Bez HDR
    ]
    labels = [item['name'] for item in options]

    # Pre-select aktuálnu hodnotu
    preselect = -1
    if 'HDR' in filter_params:
        for idx, item in enumerate(options):
            if item['id'] == filter_params['HDR']:
                preselect = idx
                break

    selected = dialog.select(ADDON.getLocalizedString(30204), labels, preselect=preselect)

    if selected >= 0:
        filter_params['HDR'] = options[selected]['id']
        debug('FilterDialog: Selected HDR: {}'.format(options[selected]))
    elif 'HDR' in filter_params:
        del filter_params['HDR']


def _select_dolby_vision(dialog, filter_params):
    """Výber Dolby Vision"""
    options = [
        {'id': 1, 'name': ADDON.getLocalizedString(30225)},  # Zobraz aj Dolby Vision
        {'id': 2, 'name': ADDON.getLocalizedString(30226)},  # Len Dolby Vision
        {'id': 0, 'name': ADDON.getLocalizedString(30227)},  # Bez Dolby Vision
    ]
    labels = [item['name'] for item in options]

    # Pre-select aktuálnu hodnotu
    preselect = -1
    if 'DV' in filter_params:
        for idx, item in enumerate(options):
            if item['id'] == filter_params['DV']:
                preselect = idx
                break

    selected = dialog.select(ADDON.getLocalizedString(30205), labels, preselect=preselect)

    if selected >= 0:
        filter_params['DV'] = options[selected]['id']
        debug('FilterDialog: Selected DV: {}'.format(options[selected]))
    elif 'DV' in filter_params:
        del filter_params['DV']


def _select_atmos(dialog, filter_params):
    """Výber Dolby Atmos - len 2 možnosti (audio filter)"""
    options = [
        {'id': 0, 'name': ADDON.getLocalizedString(30221)},  # Všetko
        {'id': 1, 'name': ADDON.getLocalizedString(30229)},  # Len Dolby Atmos
    ]
    labels = [item['name'] for item in options]

    # Pre-select aktuálnu hodnotu
    preselect = 0 if 'atmos' not in filter_params else 1

    selected = dialog.select(ADDON.getLocalizedString(30206), labels, preselect=preselect)

    if selected == 1:
        filter_params['atmos'] = 1
        debug('FilterDialog: Selected Atmos: Len Dolby Atmos')
    elif 'atmos' in filter_params:
        del filter_params['atmos']


def _select_hevc(dialog, filter_params):
    """Výber HEVC codec filter - len 2 možnosti"""
    options = [
        {'id': 0, 'name': ADDON.getLocalizedString(30221)},  # Všetko
        {'id': 1, 'name': ADDON.getLocalizedString(30270)},  # Bez HEVC
    ]
    labels = [item['name'] for item in options]

    # Pre-select aktuálnu hodnotu
    preselect = 0 if 'hevc' not in filter_params else 1

    selected = dialog.select(ADDON.getLocalizedString(30269), labels, preselect=preselect)

    if selected == 1:
        filter_params['hevc'] = 1
        debug('FilterDialog: Selected HEVC: Bez HEVC')
    elif 'hevc' in filter_params:
        del filter_params['hevc']


def _select_stereoscopic(dialog, filter_params):
    """Výber 3D/Stereoscopic filter - len 2 možnosti"""
    options = [
        {'id': 0, 'name': ADDON.getLocalizedString(30221)},  # Všetko
        {'id': 1, 'name': ADDON.getLocalizedString(30272)},  # Bez 3D
    ]
    labels = [item['name'] for item in options]

    # Pre-select aktuálnu hodnotu
    preselect = 0 if 'ste' not in filter_params else 1

    selected = dialog.select(ADDON.getLocalizedString(30271), labels, preselect=preselect)

    if selected == 1:
        filter_params['ste'] = 1
        debug('FilterDialog: Selected 3D: Bez 3D')
    elif 'ste' in filter_params:
        del filter_params['ste']


def _select_audio_options(dialog, filter_params):
    """Výber dabingu a titulkov"""
    options = [
        {'id': 'none', 'name': ADDON.getLocalizedString(30221)},  # Všetko
        {'id': 'dub', 'name': ADDON.getLocalizedString(30233)},  # Len dabing
        {'id': 'tit', 'name': ADDON.getLocalizedString(30234)},  # Len titulky
        {'id': 'both', 'name': ADDON.getLocalizedString(30235)},  # Dabing alebo titulky
    ]
    labels = [item['name'] for item in options]

    # Pre-select aktuálnu hodnotu
    preselect = 0
    if 'dub' in filter_params and 'tit' in filter_params:
        preselect = 3  # both
    elif 'dub' in filter_params:
        preselect = 1  # dub only
    elif 'tit' in filter_params:
        preselect = 2  # tit only

    selected = dialog.select(ADDON.getLocalizedString(30208), labels, preselect=preselect)

    # Vymaž staré hodnoty
    if 'dub' in filter_params:
        del filter_params['dub']
    if 'tit' in filter_params:
        del filter_params['tit']

    if selected == 1:  # Len dabing
        filter_params['dub'] = 1
        debug('FilterDialog: Selected audio: Len dabing')
    elif selected == 2:  # Len titulky
        filter_params['tit'] = 1
        debug('FilterDialog: Selected audio: Len titulky')
    elif selected == 3:  # Dabing alebo titulky
        filter_params['dub'] = 1
        filter_params['tit'] = 1
        debug('FilterDialog: Selected audio: Dabing alebo titulky')


def _input_rating(dialog, filter_params):
    """Input pre hodnotenie (rating range)"""
    current = filter_params.get('r', '')

    result = dialog.input(
        ADDON.getLocalizedString(30236),
        defaultt=str(current) if current else ''
    )

    if result:
        # Validácia formátu
        result = result.strip()
        if result:
            filter_params['r'] = result
            debug('FilterDialog: Rating filter: {}'.format(result))
    elif 'r' in filter_params:
        del filter_params['r']


def _input_year(dialog, filter_params):
    """Input pre rok vydania (year range)"""
    current = filter_params.get('y', '')

    result = dialog.input(
        ADDON.getLocalizedString(30237),
        defaultt=str(current) if current else ''
    )

    if result:
        # Validácia formátu
        result = result.strip()
        if result:
            filter_params['y'] = result
            debug('FilterDialog: Year filter: {}'.format(result))
    elif 'y' in filter_params:
        del filter_params['y']


def _input_search(dialog, filter_params):
    """Input pre vyhľadávanie (fulltextové vyhľadávanie v názvoch)"""
    current = filter_params.get('s', '')

    result = dialog.input(
        ADDON.getLocalizedString(30268),
        defaultt=str(current) if current else ''
    )

    if result:
        # Validácia formátu
        result = result.strip()
        if result:
            filter_params['s'] = result
            debug('FilterDialog: Search query: {}'.format(result))
    elif 's' in filter_params:
        del filter_params['s']


def _input_bitrate(dialog, filter_params):
    """Input pre bitrate - užívateľ zadáva Mbps, ukladá sa v kbps"""
    # Konvertuj kbps → Mbps pre zobrazenie
    current_kbps = filter_params.get('b', '')
    current_mbps = _convert_bitrate_range_from_kbps(current_kbps) if current_kbps else ''

    result = dialog.input(
        ADDON.getLocalizedString(30274),
        defaultt=str(current_mbps) if current_mbps else ''
    )

    if result:
        # Validácia formátu
        result = result.strip()
        if result:
            # Konvertuj Mbps → kbps pre uloženie
            result_kbps = _convert_bitrate_range_to_kbps(result)
            filter_params['b'] = result_kbps
            debug('FilterDialog: Bitrate filter: {} Mbps → {} kbps'.format(result, result_kbps))
    elif 'b' in filter_params:
        del filter_params['b']


def _input_filesize(dialog, filter_params):
    """Input pre filesize (filesize range) - užívateľ zadáva MB, ukladá sa v B"""
    # Ak existuje hodnota v B, konvertuj na MB pre zobrazenie
    current_bytes = filter_params.get('f', '')
    current_mb = _convert_filesize_range_from_bytes(current_bytes) if current_bytes else ''

    result = dialog.input(
        ADDON.getLocalizedString(30276),
        defaultt=str(current_mb) if current_mb else ''
    )

    if result:
        # Validácia formátu
        result = result.strip()
        if result:
            # Konvertuj MB → B pre uloženie
            result_bytes = _convert_filesize_range_to_bytes(result)
            filter_params['f'] = result_bytes
            debug('FilterDialog: Filesize filter: {} MB → {} B'.format(result, result_bytes))
    elif 'f' in filter_params:
        del filter_params['f']


def _input_keywords(dialog, filter_params):
    """Input pre keywords"""
    current = filter_params.get('kwd', '')

    result = dialog.input(
        ADDON.getLocalizedString(30278),
        defaultt=str(current) if current else ''
    )

    if result:
        # Validácia formátu
        result = result.strip()
        if result:
            filter_params['kwd'] = result
            debug('FilterDialog: Keywords filter: {}'.format(result))
    elif 'kwd' in filter_params:
        del filter_params['kwd']


def _select_mpaa(dialog, filter_params):
    """Výber MPAA vekového obmedzenia"""
    options = [
        {'id': 0, 'name': '0+'},
        {'id': 7, 'name': '7+'},
        {'id': 12, 'name': '12+'},
        {'id': 15, 'name': '15+'},
        {'id': 18, 'name': '18+'},
    ]
    labels = [item['name'] for item in options]

    # Pre-select aktuálnu hodnotu
    preselect = -1
    if 'm' in filter_params:
        for idx, item in enumerate(options):
            if item['id'] == filter_params['m']:
                preselect = idx
                break

    selected = dialog.select(ADDON.getLocalizedString(30277), labels, preselect=preselect)

    if selected >= 0:
        filter_params['m'] = options[selected]['id']
        debug('FilterDialog: Selected MPAA rating: {}'.format(options[selected]))
    elif 'm' in filter_params:
        del filter_params['m']


def _select_genres(dialog, facets, filter_params):
    """Výber žánrov a TAGov (multiselect) - používa 'mu' parameter pre univerzálnosť"""
    genres = facets.get('genres', [])
    if not genres:
        dialog.ok(ADDON.getLocalizedString(30200), ADDON.getLocalizedString(30250))
        return

    labels = [item['name'] for item in genres]

    # Pre-select aktuálne hodnoty (podporuje obe 'mu' aj staré 'ge')
    preselect = []
    current_key = 'mu' if 'mu' in filter_params else 'ge'
    if current_key in filter_params:
        current_values = filter_params[current_key] if isinstance(filter_params[current_key], list) else [filter_params[current_key]]
        for idx, item in enumerate(genres):
            if item['id'] in current_values:
                preselect.append(idx)

    selected_indexes = dialog.multiselect(ADDON.getLocalizedString(30238), labels, preselect=preselect)

    if selected_indexes is not None:
        # Vždy používaj 'mu' parameter (univerzálny URL ID)
        # Vyčisti staré 'ge' ak existuje
        if 'ge' in filter_params:
            del filter_params['ge']

        if selected_indexes:
            filter_params['mu'] = [genres[idx]['id'] for idx in selected_indexes]
            debug('FilterDialog: Selected genres/tags (mu): {}'.format(filter_params['mu']))
        elif 'mu' in filter_params:
            del filter_params['mu']


def _select_exclude_genres(dialog, facets, filter_params):
    """Výber žánrov na vylúčenie (multiselect) - používa 'mu_exclude' parameter

    POZNÁMKA: Anime TAG (ID 70393) je zahrnuté v zozname žánrov
    """
    genres = facets.get('genres', [])
    if not genres:
        dialog.ok(ADDON.getLocalizedString(30200), ADDON.getLocalizedString(30250))
        return

    labels = [item['name'] for item in genres]

    # Pre-select aktuálne hodnoty
    preselect = []
    if 'mu_exclude' in filter_params:
        current_values = filter_params['mu_exclude'] if isinstance(filter_params['mu_exclude'], list) else [filter_params['mu_exclude']]
        for idx, item in enumerate(genres):
            if item['id'] in current_values:
                preselect.append(idx)

    selected_indexes = dialog.multiselect(ADDON.getLocalizedString(30263), labels, preselect=preselect)

    if selected_indexes is not None:
        if selected_indexes:
            filter_params['mu_exclude'] = [genres[idx]['id'] for idx in selected_indexes]
            debug('FilterDialog: Selected exclude genres/tags (mu_exclude): {}'.format(filter_params['mu_exclude']))
        elif 'mu_exclude' in filter_params:
            del filter_params['mu_exclude']


def _select_countries(dialog, facets, filter_params):
    """Výber krajín (multiselect)"""
    countries = facets.get('countries', [])
    if not countries:
        dialog.ok(ADDON.getLocalizedString(30200), ADDON.getLocalizedString(30251))
        return

    labels = [item['name'] for item in countries]

    # Pre-select aktuálne hodnoty
    preselect = []
    if 'co' in filter_params:
        current_values = filter_params['co'] if isinstance(filter_params['co'], list) else [filter_params['co']]
        for idx, item in enumerate(countries):
            if item['id'] in current_values:
                preselect.append(idx)

    selected_indexes = dialog.multiselect(ADDON.getLocalizedString(30239), labels, preselect=preselect)

    if selected_indexes is not None:
        if selected_indexes:
            filter_params['co'] = [countries[idx]['id'] for idx in selected_indexes]
            debug('FilterDialog: Selected countries: {}'.format(filter_params['co']))
        elif 'co' in filter_params:
            del filter_params['co']


def _build_status_text(filter_params, facets):
    """Zostaví status text pre hlavné menu"""
    status_lines = []

    # Typ obsahu
    if 'typ' in filter_params:
        label = _get_selected_label(facets.get('types', []), filter_params['typ'])
        if label:
            status_lines.append('[B]{}:[/B] {}'.format(ADDON.getLocalizedString(30201), label))

    # Kvalita
    if 'q' in filter_params:
        status_lines.append('[B]{}:[/B] {}'.format(ADDON.getLocalizedString(30202), filter_params['q']))

    # Jazyk
    if 'la' in filter_params:
        status_lines.append('[B]{}:[/B] {}'.format(ADDON.getLocalizedString(30203), filter_params['la']))

    # Zoradenie
    if 'of' in filter_params:
        label = _get_selected_label(facets.get('sort_fields', []), filter_params['of'])
        if label:
            status_lines.append('[B]{}:[/B] {}'.format(ADDON.getLocalizedString(30213), label))

    # Smer
    if 'od' in filter_params:
        label = _get_selected_label(facets.get('sort_directions', []), filter_params['od'])
        if label:
            status_lines.append('[B]{}:[/B] {}'.format(ADDON.getLocalizedString(30214), label))

    if status_lines:
        return '\n'.join(['[COLOR yellow]{}[/COLOR]'.format(ADDON.getLocalizedString(30257))] + status_lines)
    else:
        return '[COLOR gray]{}[/COLOR]'.format(ADDON.getLocalizedString(30240))


def show_filter_dialog(current_filter=None):
    """
    Zobrazí filter dialog pomocou vstavaných KODI dialógov

    Args:
        current_filter (dict): Aktuálne nastavené filter parametre (optional)

    Returns:
        tuple: (filter_params dict, save_filter bool)
               (None, False) ak bol dialog zrušený

    Použitie:
        filter_params, save = show_filter_dialog({'typ': 1, 'q': '4K'})
        if filter_params:
            # Užívateľ aplikoval filter
            result = filter_api.get_filtered(filter_params)
    """
    if current_filter is None:
        current_filter = {}

    dialog = xbmcgui.Dialog()

    # Načítaj facets zo servera
    try:
        debug('FilterDialog: Loading facets from server...')
        facets = _get_default_facets()  # Start with defaults

        server_facets = filter_api.get_facets()

        if isinstance(server_facets, dict):
            # Merge server facets (genres, countries) with defaults
            facets.update(server_facets)
            debug('FilterDialog: Facets loaded successfully: {} genres, {} countries'.format(
                len(facets.get('genres', [])),
                len(facets.get('countries', []))
            ))
        else:
            debug('FilterDialog: Invalid facets format from server, using defaults only')
    except Exception as e:
        debug('FilterDialog: Error loading facets: {}'.format(e))
        import traceback
        debug('FilterDialog: Traceback: {}'.format(traceback.format_exc()))
        # facets already has defaults

    # Hlavné menu s možnosťami
    def _build_main_menu():
        """Zostaví hlavné menu s aktuálnym stavom"""
        menu = []

        # === ZÁKLADNÉ FILTRE ===
        # Typ obsahu
        if 'typ' in filter_params:
            label = _get_selected_label(facets.get('types', []), filter_params['typ'])
            menu.append('[B]{}:[/B] {}'.format(ADDON.getLocalizedString(30201), label or filter_params['typ']))
        else:
            menu.append(ADDON.getLocalizedString(30201))

        # Kvalita
        if 'q' in filter_params:
            menu.append('[B]{}:[/B] {}'.format(ADDON.getLocalizedString(30202), filter_params['q']))
        else:
            menu.append(ADDON.getLocalizedString(30202))

        # Jazyk
        if 'la' in filter_params:
            menu.append('[B]{}:[/B] {}'.format(ADDON.getLocalizedString(30203), filter_params['la']))
        else:
            menu.append(ADDON.getLocalizedString(30203))

        # === TECHNOLÓGIE ===
        # HDR
        if 'HDR' in filter_params:
            hdr_labels = {
                0: ADDON.getLocalizedString(30224),  # Bez HDR
                1: ADDON.getLocalizedString(30222),  # Aj HDR
                2: ADDON.getLocalizedString(30223)   # Len HDR
            }
            menu.append('[B]{}:[/B] {}'.format(ADDON.getLocalizedString(30204), hdr_labels.get(filter_params['HDR'], filter_params['HDR'])))
        else:
            menu.append(ADDON.getLocalizedString(30204))

        # Dolby Vision
        if 'DV' in filter_params:
            dv_labels = {
                0: ADDON.getLocalizedString(30227),  # Bez DV
                1: ADDON.getLocalizedString(30225),  # Aj DV
                2: ADDON.getLocalizedString(30226)   # Len DV
            }
            menu.append('[B]{}:[/B] {}'.format(ADDON.getLocalizedString(30205), dv_labels.get(filter_params['DV'], filter_params['DV'])))
        else:
            menu.append(ADDON.getLocalizedString(30205))

        # Dolby Atmos
        if 'atmos' in filter_params:
            menu.append('[B]{}:[/B] {}'.format(ADDON.getLocalizedString(30206), ADDON.getLocalizedString(30229)))
        else:
            menu.append(ADDON.getLocalizedString(30206))

        # HEVC Codec
        if 'hevc' in filter_params:
            menu.append('[B]{}:[/B] {}'.format(ADDON.getLocalizedString(30269), ADDON.getLocalizedString(30270)))
        else:
            menu.append(ADDON.getLocalizedString(30269))

        # 3D/Stereoscopic
        if 'ste' in filter_params:
            menu.append('[B]{}:[/B] {}'.format(ADDON.getLocalizedString(30271), ADDON.getLocalizedString(30272)))
        else:
            menu.append(ADDON.getLocalizedString(30271))

        # === ADVANCED FILTERS ===
        # Bitrate
        if 'b' in filter_params:
            # Konvertuj kbps → Mbps pre zobrazenie
            bitrate_mbps = _convert_bitrate_range_from_kbps(filter_params['b'])
            menu.append('[B]{}:[/B] {} Mbps'.format(ADDON.getLocalizedString(30273), bitrate_mbps))
        else:
            menu.append(ADDON.getLocalizedString(30273))

        # Filesize
        if 'f' in filter_params:
            # Konvertuj B → MB pre zobrazenie
            filesize_mb = _convert_filesize_range_from_bytes(filter_params['f'])
            menu.append('[B]{}:[/B] {} MB'.format(ADDON.getLocalizedString(30275), filesize_mb))
        else:
            menu.append(ADDON.getLocalizedString(30275))

        # MPAA Rating
        if 'm' in filter_params:
            mpaa_labels = {0: '0+', 7: '7+', 12: '12+', 15: '15+', 18: '18+'}
            menu.append('[B]{}:[/B] {}'.format(ADDON.getLocalizedString(30277), mpaa_labels.get(filter_params['m'], filter_params['m'])))
        else:
            menu.append(ADDON.getLocalizedString(30277))

        # Keywords
        if 'kwd' in filter_params:
            menu.append('[B]{}:[/B] {}'.format(ADDON.getLocalizedString(30278), filter_params['kwd']))
        else:
            menu.append(ADDON.getLocalizedString(30278))

        # === AUDIO ===
        # Dabing / Titulky
        audio_text = ADDON.getLocalizedString(30208)
        if 'dub' in filter_params and 'tit' in filter_params:
            audio_text = '[B]{}:[/B] {}'.format(ADDON.getLocalizedString(30208), ADDON.getLocalizedString(30235))
        elif 'dub' in filter_params:
            audio_text = '[B]{}:[/B] {}'.format(ADDON.getLocalizedString(30208), ADDON.getLocalizedString(30233))
        elif 'tit' in filter_params:
            audio_text = '[B]{}:[/B] {}'.format(ADDON.getLocalizedString(30208), ADDON.getLocalizedString(30234))
        menu.append(audio_text)

        # === HODNOTENIE A ROK ===
        # Hodnotenie
        if 'r' in filter_params:
            menu.append('[B]{}:[/B] {}'.format(ADDON.getLocalizedString(30209), filter_params['r']))
        else:
            menu.append(ADDON.getLocalizedString(30209))

        # Rok vydania
        if 'y' in filter_params:
            menu.append('[B]{}:[/B] {}'.format(ADDON.getLocalizedString(30210), filter_params['y']))
        else:
            menu.append(ADDON.getLocalizedString(30210))

        # === VYHĽADÁVANIE ===
        # Vyhľadávací dotaz
        if 's' in filter_params:
            menu.append('[B]{}:[/B] {}'.format(ADDON.getLocalizedString(30267), filter_params['s']))
        else:
            menu.append(ADDON.getLocalizedString(30267))

        # === ŽÁNRE A KRAJINY ===
        # Žánre / TAGy (používa 'mu' parameter)
        current_key = 'mu' if 'mu' in filter_params else 'ge'  # Backward compatibility
        if current_key in filter_params:
            mu_count = len(filter_params[current_key]) if isinstance(filter_params[current_key], list) else 1
            menu.append('[B]{}:[/B] {} vybraných'.format(ADDON.getLocalizedString(30211), mu_count))
        else:
            menu.append(ADDON.getLocalizedString(30211))

        # Vylúčiť žánre (uses 'mu_exclude' parameter)
        if 'mu_exclude' in filter_params:
            mu_ex_count = len(filter_params['mu_exclude']) if isinstance(filter_params['mu_exclude'], list) else 1
            menu.append('[B]{}:[/B] {} vybraných'.format(ADDON.getLocalizedString(30262), mu_ex_count))
        else:
            menu.append(ADDON.getLocalizedString(30262))

        # Krajiny
        if 'co' in filter_params:
            co_count = len(filter_params['co']) if isinstance(filter_params['co'], list) else 1
            menu.append('[B]{}:[/B] {} vybraných'.format(ADDON.getLocalizedString(30212), co_count))
        else:
            menu.append(ADDON.getLocalizedString(30212))

        # === ZORADENIE ===
        # Zoradiť podľa
        if 'of' in filter_params:
            label = _get_selected_label(facets.get('sort_fields', []), filter_params['of'])
            menu.append('[B]{}:[/B] {}'.format(ADDON.getLocalizedString(30213), label or filter_params['of']))
        else:
            menu.append(ADDON.getLocalizedString(30213))

        # Smer zoradenia
        if 'od' in filter_params:
            label = _get_selected_label(facets.get('sort_directions', []), filter_params['od'])
            menu.append('[B]{}:[/B] {}'.format(ADDON.getLocalizedString(30214), label or filter_params['od']))
        else:
            menu.append(ADDON.getLocalizedString(30214))

        # Separator
        menu.append('─' * 30)

        # Akcie
        if filter_params:
            menu.append('[COLOR green][B]{}[/B][/COLOR]'.format(ADDON.getLocalizedString(30215)))
        else:
            menu.append('[COLOR gray]{}[/COLOR]'.format(ADDON.getLocalizedString(30215)))

        menu.append('[COLOR orange][B]{}[/B][/COLOR]'.format(ADDON.getLocalizedString(30216)))
        menu.append('[COLOR blue][B]{}[/B][/COLOR]'.format(ADDON.getLocalizedString(30217)))
        menu.append('[COLOR red][B]{}[/B][/COLOR]'.format(ADDON.getLocalizedString(30218)))

        return menu

    filter_params = dict(current_filter)  # Copy
    last_selected = 0  # Track last selected item for focus management

    while True:
        # Zobraz hlavné menu s aktuálnym stavom
        main_menu = _build_main_menu()
        selected = dialog.select(ADDON.getLocalizedString(30200), main_menu, preselect=last_selected)

        if selected == -1 or selected == 25:  # ESC alebo Zrušiť
            debug('FilterDialog: User cancelled')
            return (None, False)

        # === ZÁKLADNÉ FILTRE ===
        elif selected == 0:  # Typ obsahu
            _select_type(dialog, facets, filter_params)
            last_selected = selected

        elif selected == 1:  # Kvalita
            _select_quality(dialog, facets, filter_params)
            last_selected = selected

        elif selected == 2:  # Jazyk
            _select_language(dialog, facets, filter_params)
            last_selected = selected

        # === TECHNOLÓGIE ===
        elif selected == 3:  # HDR
            _select_hdr(dialog, filter_params)
            last_selected = selected

        elif selected == 4:  # Dolby Vision
            _select_dolby_vision(dialog, filter_params)
            last_selected = selected

        elif selected == 5:  # Dolby Atmos
            _select_atmos(dialog, filter_params)
            last_selected = selected

        elif selected == 6:  # HEVC Codec
            _select_hevc(dialog, filter_params)
            last_selected = selected

        elif selected == 7:  # 3D/Stereoscopic
            _select_stereoscopic(dialog, filter_params)
            last_selected = selected

        # === ADVANCED FILTERS ===
        elif selected == 8:  # Bitrate
            _input_bitrate(dialog, filter_params)
            last_selected = selected

        elif selected == 9:  # Filesize
            _input_filesize(dialog, filter_params)
            last_selected = selected

        elif selected == 10:  # MPAA Rating
            _select_mpaa(dialog, filter_params)
            last_selected = selected

        elif selected == 11:  # Keywords
            _input_keywords(dialog, filter_params)
            last_selected = selected

        # === AUDIO ===
        elif selected == 12:  # Dabing / Titulky
            _select_audio_options(dialog, filter_params)
            last_selected = selected

        # === HODNOTENIE A ROK ===
        elif selected == 13:  # Hodnotenie
            _input_rating(dialog, filter_params)
            last_selected = selected

        elif selected == 14:  # Rok vydania
            _input_year(dialog, filter_params)
            last_selected = selected

        # === VYHĽADÁVANIE ===
        elif selected == 15:  # Vyhľadávanie
            _input_search(dialog, filter_params)
            last_selected = selected

        # === ŽÁNRE A KRAJINY ===
        elif selected == 16:  # Žánre
            _select_genres(dialog, facets, filter_params)
            last_selected = selected

        elif selected == 17:  # Vylúčiť žánre
            _select_exclude_genres(dialog, facets, filter_params)
            last_selected = selected

        elif selected == 18:  # Krajiny
            _select_countries(dialog, facets, filter_params)
            last_selected = selected

        # === ZORADENIE ===
        elif selected == 19:  # Zoradiť podľa
            _select_sort_field(dialog, facets, filter_params)
            last_selected = selected

        elif selected == 20:  # Smer zoradenia
            _select_sort_direction(dialog, facets, filter_params)
            last_selected = selected

        # === AKCIE ===
        elif selected == 22:  # Použiť filter (index 22 = separator je 21)
            if filter_params:
                debug('FilterDialog: Filter applied: {}'.format(filter_params))
                return (filter_params, False)
            else:
                dialog.ok(ADDON.getLocalizedString(30200), ADDON.getLocalizedString(30240))
                last_selected = selected

        elif selected == 23:  # Reset
            if filter_params:
                if dialog.yesno(ADDON.getLocalizedString(30216), ADDON.getLocalizedString(30241)):
                    filter_params.clear()
                    debug('FilterDialog: Filter reset')
            else:
                dialog.ok(ADDON.getLocalizedString(30200), ADDON.getLocalizedString(30242))
            last_selected = selected

        elif selected == 24:  # Uložiť filter
            if filter_params:
                debug('FilterDialog: User wants to save filter')
                return (filter_params, True)
            else:
                dialog.ok(ADDON.getLocalizedString(30200), ADDON.getLocalizedString(30243))
                last_selected = selected
