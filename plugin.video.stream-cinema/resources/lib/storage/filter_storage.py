# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals

from resources.lib.common.storage import Storage
from resources.lib.common.logger import debug


class FilterStorage:
    """
    Storage pre vlastné používateľské filtre

    Funkcie:
    - Ukladanie custom filtrov s názvom
    - Načítanie uložených filtrov
    - Vymazanie filtrov
    - Zoznam všetkých uložených filtrov
    """

    STORAGE_NAME = 'custom_filters'

    def __init__(self):
        """Inicializácia filter storage"""
        self.storage = Storage(self.STORAGE_NAME)
        debug('FilterStorage: Initialized')

    def save_filter(self, filter_slug, filter_params, display_name=None):
        """
        Uloží filter s daným slugom

        Args:
            filter_slug (str): Slug filtra (unikátny identifikátor bez diakritiky)
            filter_params (dict): Filter parametre
            display_name (str): Originálny názov s diakritikou pre zobrazenie (voliteľné)

        Returns:
            bool: True ak sa podarilo uložiť

        Príklad:
            storage.save_filter('4k-hdr-filmy', {
                'typ': 1,
                'q': '4K',
                'HDR': 2,
                'of': 'rating',
                'od': 'desc'
            }, display_name='4K HDR Filmy')
        """
        try:
            debug('FilterStorage: Saving filter slug="{}", display_name="{}", params: {}'.format(
                filter_slug, display_name, filter_params))

            # Skopíruj params aby sme nemodifikovali originál
            params_copy = dict(filter_params)

            # Pridaj display_name do params (pre zobrazenie originálneho názvu)
            if display_name:
                params_copy['_display_name'] = display_name

            # Ulož filter do storage (key = slug, value = params s display_name)
            self.storage[filter_slug] = params_copy

            debug('FilterStorage: Filter "{}" saved successfully'.format(filter_slug))
            return True

        except Exception as e:
            debug('FilterStorage: Error saving filter "{}": {}'.format(filter_slug, e))
            return False

    def get_filter(self, filter_slug):
        """
        Načíta filter podľa slugu

        Args:
            filter_slug (str): Slug filtra

        Returns:
            dict: Filter parametre (bez _display_name) alebo None ak neexistuje
        """
        try:
            filter_params = self.storage.get(filter_slug)

            if filter_params:
                debug('FilterStorage: Loaded filter "{}": {}'.format(
                    filter_slug, filter_params))

                # Skopíruj params a odstráň _display_name (nie je filter parameter)
                if isinstance(filter_params, dict):
                    params_clean = dict(filter_params)
                    if '_display_name' in params_clean:
                        del params_clean['_display_name']
                    return params_clean

                return filter_params
            else:
                debug('FilterStorage: Filter "{}" not found'.format(filter_slug))
                return None

        except Exception as e:
            debug('FilterStorage: Error loading filter "{}": {}'.format(filter_slug, e))
            return None

    def get_display_name(self, filter_slug):
        """
        Získa display názov (originálny názov s diakritikou) pre daný slug

        Args:
            filter_slug (str): Slug filtra

        Returns:
            str: Display názov alebo slug ak display názov neexistuje
        """
        try:
            filter_params = self.storage.get(filter_slug)

            if filter_params and isinstance(filter_params, dict):
                # Vráť display_name ak existuje, inak slug
                return filter_params.get('_display_name', filter_slug)

            return filter_slug

        except Exception as e:
            debug('FilterStorage: Error getting display name for "{}": {}'.format(filter_slug, e))
            return filter_slug

    def delete_filter(self, filter_name):
        """
        Vymaže filter

        Args:
            filter_name (str): Názov filtra

        Returns:
            bool: True ak sa podarilo vymazať
        """
        try:
            debug('FilterStorage: Deleting filter "{}"'.format(filter_name))

            if filter_name in self.storage.data:
                del self.storage[filter_name]
                debug('FilterStorage: Filter "{}" deleted successfully'.format(filter_name))
                return True
            else:
                debug('FilterStorage: Filter "{}" not found'.format(filter_name))
                return False

        except Exception as e:
            debug('FilterStorage: Error deleting filter "{}": {}'.format(filter_name, e))
            return False

    def get_all_filters(self):
        """
        Vráti zoznam všetkých uložených filtrov

        Returns:
            dict: Dictionary {filter_name: filter_params, ...}

        Príklad:
            {
                '4K HDR Filmy': {'typ': 1, 'q': '4K', 'HDR': 2, ...},
                'Nové seriály 2024': {'typ': 3, 'y': '>2023', ...},
                ...
            }
        """
        try:
            filters = self.storage.data
            debug('FilterStorage: Loaded {} filters'.format(len(filters)))
            return filters

        except Exception as e:
            debug('FilterStorage: Error loading filters: {}'.format(e))
            return {}

    def get_filter_names(self):
        """
        Vráti zoznam názvov všetkých uložených filtrov

        Returns:
            list: Zoznam názvov filtrov
        """
        try:
            names = list(self.storage.data.keys())
            debug('FilterStorage: Found {} filter names'.format(len(names)))
            return names

        except Exception as e:
            debug('FilterStorage: Error loading filter names: {}'.format(e))
            return []

    def filter_exists(self, filter_name):
        """
        Skontroluje či filter s daným názvom existuje

        Args:
            filter_name (str): Názov filtra

        Returns:
            bool: True ak filter existuje
        """
        return filter_name in self.storage.data

    def rename_filter(self, filter_slug, new_display_name):
        """
        Premenuje display name filtra (slug zostáva rovnaký pre URL konzistenciu)

        Args:
            filter_slug (str): Slug filtra (nemení sa)
            new_display_name (str): Nový display názov

        Returns:
            bool: True ak sa podarilo premenovať
        """
        try:
            if not self.filter_exists(filter_slug):
                debug('FilterStorage: Cannot rename - filter "{}" not found'.format(filter_slug))
                return False

            # Získaj filter params
            filter_params = self.storage.get(filter_slug)

            if not isinstance(filter_params, dict):
                debug('FilterStorage: Cannot rename - invalid filter params format')
                return False

            # Aktualizuj _display_name
            filter_params['_display_name'] = new_display_name

            # Ulož späť (slug zostáva rovnaký)
            self.storage[filter_slug] = filter_params

            debug('FilterStorage: Filter "{}" display name changed to "{}"'.format(filter_slug, new_display_name))
            return True

        except Exception as e:
            debug('FilterStorage: Error renaming filter: {}'.format(e))
            return False

    def clear_all_filters(self):
        """
        Vymaže všetky uložené filtre

        Returns:
            bool: True ak sa podarilo vymazať
        """
        try:
            debug('FilterStorage: Clearing all filters')

            # Vymaž všetky keys
            for filter_name in list(self.storage.data.keys()):
                del self.storage[filter_name]

            debug('FilterStorage: All filters cleared')
            return True

        except Exception as e:
            debug('FilterStorage: Error clearing filters: {}'.format(e))
            return False


# Singleton instance
filter_storage = FilterStorage()
