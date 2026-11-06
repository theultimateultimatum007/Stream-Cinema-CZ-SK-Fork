from __future__ import print_function, unicode_literals

from json import dumps
from time import time

from resources.lib.api.sc import Sc
from resources.lib.common.storage import Storage, KodiDb
from resources.lib.common.logger import debug
from resources.lib.kodiutils import hexlify


class List(object):
    def __init__(self, name, max_items=None, sorted=True):
        self.name = name
        self.max_items = max_items
        self.sorted = sorted
        self.storage = Storage(name)
        self.data = self.storage.get('list')
        if not self.data:
            self.data = []
        # debug('List data({}) {}'.format(self.name, self.data))

    def remove(self):
        self.data = []
        self.set(self.data)

    def get(self):
        # debug('List get data {}')
        return self.data

    def __len__(self):
        return len(self.data)

    def add(self, item, remove_only=False):
        # debug('List add {} | {}'.format(item, remove_only))

        if item is None:
            debug('List ignore None item')
            return

        if self.sorted is True and item in self.data \
                or remove_only is True:
            # debug('--- remove {}'.format(item))
            try:
                self.data.remove(item)
            except:
                pass

        if remove_only is False \
                or (self.sorted is False and item not in self.data and remove_only is False):
            self.data.insert(0, item)
            # debug('List insert item')

        if self.max_items:
            remove = len(self.data) - self.max_items
            if remove > 0:
                # debug('List to remove {}'.format(remove))
                for i in range(remove):
                    self.data.pop()
        # debug('List end add {}'.format(self.data))
        self.set(self.data)

    def set(self, data):
        # debug('List set {}'.format(data))
        self.storage['list'] = data


class SCKODIItem(Storage):
    SCROBBLE_START = 'start'
    SCROBBLE_PAUSE = 'pause'
    SCROBBLE_STOP = 'stop'
    LAST_EP_KEY = 'last_ep'
    ITEM_NAME = 'SCKODIItem'
    _watched = None

    def __init__(self, name, series=None, episode=None, trakt=None):
        super(SCKODIItem, self).__init__('{}-{}'.format(self.ITEM_NAME, name))
        if series is not None:
            item = '{}/{}/{}'.format(name, series, episode)
        else:
            item = '{}'.format(name)
        kodi_path = hexlify('/Play/{}'.format(item))

        if SCKODIItem._watched is None:
            SCKODIItem._watched = List('all_watched')
            # debug('__: {}'.format(SCKODIItem._watched.get()))

        self.watched = SCKODIItem._watched
        self.item = item
        self.name = name
        self.series = series
        self.episode = episode
        self.trakt = trakt
        self.kodi_path = '%{}%'.format(kodi_path)
        self.kodi_db = None
        self.kodi_db = KodiDb()

    def _set(self, key, val):
        if val is None:
            del self[self._key(key)]
        else:
            self[self._key(key)] = val

    def _get(self, key):
        return self.get(self._key(key))

    def _key(self, key):
        if self.series is not None:
            key = '{}:{}:{}'.format(key, self.series, self.episode)
        return key

    def set_watched(self, percent):
        self._set('watched', percent)

    def get_watched(self):
        return self._get('watched')

    def set_last_played(self, percent):
        self._set('last_played', percent)

    def get_last_played(self):
        return self._get('last_played')

    def get_last_ep(self):
        last = self[self.LAST_EP_KEY]
        if last is not None:
            last = self[self.LAST_EP_KEY].split('x')
        else:
            last = (1, 0)
        # debug('posielam LAST_EP {}'.format(last))
        return last

    def set_last_ep(self, s, e, last_time=None, allow_api_calls=True):
        self[self.LAST_EP_KEY] = '{}x{}'.format(s, e)
        ne = Storage('nextep')

        try:
            # OPTIMALIZÁCIA: Skús najprv EpisodeCache (bez API call)
            from resources.lib.services.episode_cache import episode_cache

            next_ep = episode_cache.get_next_episode(self.name, s, e, allow_lazy_load=allow_api_calls)

            if next_ep:
                # Cache HIT - máme ďalšiu epizódu bez API callu!
                next_season, next_episode = next_ep
                debug('EpisodeCache HIT: Next episode for {}x{} is {}x{} (no API call)'.format(
                    s, e, next_season, next_episode))

                # DÔLEŽITÉ: Storage ukladá AKTUÁLNU epizódu (nie ďalšiu!)
                # Up Next plugin si ďalšiu epizódu vypočíta sám z EpisodeCache
                new = {
                    's': s,  # Aktuálna sezóna
                    'e': e,  # Aktuálna epizóda
                    't': int(time()) if last_time is None else last_time,
                }
                ne[self.name] = new
                debug('nastavujem LAST_EP na: {} pre {} (from cache)'.format(self[self.LAST_EP_KEY], self.name))
                return

            # Cache MISS - fallback na API (ak je povolený)
            if not allow_api_calls:
                debug('EpisodeCache MISS for {}x{}, API calls DISABLED - skipping'.format(s, e))
                # Len uložíme aktuálnu epizódu bez kontroly ďalšej
                debug('nastavujem LAST_EP na: {} pre {} (bez API call)'.format(self[self.LAST_EP_KEY], self.name))
                return

            debug('EpisodeCache MISS for {}x{}, trying API...'.format(s, e))

            info = Sc.up_next(self.name, s, e)
            if 'error' in info or ('info' in info and info.get('info') is None):
                debug('nemame data k next EP')
                del (ne[self.name])
                return

            new = {
                's': s,
                'e': e,
                't': int(time()) if last_time is None else last_time,
            }
            ne[self.name] = new
        except:
            import traceback
            debug('ERR: {}'.format(traceback.format_exc()))
            del(ne[self.name])
        debug('nastavujem LAST_EP na: {} pre {}'.format(self[self.LAST_EP_KEY], self.name))

    def set_play_count(self, times, from_kodi_player=False):
        self._set('play_count', times)

        if times:
            self._watched.add(self.item)
        else:
            self._watched.add(self.item, True)

        if self.series:
            key = 'series:{}'.format(self.series)
            series = self.data.get(key, {})
            if times:
                series.update({self.episode: True})
            else:
                del series[self.episode]
            self.data[key] = series

        # if self.kodi_db:
        #     self.kodi_db.set_watched_path(self.kodi_path, times)

        if from_kodi_player and self.series:
            self.set_last_ep(self.series, self.episode)

        # Volaj Trakt API len ak to NIE je z KODI playera
        # Pri prehravani uz scrobble STOP pridal do Trakt history
        from resources.lib.trakt.Trakt import trakt
        if self.trakt is not None and trakt.is_enabled() and not from_kodi_player:
            trakt.set_watched(self.trakt, times, season=self.series, episode=self.episode)

            # OPTIMALIZÁCIA: Auto-markérovanie celej sezóny
            # Po označení epizódy zkontroluj, či sú všetky epizódy v sezóne videné
            if times and self.series:
                self.check_and_mark_season_complete(trakt)

    def check_and_mark_season_complete(self, trakt_api):
        """
        Skontroluje, či sú všetky epizódy v sezóne označené ako videné.
        Ak áno, označí celú sezónu v Trakt.
        """
        try:
            # Získaj info o sezóne z Trakt API
            season_info = trakt_api.get_season_info(self.trakt, self.series)
            if not season_info:
                debug('Could not get season info for show={}, season={}'.format(self.trakt, self.series))
                return

            # Počet epizód v sezóne (bez špeciálnych epizód)
            total_episodes = len([ep for ep in season_info if ep.get('number', 0) > 0])
            debug('Season {} has {} episodes'.format(self.series, total_episodes))

            # Získaj zoznam videných epizód z lokálneho storage
            key = 'series:{}'.format(self.series)
            watched_episodes = self.data.get(key, {})
            watched_count = len(watched_episodes)

            debug('Season {} has {}/{} episodes watched'.format(
                self.series, watched_count, total_episodes))

            # Ak sú všetky epizódy videné, označ celú sezónu
            if watched_count >= total_episodes:
                debug('All episodes watched! Marking season {} as complete'.format(self.series))
                trakt_api.mark_season_watched(self.trakt, self.series)

                # Ulož flag, že sezóna bola označená, aby sme to nerobili opakovane
                season_key = 'season_marked:{}:{}'.format(self.trakt, self.series)
                self.data[season_key] = True
                self.save()
        except:
            import traceback
            debug('Error checking season complete: {}'.format(traceback.format_exc()))

    def scrobble(self, percent, action):
        from resources.lib.trakt.Trakt import trakt
        if self.trakt is not None and trakt.is_enabled():
            ret = trakt.scroble(self.trakt, self.series, self.episode, percent, action)
            debug('scrobble resp: {}'.format(ret))

    def get_play_count(self):
        if self.item in self._watched.get():
            return 1

        pc = self._get('play_count')
        play_count = int(pc) if pc is not None else 0
        if pc is not None:
            self._watched.add(self.item)
            return play_count

        # if self.kodi_db:
        #     res = self.kodi_db.get_watched_path(self.kodi_path)
        #     if res and res[3] is not None:
        #         kodi_play_count = int(res[3])
        #         if kodi_play_count > play_count:
        #             play_count = kodi_play_count
        #         self._watched.add(self.item)
        #         self.set_play_count(play_count)
        #     else:
        #         self.set_play_count(0)

        return play_count

        # if kodi_play_count is not None and kodi_play_count > 0 and (
        #         play_count is None or play_count == 0) and kodi_play_count != play_count:
        #     # debug('setujem item ako videny')
        #     self.set_play_count(kodi_play_count)
        #     play_count = kodi_play_count
        #     # if self.trakt:
        #     #     from resources.lib.trakt.Trakt import trakt
        #     #     trakt.set_watched(trid=self.trakt, times=kodi_play_count, season=self.series, episode=self.episode)
        # elif play_count != kodi_play_count:
        #     # debug('setujem item ako NE videny {}/{}'.format(kodi_play_count, play_count))
        #     self.set_play_count(kodi_play_count)
        #     # if self.trakt:
        #     #     from resources.lib.trakt.Trakt import trakt
        #     #     trakt.set_watched(trid=self.trakt, times=kodi_play_count, season=self.series, episode=self.episode)
        #     play_count = kodi_play_count
        #
        # # debug('return play count: {}'.format(play_count))
        # return play_count


