# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals

import xbmc


def get_language_code():
    """
    Získa aktuálny jazyk GUI z KODI.

    Od KODI 21 s reuselanguageinvoker sa Python proces nerestartuje,
    ale táto funkcia vždy volá xbmc.getLanguage() aby získala aktuálny
    jazyk namiesto globálnej konštanty načítanej pri štarte.

    Returns:
        str: ISO 639-1 kód jazyka (napr. 'sk', 'en', 'cs')
    """
    return xbmc.getLanguage(xbmc.ISO_639_1)


def get_skin_name():
    """
    Získa aktuálny skin GUI z KODI.

    Od KODI 21 s reuselanguageinvoker sa Python proces nerestartuje,
    ale táto funkcia vždy volá xbmc.getSkinDir() aby získala aktuálny
    skin namiesto globálnej konštanty načítanej pri štarte.

    Returns:
        str: Názov skinu (napr. 'skin.estuary')
    """
    return xbmc.getSkinDir()
