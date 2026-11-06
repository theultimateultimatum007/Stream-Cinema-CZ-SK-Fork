# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals

import traceback
from time import time
from json import dumps, loads

from xbmcgui import Window

from resources.lib.services.timer_service import TimerService
from resources.lib.api.sc import Sc
from resources.lib.gui.item import SCItem
from resources.lib.constants import SC
from resources.lib.common.logger import debug
from resources.lib.common.storage import Storage


class MenuCacheServer(TimerService):
    """
    Service ktorý v pozadí generuje a cachuje SERIALIZED menu items

    KĽÚČOVÁ OPTIMALIZÁCIA:
    - Service pre-spracuje menu (SCItem, visible checks, atď.)
    - Serializuje MINIMÁLNE údaje potrebné na vytvorenie ListItem
    - Uloží do KODI Window properties (zdieľané medzi procesmi!)
    - Plugin len načíta a vytvorí ListItems → 5-10ms namiesto 50ms+
    """

    SERVICE_NAME = "MenuCacheServer"
    DEFAULT_INTERVAL = 3600  # Refresh každú hodinu
    CHECK_PLAYER_STATE = True  # Pausuje cache počas prehrávania pre lepší výkon

    def __init__(self):
        super(MenuCacheServer, self).__init__()
        self.window = Window(10000)  # KODI Home window - GLOBÁLNY medzi procesmi
        self.cache = {}
        debug('MenuCacheServer: Initialized')

        # Nepotrebujeme mazať cache pri každej inicializácii
        # Cache expiruje automaticky cez max_age parameter

    def _clear_old_cache(self):
        """Vymaž staré cache z Window properties pri štarte"""
        try:
            # Zoznam známych cache keys
            urls = ['/', '/FMovies', '/FTVShows', '/FSeries']
            for url in urls:
                prop_key = 'SC.MenuCache.{}'.format(url.replace('/', '_'))
                self.window.clearProperty(prop_key)
            debug('MenuCacheServer: Old cache cleared')
        except Exception as e:
            debug('MenuCacheServer: Error clearing old cache: {}'.format(e))

    def run(self):
        """
        Voliteľný preheat cache pre často používané URL
        (nie je potrebný, cache sa vytvára automaticky on-demand)
        """
        try:
            # Homepage - najdôležitejšie
            self._prepare_menu('/')

            # Ďalšie často používané (voliteľné)
            # self._prepare_menu('/FMovies')
            # self._prepare_menu('/FTVShows')

        except Exception:
            debug('MenuCacheServer error: {}'.format(traceback.format_exc()))

    def _prepare_menu(self, url, episodes_only=False):
        """
        PRE-SPRACUJE menu:
        1. Stiahne z API
        2. Vytvorí SCItem objekty
        3. Skontroluje visible (môže obsahovať sc:// logiku!)
        4. Serializuje do minimálnych údajov
        5. Uloží do Window property

        Args:
            url: URL na spracovanie
            episodes_only: Ak True, spracuje len epizódy (preskočí SCItem vytvorenie)
        """
        debug('MenuCacheServer: Preparing menu for {} (episodes_only={})'.format(url, episodes_only))

        try:
            start_time = time()

            # 1. Stiahni menu (z SimpleCache alebo API)
            response = Sc.get(url)
            debug('MenuCacheServer: Got response, keys: {}'.format(response.keys() if response else 'None'))

            if SC.ITEM_MENU not in response:
                debug('MenuCacheServer: No menu in response for {}'.format(url))
                return

            menu_items_count = len(response.get(SC.ITEM_MENU, []))
            debug('MenuCacheServer: Found {} menu items in response (episodes_only={})'.format(menu_items_count, episodes_only))


            # 2. Načítaj user-specific data (pinned/hidden)
            storage = Storage('scinema')
            pinned_key = 'pinned.{}'.format(url)
            pinned = storage.get(pinned_key) or {}
            hidden = storage.get('h-{}'.format(url)) or {}

            # 3. Pre-procesuj všetky items
            serialized_items = []
            menu_items = response.get(SC.ITEM_MENU, [])

            # Pre detekciu epizód a sezón
            episodes_by_show = {}  # {show_id: {season: [episodes]}}
            seasons_by_show = {}   # {show_id: [seasons]}
            episode_detection_count = 0

            for item_data in menu_items:
                # NAJPRV: Detekcia epizód a sezón pre EpisodeCache
                # MIMO try bloku aby sa vykonala aj keď SCItem() failne!

                # API vracia dáta priamo v item_data, nie v item_data['info']!
                mediatype = item_data.get('mediatype')

                # Detekcia sezón (mediatype='season')
                if mediatype == 'season' and 'season' in item_data:
                    # Toto je sezóna!
                    show_id = item_data.get('id', '').split('-')[0] if '-' in item_data.get('id', '') else item_data.get('id')
                    season = int(item_data.get('season'))

                    if show_id:
                        if show_id not in seasons_by_show:
                            seasons_by_show[show_id] = []
                        seasons_by_show[show_id].append(season)
                        debug('MenuCacheServer: Detected season: show={}, season={}'.format(show_id, season))

                # Detekcia epizód (season a episode sú v info dict)
                # POZOR: Sezóny tiež môžu mať info['season'] a info['episode'] (posledná epizóda),
                # takže musíme vylúčiť položky ktoré sú sezóny
                # RIEŠENIE: Sezóny majú type='dir', epizódy majú type='video'
                elif 'info' in item_data and 'season' in item_data['info'] and 'episode' in item_data['info']:
                    item_type = item_data.get('type')

                    # Ak je type='dir', je to sezóna (directory), nie epizóda - IGNORUJ!
                    if item_type == 'dir':
                        # Toto je SEZÓNA s metadátami o poslednej epizóde, preskočiť
                        continue

                    # Toto je skutočná EPIZÓDA (type='video')!
                    episode_detection_count += 1
                    info = item_data['info']
                    show_id = item_data.get('id')
                    season = int(info['season'])
                    episode = int(info['episode'])

                    # Ignoruj špeciálne epizódy (S0Exx alebo SxxE0)
                    if season == 0 or episode == 0:
                        debug('MenuCacheServer: Skipping special episode S{}E{}'.format(season, episode))
                        continue

                    if show_id:
                        if show_id not in episodes_by_show:
                            episodes_by_show[show_id] = {}
                        if season not in episodes_by_show[show_id]:
                            episodes_by_show[show_id][season] = []
                        episodes_by_show[show_id][season].append(episode)

                # Ak je episodes_only mode, preskočíme SCItem vytvorenie
                if episodes_only:
                    continue

                # Teraz skús vytvoriť SCItem pre serialized menu (môže failnúť)
                try:
                    # Vytvor SCItem (môže kontrolovať sc:// conditions!)
                    item = SCItem(item_data)

                    if not item.visible:
                        continue

                    # Check hidden
                    li = item.li()
                    if li is None:
                        # SCItem.li() vrátil None (nie je dostupný v tomto kontexte)
                        # Pokračuj bez hidden check
                        debug('MenuCacheServer: item.li() returned None for item, skipping')
                        continue

                    if hidden.get(li.getLabel()):
                        continue

                    # Získaj URL a isFolder z item.get()
                    item_tuple = item.get()
                    if item_tuple is None:
                        debug('MenuCacheServer: item.get() returned None, skipping')
                        continue

                    plugin_url = item_tuple[0]  # Plugin URL (plugin://...)
                    isFolder = item_tuple[2] if len(item_tuple) > 2 else True

                    # Serializuj ListItem do minimálnych údajov
                    serialized = {
                        'url': plugin_url,  # Použij plugin URL (nie čistú URL)
                        'label': li.getLabel(),
                        'isFolder': isFolder,
                        # Tieto údaje sú potrebné pre ListItem
                        'info': item_data.get('info', {}),
                        'art': item_data.get('art', {}),
                        'properties': item_data.get('properties', {}),
                        'context': item_data.get('context', []),
                        # Pinned info
                        'is_pinned': bool(item_data.get(SC.ITEM_URL) and pinned.get(item_data.get(SC.ITEM_URL))),
                    }

                    serialized_items.append(serialized)

                except Exception as e:
                    debug('MenuCacheServer: Error processing item: {}'.format(e))
                    debug('MenuCacheServer: Traceback: {}'.format(traceback.format_exc()))
                    # Aj keď nastala chyba pri spracovaní SerializedItem, pokračuj (epizódy už máme uložené)
                    continue

            # 3b. Ulož detekované epizódy do EpisodeCache
            if episodes_by_show:
                from resources.lib.services.episode_cache import episode_cache
                for show_id, seasons in episodes_by_show.items():
                    for season, episodes in seasons.items():
                        episode_cache.save_season_episodes(show_id, season, episodes)
                        debug('MenuCacheServer: Saved {} episodes to EpisodeCache for show={}, season={}'.format(
                            len(episodes), show_id, season))

            # 3c. Ulož detekované sezóny do EpisodeCache
            if seasons_by_show:
                from resources.lib.services.episode_cache import episode_cache
                for show_id, seasons in seasons_by_show.items():
                    episode_cache.save_season_episodes(show_id, None, seasons, is_season_list=True)
                    debug('MenuCacheServer: Saved {} seasons to EpisodeCache for show={}'.format(
                        len(seasons), show_id))

            # 4. Ulož do Window property ako JSON
            cache_data = {
                'items': serialized_items,
                'timestamp': time(),
                'count': len(serialized_items),
                'raw_response': response  # Pre system data
            }

            # Window property key
            prop_key = 'SC.MenuCache.{}'.format(url.replace('/', '_'))
            debug('MenuCacheServer: Saving cache - URL: {}, prop_key: {}, items: {}'.format(url, prop_key, len(serialized_items)))
            self.window.setProperty(prop_key, dumps(cache_data))

            # Ulož aj do RAM (backup)
            self.cache[url] = cache_data

            elapsed = time() - start_time
            debug('MenuCacheServer: Cache saved successfully for URL: {} ({} items in {:.2f}ms)'.format(
                url, len(serialized_items), elapsed * 1000))

        except Exception as e:
            debug('MenuCacheServer: Error preparing {}: {}'.format(url, e))

    def get_cached_menu(self, url, max_age=300):
        """
        Vráť cached menu z Window property
        Ak cache neexistuje, vytvor ho automaticky (lazy initialization)

        Returns:
            dict alebo None: {'items': [...], 'timestamp': int, 'count': int, 'raw_response': {...}}
        """
        try:
            prop_key = 'SC.MenuCache.{}'.format(url.replace('/', '_'))
            cached_json = self.window.getProperty(prop_key)

            if not cached_json:
                # Lazy initialization - vytvor cache pre akúkoľvek URL
                debug('MenuCacheServer: Creating cache for {}'.format(url))
                self._prepare_menu(url)

                # Skús znova načítať
                cached_json = self.window.getProperty(prop_key)
                if not cached_json:
                    debug('MenuCacheServer: Failed to create cache for {}'.format(url))
                    return None

            cached = loads(cached_json)
            age = time() - cached['timestamp']

            # Robustná kontrola: Detekcia časového posunu
            MAX_REASONABLE_AGE = 86400  # 24 hodín - ak je cache staršia, niečo je divné

            if age < 0 or age > MAX_REASONABLE_AGE:
                # Čas sa posunul DOZADU alebo cache je podozrivo stará
                reason = 'backwards' if age < 0 else 'unusually old'
                debug('MenuCacheServer: Time issue for {} (age: {:.0f}s, {}), refreshing...'.format(url, age, reason))
                self._prepare_menu(url)

                # Načítaj znova s novým timestampom
                cached_json = self.window.getProperty(prop_key)
                if not cached_json:
                    debug('MenuCacheServer: Failed to refresh cache for {}'.format(url))
                    return None

                cached = loads(cached_json)
                age = 0

            elif age > max_age:
                debug('MenuCacheServer: Cache expired for {} (age: {:.0f}s), refreshing...'.format(url, age))
                # Cache expirovala - refresh
                self._prepare_menu(url)

                # Načítaj znova
                cached_json = self.window.getProperty(prop_key)
                if not cached_json:
                    debug('MenuCacheServer: Failed to refresh cache for {}'.format(url))
                    return None

                cached = loads(cached_json)
                age = 0  # Nová cache

            debug('MenuCacheServer: Cache HIT for {} ({} items, age: {:.0f}s)'.format(
                url, cached['count'], age))

            return cached

        except Exception as e:
            debug('MenuCacheServer: Error getting cache: {}'.format(e))
            return None

    def invalidate(self, url=None):
        """Invaliduj cache pre URL alebo všetko"""
        if url:
            prop_key = 'SC.MenuCache.{}'.format(url.replace('/', '_'))
            self.window.clearProperty(prop_key)
            if url in self.cache:
                del self.cache[url]
        else:
            # Vymaž všetky SC.MenuCache.* properties
            self.cache = {}

        debug('MenuCacheServer: Cache invalidated for {}'.format(url or 'ALL'))


# Singleton instance
menu_cache_server = MenuCacheServer()
