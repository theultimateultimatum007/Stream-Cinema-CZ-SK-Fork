# -*- coding: utf-8 -*-
"""
Storage layer - Lokálne úložisko dát

Obsahuje:
- FilterStorage - Uložené používateľské filtre
- SearchHistory - História vyhľadávania
"""

from __future__ import print_function, unicode_literals

from .filter_storage import FilterStorage, filter_storage
from .search_history import SearchHistory

__all__ = ['FilterStorage', 'filter_storage', 'SearchHistory']
