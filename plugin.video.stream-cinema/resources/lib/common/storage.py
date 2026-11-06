# -*- coding: utf-8 -*-
from __future__ import print_function, unicode_literals

import os
import re
import sqlite3
import time
from json import loads, dumps

from resources.lib.constants import ADDON, KodiDbMap, ADDON_ID, SC
from resources.lib.common.logger import debug
from resources.lib.kodiutils import translate_path, get_skin_name
from resources.lib.system import SYSTEM_VERSION

import xbmcvfs
from xbmcgui import Window

checked = False
_storage_cache = {}
_connection_cache = {}


def find_db_version(db_basename, fallback_version=None):
    """
    Automaticky nájde verziu Kodi databázy.

    Najprv skúsi použiť fallback_version (z KodiDbMap), ak je poskytnutá.
    Ak súbor neexistuje alebo fallback nie je zadaný, automaticky nájde
    najnovší databázový súbor s daným prefixom.

    Args:
        db_basename: Prefix názvu DB (napr. 'Addons', 'MyVideos', 'Textures')
        fallback_version: Odporúčaná verzia z KodiDbMap (ak existuje)

    Returns:
        int: Číslo verzie databázy

    Raises:
        RuntimeError: Ak sa nepodarí nájsť žiadnu databázu
    """
    # 1. Skús fallback verziu (ak je zadaná)
    if fallback_version is not None:
        fallback_path = 'special://database/{}{}.db'.format(db_basename, fallback_version)
        if xbmcvfs.exists(translate_path(fallback_path)):
            debug('find_db_version: Using fallback version {} for {}'.format(fallback_version, db_basename))
            return fallback_version
        else:
            debug('find_db_version: Fallback version {} not found for {}, trying auto-detection'.format(
                fallback_version, db_basename))

    # 2. Auto-detekcia: nájdi najnovší súbor
    db_dir = translate_path('special://database/')

    if not xbmcvfs.exists(db_dir):
        raise RuntimeError('Database directory does not exist: {}'.format(db_dir))

    # Nájdi všetky súbory v database adresári
    dirs, files = xbmcvfs.listdir(db_dir)

    # Pattern pre názov databázy: BaseName + číslo + .db
    pattern = re.compile(r'^{}\s*(\d+)\.db$'.format(re.escape(db_basename)))

    versions = []
    for filename in files:
        match = pattern.match(filename)
        if match:
            version = int(match.group(1))
            versions.append(version)
            debug('find_db_version: Found {} version {}'.format(db_basename, version))

    if not versions:
        raise RuntimeError('No database file found matching pattern: {}<number>.db'.format(db_basename))

    # Vráť najvyššiu verziu
    max_version = max(versions)
    debug('find_db_version: Using auto-detected version {} for {}'.format(max_version, db_basename))
    return max_version


class Sqlite(object):
    def __init__(self, path):
        self._path = translate_path(path)
        self._connection = None
        # debug('db file: {}'.format(self._path))

    def _get_conn(self):
        if self._connection is None:
            self._connection = sqlite3.Connection(self._path, timeout=1, check_same_thread=False)
        try:
            self._connection.cursor()
        except sqlite3.ProgrammingError:
            self._connection = None
            return self._get_conn()
        return self._connection

    def execute(self, query, *args):
        # debug('SQL: {} <- {}'.format(query, args))
        # debug('SQL')
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute(query, args)
            return c


class KodiAddonsDb:
    def __init__(self):
        fallback_version = KodiDbMap.Addons.get(SYSTEM_VERSION)
        db_version = find_db_version('Addons', fallback_version)
        path = 'special://database/Addons{}.db'.format(db_version)
        self._db = Sqlite(path)

    def check_repo(self):
        query = 'select id from repo where id in (' \
                'select idRepo from addonlinkrepo where idAddon in (' \
                'select id from addons where addonID=?))'
        res = self._db.execute(query, ADDON_ID).fetchone()
        if res is not None:
            return True
        return False

    def enable_auto_update(self):
        if not self.check_repo():
            # Lazy import - storage (infra vrstva) nesmie importovat GUI
            # na urovni modulu, vznikal by cyklicky import cez gui/__init__
            from resources.lib.gui.dialog import dok
            from resources.lib.language import Strings
            dok(Strings.txt(Strings.SYSTEM_H1), Strings.txt(Strings.SYSTEM_NOT_INSTALLED_FROM_REPOSITORY))
        query = 'delete from update_rules where addonID=?'
        self._db.execute(query, ADDON_ID)


class KodiDb:
    _static_db = None

    def __init__(self):
        fallback_version = KodiDbMap.MyVideos.get(SYSTEM_VERSION)
        db_version = find_db_version('MyVideos', fallback_version)
        path = 'special://database/MyVideos{}.db'.format(db_version)
        if KodiDb._static_db is None:
            KodiDb._static_db = Sqlite(path)
        self._db = KodiDb._static_db
        # debug('tables: {}'.format(self._db.execute('SELECT name FROM sqlite_master WHERE type =\'table\'').fetchall()))

    def get_watched_path(self, path):
        try:
            sql = 'select f.* ' \
                  'from files f join path p on p.idPath = f.idPath ' \
                  'where f.strfilename like ? or p.strpath like ?'
            return self._db.execute(sql, path, path).fetchone()
        except:
            return None

    def set_watched_path(self, path, times):
        res = self.get_watched_path(path)
        if res and res[0]:
            # debug('MAME PATH: {}'.find(path))
            sql = 'update files set playcount=? where idfile=?'
            self._db.execute(sql, times, res[0])
        else:
            debug('Nemame PATH: {}'.format(path))
            pass

    def get_watched(self):
        try:
            query = 'select p.strPath || f.strFilename ' \
                    'from files f join path p on p.idPath = f.idPath ' \
                    'where f.playCount > 0'
            return self._db.execute(query).fetchall()
        except:
            return None


class TexturesDb:
    def __init__(self):
        fallback_version = KodiDbMap.Textures.get(SYSTEM_VERSION)
        db_version = find_db_version('Textures', fallback_version)
        path = 'special://database/Textures{}.db'.format(db_version)
        self._db = Sqlite(path)

    def clean(self):
        # Lazy import - storage (infra vrstva) nesmie importovat GUI
        # na urovni modulu, vznikal by cyklicky import cez gui/__init__
        from resources.lib.gui.dialog import dprogressgb
        zoznam = self.to_clean()
        total = len(zoznam)
        d = dprogressgb()
        d.create('mazanie', 'mazem')
        for pos, i in enumerate(zoznam):
            p = int(pos/total*100)
            debug('item: {}/{} {}'.format(pos, total, TexturesDb.file_name(i)))
            self.remove_item(i)
            d.update(p, 'mazanie', 'mazem {}'.format(i[1]))
        d.close()

    @staticmethod
    def file_name(item):
        return translate_path("special://masterprofile/Thumbnails/{}".format(item[1]))

    def remove_item(self, item):
        xbmcvfs.delete(TexturesDb.file_name(item))
        self._db.execute('delete from sizes where idtexture=?', item[0])
        self._db.execute('delete from texture where id=?', item[0])

    def to_clean(self):
        q = "SELECT s.idtexture, t.cachedurl, s.lastusetime FROM sizes AS s JOIN texture t ON (t.id=s.idtexture) WHERE lastusetime <= DATETIME('now', '-1 month') ORDER BY 3 ASC"
        return self._db.execute(q).fetchall()


class Storage(object):
    _sql_create = (
        'CREATE TABLE IF NOT EXISTS storage '
        '('
        '  item_key VARCHAR(255) PRIMARY KEY ,'
        '  item_value BLOB'
        ')'
    )
    _sql_set = 'INSERT OR REPLACE INTO storage (item_key, item_value) VALUES (?, ?)'
    _sql_get = 'SELECT item_value FROM storage WHERE item_key = ?'
    _sql_del = 'DELETE FROM storage WHERE item_key = ?'
    _data = {}
    _static_db = None

    def __init__(self, name):
        path = ADDON.getAddonInfo("profile")
        if not xbmcvfs.exists(path):
            debug("storage path: {}".format(repr(path)))
            xbmcvfs.mkdir(path)
        path = os.path.join(path, 'storage.db')
        if Storage._static_db is None:
            Storage._static_db = Sqlite(path=path)
        self._db = Storage._static_db
        global checked
        self._data = {}
        self._last_saved = {}
        self._name = name
        if not checked:
            checked = True
            self._db.execute(self._sql_create)
        self.load()

    def __setitem__(self, key, value):
        if value is not None:
            self._data[key] = value
        else:
            if key in self._data:
                del self._data[key]
        self.save()

    def __getitem__(self, item):
        return self._data.get(item)

    def __delitem__(self, key):
        if key in self._data:
            del self._data[key]
        self.save()

    def get(self, name):
        if name in self._data:
            return self._data[name]
        return None

    def update(self, up):
        debug('updatujem {} o {}'.format(self._name, up))
        self._data.update(up)
        self.save()

    def save(self):
        # if self._data == self._last_saved:
        #     debug('stare aj nove data su rovnake, neupdatujem {}'.format(self._name))
        #     return
        self._last_saved = self._data
        self._db.execute(self._sql_set, '{}'.format(self._name), '{}'.format(dumps(self._data)))
        _storage_cache[self._name] = self._data

    def load(self, force=False):
        # debug('name {}'.format(self._name))
        if force is False and self._name in _storage_cache:
            self._data = _storage_cache.get(self._name)
            self._last_saved = self._data
            return
        # debug('storage cache: {}'.format(_storage_cache))
        try:
            val = self._db.execute(self._sql_get, self._name).fetchone()
            # debug('load: {}'.format(val))
            self._data = loads(val[0])
        except:
            self._data = {}
        _storage_cache[self._name] = self._data
        self._last_saved = self._data
        # debug('loaded data {}'.format(self._data))

    @property
    def data(self):
        return self._data


# ---------------------------------------------------------------------------
# Cross-process dirty-marker (Kodi Window(10000) property, zdieľané medzi
# plugin a service procesmi - rovnaký IPC vzor ako menu_cache_server.py).
#
# KONTRAKT: každý PLUGIN-procesový writer storage namespace, ktorý má
# service-side reader s force-reload gatingom (load(True) len pri zmene),
# MUSÍ zavolať mark_dirty(name) HNEĎ PO save() (write-then-mark poradie).
# Service-lokálne self-writes (zápisy, ktoré si service robí sám na svojich
# dátach, napr. vyčistenie vlastného timestampu) NESMÚ volať mark_dirty -
# tie sa v rámci toho istého procesu prejavia cez modul-globálny
# _storage_cache (load(force=False) resync), nie cez marker.
# ---------------------------------------------------------------------------

def mark_dirty(name):
    """Označí storage namespace `name` ako zmenený (bump cross-process marker)."""
    try:
        Window(10000).setProperty('sc.dirty.{}'.format(name), '{}'.format(time.time()))
    except Exception:
        debug('mark_dirty error for {}'.format(name))


def get_dirty(name):
    """Vráti aktuálnu hodnotu dirty markera pre storage namespace `name`."""
    try:
        return Window(10000).getProperty('sc.dirty.{}'.format(name))
    except Exception:
        return ''


class KodiViewModeDb:
    def __init__(self):
        fallback_version = KodiDbMap.ViewModes.get(SYSTEM_VERSION)
        db_version = find_db_version('ViewModes', fallback_version)
        path = 'special://database/ViewModes{}.db'.format(db_version)
        self._db = Sqlite(path)

    def get_sort(self, url):
        query = 'select sortMethod, sortOrder from view where path=? and skin=?'
        return self._db.execute(query, url, get_skin_name()).fetchone()


class WatchHistoryDb(object):
    """
    SQLite databáza pre watch history s optimalizovanou štruktúrou

    Výhody oproti file-based storage:
    - Rýchlejší prístup k dátam (indexované vyhľadávanie)
    - ACID compliance
    - Lepšia integrita dát
    - Možnosť komplexných queries
    - Migrácia z JSON BLOB do proper tabuľky
    """

    _sql_create_table = '''
        CREATE TABLE IF NOT EXISTS watch_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id TEXT NOT NULL,
            series INTEGER,
            episode INTEGER,
            watched_time INTEGER,
            play_count INTEGER DEFAULT 0,
            last_played TEXT,
            trakt_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(item_id, series, episode)
        )
    '''

    _sql_create_idx_item = '''
        CREATE INDEX IF NOT EXISTS idx_item_id
        ON watch_history(item_id)
    '''

    _sql_create_idx_playcount = '''
        CREATE INDEX IF NOT EXISTS idx_play_count
        ON watch_history(play_count)
    '''

    _sql_create_idx_trakt = '''
        CREATE INDEX IF NOT EXISTS idx_trakt_id
        ON watch_history(trakt_id)
    '''

    _static_db = None

    def __init__(self):
        """Inicializuje databázu a vytvorí tabuľky"""
        path = ADDON.getAddonInfo("profile")
        if not xbmcvfs.exists(path):
            debug("WatchHistoryDb: Creating profile path: {}".format(repr(path)))
            xbmcvfs.mkdir(path)

        path = os.path.join(path, 'watch_history.db')

        if WatchHistoryDb._static_db is None:
            WatchHistoryDb._static_db = Sqlite(path=path)
            self._init_db()

        self._db = WatchHistoryDb._static_db

    def _init_db(self):
        """Vytvorí databázové tabuľky a indexy"""
        debug('WatchHistoryDb: Initializing database')
        self._db.execute(self._sql_create_table)
        self._db.execute(self._sql_create_idx_item)
        self._db.execute(self._sql_create_idx_playcount)
        self._db.execute(self._sql_create_idx_trakt)
        debug('WatchHistoryDb: Database initialized')

    def _make_key(self, item_id, series=None, episode=None):
        """Vytvorí unikátny kľúč pre item"""
        if series is not None and episode is not None:
            return (item_id, series, episode)
        return (item_id, None, None)

    def set_watched(self, item_id, watched_time, series=None, episode=None):
        """
        Uloží watched pozíciu (resume position)

        Args:
            item_id: ID položky
            watched_time: Čas v sekundách
            series: Číslo sezóny (pre seriály)
            episode: Číslo epizódy (pre seriály)
        """
        try:
            sql = '''
                INSERT INTO watch_history (item_id, series, episode, watched_time, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(item_id, series, episode)
                DO UPDATE SET watched_time=?, updated_at=CURRENT_TIMESTAMP
            '''
            self._db.execute(sql, item_id, series, episode, watched_time, watched_time)
            debug('WatchHistoryDb: Set watched {} s={} e={} time={}'.format(
                item_id, series, episode, watched_time))
        except Exception as e:
            debug('WatchHistoryDb: Error set_watched: {}'.format(e))

    def get_watched(self, item_id, series=None, episode=None):
        """
        Získa watched pozíciu

        Returns:
            int: Čas v sekundách alebo None
        """
        try:
            sql = '''
                SELECT watched_time FROM watch_history
                WHERE item_id = ? AND series IS ? AND episode IS ?
            '''
            result = self._db.execute(sql, item_id, series, episode).fetchone()
            return result[0] if result else None
        except Exception as e:
            debug('WatchHistoryDb: Error get_watched: {}'.format(e))
            return None

    def set_play_count(self, item_id, play_count, series=None, episode=None, trakt_id=None):
        """
        Nastaví play count

        Args:
            item_id: ID položky
            play_count: Počet prehratí
            series: Číslo sezóny (pre seriály)
            episode: Číslo epizódy (pre seriály)
            trakt_id: Trakt ID (optional)
        """
        try:
            sql = '''
                INSERT INTO watch_history (item_id, series, episode, play_count, trakt_id, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(item_id, series, episode)
                DO UPDATE SET play_count=?, trakt_id=?, updated_at=CURRENT_TIMESTAMP
            '''
            self._db.execute(sql, item_id, series, episode, play_count, trakt_id,
                           play_count, trakt_id)
            debug('WatchHistoryDb: Set play_count {} s={} e={} count={}'.format(
                item_id, series, episode, play_count))
        except Exception as e:
            debug('WatchHistoryDb: Error set_play_count: {}'.format(e))

    def get_play_count(self, item_id, series=None, episode=None):
        """
        Získa play count

        Returns:
            int: Počet prehratí alebo 0
        """
        try:
            sql = '''
                SELECT play_count FROM watch_history
                WHERE item_id = ? AND series IS ? AND episode IS ?
            '''
            result = self._db.execute(sql, item_id, series, episode).fetchone()
            return result[0] if result else 0
        except Exception as e:
            debug('WatchHistoryDb: Error get_play_count: {}'.format(e))
            return 0

    def set_last_played(self, item_id, last_played, series=None, episode=None):
        """
        Nastaví dátum posledného prehratia

        Args:
            item_id: ID položky
            last_played: Dátum (string vo formáte 'YYYY-MM-DD HH:MM:SS')
            series: Číslo sezóny (pre seriály)
            episode: Číslo epizódy (pre seriály)
        """
        try:
            sql = '''
                INSERT INTO watch_history (item_id, series, episode, last_played, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(item_id, series, episode)
                DO UPDATE SET last_played=?, updated_at=CURRENT_TIMESTAMP
            '''
            self._db.execute(sql, item_id, series, episode, last_played, last_played)
            debug('WatchHistoryDb: Set last_played {} s={} e={} date={}'.format(
                item_id, series, episode, last_played))
        except Exception as e:
            debug('WatchHistoryDb: Error set_last_played: {}'.format(e))

    def get_last_played(self, item_id, series=None, episode=None):
        """
        Získa dátum posledného prehratia

        Returns:
            str: Dátum alebo None
        """
        try:
            sql = '''
                SELECT last_played FROM watch_history
                WHERE item_id = ? AND series IS ? AND episode IS ?
            '''
            result = self._db.execute(sql, item_id, series, episode).fetchone()
            return result[0] if result else None
        except Exception as e:
            debug('WatchHistoryDb: Error get_last_played: {}'.format(e))
            return None

    def get_all_watched(self, limit=None):
        """
        Získa zoznam všetkých pozretých položiek

        Args:
            limit: Maximálny počet (optional)

        Returns:
            list: Zoznam tuples (item_id, series, episode, play_count, last_played)
        """
        try:
            sql = '''
                SELECT item_id, series, episode, play_count, last_played
                FROM watch_history
                WHERE play_count > 0
                ORDER BY updated_at DESC
            '''
            if limit:
                sql += ' LIMIT {}'.format(int(limit))

            return self._db.execute(sql).fetchall()
        except Exception as e:
            debug('WatchHistoryDb: Error get_all_watched: {}'.format(e))
            return []

    def get_season_watched_episodes(self, item_id, series):
        """
        Získa zoznam pozretých epizód pre danú sezónu

        Args:
            item_id: ID seriálu
            series: Číslo sezóny

        Returns:
            list: Zoznam čísel epizód
        """
        try:
            sql = '''
                SELECT episode FROM watch_history
                WHERE item_id = ? AND series = ? AND play_count > 0
                ORDER BY episode
            '''
            result = self._db.execute(sql, item_id, series).fetchall()
            return [row[0] for row in result if row[0] is not None]
        except Exception as e:
            debug('WatchHistoryDb: Error get_season_watched_episodes: {}'.format(e))
            return []

    def migrate_from_storage(self, storage_name):
        """
        Migruje dáta z file-based Storage do WatchHistoryDb

        Args:
            storage_name: Názov Storage objektu (napr. 'SCKODIItem-12345')
        """
        try:
            debug('WatchHistoryDb: Migrating from Storage: {}'.format(storage_name))
            old_storage = Storage(storage_name)

            # Prejdi všetky keys v storage
            migrated_count = 0
            for key, value in old_storage.data.items():
                # Parsuj key (môže byť 'watched:1:2' alebo 'play_count')
                if ':' in key:
                    parts = key.split(':')
                    field = parts[0]
                    series = int(parts[1]) if len(parts) > 1 else None
                    episode = int(parts[2]) if len(parts) > 2 else None

                    if field == 'watched':
                        self.set_watched(storage_name, value, series, episode)
                        migrated_count += 1
                    elif field == 'play_count':
                        self.set_play_count(storage_name, value, series, episode)
                        migrated_count += 1
                    elif field == 'last_played':
                        self.set_last_played(storage_name, value, series, episode)
                        migrated_count += 1

            debug('WatchHistoryDb: Migrated {} items from {}'.format(
                migrated_count, storage_name))

        except Exception as e:
            debug('WatchHistoryDb: Error during migration: {}'.format(e))


preferred_lang_list = Storage(SC.ITEM_PREFERRED_LANG)