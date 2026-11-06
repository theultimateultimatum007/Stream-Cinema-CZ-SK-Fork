from __future__ import absolute_import, division, print_function

import traceback

from resources.lib.api.sc import Sc
from resources.lib.common.lists import List, SCKODIItem
from resources.lib.common.logger import debug
from resources.lib.common.storage import Storage
from resources.lib.constants import ADDON_ID, ADDON
from resources.lib.gui import get_cond_visibility, home_win
from resources.lib.gui.dialog import dok, dprogress, dprogressgb
from resources.lib.gui.item import SCItem
from resources.lib.kodiutils import set_setting, get_setting_as_bool, set_setting_as_bool, get_setting
from resources.lib.services.player import player
from json import loads, dumps
from dataclasses import asdict
import time
from datetime import datetime, timezone
from xbmcaddon import Addon


time.strptime("1970-01-01 12:00:00", "%Y-%m-%d %H:%M:%S")

CHECK_SYNC = {
    'movies': ['watched_at', 'paused_at'],
    'episodes': ['watched_at', 'paused_at'],
}


class TraktAPI(object):
    __client_id = "bb21f3665cf0fa07f2a1a420ec6990317c49dee91af8e012cb836d66674e75c4"
    __client_secret = "fcc25d240d560326147cfb32fc0554868333dc954dc150ea2519f0a2a259f6e2"
    authDialog = None
    authPollProgress = None
    storage = {
        'sync.movies': Storage('trakt.sync.movies'),
        'sync.episodes': Storage('trakt.sync.episodes'),
        'watched.movies': List('trakt.watched.movies', sorted=False),
        'watched.shows': List('trakt.watched.shows', sorted=False),
        'last.activities': Storage('trakt.last.activities'),
    }
    authorization = {}
    initialized = False
    last_activities = None

    def __init__(self, force=False):
        debug("TRAKT Initializing.")

        # Import našich vlastných Trakt tried
        from resources.lib.trakt.http_client import TraktHttpClient, TraktToken
        from resources.lib.trakt.api import TraktApi

        # Ulož TraktToken do class namespace pre použitie v callbackoch
        self.TraktToken = TraktToken

        # Vytvor HTTP klient a API wrapper
        self.http_client = TraktHttpClient(
            client_id=self.__client_id,
            client_secret=self.__client_secret,
            token_callback=self._get_token,
            save_token_callback=self._save_token
        )
        self.api = TraktApi(self.http_client)

        from resources.lib.services.monitor import monitor
        self.monitor = monitor

        if not get_setting_as_bool('trakt.enabled'):
            debug('Trak nieje zapnuty')
            return

        self.initialize(force=force)

    def _get_token(self):
        """
        Callback pre získanie aktuálneho tokenu

        Returns:
            TraktToken alebo None
        """
        auth_json = get_setting('trakt.authorization')
        if not auth_json:
            return None

        try:
            auth_dict = loads(auth_json)
            return self.TraktToken(**auth_dict)
        except Exception as e:
            debug(f'TRAKT: Error loading token: {e}')
            return None

    def _save_token(self, token):
        """
        Callback pre uloženie nového tokenu

        Args:
            token: TraktToken inštancia
        """
        try:
            token_dict = asdict(token)
            token_json = dumps(token_dict)
            set_setting('trakt.authorization', token_json)
            self.authorization = token_dict  # Aktualizuj aj lokálnu kópiu

            # Ulož aj do HTTP klienta cache
            self.http_client.set_token(token)

            debug('TRAKT: Token saved')
        except Exception as e:
            debug(f'TRAKT: Error saving token: {e}')

    def initialize(self, force=False):
        """
        Inicializuje Trakt klienta

        Args:
            force: Ak True, vynutí re-autorizáciu (spustí login dialog)
        """
        auth_token = get_setting('trakt.authorization')

        if auth_token and not force:
            # Máme uložený token, načítame ho
            self.initialized = True
            self.authorization = loads(auth_token)
            # Načítaj token aj do HTTP klienta cache
            token = self._get_token()
            if token:
                self.http_client.set_token(token)
            debug('TRAKT: Loaded existing authorization')
        elif force:
            # Explicitný force - spusť login (manuálne volanie z používateľa)
            self.initialized = True
            self.login()
        else:
            # Token chýba, ale NEspúšťame automaticky login z background service
            debug('TRAKT: No authorization token found, skipping auto-login')
            debug('TRAKT: User must manually login via addon settings')
            self.initialized = False

    def login(self):
        try:
            debug(f'TRAKT: Attempting to get device code from Trakt API...')
            debug(f'TRAKT: Using client_id: {self.__client_id[:30]}...')

            # Použiť nový API wrapper
            code = self.api.auth.device_code(self.__client_id)

            if not code:
                debug('TRAKT Error can not reach trakt - API returned empty response')
                dok('ERROR', 'Trakt.tv error - Cannot reach Trakt API')
                return

            debug(f'TRAKT: Successfully got device code')
            debug(f'TRAKT Enter the code "{code.get("user_code")}" at {code.get("verification_url")} to authenticate your account')

            self.authDialog = dprogress()
            self.authDialog.create('Trakt', f'{code.get("verification_url")} -> {code.get("user_code")}')

            # Vlastný polling loop
            device_code = code.get('device_code')
            interval = int(code.get('interval', 5))
            expires_in = int(code.get('expires_in', 600))
            start_time = time.time()

            debug(f'TRAKT: Starting polling (interval={interval}s, expires_in={expires_in}s)')

            while True:
                elapsed = time.time() - start_time

                # Check if expired
                if elapsed >= expires_in:
                    debug(f'TRAKT: Polling expired after {elapsed}s')
                    self.on_expired()
                    break

                # Check if user canceled
                if self.authDialog.iscanceled():
                    debug('TRAKT: User canceled authentication')
                    self.on_aborted()
                    break

                # Update progress
                progress = int(elapsed / expires_in * 100)
                debug(f'TRAKT poll: Progress {progress}%, waiting for user authorization...')
                self.authDialog.update(progress)

                # Poll Trakt API for token - použiť nový API wrapper
                token = self.api.auth.device_token(device_code, self.__client_id, self.__client_secret)

                if token:
                    # Success! Got token
                    debug('TRAKT: Authentication successful! Got token.')
                    self.on_authenticated(token)
                    break

                # Token is None - user hasn't authorized yet (HTTP 400)
                # Wait before next poll
                time.sleep(interval)
        except Exception as e:
            debug('TRAKT login exception: {}'.format(e))
            import traceback
            debug('TRAKT traceback: {}'.format(traceback.format_exc()))
            dok('ERROR', 'Trakt.tv login error: {}'.format(str(e)))

    def on_aborted(self):
        debug('TRAKT Authentication aborted by user')
        self.authDialog.close()

    def on_authenticated(self, token):
        debug(f'TRAKT on_authenticated called with token')
        debug(f'TRAKT Token data: expires_in={token.get("expires_in")}, created_at={token.get("created_at")}, has_refresh_token={bool(token.get("refresh_token"))}')

        # Vytvor TraktToken dataclass inštanciu
        trakt_token = self.TraktToken(**token)

        # Ulož token (použije _save_token callback)
        self._save_token(trakt_token)

        debug('TRAKT Authentication complete and saved')
        self.authDialog.close()
        dok('Trakt', 'Autorizacia uspesna')
        debug('TRAKT Updating user info...')
        self.update_user()
        debug('TRAKT User info updated')

    def on_expired(self):
        debug('TRAKT Authentication expired - user did not authorize in time')
        self.authDialog.close()

    def on_poll(self, callback):
        # Táto funkcia sa volá každých N sekúnd (interval z device code response)
        if self.authDialog.iscanceled():
            debug('TRAKT poll: User canceled dialog')
            callback(False)
        else:
            self.authPollProgress[2] += self.authPollProgress[1]
            exp, _, current = self.authPollProgress
            progress = int(current / exp * 100)
            debug('TRAKT poll: Progress {}%, waiting for user authorization...'.format(progress))
            self.authDialog.update(progress)
            callback(True)

    def on_token_refreshed(self, response):
        """
        DEPRECATED: Token refresh je teraz automatický v TraktHttpClient
        Táto metóda tu ostáva pre backward compatibility ale už sa nepoužíva
        """
        pass

    # ##################################################################################################################

    def update_user(self):
        data = self.get_user()
        debug('trakt user: {}'.format(dumps(data)))

        # Defensive check - API môže vrátiť None pri chybe
        if not data or 'user' not in data:
            debug('TRAKT: update_user failed - no user data received')
            return

        user = data['user']['username'] if 'username' in data.get('user', {}) else data['user']['name']
        set_setting('trakt.user', user)

    def get_user(self):
        """Získa nastavenia aktuálneho používateľa"""
        return self.api.users.settings()

    def get_playback_movies(self, movies):
        """Získa nedopozerané filmy (in progress) z Trakt.tv"""
        result = self.api.sync.playback_movies()
        return result if result else []

    def get_playback_shows(self):
        """Získa nedopozerané seriály/epizódy (in progress) z Trakt.tv"""
        result = self.api.sync.playback_episodes()
        return result if result else []

    def get_shows_watched(self, ids={}):
        """Získa sledované seriály z Trakt.tv"""
        debug('get_shows_watched: Downloading watched shows from Trakt (this may take a while)...')

        shows = self.api.sync.watched_shows()

        if not shows:
            debug('get_shows_watched: No watched shows found or API error')
            return []

        debug(f'get_shows_watched: Received {len(shows)} shows, processing...')
        ids = [(i['show']['ids']['trakt'], i.get('show', {}).get('aired_episodes', 0),
                sum([[(s['number'], e['number'], e['last_watched_at']) for e in s['episodes']]
                     for s in i['seasons']], [])) for i in shows]
        debug('get_shows_watched: Processing complete')

        return ids

    def get_shows_history(self, start_at=None, end_at=None, page=1, limit=50):
        """
        Získa históriu sledovaných seriálov z Trakt.tv

        Args:
            start_at: Datetime objekt - začiatok obdobia (None = všetko)
            end_at: Datetime objekt - koniec obdobia (None = až po súčasnosť)
            page: Číslo stránky (default: 1)
            limit: Počet položiek na stránku (default: 50)

        Returns:
            list: [(history_id, show_trakt_id, season, episode, watched_at, show_title, show_year), ...]
        """
        shows = self.api.sync.history_shows(start_at, end_at, page, limit)

        if not shows:
            return []

        # Zoskupíme epizódy po seriáloch do rovnakého formátu ako get_shows_watched()
        # Formát: [(show_trakt_id, 0, [(season, episode, watched_at), ...]), ...]
        shows_dict = {}
        episode_count = 0
        for i in shows:
            if i['action'] == 'watch' and i['type'] == 'episode':
                show_trakt_id = i['show']['ids']['trakt']
                season = i['episode']['season']
                episode = i['episode']['number']
                watched_at = i['watched_at']
                episode_count += 1
                if show_trakt_id not in shows_dict:
                    shows_dict[show_trakt_id] = []
                shows_dict[show_trakt_id].append((season, episode, watched_at))

        result = [(trakt_id, 0, eps) for trakt_id, eps in shows_dict.items()]
        debug(f'get_shows_history: Found {episode_count} episode entries on page {page} (including duplicates)')
        return result

    def get_movies_history(self, start_at=None, end_at=None, page=1, limit=50):
        """
        Získa históriu sledovaných filmov z Trakt.tv

        Args:
            start_at: Datetime objekt - začiatok obdobia (None = všetko)
            end_at: Datetime objekt - koniec obdobia (None = až po súčasnosť)
            page: Číslo stránky (default: 1)
            limit: Počet položiek na stránku (default: 50)

        Returns:
            list: [(history_id, trakt_id, watched_at, movie_title, movie_year), ...]
        """
        movies = self.api.sync.history_movies(start_at, end_at, page, limit)

        if not movies:
            return []

        # Vrátime plné záznamy aby sme mohli zobraziť každé sledovanie samostatne
        movie_records = []
        for i in movies:
            if i['action'] in ['scrobble', 'watch'] and i['type'] == 'movie':
                history_id = i['id']
                trakt_id = i['movie']['ids']['trakt']
                watched_at = i['watched_at']
                movie_title = i['movie'].get('title', 'Unknown')
                movie_year = i['movie'].get('year', 0)
                movie_records.append((history_id, trakt_id, watched_at, movie_title, movie_year))

        debug(f'get_movies_history: Found {len(movie_records)} movie entries on page {page} (including duplicates)')
        return movie_records

    def get_movies_watched(self, movies):
        """Získa sledované filmy z Trakt.tv"""
        debug('get_movies_watched: Downloading watched movies from Trakt...')

        movies_data = self.api.sync.watched_movies()

        if not movies_data:
            debug('get_movies_watched: No watched movies found or API error')
            return []

        debug(f'get_movies_watched: Received {len(movies_data)} movies')
        return movies_data

    def get_episode_info(self, id, season, episode, extended=None):
        """Získa info o epizóde"""
        return self.api.shows.episode(id, season, episode, extended)

    def get_season_info(self, id, season):
        """Získa info o sezóne vrátane počtu epizód"""
        result = self.api.shows.season(id, season)
        if not result:
            debug(f'Error getting season info for show {id} season {season}')
        return result

    def mark_season_watched(self, trid, season):
        """Označí celú sezónu ako videnú v Trakt"""
        debug(f'Marking entire season as watched: show={trid}, season={season}')
        obj = {
            "shows": [{
                "ids": {"trakt": int(trid)},
                "seasons": [{
                    "number": season
                }]
            }]
        }
        result = self.add_to_history(obj)
        debug(f'Season marked as watched: {result}')
        return result

    def get_last_activities(self):
        """Získa posledné aktivity používateľa"""
        return self.api.sync.last_activities()

    def add_to_history(self, item):
        """Pridá položky do watch history"""
        return self.api.sync.add_to_history(item)

    def remove_from_history(self, item):
        """Odstráni položky z watch history"""
        return self.api.sync.remove_from_history(item)

    def get_lists(self, user='me'):
        """Získa zoznamy používateľa"""
        return self.api.users.lists(user)

    def get_list_items(self, id, user='me'):
        """Získa položky v zozname"""
        return self.api.users.list_items(user, id)

    def get_watchlist(self, user='me'):
        """Získa watchlist používateľa"""
        return self.api.users.watchlist(user)

    def get_friends(self, user='me'):
        """
        Získa zoznam priateľov (friends) daného používateľa

        Args:
            user (str): Používateľské meno, default 'me'

        Returns:
            list: Zoznam priateľov s informáciami o používateľovi
        """
        return self.api.users.friends(user)

    def get_following(self, user='me'):
        """
        Získa zoznam sledovaných používateľov (following) daného používateľa

        Args:
            user (str): Používateľské meno, default 'me'

        Returns:
            list: Zoznam sledovaných používateľov s informáciami
        """
        return self.api.users.following(user)

    @staticmethod
    def script_trakt():
        return Addon('script.trakt')

    @staticmethod
    def is_enabled():
        return get_setting_as_bool('trakt.enabled') and get_setting('trakt.authorization')

    @staticmethod
    def can_check():
        return home_win.getProperty('check_trakt') == '' and TraktAPI.is_enabled() and not player.isPlaying()

    @staticmethod
    def clean_prop():
        home_win.clearProperty('check_trakt')

    def check_trakt(self, force=False):
        if TraktAPI.can_check() or force:
            home_win.setProperty('check_trakt', '1')

            # Inicializuj ak ešte nie je
            if self.initialized is False:
                self.initialize()

            # Skontroluj či máme platný token
            # Ak nie, skip sync (používateľ sa musí manuálne prihlásiť)
            if not self.initialized or not get_setting('trakt.authorization'):
                debug('TRAKT: No valid authorization, skipping sync')
                debug('TRAKT: Please login manually via addon settings')
                self.clean_prop()
                return None

            # KRITICKÉ: Nikdy nevolaj API počas prehrávania (aj s force=True)
            # last_activities API call môže spomaliť prehrávanie
            if player.isPlaying():
                debug('TRAKT: Skipping sync - player is active (avoiding API calls during playback)')
                self.clean_prop()
                return None

            # Preventívny token refresh - skontroluj či token čoskoro expiruje
            token = self._get_token()
            if token and self.http_client._is_token_expiring(token):
                debug('TRAKT: Token expiring soon, triggering preventive refresh')
                # Priamo zavolaj refresh metódu
                if self.http_client._refresh_token():
                    debug('TRAKT: Preventive token refresh successful')
                else:
                    debug('TRAKT: Preventive token refresh failed')
                    self.clean_prop()
                    return None

            # OPTIMALIZÁCIA: Incremental sync - porovnaj last_activities
            # Načítaj uloženú poslednú aktivitu
            self.storage['last.activities'].load(True)
            stored_activities = self.storage['last.activities'].data or {}

            # Získaj aktuálnu aktivitu z Trakt API
            current_activities = self.get_last_activities()

            # Skontroluj rate limit
            if isinstance(current_activities, dict) and current_activities.get('rate_limited'):
                debug('TRAKT: API is rate limited, skipping sync until {}'.format(
                    current_activities.get('retry_after', 'unknown')))
                self.clean_prop()
                return None

            if current_activities is None:
                debug('trakt data is NONE')
                self.clean_prop()
                return None

            # Zisti, či sú zmeny
            has_changes = False
            if not stored_activities or force:
                debug('First sync or forced sync - syncing all')
                has_changes = True
            else:
                # Porovnaj watched_at a paused_at pre movies a episodes
                for check_type in CHECK_SYNC.keys():
                    current = current_activities.get(check_type, {})
                    stored = stored_activities.get(check_type, {})

                    for field in CHECK_SYNC[check_type]:
                        current_val = current.get(field)
                        stored_val = stored.get(field)

                        if current_val != stored_val:
                            debug('Detected change in {}[{}]: {} -> {}'.format(
                                check_type, field, stored_val, current_val))
                            has_changes = True
                            break

                    if has_changes:
                        break

            # Syncuj len ak sú zmeny
            if has_changes:
                debug('Changes detected - syncing...')
                for check in CHECK_SYNC.items():
                    synced = False
                    item = current_activities.get(check[0])
                    for a, i in enumerate(item):
                        if i in check[1]:
                            key = 'sync.{}'.format(check[0])
                            if self.storage[key].get(i) != item.get(i):
                                debug('zmena {}[{}] z {} na {}'.format(key, i, self.storage[key].get(i), item.get(i)))
                                if not synced:
                                    synced = True
                                    try:
                                        if self.sync_local(check[0], self.storage[key].get(i), force=force):
                                            self.storage[key].update({i: item.get(i)})
                                    except:
                                        debug('TRAKT ERR: {}'.format(traceback.format_exc()))
                                        pass

                # Ulož aktuálnu aktivitu po úspešnom syncu
                # Storage.data je read-only property, musíme použiť _data priamo
                self.storage['last.activities']._data.clear()
                self.storage['last.activities']._data.update(current_activities)
                self.storage['last.activities'].save()
                debug('Saved new last_activities to storage')
            else:
                debug('No changes detected - skipping sync (API call saved!)')

            self.clean_prop()

    def sync_playback_movies(self, last=0):
        last_at = TraktAPI.utc2timestamp(last)
        playback = self.get_playback_movies({})
        debug('paused at {}'.format(len(playback)))
        sync = {}
        tr = []
        for m in playback:
            paused_at = TraktAPI.utc2timestamp(m['paused_at'])
            if paused_at is None or last_at is None or paused_at >= last_at:
                sync.update({m['movie']['ids']['trakt']: m})
                tr.append(m['movie']['ids']['trakt'])

        if len(sync):
            dialog = dprogressgb()
            try:
                res = Sc.post('/Ftrakt2sc', data={'trakt': dumps(tr), 't': 1})
                # Prazdne mapovanie pride z backendu ako pole [] - res.get() by padol
                if not isinstance(res, dict):
                    debug('sync_playback_movies: neocakavana odpoved typu {}, pouzivam prazdne mapovanie'.format(type(res).__name__))
                    res = {}
                debug('sync {} / {}     {}'.format(len(sync), len(res), res))
                total = len(res)
                dialog.create('Trakt Playback Sync', 'Syncing {} paused movies...'.format(total))

                for pos, scid in enumerate(res):
                    if self.monitor.abortRequested():
                        debug('sync_playback_movies: Aborted by user')
                        return

                    progress = int((pos / total) * 100) if total > 0 else 0
                    debug('trakt {}%'.format(progress))
                    dialog.update(progress, 'Trakt Playback Sync', 'Syncing movie {} of {}...'.format(pos + 1, total))

                    itm = res.get(scid)
                    item = SCKODIItem(scid, trakt=itm['trakt'])
                    tr = sync.get(int(itm['trakt']))
                    playback_progress = float(sync.get(int(itm['trakt']))['progress'])
                    try:
                        watched = int(float(itm['duration']) * float(playback_progress / 100))
                    except:
                        watched = 0
                    debug('itm {} {} {} {} {} {}'.format(scid, itm, itm['duration'], watched, playback_progress, tr))
                    item.set_watched(watched)
                    d = datetime.fromtimestamp(self.utc2timestamp(tr.get('paused_at')), tz=timezone.utc)
                    item.set_last_played(d.strftime('%Y-%m-%d %H:%M:%S'))

                dialog.update(100, 'Trakt Playback Sync', 'Completed!')
                debug('sync_playback_movies: Sync completed successfully')

            except Exception as e:
                debug('sync_playback_movies: ERROR - {}'.format(traceback.format_exc()))
            finally:
                # VŽDY zavri dialog, aj keď nastane exception
                try:
                    dialog.close()
                    debug('sync_playback_movies: Dialog closed')
                except:
                    pass

    def sync_local(self, type, last, force=False):
        if type == 'movies':
            return self.sync_local_movies(last)
        else:
            return self.sync_local_episodes(last, force=force)

    def scroble(self, id, season=None, episode=None, percent=0, action='stop'):
        """
        Scrobble položku do Trakt

        OPTIMALIZÁCIA: Scrobble requesty idú do fronty a spracovávajú sa na pozadí.
        Tým sa predchádza blokovaniu playback pri rate limite alebo slow API.

        Args:
            id: Trakt ID (show ID pre epizódy)
            season: Číslo sezóny (pre TV show)
            episode: Číslo epizódy (pre TV show)
            percent: Progress v percentách
            action: 'start', 'pause', alebo 'stop'

        Returns:
            dict: {'queued': True} ak bol request pridaný do fronty
        """
        debug(f'scrobble: id={id}, season={season}, episode={episode}, percent={percent}, action={action}')

        # Určiť typ (movie vs episode)
        if season is not None:
            item_type = 'show'
        else:
            item_type = 'movie'

        # NOVÉ: Pridaj do fronty namiesto okamžitého volania API
        # Tým sa predchádza blokovaniu playback pri rate limite
        from resources.lib.services.trakt_queue import trakt_queue_service

        success = trakt_queue_service.enqueue_scrobble(
            action=action,
            item_type=item_type,
            trakt_id=id,
            percent=percent,
            season=season,
            episode=episode
        )

        if success:
            debug('scrobble: Enqueued {} for processing in background'.format(action))
            return {'queued': True, 'action': action}
        else:
            debug('scrobble: Failed to enqueue (queue full?)')
            return {'queued': False, 'error': 'queue_full'}

    def sync_get_list(self, data, typ):
        """
        Konvertuje watched movies/shows do mapy {trakt_id: item}

        Args:
            data: List of dicts z Trakt API (watched movies alebo shows)
            typ: 1=movies, 3=shows

        Returns:
            tuple: (res, items) kde res je mapovanie SC ID -> Trakt ID
        """
        items = {}
        for item in data:
            # API vracia dict, nie objekt
            # Extrahuj movie/show data (môže byť priamo alebo v 'movie'/'show' kľúči)
            if typ == 1:  # movies
                movie_data = item.get('movie', item)
                tr = movie_data['ids']['trakt']
                items[tr] = movie_data
            else:  # shows
                show_data = item.get('show', item)
                tr = show_data['ids']['trakt']
                items[tr] = show_data

        return self.trakt2sc(items, typ)

    def trakt2sc(self, items, typ):
        debug('items {}'.format(len(items)))
        res = Sc.post('/Ftrakt2sc', data={'trakt': dumps(list(items.keys())), 't': typ})
        # Backend serializuje prazdne mapovanie ako JSON pole [] (nie objekt {});
        # callery ocakavaju dict scid -> trakt ids, inak pada res.items()
        if not isinstance(res, dict):
            debug('trakt2sc: neocakavana odpoved typu {}, pouzivam prazdne mapovanie'.format(type(res).__name__))
            res = {}
        debug('res: {}'.format(len(res)))
        return res, items

    def sync_local_episodes(self, last=0, force=False):
        last_at = TraktAPI.utc2timestamp(last)
        dialog = dprogressgb()

        try:
            dialog.create('Trakt Sync', 'Starting sync...')
            debug('sync local episodes {} / {}'.format(last, last_at))

            # Progress update 1: Sťahovanie dát z Trakt
            dialog.update(0, 'Trakt Sync', 'Downloading data from Trakt...')
            if force or last_at is None:
                debug('sync_local_episodes: force={} or last_at is None, using get_shows_watched'.format(force))
                data = self.get_shows_watched({})
            else:
                data = self.get_shows_history(datetime.fromtimestamp(last_at, tz=timezone.utc))

            debug('sync_local_episodes: Received {} shows from Trakt'.format(len(data)))

            if data == []:
                debug('sync_local_episodes: No data to sync, returning')
                return True

            # Progress update 2: Spracovanie dát
            dialog.update(10, 'Trakt Sync', 'Processing {} shows...'.format(len(data)))
            items = {}
            for trid, num, eps in data:
                if self.abortRequested():
                    debug('sync_local_episodes: Aborted by user during processing')
                    return False
                items.update({trid: eps})

            # Progress update 3: Mapovanie Trakt -> SC
            dialog.update(20, 'Trakt Sync', 'Mapping {} shows to local database...'.format(len(items)))
            res, items = self.trakt2sc(items, 3)
            debug('sync_local_episodes: Mapped {} shows to SC'.format(len(res)))

            pos = 0
            total = len(res)
            debug('sync_local_episodes: Processing {} items...'.format(total))

            for scid, trid in res.items():
                if self.abortRequested():
                    debug('sync_local_episodes: Aborted by user during item processing')
                    return False
                pos += 1
                max_time = 0
                last_ep = None

                # Vypočítaj progress: 20% (mapping done) + 80% * aktuálny progress
                progress = 20 + int((pos / total) * 80)
                debug('episodes: {}% ({}/{})'.format(progress, pos, total))
                dialog.update(progress, 'Trakt Sync', 'Processing show {} of {}...'.format(pos, total))

                item = SCKODIItem(scid)
                debug('ITEM: {}'.format(item.data))
                for s, e, watched_at in items[int(trid['trakt'])]:
                    item.series = s
                    item.episode = e
                    if self.abortRequested():
                        debug('sync_local_episodes: Aborted by user during episode processing')
                        return False
                    wa = TraktAPI.utc2timestamp(watched_at)

                    if int(wa) >= int(max_time):
                        ''' ak su epizody vsetky oznacene ako videne v rovnaky cas alebo novsie '''
                        max_time = wa
                        last_ep = (s, e)

                    old = item.get_play_count()
                    if force or old is None or last_at is None or wa >= last_at:
                        debug('SCID ADD {} {}x{}'.format(scid, s, e))
                        item.set_play_count('1')

                if item and last_ep is not None:
                    # IMPORTANT: allow_api_calls=False aby sa zabralo rate limitingu
                    # Cache sa načíta automaticky keď užívateľ zobrazí seriál
                    item.set_last_ep(last_ep[0], last_ep[1], max_time, allow_api_calls=False)

            dialog.update(100, 'Trakt Sync', 'Completed!')
            debug('sync_local_episodes: Sync completed successfully')
            return True

        except Exception as e:
            debug('sync_local_episodes: ERROR - {}'.format(traceback.format_exc()))
            return False
        finally:
            # VŽDY zavri dialog, aj keď nastane exception
            try:
                dialog.close()
                debug('sync_local_episodes: Dialog closed')
            except:
                pass

    def abortRequested(self):
        return self.monitor.abortRequested() or player.isPlayback()

    def sync_local_movies(self, last):
        dialog = dprogressgb()

        try:
            dialog.create('Trakt Sync Movies', 'Starting movie sync...')
            self.sync_playback_movies(last)

            dialog.update(10, 'Trakt Sync Movies', 'Downloading watched movies...')
            data = self.get_movies_watched({})
            res, movies = self.sync_get_list(data, 1)
            debug('res: {}'.format(len(res)))

            all_items = self.storage['watched.movies'].get()[:]
            pos = 0
            total = len(res)

            # Fáza 1: Pridávanie nových videných filmov
            dialog.update(20, 'Trakt Sync Movies', 'Processing {} movies...'.format(total))
            for scid, trid in res.items():
                if self.monitor.abortRequested():
                    debug('sync_local_movies: Aborted by user')
                    return False
                pos += 1
                progress = 20 + int((pos / total) * 40) if total > 0 else 60
                dialog.update(progress, 'Trakt Sync Movies', 'Processing movie {} of {}...'.format(pos, total))

                item = SCKODIItem(scid)
                if scid not in all_items:
                    debug('pridavam do zoznamu {}'.format(scid))
                    self.storage['watched.movies'].add(scid)
                    item.set_play_count('1')
                else:
                    all_items.remove(scid)

            # Fáza 2: Odstraňovanie filmov, ktoré už nie sú videné
            if len(all_items) > 0:
                dialog.update(60, 'Trakt Sync Movies', 'Removing {} unwatched movies...'.format(len(all_items)))
                total_remove = len(all_items)
                pos = 0
                for scid in all_items:
                    if self.monitor.abortRequested():
                        debug('sync_local_movies: Aborted by user during cleanup')
                        return False
                    pos += 1
                    progress = 60 + int((pos / total_remove) * 40)
                    dialog.update(progress, 'Trakt Sync Movies', 'Removing movie {} of {}...'.format(pos, total_remove))
                    self.storage['watched.movies'].add(scid, remove_only=True)
                    item = SCKODIItem(scid)
                    item.set_play_count(None)

            dialog.update(100, 'Trakt Sync Movies', 'Completed!')
            debug('sync_local_movies: Sync completed successfully')
            return True

        except Exception as e:
            debug('sync_local_movies: ERROR - {}'.format(traceback.format_exc()))
            return False
        finally:
            # VŽDY zavri dialog, aj keď nastane exception
            try:
                dialog.close()
                debug('sync_local_movies: Dialog closed')
            except:
                pass

    @staticmethod
    def utc2timestamp(to_convert):
        if to_convert:
            try:
                # Pokus parsovať ISO 8601 formát (napr. "2024-10-25T23:16:50.000Z")
                # Odstránime 'Z' a nahradíme '+00:00' ak je potrebné
                date_str = to_convert.replace('Z', '+00:00')
                utc = datetime.fromisoformat(date_str)
                # Ak nemá timezone info, pridáme UTC
                if utc.tzinfo is None:
                    utc = utc.replace(tzinfo=timezone.utc)
            except (ValueError, AttributeError):
                debug('utc2timestamp() problem, nastavujem aktualny cas')
                utc = datetime.now(timezone.utc)
            try:
                to_convert = int(utc.timestamp())
            except:
                debug('utc2timestamp() timestamp conversion failed')
                to_convert = int(datetime.now(timezone.utc).timestamp())

        return to_convert

    def set_watched(self, trid, times=None, season=None, episode=None):
        if season is None:
            if 'trakt' in trid:
                obj = {"movies": [{"ids": {"trakt": int(trid.get('trakt'))}}]}
            else:
                obj = {"movies": [{"ids": {"trakt": int(trid)}}]}
        else:
            ep_info = self.get_episode_info(int(trid), season, episode)
            debug('EP INFO: {}'.format(ep_info))
            if ep_info:
                obj = {"episodes": [{"ids": ep_info.get('ids', {})}]}
            else:
                obj = {"shows": [
                    {"ids": {
                        "trakt": int(trid)},
                        "seasons": {
                            "number": season,
                            "episodes": [
                                {"number": episode}
                            ]
                        }
                    }
                ]}
        debug('posielam obj: {}'.format(dumps(obj)))
        if times is not None and int(times) > 0:
            ret = self.add_to_history(obj)
        else:
            ret = self.remove_from_history(obj)
        debug('Hotovo trakt history.... {}'.format(ret))

    def show_items(self, items, sc):
        sc.url = '/Search/getTrakt'
        sc.payload = {'ids': dumps(items)}
        sc.call_url_and_response()

    def action(self, action, sc):
        from resources.lib.params import params
        import xbmcplugin

        debug('trakt action: {} / {}'.format(action, params.args))
        if action == 'trakt.login':
            set_setting_as_bool('trakt.enabled', True)
            self.login()
        elif action == 'trakt.logout':
            set_setting('trakt.authorization', '')
            set_setting('trakt.user', '')
        elif action == 'trakt.list':
            u = 'me' if not params.args.get('user', None) else params.args.get('user')

            # Pre vlastné menu (u == 'me') pridaj špeciálne položky na začiatok
            if u == 'me':
                # 1. Watchlist (žltá)
                watchlist_itm = {
                    'type': 'action',
                    'title': '[COLOR yellow]Watchlist[/COLOR]',
                    'action': 'trakt.list.items',
                    'id': 'watchlist',
                    'user': u
                }
                item = SCItem(watchlist_itm)
                if item.visible:
                    sc.items.append(item.get())

                # 2. Movie History (oranžová)
                movie_history_itm = {
                    'type': 'action',
                    'title': '[COLOR orange]{}[/COLOR]'.format(ADDON.getLocalizedString(30310)),
                    'action': 'trakt.history.movies',
                    'user': u
                }
                item = SCItem(movie_history_itm)
                if item.visible:
                    sc.items.append(item.get())

                # 3. TV History (tyrkysová)
                tv_history_itm = {
                    'type': 'action',
                    'title': '[COLOR cyan]{}[/COLOR]'.format(ADDON.getLocalizedString(30311)),
                    'action': 'trakt.history.shows',
                    'user': u
                }
                item = SCItem(tv_history_itm)
                if item.visible:
                    sc.items.append(item.get())

                # 4. In Progress Movies (fialová)
                in_progress_movies_itm = {
                    'type': 'action',
                    'title': '[COLOR violet]{}[/COLOR]'.format(ADDON.getLocalizedString(30315)),
                    'action': 'trakt.playback.movies',
                    'user': u
                }
                item = SCItem(in_progress_movies_itm)
                if item.visible:
                    sc.items.append(item.get())

                # 5. In Progress TV Shows (ružová)
                in_progress_shows_itm = {
                    'type': 'action',
                    'title': '[COLOR hotpink]{}[/COLOR]'.format(ADDON.getLocalizedString(30316)),
                    'action': 'trakt.playback.shows',
                    'user': u
                }
                item = SCItem(in_progress_shows_itm)
                if item.visible:
                    sc.items.append(item.get())

                # 6. Friends (modrá)
                friends_itm = {
                    'type': 'action',
                    'title': '[COLOR skyblue]Friends[/COLOR]',
                    'action': 'trakt.friends',
                    'user': u
                }
                item = SCItem(friends_itm)
                if item.visible:
                    sc.items.append(item.get())

                # 7. Following (zelená)
                following_itm = {
                    'type': 'action',
                    'title': '[COLOR lightgreen]Following[/COLOR]',
                    'action': 'trakt.following',
                    'user': u
                }
                item = SCItem(following_itm)
                if item.visible:
                    sc.items.append(item.get())

            # Potom pridaj custom lists (bežné farby)
            lists = self.get_lists(user=u)
            if lists:
                for l in lists:
                    # API vracia dict, nie objekt
                    itm = {'type': 'action', 'title': l['name'], 'action': 'trakt.list.items', 'id': l['ids']['trakt'], 'user': u}
                    item = SCItem(itm)
                    if item.visible:
                        sc.items.append(item.get())
            else:
                debug('trakt.list: get_lists returned None (authentication failed?)')

            # OPRAVA: Ručne pridaj items do KODI (kvôli optimalizácii v streamcinema.py)
            if sc.items:
                xbmcplugin.addDirectoryItems(params.handle, sc.items)
        elif action == 'trakt.friends':
            # Zobrazenie priateľov (friends)
            try:
                friends = self.get_friends(user='me')
                debug('trakt.friends: Loaded {} friends'.format(len(friends) if friends else 0))

                if friends:
                    for friend in friends:
                        # API vracia dict s 'user' kľúčom
                        user_data = friend.get('user', friend)  # Môže byť priamo user alebo zabalené
                        username = user_data.get('username') or user_data.get('name')

                        if username:
                            itm = {
                                'type': 'action',
                                'title': username,
                                'action': 'trakt.user.menu',
                                'user': username
                            }
                            item = SCItem(itm)
                            if item.visible:
                                sc.items.append(item.get())

                # Pridaj items do KODI
                if sc.items:
                    xbmcplugin.addDirectoryItems(params.handle, sc.items)
            except Exception as e:
                debug('trakt.friends error: {}'.format(e))
                import traceback
                debug('trakt.friends traceback: {}'.format(traceback.format_exc()))
        elif action == 'trakt.following':
            # Zobrazenie sledovaných používateľov (following)
            try:
                following = self.get_following(user='me')
                debug('trakt.following: Loaded {} following'.format(len(following) if following else 0))

                if following:
                    for follow in following:
                        # API vracia dict s 'user' kľúčom
                        user_data = follow.get('user', follow)  # Môže byť priamo user alebo zabalené
                        username = user_data.get('username') or user_data.get('name')

                        if username:
                            itm = {
                                'type': 'action',
                                'title': username,
                                'action': 'trakt.user.menu',
                                'user': username
                            }
                            item = SCItem(itm)
                            if item.visible:
                                sc.items.append(item.get())

                # Pridaj items do KODI
                if sc.items:
                    xbmcplugin.addDirectoryItems(params.handle, sc.items)
            except Exception as e:
                debug('trakt.following error: {}'.format(e))
                import traceback
                debug('trakt.following traceback: {}'.format(traceback.format_exc()))
        elif action == 'trakt.user.menu':
            # Menu pre konkrétneho používateľa (watchlist + listy)
            user = params.args.get('user', 'me')
            debug('trakt.user.menu: user={}'.format(user))

            try:
                # Pridaj watchlist položku
                watchlist_itm = {
                    'type': 'action',
                    'title': 'Watchlist',
                    'action': 'trakt.list.items',
                    'id': 'watchlist',
                    'user': user
                }
                item = SCItem(watchlist_itm)
                if item.visible:
                    sc.items.append(item.get())

                # Načítaj custom lists používateľa
                lists = self.get_lists(user=user)
                if lists:
                    for l in lists:
                        # API vracia dict, nie objekt
                        itm = {
                            'type': 'action',
                            'title': l['name'],
                            'action': 'trakt.list.items',
                            'id': l['ids']['trakt'],
                            'user': user
                        }
                        item = SCItem(itm)
                        if item.visible:
                            sc.items.append(item.get())

                # Pridaj items do KODI
                if sc.items:
                    xbmcplugin.addDirectoryItems(params.handle, sc.items)
            except Exception as e:
                debug('trakt.user.menu error: {}'.format(e))
                import traceback
                debug('trakt.user.menu traceback: {}'.format(traceback.format_exc()))
        elif action == 'trakt.sync.shows':
            self.sync_local_episodes(last=0, force=True)
        elif action == 'trakt.history.movies':
            # Zobrazenie histórie sledovaných filmov
            try:
                page = int(params.args.get('page', 1))
                limit = 50

                debug('trakt.history.movies: Loading page {}'.format(page))

                # Získaj históriu filmov z Trakt API - vracia plné záznamy
                movie_records = self.get_movies_history(page=page, limit=limit)
                debug('trakt.history.movies: Got {} movie records'.format(len(movie_records)))

                if movie_records:
                    # Zbierme unikátne Trakt IDs pre bulk load z SC servera
                    # DÔLEŽITÉ: Zachovať poradie z Trakt historie (najnovšie prvé)
                    # Použijeme dict.fromkeys() na deduplication so zachovaním poradia
                    unique_trakt_ids = list(dict.fromkeys([trakt_id for _, trakt_id, _, _, _ in movie_records]))
                    debug('trakt.history.movies: {} unique movies to load from SC server'.format(len(unique_trakt_ids)))

                    # Načítaj plné movie info z SC servera
                    items_for_sc = ["{},{}".format(1, mid) for mid in unique_trakt_ids]
                    debug('trakt.history.movies: Requesting IDs in order: {}'.format(unique_trakt_ids[:10]))  # Prvých 10 pre debug
                    self.show_items(items_for_sc, sc)

                    # Teraz sc.items obsahuje KODI ListItems pre unikátne filmy
                    # Musíme ich "zduplikovať" podľa history záznamov a pridať watched_at do titulku

                    # Vytvor mapping trakt_id -> KODI ListItem
                    trakt_to_item = {}
                    debug('trakt.history.movies: Received {} items from SC server'.format(len(sc.items)))
                    for idx, list_item in enumerate(sc.items):
                        # Získaj trakt_id z URL
                        # URL má format: plugin://plugin.video.stream-cinema/?...&id=XXX&trakt=YYY
                        url = list_item[0]
                        if idx < 3:  # Log prvé 3 pre debug
                            debug('trakt.history.movies: URL {}: {}'.format(idx, url))
                        import re
                        match = re.search(r'trakt=(\d+)', url)
                        if match:
                            tid = int(match.group(1))
                            trakt_to_item[tid] = list_item
                            if idx < 3:
                                debug('trakt.history.movies: Mapped trakt_id={} to item'.format(tid))
                        else:
                            debug('trakt.history.movies: WARNING - No trakt ID found in URL: {}'.format(url[:200]))

                    # Vyčisti sc.items a pridaj záznamy podľa history (s duplikátmi)
                    sc.items = []
                    for history_id, trakt_id, watched_at, movie_title, movie_year in movie_records:
                        if trakt_id in trakt_to_item:
                            # Kópia KODI ListItem
                            orig_item = trakt_to_item[trakt_id]
                            url, list_item, is_folder = orig_item

                            # Uprav titul aby zahŕňal dátum sledovania
                            from datetime import datetime
                            watched_dt = datetime.fromisoformat(watched_at.replace('Z', '+00:00'))
                            watched_str = watched_dt.strftime('%d.%m.%Y %H:%M')

                            # Uprav URL aby obsahoval history_id pre unikátnosť
                            new_url = url + '&history_id={}'.format(history_id)

                            # Uprav label
                            old_label = list_item.getLabel()
                            new_label = '{} [COLOR gray]({})[/COLOR]'.format(old_label, watched_str)
                            list_item.setLabel(new_label)

                            sc.items.append((new_url, list_item, is_folder))
                        else:
                            debug('trakt.history.movies: Movie {} not found in SC server response'.format(trakt_id))

                # Pridaj pagination položky
                if len(movie_records) >= limit:
                    # Pridaj "Next Page" položku
                    next_page_itm = {
                        'type': 'action',
                        'title': '{} ({})'.format(ADDON.getLocalizedString(30312), page + 1),
                        'action': 'trakt.history.movies',
                        'page': page + 1
                    }
                    item = SCItem(next_page_itm)
                    if item.visible:
                        sc.items.append(item.get())

                if page > 1:
                    # Pridaj "Previous Page" položku
                    prev_page_itm = {
                        'type': 'action',
                        'title': '{} ({})'.format(ADDON.getLocalizedString(30313), page - 1),
                        'action': 'trakt.history.movies',
                        'page': page - 1
                    }
                    item = SCItem(prev_page_itm)
                    if item.visible:
                        sc.items.insert(0, item.get())  # Vložiť na začiatok

                # Pridaj items do KODI
                if sc.items:
                    xbmcplugin.addDirectoryItems(params.handle, sc.items)

            except Exception as e:
                debug('trakt.history.movies error: {}'.format(e))
                import traceback
                debug('trakt.history.movies traceback: {}'.format(traceback.format_exc()))
        elif action == 'trakt.history.shows':
            # Zobrazenie histórie sledovaných seriálov (jednotlivé epizódy)
            try:
                page = int(params.args.get('page', 1))
                limit = 50

                debug('trakt.history.shows: Loading page {}'.format(page))

                # Získaj históriu seriálov z Trakt API - vracia plné záznamy epizód
                episode_records = self.get_shows_history(page=page, limit=limit)
                debug('trakt.history.shows: Got {} episode records'.format(len(episode_records)))

                if episode_records:
                    # Zbierme unikátne Show Trakt IDs pre bulk load z SC servera
                    # DÔLEŽITÉ: Zachovať poradie z Trakt historie (najnovšie prvé)
                    unique_show_ids = list(dict.fromkeys([show_id for _, show_id, _, _, _, _, _ in episode_records]))
                    debug('trakt.history.shows: {} unique shows to load from SC server'.format(len(unique_show_ids)))

                    # Načítaj plné show info z SC servera
                    items_for_sc = ["{},{}".format(3, sid) for sid in unique_show_ids]  # 3 = show type
                    debug('trakt.history.shows: Requesting show IDs in order: {}'.format(unique_show_ids[:10]))  # Prvých 10 pre debug
                    self.show_items(items_for_sc, sc)

                    # Vytvor mapping show_trakt_id -> KODI ListItem
                    show_to_item = {}
                    debug('trakt.history.shows: Received {} items from SC server'.format(len(sc.items)))
                    for idx, list_item in enumerate(sc.items):
                        url = list_item[0]
                        if idx < 3:  # Log prvé 3 pre debug
                            debug('trakt.history.shows: URL {}: {}'.format(idx, url))
                        import re
                        match = re.search(r'trakt=(\d+)', url)
                        if match:
                            sid = int(match.group(1))
                            show_to_item[sid] = list_item
                            if idx < 3:
                                debug('trakt.history.shows: Mapped show_trakt_id={} to item'.format(sid))
                        else:
                            debug('trakt.history.shows: WARNING - No trakt ID found in URL: {}'.format(url[:200]))

                    # Vyčisti sc.items a pridaj záznamy podľa history (jednotlivé epizódy s duplikátmi)
                    sc.items = []
                    for history_id, show_trakt_id, season, episode, watched_at, show_title, show_year in episode_records:
                        if show_trakt_id in show_to_item:
                            # Kópia KODI ListItem
                            orig_item = show_to_item[show_trakt_id]
                            url, list_item, is_folder = orig_item

                            # Uprav titul aby zahŕňal sezónu, epizódu a dátum sledovania
                            from datetime import datetime
                            watched_dt = datetime.fromisoformat(watched_at.replace('Z', '+00:00'))
                            watched_str = watched_dt.strftime('%d.%m.%Y %H:%M')

                            # Uprav URL aby obsahoval history_id pre unikátnosť
                            new_url = url + '&history_id={}'.format(history_id)

                            # Uprav label: "Show Name - S01E05 (18.10.2025 14:30)"
                            old_label = list_item.getLabel()
                            new_label = '{} - S{:02d}E{:02d} [COLOR gray]({})[/COLOR]'.format(
                                old_label, season, episode, watched_str)
                            list_item.setLabel(new_label)

                            sc.items.append((new_url, list_item, is_folder))
                        else:
                            debug('trakt.history.shows: Show {} not found in SC server response'.format(show_trakt_id))

                # Pridaj pagination položky
                if len(episode_records) >= limit:
                    # Pridaj "Next Page" položku
                    next_page_itm = {
                        'type': 'action',
                        'title': '{} ({})'.format(ADDON.getLocalizedString(30312), page + 1),
                        'action': 'trakt.history.shows',
                        'page': page + 1
                    }
                    item = SCItem(next_page_itm)
                    if item.visible:
                        sc.items.append(item.get())

                if page > 1:
                    # Pridaj "Previous Page" položku
                    prev_page_itm = {
                        'type': 'action',
                        'title': '{} ({})'.format(ADDON.getLocalizedString(30313), page - 1),
                        'action': 'trakt.history.shows',
                        'page': page - 1
                    }
                    item = SCItem(prev_page_itm)
                    if item.visible:
                        sc.items.insert(0, item.get())  # Vložiť na začiatok

                # Pridaj items do KODI
                if sc.items:
                    xbmcplugin.addDirectoryItems(params.handle, sc.items)

            except Exception as e:
                debug('trakt.history.shows error: {}'.format(e))
                import traceback
                debug('trakt.history.shows traceback: {}'.format(traceback.format_exc()))
        elif action == 'trakt.playback.movies':
            # Zobrazenie nedopozeraných filmov (in progress)
            try:
                debug('trakt.playback.movies: Loading in-progress movies')

                # Získaj nedopozerané filmy z Trakt API
                playback_data = self.get_playback_movies({})
                debug('trakt.playback.movies: Got {} movies'.format(len(playback_data) if playback_data else 0))

                if playback_data:
                    # Extrahuj Trakt IDs
                    movie_ids = [m['movie']['ids']['trakt'] for m in playback_data]
                    debug('trakt.playback.movies: Extracted {} movie IDs'.format(len(movie_ids)))

                    # Konvertuj Trakt IDs na SC IDs
                    items = ["{},{}".format(1, mid) for mid in movie_ids]  # 1 = movie type
                    debug('trakt.playback.movies: Showing {} items'.format(len(items)))
                    self.show_items(items, sc)

                # Pridaj items do KODI
                if sc.items:
                    xbmcplugin.addDirectoryItems(params.handle, sc.items)

            except Exception as e:
                debug('trakt.playback.movies error: {}'.format(e))
                import traceback
                debug('trakt.playback.movies traceback: {}'.format(traceback.format_exc()))
        elif action == 'trakt.playback.shows':
            # Zobrazenie nedopozeraných seriálov (in progress)
            try:
                debug('trakt.playback.shows: Loading in-progress TV shows')

                # Získaj nedopozerané seriály z Trakt API
                playback_data = self.get_playback_shows()
                debug('trakt.playback.shows: Got {} episodes'.format(len(playback_data) if playback_data else 0))

                if playback_data:
                    # Extrahuj unique show IDs (môže byť viac epizód z jedného seriálu)
                    show_ids = list(set([e['show']['ids']['trakt'] for e in playback_data]))
                    debug('trakt.playback.shows: Extracted {} unique show IDs'.format(len(show_ids)))

                    # Konvertuj Trakt IDs na SC IDs
                    items = ["{},{}".format(3, sid) for sid in show_ids]  # 3 = show type
                    debug('trakt.playback.shows: Showing {} items'.format(len(items)))
                    self.show_items(items, sc)

                # Pridaj items do KODI
                if sc.items:
                    xbmcplugin.addDirectoryItems(params.handle, sc.items)

            except Exception as e:
                debug('trakt.playback.shows error: {}'.format(e))
                import traceback
                debug('trakt.playback.shows traceback: {}'.format(traceback.format_exc()))
        elif action == 'trakt.list.items':
            u = 'me' if not params.args.get('user', None) else params.args.get('user')
            name = params.args.get('id')

            try:
                if name == 'watchlist':
                    watchlist_result = self.get_watchlist(u)
                    if watchlist_result is None:
                        debug('trakt.list.items: Watchlist returned None for user {}'.format(u))
                        sc.succeeded = True
                        sc.end()
                        return
                    # API už vracia list, nie PyTrakt objekt
                    data = watchlist_result
                else:
                    list_result = self.get_list_items(name, u)
                    if list_result is None:
                        debug('trakt.list.items: List {} returned None for user {}'.format(name, u))
                        sc.succeeded = True
                        sc.end()
                        return
                    # API už vracia list, nie PyTrakt objekt
                    data = list_result

                items = []
                for i in data:
                    t = i.get('type')
                    debug('item: {} {}'.format(t, i))
                    if t not in ['movie', 'tvshow', 'show']:
                        continue
                    sc_type = 1 if t == 'movie' else 3
                    item_data = i.get(t, {})
                    ids = item_data.get('ids')
                    tr = ids.get('trakt')
                    itm = "{},{}".format(sc_type, tr)
                    items.append(itm)
                debug('items: {}'.format(items))
                self.show_items(items, sc)
            except Exception as e:
                debug('trakt.list.items error: {}'.format(e))
                import traceback
                debug('trakt.list.items traceback: {}'.format(traceback.format_exc()))
                sc.succeeded = True
                sc.end()
        else:
            debug('Neznama akcia trakt.tv {}'.format(action))
        sc.succeeded = True
        sc.end()


trakt = TraktAPI()
