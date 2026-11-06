import xbmcvfs
import xbmcgui
import xbmc
import datetime
import time
import sqlite3
import threading
import zlib
from json import loads, dumps

from resources.lib.common.logger import debug
from resources.lib.constants import ADDON


# Housekeeping kľúče MUSIA byť namespacované. Bežíme nad globálnym oknom
# Window(10000), ktoré zdieľajú VŠETKY doplnky. Samostatný doplnok
# script.module.simplecache používa presne 'simplecache.clean.lastexecuted' a
# 'simplecachecleanbusy' a hodnotu lastexecuted vyhodnocuje cez Python-eval na
# repr(datetime) a pripočíta timedelta. Náš vendored cache tam píše int-timestamp
# (str(int)), čo cudziemu simplecache spôsobí `TypeError: int + datetime.timedelta`
# a zhodí napr. script.embuary.info. Namespacovaním sa s cudzími globálmi nikdy
# neprekrývame.
_WIN_CLEAN_LAST_KEY = 'plugin.video.stream-cinema.simplecache.clean.lastexecuted'
_WIN_CLEAN_BUSY_KEY = 'plugin.video.stream-cinema.simplecachecleanbusy'


class SimpleCache(object):
    """simple stateless caching system for Kodi"""
    enable_mem_cache = True
    global_checksum = None
    _exit = False
    _auto_clean_interval = datetime.timedelta(hours=4)
    _win = None
    _busy_tasks = []
    _database = None
    _enabled = True
    # shared sqlite connection across all SimpleCache instances/threads
    # (avoid opening/closing a fresh connection on every _execute_sql call)
    _static_connection = None
    _connection_lock = threading.Lock()

    def __init__(self, enabled=True):
        """Initialize our caching class"""
        self._enabled = enabled
        self._win = xbmcgui.Window(10000)
        self._monitor = xbmc.Monitor()
        self.check_cleanup()
        self._log_msg("Initialized")

    def close(self):
        """tell any tasks to stop immediately (as we can be called multithreaded) and cleanup objects"""
        self._exit = True
        # wait for all tasks to complete
        while self._busy_tasks and not self._monitor.abortRequested():
            xbmc.sleep(25)
        del self._win
        del self._monitor
        self._log_msg("Closed")

    def __del__(self):
        """make sure close is called"""
        if not self._exit:
            self.close()

    def get(self, endpoint, checksum=""):
        """
            get object from cache and return the results
            endpoint: the (unique) name of the cache object as reference
            checkum: optional argument to check if the checksum in the cacheobject matches the checkum provided
        """
        if self._enabled is not True:
            return None
        checksum = self._get_checksum(checksum)
        cur_time = self._get_timestamp(datetime.datetime.now())
        result = None
        # 1: try memory cache first
        if self.enable_mem_cache:
            result = self._get_mem_cache(endpoint, checksum, cur_time)

        # 2: fallback to _database cache
        if result is None:
            result = self._get_db_cache(endpoint, checksum, cur_time)

        return result

    def set(self, endpoint, data, checksum="", expiration=datetime.timedelta(seconds=3600)):
        """
            set data in cache
        """
        task_name = "set.%s" % endpoint
        self._busy_tasks.append(task_name)
        checksum = self._get_checksum(checksum)
        expires = self._get_timestamp(datetime.datetime.now() + expiration)

        # memory cache: write to window property
        if self.enable_mem_cache and not self._exit:
            self._set_mem_cache(endpoint, checksum, expires, data)

        # db cache
        if not self._exit:
            self._set_db_cache(endpoint, checksum, expires, data)

        # remove this task from list
        self._busy_tasks.remove(task_name)

    def check_cleanup(self):
        """check if cleanup is needed - public method, may be called by calling addon"""
        cur_time = datetime.datetime.now()
        lastexecuted = self._win.getProperty(_WIN_CLEAN_LAST_KEY)
        if not lastexecuted:
            self._win.setProperty(_WIN_CLEAN_LAST_KEY, str(self._get_timestamp(cur_time)))
        else:
            try:
                cleanup_needed = (
                    int(lastexecuted) + self._auto_clean_interval.total_seconds()
                    < self._get_timestamp(cur_time)
                )
            except (ValueError, TypeError):
                # old repr(datetime) format or corrupt value - treat as cleanup due
                cleanup_needed = True
                self._win.setProperty(_WIN_CLEAN_LAST_KEY, str(self._get_timestamp(cur_time)))
            if cleanup_needed:
                # cleanup needed...
                self._do_cleanup()

    def _get_mem_cache(self, endpoint, checksum, cur_time):
        """
            get cache data from memory cache
            we use window properties because we need to be stateless
        """
        result = None
        cachedata = self._win.getProperty(endpoint)

        if cachedata:
            try:
                cachedata = loads(cachedata)
            except (ValueError, TypeError):
                # old repr format or corrupt value - treat as cache miss
                return None
            expires = cachedata[0]

            # Robustná kontrola: Detekcia časového posunu
            # Ak je expires výrazne v budúcnosti (>24h), možný časový posun
            MAX_REASONABLE_CACHE = 86400  # 24 hodín
            time_diff = expires - cur_time

            if time_diff < 0:
                # Cache expirovala - normálne
                return None
            elif time_diff > MAX_REASONABLE_CACHE:
                # Cache je podozrivo ďaleko v budúcnosti - možný časový posun
                self._log_msg("Cache %s has suspicious expiry (diff: %ds), invalidating" % (endpoint, time_diff))
                return None
            elif expires > cur_time:
                # Cache je platná
                if not checksum or checksum == cachedata[2]:
                    result = cachedata[1]
        return result

    def _set_mem_cache(self, endpoint, checksum, expires, data):
        """
            window property cache as alternative for memory cache
            usefull for (stateless) plugins
        """
        cachedata = (expires, data, checksum)
        cachedata_str = dumps(cachedata)
        self._win.setProperty(endpoint, cachedata_str)

    def _get_db_cache(self, endpoint, checksum, cur_time):
        """get cache data from sqllite _database"""
        result = None
        query = "SELECT expires, data, checksum FROM simplecache WHERE id = ?"
        cache_data = self._execute_sql(query, (endpoint,))
        if cache_data:
            cache_data = cache_data.fetchone()
            if cache_data:
                expires = cache_data[0]

                # Robustná kontrola: Detekcia časového posunu
                MAX_REASONABLE_CACHE = 86400  # 24 hodín
                time_diff = expires - cur_time

                if time_diff < 0:
                    # Cache expirovala
                    return None
                elif time_diff > MAX_REASONABLE_CACHE:
                    # Podozrivá cache - možný časový posun
                    self._log_msg("DB Cache %s has suspicious expiry (diff: %ds), invalidating" % (endpoint, time_diff))
                    return None
                elif expires > cur_time:
                    # Cache je platná
                    if not checksum or cache_data[2] == checksum:
                        try:
                            result = loads(cache_data[1])
                        except (ValueError, TypeError):
                            # old repr format or corrupt value - treat as cache miss
                            return None
                        # also set result in memory cache for further access
                        if self.enable_mem_cache:
                            self._set_mem_cache(endpoint, checksum, cache_data[0], result)
        return result

    def _set_db_cache(self, endpoint, checksum, expires, data):
        """ store cache data in _database """
        query = "INSERT OR REPLACE INTO simplecache( id, expires, data, checksum) VALUES (?, ?, ?, ?)"
        data = dumps(data)
        self._execute_sql(query, (endpoint, expires, data, checksum))

    def _do_cleanup(self):
        """perform cleanup task"""
        if self._exit or self._monitor.abortRequested():
            return
        self._busy_tasks.append(__name__)
        cur_time = datetime.datetime.now()
        cur_timestamp = self._get_timestamp(cur_time)
        self._log_msg("Running cleanup...")
        if self._win.getProperty(_WIN_CLEAN_BUSY_KEY):
            return
        self._win.setProperty(_WIN_CLEAN_BUSY_KEY, "busy")

        query = "SELECT id, expires FROM simplecache"
        for cache_data in self._execute_sql(query).fetchall():
            cache_id = cache_data[0]
            cache_expires = cache_data[1]

            if self._exit or self._monitor.abortRequested():
                return

            # always cleanup all memory objects on each interval
            self._win.clearProperty(cache_id)

            # clean up db cache object only if expired
            if cache_expires < cur_timestamp:
                query = 'DELETE FROM simplecache WHERE id = ?'
                self._execute_sql(query, (cache_id,))
                self._log_msg("delete from db %s" % cache_id)

        # compact db
        self._execute_sql("VACUUM")

        # remove task from list
        self._busy_tasks.remove(__name__)
        self._win.setProperty(_WIN_CLEAN_LAST_KEY, str(self._get_timestamp(cur_time)))
        self._win.clearProperty(_WIN_CLEAN_BUSY_KEY)
        self._log_msg("Auto cleanup done")

    def _get_database(self):
        """get reference to our shared sqllite _database connection - performs basic integrity check.

        The connection is kept open and shared (class-level) across all SimpleCache
        instances/threads instead of being reopened on every call. If the shared
        connection turns out to be stale/closed, it is discarded and reopened here
        (same reconnect-on-stale pattern as Sqlite._get_conn in common/storage.py),
        preserving the existing corrupt-_database recreate logic below.
        """
        if SimpleCache._static_connection is not None:
            try:
                SimpleCache._static_connection.cursor()
                return SimpleCache._static_connection
            except sqlite3.Error:
                # stale/closed connection - discard and reconnect below
                SimpleCache._static_connection = None

        dbpath = ADDON.getAddonInfo('profile')
        dbfile = xbmcvfs.translatePath("%s/simplecache.db" % dbpath)

        if not xbmcvfs.exists(dbpath):
            xbmcvfs.mkdirs(dbpath)
        try:
            connection = sqlite3.connect(dbfile, timeout=30, isolation_level=None, check_same_thread=False)
            connection.execute('SELECT * FROM simplecache LIMIT 1')
            SimpleCache._static_connection = connection
            return SimpleCache._static_connection
        except Exception as error:
            # our _database is corrupt or doesn't exist yet, we simply try to recreate it
            if xbmcvfs.exists(dbfile):
                xbmcvfs.delete(dbfile)
            try:
                connection = sqlite3.connect(dbfile, timeout=30, isolation_level=None, check_same_thread=False)
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS simplecache(
                    id TEXT UNIQUE, expires INTEGER, data TEXT, checksum INTEGER)""")
                SimpleCache._static_connection = connection
                return SimpleCache._static_connection
            except Exception as error:
                self._log_msg("Exception while initializing _database: %s" % str(error), xbmc.LOGWARNING)
                self.close()
                return None

    def _execute_sql(self, query, data=None):
        """little wrapper around execute and executemany to just retry a db command if db is locked"""
        retries = 0
        result = None
        error = None
        # use the shared _database connection, serialized with a lock since it is
        # reused across threads (check_same_thread=False on the underlying connection)
        with SimpleCache._connection_lock:
            with self._get_database() as _database:
                while not retries == 10 and not self._monitor.abortRequested():
                    if self._exit:
                        return None
                    try:
                        if isinstance(data, list):
                            result = _database.executemany(query, data)
                        elif data:
                            result = _database.execute(query, data)
                        else:
                            result = _database.execute(query)
                        return result
                    except sqlite3.OperationalError as ex:
                        # bind the message to a function-scoped name: in Python 3
                        # the `as ex` target is unbound when the except block ends,
                        # so it must not be referenced after the loop
                        error = str(ex)
                        if "database is locked" in error:
                            self._log_msg("retrying DB commit...")
                            retries += 1
                            self._monitor.waitForAbort(0.5)
                        else:
                            break
                    except Exception as ex:
                        error = str(ex)
                        break
                self._log_msg("_database ERROR ! -- %s" % str(error), xbmc.LOGWARNING)
        return None

    @staticmethod
    def _log_msg(msg, loglevel=xbmc.LOGDEBUG):
        """helper to send a message to the kodi log"""
        debug("CACHE {}".format(msg))

    @staticmethod
    def _get_timestamp(date_time):
        """Converts a datetime object to unix timestamp"""
        return int(time.mktime(date_time.timetuple()))

    def _get_checksum(self, stringinput):
        """get int checksum from string"""
        if not stringinput and not self.global_checksum:
            return 0
        if self.global_checksum:
            stringinput = "%s-%s" % (self.global_checksum, stringinput)
        else:
            stringinput = str(stringinput)
        # crc32 masked to unsigned range: deterministic across processes/PY2-PY3
        # (never use hash() - it is salted per-process in PY3)
        return zlib.crc32(stringinput.encode('utf-8')) & 0xffffffff


def use_cache(cache_days=14):
    """
        wrapper around our simple cache to use as decorator
        Usage: define an instance of SimpleCache with name "cache" (self.cache) in your class
        Any method that needs caching just add @use_cache as decorator
        NOTE: use unnamed arguments for calling the method and named arguments for optional settings
    """

    def decorator(func):
        """our decorator"""

        def decorated(*args, **kwargs):
            """process the original method and apply caching of the results"""
            method_class = args[0]
            method_class_name = method_class.__class__.__name__
            cache_str = "%s.%s" % (method_class_name, func.__name__)
            # cache identifier is based on positional args only
            # named args are considered optional and ignored
            for item in args[1:]:
                cache_str += u".%s" % item
            cache_str = cache_str.lower()
            cachedata = method_class.cache.get(cache_str)
            global_cache_ignore = False
            try:
                global_cache_ignore = method_class.ignore_cache
            except Exception:
                pass
            if cachedata is not None and not kwargs.get("ignore_cache", False) and not global_cache_ignore:
                return cachedata
            else:
                result = func(*args, **kwargs)
                method_class.cache.set(cache_str, result, expiration=datetime.timedelta(days=cache_days))
                return result

        return decorated

    return decorator
