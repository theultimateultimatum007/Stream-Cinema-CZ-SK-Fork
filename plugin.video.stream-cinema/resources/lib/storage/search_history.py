# -*- coding: utf-8 -*-
from __future__ import print_function, unicode_literals

import time
from resources.lib.common.storage import Storage
from resources.lib.common.logger import debug


class SearchHistory(object):
    """
    Správa histórie vyhľadávania pre rôzne typy vyhľadávania

    Každý typ vyhľadávania má vlastnú izolovanú históriu:
    - 'search-movies' → história vyhľadávania filmov
    - 'search-series' → história vyhľadávania seriálov
    - 'search-people' → história vyhľadávania hercov
    """

    MAX_ITEMS = 50  # Maximálny počet položiek v histórii

    def __init__(self, search_type):
        """
        Inicializuje históriu vyhľadávania pre daný typ

        Args:
            search_type: ID typu vyhľadávania
                - 'search-movies' → filmy
                - 'search-series' → seriály
                - 'search-people' → herci
        """
        self.search_type = search_type
        self.storage_key = 'search_history_{}'.format(search_type)
        self._storage = Storage(self.storage_key)

        # Inicializácia - ak storage neexistuje, vytvor prázdny zoznam
        if self._storage.get('data') is None:
            self._storage['data'] = []
            debug('SearchHistory: Initialized empty history for {}'.format(search_type))

    def add(self, query):
        """
        Pridá vyhľadávací dotaz do histórie
        - Ak existuje, posunie ho na vrch (timestamp update)
        - Ak neexistuje, pridá nový
        - Automaticky limituje na MAX_ITEMS

        Args:
            query: Vyhľadávací text
        """
        if not query or not query.strip():
            return

        query = query.strip()
        data = self._storage.get('data') or []
        current_time = int(time.time())

        # Kontrola či query už existuje
        existing_item = None
        for item in data:
            if item.get('query') == query:
                existing_item = item
                break

        if existing_item:
            # Aktualizuj timestamp a posun na vrch
            debug('SearchHistory: Updating existing query "{}" for {}'.format(query, self.search_type))
            data.remove(existing_item)
            existing_item['timestamp'] = current_time
            data.insert(0, existing_item)
        else:
            # Pridaj nový item
            debug('SearchHistory: Adding new query "{}" for {}'.format(query, self.search_type))
            new_item = {
                'query': query,
                'timestamp': current_time
            }
            data.insert(0, new_item)

        # Limit na MAX_ITEMS - odstráň najstaršie
        if len(data) > self.MAX_ITEMS:
            removed_count = len(data) - self.MAX_ITEMS
            data = data[:self.MAX_ITEMS]
            debug('SearchHistory: Removed {} oldest items from {}'.format(removed_count, self.search_type))

        # Ulož do storage
        self._storage['data'] = data
        debug('SearchHistory: Saved {} items for {}'.format(len(data), self.search_type))

    def get_all(self):
        """
        Vráti všetky položky histórie

        Returns:
            list: [{'query': str, 'timestamp': int}, ...]
            Sorted by timestamp DESC (najnovšie hore)
        """
        data = self._storage.get('data') or []
        # Už je sorted by timestamp DESC (pridávame na začiatok)
        debug('SearchHistory: Retrieved {} items for {}'.format(len(data), self.search_type))
        return data

    def edit(self, old_query, new_query):
        """
        Upraví existujúcu položku v histórii
        - Aktualizuje query
        - Aktualizuje timestamp (posunie na vrch)

        Args:
            old_query: Starý text
            new_query: Nový text
        """
        if not new_query or not new_query.strip():
            return

        old_query = old_query.strip()
        new_query = new_query.strip()

        data = self._storage.get('data') or []

        # Nájdi starú položku
        old_item = None
        for item in data:
            if item.get('query') == old_query:
                old_item = item
                break

        if not old_item:
            debug('SearchHistory: Old query "{}" not found in {}'.format(old_query, self.search_type))
            # Ak sa nenašla stará, pridaj novú
            self.add(new_query)
            return

        # Odstráň starú položku
        data.remove(old_item)

        # Skontroluj či nový query už existuje
        existing_new_item = None
        for item in data:
            if item.get('query') == new_query:
                existing_new_item = item
                break

        if existing_new_item:
            # Ak nový query už existuje, odstráň ho (pridáme ho na vrch)
            data.remove(existing_new_item)

        # Pridaj upravenú položku na vrch
        current_time = int(time.time())
        updated_item = {
            'query': new_query,
            'timestamp': current_time
        }
        data.insert(0, updated_item)

        # Ulož do storage
        self._storage['data'] = data
        debug('SearchHistory: Edited query from "{}" to "{}" in {}'.format(
            old_query, new_query, self.search_type))

    def delete(self, query):
        """
        Vymaže položku z histórie

        Args:
            query: Text na vymazanie
        """
        query = query.strip()
        data = self._storage.get('data') or []

        # Nájdi a odstráň položku
        item_to_remove = None
        for item in data:
            if item.get('query') == query:
                item_to_remove = item
                break

        if item_to_remove:
            data.remove(item_to_remove)
            self._storage['data'] = data
            debug('SearchHistory: Deleted query "{}" from {}'.format(query, self.search_type))
        else:
            debug('SearchHistory: Query "{}" not found in {} for deletion'.format(
                query, self.search_type))

    def clear(self):
        """Vymaže celú históriu pre tento search_type"""
        self._storage['data'] = []
        debug('SearchHistory: Cleared all history for {}'.format(self.search_type))
