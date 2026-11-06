# -*- coding: utf-8 -*-
"""
Bug Report — zber systémových informácií a stream kontextu.

collect_system()  — vždy priložené k reportu
collect_stream()  — priložené pri stream-kategóriách
build_dedupe_hash() — mäkký dedupe: sha1(str(category)+str(media_id)+str(description))
"""
from __future__ import print_function, unicode_literals

import hashlib

from resources.lib.kodiutils import (
    get_info_label,
    get_kodi_version,
    get_setting,
    get_skin_name,
    get_system_platform,
    get_uuid,
)


def collect_system():
    """Zozbiera systémové informácie pluginu a Kodi.

    Returns:
        dict: mapovania zodpovedajúce Backend Contract system.* (spec r. 64–66).
    """
    try:
        import xbmcaddon
        from resources.lib.constants import ADDON_ID
        plugin_ver = xbmcaddon.Addon(id=ADDON_ID).getAddonInfo('version')
    except Exception:
        plugin_ver = ''

    try:
        kodi_ver = get_kodi_version()
    except Exception:
        kodi_ver = ''

    try:
        platform = get_system_platform()
    except Exception:
        platform = ''

    try:
        uid = get_uuid()
    except Exception:
        uid = ''

    try:
        skin = get_skin_name()
    except Exception:
        skin = ''

    try:
        lang = get_info_label('System.Language')
    except Exception:
        lang = ''

    try:
        device_name = get_info_label('System.FriendlyName')
    except Exception:
        device_name = ''

    return {
        'plugin_ver': plugin_ver,
        'kodi_ver': kodi_ver,
        'platform': platform,
        'uid': uid,
        'skin': skin,
        'lang': lang,
        'device_name': device_name,
    }


def extract_play_id(play_url):
    """Vytiahne ID média z /Play/<id>/... URL (alebo '' ak sa nenájde).

    Pre filmy je to zakódované media ID (napr. 'm_OcRtIMBm7WFA').
    """
    if not play_url:
        return ''
    import re
    m = re.search(r'/Play/([^/?#]+)', play_url)
    return m.group(1) if m else ''


def extract_stream_id(stream_url):
    """Vráti posledný path segment resolve URL (napr. /ws2/<token>/<id> -> <id>).

    Hodnota sa ZÁMERNE NEKONVERTUJE na integer — prechádza ako reťazec.
    Backend v tomto segmente posiela ID streamu; keď ho začne posielať
    'cryptovaný' (ako media ID, len s iným prefixom, napr. 'e_…'/'s_…'),
    plugin ho automaticky prepošle v tej podobe bez ďalšej zmeny v klientovi.
    """
    if not stream_url:
        return ''
    path = stream_url.split('?', 1)[0].split('#', 1)[0].rstrip('/')
    return path.rsplit('/', 1)[-1] if path else ''


def collect_stream(source, item_data):
    """Mapuje stream kontext na Backend Contract stream.* (spec r. 68–74).

    Args:
        source (str): 'live_fail' | 'last_played' | 'none'
        item_data (dict | None): JSON data z SELECTED_ITEM / last_stream cache.
            Môže byť None pri source='none'.

    Returns:
        dict: stream kontext pripravený na vloženie do payloadu.
    """
    if item_data is None:
        item_data = {}

    # Pomocná funkcia pre bezpečné získanie hodnoty
    def _get(key, default=None):
        val = item_data.get(key)
        if val is None:
            return default
        return val

    # play_url  = menu/Play URL (self.url): /Play/<media_id> (film) alebo
    #             /Play/<show>/<s>/<e> (epizóda).
    # stream_url = skutočný stream resolve URL (res.getPath()): pre epizódy
    #             /ws2/<token>/<streamId> s reálnym ID prehrávaného streamu.
    play_url = _get('play_url', '')
    stream_url = _get('stream_url', '')
    play_id = extract_play_id(play_url)        # zakódované media ID (m_…)
    stream_id = extract_stream_id(stream_url)  # ID streamu (reťazec, passthrough)
    # media_id: explicitné -> 'id' -> media ID z /Play -> stream ID z /ws2.
    media_id = item_data.get('media_id') or item_data.get('id') or play_id or stream_id

    # season/episode: play_url (/Play/<show>/<s>/<e>) je autoritatívny — 'info'
    # dict z /Play odpovede môže mať season=0. Ak URL nesie epizódne číslo,
    # má prednosť pred (potenciálne rozbitou) hodnotou zo stream kontextu.
    season = _get('season', 0)
    episode = _get('episode', 0)
    url_season, url_episode = extract_season_episode(play_url)
    if url_season is not None:
        season = url_season
    if url_episode is not None:
        episode = url_episode

    # Zber stream metadát podľa Backend Contract
    stream = {
        'source': source,
        'ident': _get('ident', ''),
        'quality': _get('quality', ''),
        'codec': _get('codec', ''),
        'width': _get('width', 0),
        'height': _get('height', 0),
        'bitrate': _get('bitrate', 0),
        'audio_langs': _get('audio_langs', []),
        'sub_langs': _get('sub_langs', []),
        'provider': _get('provider', ''),
        'play_url': play_url,
        'play_id': play_id,
        'stream_url': stream_url,
        'stream_id': stream_id,
        'media_id': media_id,
        'media_title': _get('media_title', ''),
        'season': season,
        'episode': episode,
        'selected_by': _get('selected_by', ''),
        'position': _get('position', 0),
        'duration': _get('duration', 0),
        'percent': _get('percent', 0),
    }

    return stream


def extract_season_episode(play_url):
    """Zo /Play/<show>/<season>/<episode> vytiahne (season, episode) ako int.

    play_url je autoritatívny zdroj čísla sezóny/epizódy pre prehrávanú
    epizódu — 'info' dict z /Play odpovede môže mať season=0/chýbajúcu, kým
    URL nesie správne číslo (napr. /Play/s_Show/9/9 pri S09E09).

    Pre filmy (/Play/<media_id>) alebo neúplné URL vráti (None, None).

    Args:
        play_url (str): /Play URL vybraného streamu.

    Returns:
        tuple: (season, episode) ako int, alebo (None, None) ak URL nie je
            epizódneho tvaru.
    """
    if not play_url:
        return None, None
    path = play_url.split('?', 1)[0].split('#', 1)[0].strip('/')
    parts = path.split('/')
    # Epizóda: ['Play', '<show>', '<season>', '<episode>']; film má len 2 časti.
    if len(parts) >= 4 and parts[0] == 'Play':
        try:
            return int(parts[-2]), int(parts[-1])
        except (ValueError, TypeError):
            return None, None
    return None, None


def build_dedupe_hash(category, media_id, description):
    """Vypočíta mäkký dedupe hash zo vstupných polí.

    Všetky vstupy sú str()-coercované pred konkatenáciou — media_id môže byť
    int alebo None.

    Args:
        category (str): kategória reportu.
        media_id: identifikátor média (str, int alebo None).
        description (str | None): voľný popis.

    Returns:
        str: 40-znakový hex SHA-1 hash.
    """
    raw = str(category) + str(media_id) + str(description)
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()
