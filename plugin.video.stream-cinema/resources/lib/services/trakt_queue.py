# -*- coding: utf-8 -*-
"""
Trakt Queue Service - fronta pre odložiteľné Trakt API requesty

Rieši problém blokovania UI/playback pri rate limite alebo slow API response.
Scrobble, sync/history a ostatné "fire-and-forget" requesty idú do fronty
a spracovávajú sa na pozadí.
"""

from __future__ import print_function, unicode_literals

import threading
import traceback
from time import time, sleep
from collections import deque
from json import dumps, loads

from resources.lib.common.logger import debug
from resources.lib.common.storage import Storage


class TraktQueueService:
    """
    Background service pre spracovanie Trakt API requestov vo fronte

    Vlastnosti:
    - Thread-safe fronta s automatickým retry
    - Persistence pri shutdown (uloží pending requests)
    - Rate limit handling s Retry-After
    - Neblokuje UI ani playback
    - Odložená fronta pre requesty, ktoré zlyhali po všetkých pokusoch
    """

    MAX_QUEUE_SIZE = 100
    MAX_DEFERRED_SIZE = 500  # väčší limit pre odloženú frontu
    PROCESS_INTERVAL = 3  # sekundy medzi spracovaním položiek
    DEFERRED_RETRY_INTERVAL = 300  # 5 minút - interval pre retry odložených requestov
    MAX_RETRIES = 3
    MAX_DEFERRED_RETRIES = 10  # viac pokusov pre odložené requesty

    def __init__(self):
        self.queue = deque(maxlen=self.MAX_QUEUE_SIZE)
        self.deferred_queue = deque(maxlen=self.MAX_DEFERRED_SIZE)  # odložená fronta
        self.lock = threading.Lock()
        self.storage = Storage('trakt_queue')
        self.is_processing = False
        self.last_process_time = 0
        self.last_deferred_process_time = 0  # pre odloženú frontu
        self.rate_limit_until = 0  # timestamp - čakať do tohto času kvôli rate limit

        # Načítaj pending requests zo storage (z predošlého reštartu)
        self._load_queue()

        debug('TraktQueueService: Initialized with {} pending, {} deferred requests'.format(
            len(self.queue), len(self.deferred_queue)))

    def _load_queue(self):
        """Načíta uloženú frontu zo storage"""
        try:
            self.storage.load(True)

            # Načítaj hlavnú frontu
            saved_queue = self.storage.get('pending_requests')
            if saved_queue:
                for item in saved_queue:
                    self.queue.append(item)
                debug('TraktQueueService: Loaded {} pending requests from storage'.format(len(saved_queue)))

            # Načítaj odloženú frontu
            saved_deferred = self.storage.get('deferred_requests')
            if saved_deferred:
                for item in saved_deferred:
                    self.deferred_queue.append(item)
                debug('TraktQueueService: Loaded {} deferred requests from storage'.format(len(saved_deferred)))

        except Exception as e:
            debug('TraktQueueService: Error loading queue: {}'.format(e))

    def _save_queue(self):
        """Uloží frontu do storage (pre persistence pri reštarte)"""
        try:
            with self.lock:
                # Konvertuj deque na list pre JSON serialization
                queue_list = list(self.queue)
                deferred_list = list(self.deferred_queue)

            self.storage['pending_requests'] = queue_list
            self.storage['deferred_requests'] = deferred_list
            self.storage.save()
            debug('TraktQueueService: Saved {} pending, {} deferred requests to storage'.format(
                len(queue_list), len(deferred_list)))
        except Exception as e:
            debug('TraktQueueService: Error saving queue: {}'.format(e))

    def enqueue_scrobble(self, action, item_type, trakt_id, percent, season=None, episode=None):
        """
        Pridá scrobble request do fronty

        Args:
            action: 'start', 'pause', 'stop'
            item_type: 'show' alebo 'movie'
            trakt_id: Trakt ID
            percent: Progress v percentách
            season: Číslo sezóny (pre shows)
            episode: Číslo epizódy (pre shows)

        Returns:
            bool: True ak sa podarilo pridať do fronty
        """
        # VALIDÁCIA: Trakt API vyžaduje minimálne 1% pre pause/stop
        # Pre 'start' akceptujeme aj 0%
        if action in ['pause', 'stop'] and percent < 1.0:
            debug('TraktQueueService: Skipping {} scrobble - progress {:.2f}% is below 1% minimum'.format(
                action, percent))
            return True  # Vrátime True aby sa nezdalo že je problém s frontou

        request = {
            'type': 'scrobble',
            'action': action,
            'item_type': item_type,
            'trakt_id': trakt_id,
            'percent': percent,
            'season': season,
            'episode': episode,
            'timestamp': time(),
            'retries': 0
        }

        return self._enqueue(request)

    def enqueue_sync_history(self, items, remove=False):
        """
        Pridá sync/history request do fronty

        Args:
            items: List of items (movies/episodes) pre sync
            remove: True ak je to remove z history, False pre add

        Returns:
            bool: True ak sa podarilo pridať do fronty
        """
        request = {
            'type': 'sync_history',
            'items': items,
            'remove': remove,
            'timestamp': time(),
            'retries': 0
        }

        return self._enqueue(request)

    def enqueue_rating(self, item_type, trakt_id, rating, season=None, episode=None):
        """
        Pridá rating request do fronty

        Args:
            item_type: 'show', 'movie', 'episode'
            trakt_id: Trakt ID
            rating: Rating 1-10
            season: Číslo sezóny (pre episodes)
            episode: Číslo epizódy (pre episodes)

        Returns:
            bool: True ak sa podarilo pridať do fronty
        """
        request = {
            'type': 'rating',
            'item_type': item_type,
            'trakt_id': trakt_id,
            'rating': rating,
            'season': season,
            'episode': episode,
            'timestamp': time(),
            'retries': 0
        }

        return self._enqueue(request)

    def _enqueue(self, request):
        """
        Thread-safe pridanie requestu do fronty

        Args:
            request: Dict s request údajmi

        Returns:
            bool: True ak sa podarilo pridať, False ak je fronta plná
        """
        try:
            with self.lock:
                if len(self.queue) >= self.MAX_QUEUE_SIZE:
                    debug('TraktQueueService: Queue full ({} items), dropping oldest request'.format(
                        self.MAX_QUEUE_SIZE))
                    # deque s maxlen automaticky dropne najstarší item

                self.queue.append(request)
                queue_size = len(self.queue)

            debug('TraktQueueService: Enqueued {} request (queue size: {})'.format(
                request['type'], queue_size))

            # Automaticky ulož frontu (persistence)
            self._save_queue()

            return True
        except Exception as e:
            debug('TraktQueueService: Error enqueueing request: {}'.format(e))
            return False

    def process_queue(self):
        """
        Spracuje frontu - volá sa periodicky zo service.py

        Kontroluje:
        - Rate limit (čaká ak je aktívny)
        - Interval (neprocessuje príliš často)
        - Processing flag (neprekrýva sa)

        Returns:
            int: Počet spracovaných requestov
        """
        # Skontroluj či už nie je processing aktívny
        if self.is_processing:
            return 0

        # Skontroluj rate limit
        now = time()
        if now < self.rate_limit_until:
            remaining = int(self.rate_limit_until - now)
            if remaining > 0 and remaining % 10 == 0:  # Log každých 10s
                debug('TraktQueueService: Rate limited, waiting {}s'.format(remaining))
            return 0

        # Skontroluj interval (neprocessujeme príliš často)
        if now - self.last_process_time < self.PROCESS_INTERVAL:
            return 0

        # Skontroluj či je fronta prázdna
        with self.lock:
            if not self.queue:
                return 0

        self.is_processing = True
        processed_count = 0

        try:
            # Spracuj max 5 requestov za jeden cyklus
            max_batch = 5

            for _ in range(max_batch):
                # Získaj ďalší request z fronty
                request = None
                with self.lock:
                    if self.queue:
                        request = self.queue.popleft()

                if not request:
                    break

                # Spracuj request
                success = self._process_request(request)

                if success is True:
                    processed_count += 1
                    debug('TraktQueueService: Successfully processed {} request'.format(request['type']))
                elif success == 'skip':
                    # Špeciálna hodnota 'skip' - validačná chyba, dropni bez retry
                    processed_count += 1  # Počítame ako spracovaný
                    debug('TraktQueueService: Skipping {} request - validation error, will not retry'.format(
                        request['type']))
                else:
                    # Neúspešný request (False) - pridaj späť do fronty ak má retry
                    request['retries'] = request.get('retries', 0) + 1

                    if request['retries'] < self.MAX_RETRIES:
                        debug('TraktQueueService: Retrying {} request (attempt {}/{})'.format(
                            request['type'], request['retries'], self.MAX_RETRIES))

                        with self.lock:
                            self.queue.append(request)
                    else:
                        # Po MAX_RETRIES presuň do odloženej fronty
                        debug('TraktQueueService: Moving {} request to deferred queue after {} retries'.format(
                            request['type'], self.MAX_RETRIES))

                        # Reset počítadla retry pre odloženú frontu
                        request['retries'] = 0
                        request['deferred_at'] = time()

                        with self.lock:
                            self.deferred_queue.append(request)

                # Krátka pauza medzi requestami (rate limit friendly)
                sleep(0.5)

            # Update last process time
            self.last_process_time = time()

            # Ulož frontu po spracovaní
            if processed_count > 0:
                self._save_queue()

            return processed_count

        except Exception as e:
            debug('TraktQueueService: Error processing queue: {}'.format(e))
            debug('TraktQueueService: Traceback: {}'.format(traceback.format_exc()))
            return processed_count

        finally:
            self.is_processing = False

    def process_deferred_queue(self):
        """
        Spracuje odloženú frontu - volá sa periodicky zo service.py

        Odložené requesty sa spracúvajú menej často (každých 5 minút)
        a majú viac pokusov (MAX_DEFERRED_RETRIES).

        Returns:
            int: Počet spracovaných requestov
        """
        # Skontroluj či už nie je processing aktívny
        if self.is_processing:
            return 0

        # Skontroluj rate limit
        now = time()
        if now < self.rate_limit_until:
            return 0

        # Skontroluj interval (každých 5 minút)
        if now - self.last_deferred_process_time < self.DEFERRED_RETRY_INTERVAL:
            return 0

        # Skontroluj či je odložená fronta prázdna
        with self.lock:
            if not self.deferred_queue:
                return 0

        debug('TraktQueueService: Processing deferred queue ({} items)'.format(len(self.deferred_queue)))

        self.is_processing = True
        processed_count = 0

        try:
            # Spracuj max 10 requestov z odloženej fronty za jeden cyklus
            max_batch = 10

            for _ in range(max_batch):
                # Získaj ďalší request z odloženej fronty
                request = None
                with self.lock:
                    if self.deferred_queue:
                        request = self.deferred_queue.popleft()

                if not request:
                    break

                # Spracuj request
                success = self._process_request(request)

                if success is True:
                    processed_count += 1
                    debug('TraktQueueService: Successfully processed deferred {} request'.format(request['type']))
                elif success == 'skip':
                    # Špeciálna hodnota 'skip' - validačná chyba, dropni bez retry
                    processed_count += 1  # Počítame ako spracovaný
                    debug('TraktQueueService: Skipping deferred {} request - validation error, will not retry'.format(
                        request['type']))
                else:
                    # Neúspešný request (False) - pridaj späť do odloženej fronty ak má retry
                    request['retries'] = request.get('retries', 0) + 1

                    if request['retries'] < self.MAX_DEFERRED_RETRIES:
                        debug('TraktQueueService: Retrying deferred {} request (attempt {}/{})'.format(
                            request['type'], request['retries'], self.MAX_DEFERRED_RETRIES))

                        with self.lock:
                            self.deferred_queue.append(request)
                    else:
                        # Ani odložená fronta nepomohla - definitívne drop
                        debug('TraktQueueService: Dropping deferred {} request after {} retries (total {} attempts)'.format(
                            request['type'], self.MAX_DEFERRED_RETRIES, self.MAX_RETRIES + self.MAX_DEFERRED_RETRIES))

                # Krátka pauza medzi requestami (rate limit friendly)
                sleep(0.5)

            # Update last process time
            self.last_deferred_process_time = time()

            # Ulož frontu po spracovaní
            if processed_count > 0:
                self._save_queue()

            return processed_count

        except Exception as e:
            debug('TraktQueueService: Error processing deferred queue: {}'.format(e))
            debug('TraktQueueService: Traceback: {}'.format(traceback.format_exc()))
            return processed_count

        finally:
            self.is_processing = False

    def _process_request(self, request):
        """
        Spracuje jednotlivý request

        Args:
            request: Dict s request údajmi

        Returns:
            bool: True ak bol request úspešný
        """
        try:
            request_type = request['type']

            if request_type == 'scrobble':
                return self._process_scrobble(request)
            elif request_type == 'sync_history':
                return self._process_sync_history(request)
            elif request_type == 'rating':
                return self._process_rating(request)
            else:
                debug('TraktQueueService: Unknown request type: {}'.format(request_type))
                return False

        except Exception as e:
            debug('TraktQueueService: Error processing request: {}'.format(e))
            debug('TraktQueueService: Traceback: {}'.format(traceback.format_exc()))
            return False

    def _process_scrobble(self, request):
        """
        Spracuje scrobble request

        Returns:
            bool or str: True = success, False = retry, 'skip' = drop without retry
        """
        from resources.lib.trakt.Trakt import trakt

        try:
            # Priprav kwargs pre episode ak je to show
            kwargs = {}
            if request['season'] is not None:
                kwargs['episode'] = {
                    'season': request['season'],
                    'number': request['episode']
                }

            # Zavolaj správnu scrobble metódu podľa action
            action = request['action']
            if action == 'start':
                result = trakt.api.scrobble.start(
                    item_type=request['item_type'],
                    item_id=request['trakt_id'],
                    progress=request['percent'],
                    **kwargs
                )
            elif action == 'pause':
                result = trakt.api.scrobble.pause(
                    item_type=request['item_type'],
                    item_id=request['trakt_id'],
                    progress=request['percent'],
                    **kwargs
                )
            else:  # stop
                result = trakt.api.scrobble.stop(
                    item_type=request['item_type'],
                    item_id=request['trakt_id'],
                    progress=request['percent'],
                    **kwargs
                )

            # Skontroluj či je response rate limited
            if isinstance(result, dict) and result.get('rate_limited'):
                self._handle_rate_limit(result.get('retry_after', 60))
                return False

            # result je None keď API vráti chybu (HTTP 422, 404, atď.)
            # Validačné chyby (progress < 1%) sa už filtrujú v enqueue_scrobble(),
            # ale ak nejaká prejde, logujeme a skipujeme retry
            if result is None:
                debug('TraktQueueService: Scrobble {} returned None - likely validation error (HTTP 422?), skipping retry'.format(action))
                return 'skip'  # Špeciálna hodnota - drop bez retry

            return result is not None

        except Exception as e:
            debug('TraktQueueService: Scrobble error: {}'.format(e))
            debug('TraktQueueService: Traceback: {}'.format(traceback.format_exc()))
            return False

    def _process_sync_history(self, request):
        """Spracuje sync/history request"""
        from resources.lib.trakt.Trakt import trakt

        try:
            if request['remove']:
                result = trakt.api.sync.remove_from_history(request['items'])
            else:
                result = trakt.api.sync.add_to_history(request['items'])

            # Skontroluj rate limit
            if isinstance(result, dict) and result.get('rate_limited'):
                self._handle_rate_limit(result.get('retry_after', 60))
                return False

            return result is not None

        except Exception as e:
            debug('TraktQueueService: Sync history error: {}'.format(e))
            return False

    def _process_rating(self, request):
        """Spracuje rating request"""
        from resources.lib.trakt.Trakt import trakt

        try:
            # TODO: Implementovať rating API call
            # Teraz len placeholder
            debug('TraktQueueService: Rating not implemented yet')
            return True

        except Exception as e:
            debug('TraktQueueService: Rating error: {}'.format(e))
            return False

    def _handle_rate_limit(self, retry_after):
        """
        Nastaví rate limit flag

        Args:
            retry_after: Počet sekúnd čakania
        """
        self.rate_limit_until = time() + retry_after
        debug('TraktQueueService: Rate limited, pausing queue for {}s'.format(retry_after))

    def get_queue_size(self):
        """Vráti aktuálnu veľkosť hlavnej fronty"""
        with self.lock:
            return len(self.queue)

    def get_deferred_queue_size(self):
        """Vráti aktuálnu veľkosť odloženej fronty"""
        with self.lock:
            return len(self.deferred_queue)

    def clear_queue(self, include_deferred=False):
        """
        Vymaže všetky pending requesty (použiť opatrne!)

        Args:
            include_deferred: Ak True, vymaže aj odloženú frontu
        """
        with self.lock:
            self.queue.clear()
            if include_deferred:
                self.deferred_queue.clear()

        self._save_queue()
        debug('TraktQueueService: Queue cleared (deferred: {})'.format(include_deferred))


# Singleton instance
trakt_queue_service = TraktQueueService()
