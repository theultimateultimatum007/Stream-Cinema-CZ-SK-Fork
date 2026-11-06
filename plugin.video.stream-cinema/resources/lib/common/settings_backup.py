# -*- coding: utf-8 -*-
"""
Zaloha a obnova settings.xml doplnku.

Kodi obcas poskodi settings.xml (pad/vypnutie uprostred zapisu, subeh
zapisov z viacerych invokerov) - subor ostane orezany alebo 0-bajtovy
a doplnok pride o vsetky nastavenia vratane prihlasovacich udajov.

Princip:
- do zalohy (settings.xml.bak) sa kopiruje LEN validny subor, takze
  poskodenie sa do nej nikdy neprenesie
- pri starte service sa validita skontroluje a poskodeny subor sa
  obnovi zo zalohy SKOR, nez si nastavenia nacita zvysok doplnku

Modul zamerne nepouziva kodiutils/constants helpre na citanie nastaveni -
musi byt importovatelny a funkcny este pred ich inicializaciou.
Subory su vzdy na lokalnom disku (special://profile), preto stacia os/shutil.
"""
import os
import shutil
import time
import xml.etree.ElementTree as ET

import xbmc

from resources.lib.constants import ADDON_ID

BACKUP_SUFFIX = '.bak'
# Minimalny odstup medzi zalohami - onSettingsChanged strieli pri kazdom
# setSetting (tokeny, speedtest, ...), netreba kopirovat zakazdym
BACKUP_MIN_INTERVAL = 30

_last_backup_time = 0


def _log(msg):
    xbmc.log('[{}] settings_backup: {}'.format(ADDON_ID, msg), xbmc.LOGINFO)


def _translate(path):
    try:
        import xbmcvfs
        return xbmcvfs.translatePath(path)
    except AttributeError:
        return xbmc.translatePath(path)


def settings_path():
    return _translate('special://profile/addon_data/{}/settings.xml'.format(ADDON_ID))


def backup_path():
    return settings_path() + BACKUP_SUFFIX


def is_valid_settings_file(path):
    """Subor existuje, nie je prazdny a je to XML s korenom <settings>."""
    try:
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            return False
        root = ET.parse(path).getroot()
        return root.tag == 'settings'
    except Exception:
        return False


def backup_settings(force=False):
    """Skopiruje validny settings.xml do zalohy. Vrati True pri uspechu.

    Nevalidny subor sa NIKDY nezalohuje - existujuca zaloha ostava
    poslednym znamym dobrym stavom.
    """
    global _last_backup_time
    if not force and (time.time() - _last_backup_time) < BACKUP_MIN_INTERVAL:
        return False
    src = settings_path()
    if not is_valid_settings_file(src):
        _log('settings.xml nie je validny, zaloha sa nevytvara')
        return False
    bak = backup_path()
    tmp = bak + '.tmp'
    try:
        # Kopirujeme do docasneho suboru a overime ho EST PRED prepisanim
        # zalohy - poskodena kopia (orezany zapis, plny disk) tak nikdy
        # neznici poslednu znamu dobru zalohu
        shutil.copy2(src, tmp)
        if not is_valid_settings_file(tmp):
            _log('kopia zalohy nie je validna, povodna zaloha ostava')
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False
        os.replace(tmp, bak)  # atomicky presun
        _last_backup_time = time.time()
        return True
    except Exception as e:
        _log('zaloha zlyhala: {}'.format(e))
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def restore_settings():
    """Obnovi settings.xml z validnej zalohy. Vrati True pri uspechu."""
    bak = backup_path()
    if not is_valid_settings_file(bak):
        _log('zaloha neexistuje alebo nie je validna, niet z coho obnovit')
        return False
    try:
        shutil.copy2(bak, settings_path())
        _log('settings.xml OBNOVENY zo zalohy')
        return True
    except Exception as e:
        _log('obnova zlyhala: {}'.format(e))
        return False


def ensure_settings_integrity():
    """Startup kontrola: poskodeny settings.xml obnovi zo zalohy,
    validny zazalohuje. Vrati 'restored' / 'backed_up' / 'noop'.

    Volat na zaciatku service.py PRED prvym citanim nastaveni -
    nove xbmcaddon.Addon() instancie si potom nacitaju obnoveny subor.
    """
    sp = settings_path()
    if is_valid_settings_file(sp):
        backup_settings(force=True)
        return 'backed_up'

    if os.path.exists(sp):
        _log('settings.xml je POSKODENY (size={})'.format(
            os.path.getsize(sp) if os.path.isfile(sp) else 'N/A'))
    else:
        _log('settings.xml neexistuje')

    if restore_settings():
        return 'restored'
    return 'noop'
