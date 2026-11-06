# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals

import traceback
from time import time

from resources.lib.services.timer_service import TimerService
from resources.lib.api.sc import Sc
from resources.lib.gui.item import SCItem
from resources.lib.constants import SC
from resources.lib.common.logger import debug


class MenuCacheService(TimerService):
    """
    Service ktorý v pozadí generuje a cachuje menu
    Sťahuje static menu cache z API a pre-procesuje všetky items

    DÔLEŽITÉ: Používa IN-MEMORY cache (nie disk), pretože KODI ListItem
    objekty nie sú pickle-serializable. Cache zostáva aktívna počas
    behu služby a poskytuje benefit pri opakovanom otváraní menu.
    """

    SERVICE_NAME = "MenuCacheService"
    DEFAULT_INTERVAL = 300  # Refresh každých 5 minút

    def __init__(self):
        super(MenuCacheService, self).__init__()
        self.menu_cache = {}
        self.menu_raw = {}  # Raw JSON cache
        self.last_fetch = {}

        debug('MenuCacheService: Initialized (IN-MEMORY cache)')

    def run(self):
        """Refresh často používaných menu"""
        try:
            # Homepage - najdôležitejšie
            self._prepare_menu('/')

            # Ďalšie často používané (voliteľné)
            # self._prepare_menu('/Movies')
            # self._prepare_menu('/TVShows')

        except Exception:
            debug('MenuCacheService error: {}'.format(traceback.format_exc()))

    def _prepare_menu(self, url):
        """
        Stiahne a pre-spracuje menu z API static cache
        Vytvorí hotové ListItem tuples pripravené na zobrazenie
        """
        debug('MenuCacheService: Preparing menu for {}'.format(url))

        try:
            start_time = time()

            # 1. Stiahni menu (z static cache alebo API)
            response = Sc.get(url)

            if SC.ITEM_MENU not in response:
                debug('MenuCacheService: No menu in response for {}'.format(url))
                return

            # 2. Ulož raw response
            self.menu_raw[url] = response

            # 3. Pre-procesuj všetky items pomocou generátora
            items = list(self._generate_items(url, response))

            # 4. Ulož do cache
            self.menu_cache[url] = {
                'items': items,
                'timestamp': time(),
                'count': len(items)
            }

            elapsed = time() - start_time
            debug('MenuCacheService: Cached {} items for {} in {:.2f}s'.format(
                len(items), url, elapsed))

        except Exception as e:
            debug('MenuCacheService: Error preparing {}: {}'.format(url, e))

    def _generate_items(self, url, response):
        """
        Generator ktorý postupne vytvára ListItem tuples
        Použitie yield pre efektívne spracovanie
        """
        from resources.lib.common.storage import Storage
        from resources.lib.gui import GUI

        # Načítaj user data (pinned, hidden)
        storage = Storage('scinema')
        pinned_key = 'pinned.{}'.format(url)
        pinned = storage.get(pinned_key) or {}
        hidden = storage.get('h-{}'.format(url)) or {}

        menu_items = response.get(SC.ITEM_MENU, [])

        for item_data in menu_items:
            try:
                # Vytvor SCItem
                item = SCItem(item_data)

                if not item.visible:
                    continue

                # Check hidden
                if hidden.get(item.li().getLabel()):
                    continue

                # Check pinned (tie idú ako prvé)
                is_pinned = False
                if item_data.get(SC.ITEM_URL) and pinned.get(item_data.get(SC.ITEM_URL)):
                    item.li().setProperty('SpecialSort', GUI.TOP)
                    is_pinned = True

                # Yield hotový tuple (url, listitem, isFolder)
                yield item.get()

            except Exception as e:
                debug('MenuCacheService: Error processing item: {}'.format(e))
                continue

    def get_menu(self, url, max_age=300):
        """
        Vráť cached menu ak existuje a je fresh

        Returns:
            dict alebo None: {'items': [...], 'timestamp': int, 'count': int}
        """
        cached = self.menu_cache.get(url)

        if not cached:
            debug('MenuCacheService: No cache for {}'.format(url))
            return None

        age = time() - cached['timestamp']

        if age > max_age:
            debug('MenuCacheService: Cache expired for {} (age: {:.0f}s)'.format(url, age))
            return None

        debug('MenuCacheService: Cache hit for {} ({} items, age: {:.0f}s)'.format(
            url, cached['count'], age))

        return cached

    def get_raw_response(self, url):
        """Vráť raw API response (pre system data atď.)"""
        return self.menu_raw.get(url)

    def save_menu_from_response(self, url, response, items):
        """
        Uloží už spracované menu do cache
        Používa sa keď je cache miss a menu sa už načítalo z API

        Args:
            url: URL menu
            response: Raw API response
            items: Už spracované ListItem tuples
        """
        try:
            # Ulož raw response
            self.menu_raw[url] = response

            # Ulož spracované items
            self.menu_cache[url] = {
                'items': items,
                'timestamp': time(),
                'count': len(items)
            }

            debug('MenuCacheService: Saved {} items for {} to cache'.format(len(items), url))

        except Exception as e:
            debug('MenuCacheService: Error saving menu: {}'.format(e))

    def invalidate(self, url=None):
        """Invaliduj cache pre URL alebo všetko"""
        if url:
            if url in self.menu_cache:
                del self.menu_cache[url]
            if url in self.menu_raw:
                del self.menu_raw[url]
        else:
            self.menu_cache = {}
            self.menu_raw = {}

        debug('MenuCacheService: Cache invalidated for {}'.format(url or 'ALL'))


# Singleton instance
menu_cache_service = MenuCacheService()
