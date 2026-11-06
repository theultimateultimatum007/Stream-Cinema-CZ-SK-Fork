# -*- coding: utf-8 -*-
"""
BugReportQueueService — perzistentná fronta pre odosielanie bug reportov.

Klon TraktQueueService (trakt_queue.py:22-567) s týmito odlišnosťami:
- _process_request volá transport.send_report namiesto Trakt API
- drain_inbox() prenáša reporty z cross-process SQLite inbox do in-memory fronty
  KRITICKÉ FIX #1: load(True) na ZAČIATKU každého drain cyklu (cache-trap)
  KRITICKÉ FIX #6: del len prenesených kľúčov, NIKDY whole-namespace clear (clear-race)
- soft dedupe pri enqueue podľa client_dedupe_hash
"""

from __future__ import print_function, unicode_literals

import threading
import traceback
from time import time, sleep
from collections import deque

from resources.lib.common.logger import debug
from resources.lib.common.storage import Storage, get_dirty
from resources.lib.constants import SC


class BugReportQueueService(object):
    """Background service pre odosielanie bug reportov vo fronte."""

    MAX_QUEUE_SIZE = 50
    MAX_DEFERRED_SIZE = 200
    PROCESS_INTERVAL = 10         # sekundy medzi spracovaním (bug reporty sú zriedkavé)
    DEFERRED_RETRY_INTERVAL = 300  # 5 minút
    MAX_RETRIES = 3
    MAX_DEFERRED_RETRIES = 10

    def __init__(self):
        self.queue = deque(maxlen=self.MAX_QUEUE_SIZE)
        self.deferred_queue = deque(maxlen=self.MAX_DEFERRED_SIZE)
        self.lock = threading.Lock()
        self.storage = Storage(SC.BUG_REPORT_QUEUE)
        self.inbox_storage = Storage(SC.BUG_REPORT_INBOX)
        self.is_processing = False
        self.last_process_time = 0
        self.last_deferred_process_time = 0
        self.rate_limit_until = 0
        # Množina hashov reportov vo fronte / už odoslaných (soft dedupe)
        self._queued_hashes = set()
        # Cross-process dirty-marker gating pre drain_inbox (viz storage.get_dirty) —
        # None zaručuje 1 počiatočný load(True) pri prvom draine po štarte service.
        self._inbox_last_dirty = None

        self._load_queue()
        debug('BugReportQueueService: Initialized with {} pending, {} deferred'.format(
            len(self.queue), len(self.deferred_queue)))

    # ------------------------------------------------------------------
    # Persistencia (vzor TraktQueueService._save_queue / _load_queue)
    # ------------------------------------------------------------------

    def _load_queue(self):
        """Načíta uloženú frontu zo storage (pri štarte / reštarte)."""
        try:
            self.storage.load(True)
            saved_queue = self.storage.get('pending_requests')
            if saved_queue:
                for item in saved_queue:
                    self.queue.append(item)
                    h = item.get('client_dedupe_hash')
                    if h:
                        self._queued_hashes.add(h)
                debug('BugReportQueueService: Loaded {} pending'.format(len(saved_queue)))

            saved_deferred = self.storage.get('deferred_requests')
            if saved_deferred:
                for item in saved_deferred:
                    self.deferred_queue.append(item)
                    h = item.get('client_dedupe_hash')
                    if h:
                        self._queued_hashes.add(h)
                debug('BugReportQueueService: Loaded {} deferred'.format(len(saved_deferred)))
        except Exception as e:
            debug('BugReportQueueService: Error loading queue: {}'.format(e))

    def _save_queue(self):
        """Uloží frontu do storage (persistencia pri reštarte)."""
        try:
            with self.lock:
                queue_list = list(self.queue)
                deferred_list = list(self.deferred_queue)

            self.storage['pending_requests'] = queue_list
            self.storage['deferred_requests'] = deferred_list
            self.storage.save()
            debug('BugReportQueueService: Saved {} pending, {} deferred'.format(
                len(queue_list), len(deferred_list)))
        except Exception as e:
            debug('BugReportQueueService: Error saving queue: {}'.format(e))

    # ------------------------------------------------------------------
    # Enqueue (z drain_inbox alebo priameho volania)
    # ------------------------------------------------------------------

    def enqueue(self, payload):
        """Pridá report do fronty so soft dedupe podľa client_dedupe_hash.

        Args:
            payload (dict): Report payload (musí obsahovať 'client_dedupe_hash').

        Returns:
            bool: True ak pridaný alebo duplikát (idempotentné), False pri chybe.
        """
        try:
            dedupe_hash = payload.get('client_dedupe_hash', '')
            with self.lock:
                if dedupe_hash and dedupe_hash in self._queued_hashes:
                    debug('BugReportQueueService: Skipping duplicate hash {}'.format(
                        dedupe_hash[:8]))
                    return True

                request = dict(payload)
                request['retries'] = 0
                request['timestamp'] = time()
                self.queue.append(request)
                if dedupe_hash:
                    self._queued_hashes.add(dedupe_hash)
                queue_size = len(self.queue)

            debug('BugReportQueueService: Enqueued report (queue size: {})'.format(queue_size))
            self._save_queue()
            return True
        except Exception as e:
            debug('BugReportQueueService: Error enqueueing: {}'.format(e))
            return False

    # ------------------------------------------------------------------
    # Drain inbox (cross-process, FIX #1 + #6)
    # ------------------------------------------------------------------

    def drain_inbox(self):
        """Prenesie reporty z SQLite inbox (plugin proces) do internej fronty.

        FIX #1 — cache-trap: Storage.load(False) vracia modul-globálnu cache
        a nikdy znova nečíta DB (storage.py:275-278). Preto MUSÍ volať load(True)
        na ZAČIATKU cyklu keď inbox writer bumpol cross-process marker (viz
        storage.mark_dirty/get_dirty), inak service nikdy nezdvihne reporty
        zapísané pluginom po štarte service. Prvý drain po štarte service
        vždy vykoná load(True) (self._inbox_last_dirty začína ako None).

        FIX #6 — clear-race: Storage.save() prepisuje celý namespace blob
        (storage.py:270). Blind clear po draine by zmazal report zapísaný
        pluginom počas drain-okna. Preto mažeme IBA prenesené kľúče cez
        __delitem__, NIKDY whole-namespace clear. Toto druhé load(True)
        (tesne pred mazaním) je NEPODMIENENÉ markerom - beží vždy na tejto ceste.
        """
        try:
            # FIX #1 + dirty-marker gate: force re-read len pri zmene markera
            # (alebo pri prvom draine po štarte service) — defeats storage cache-trap
            # bez zbytočného SQLite čítania keď plugin nič nezapísal.
            _current_dirty = get_dirty(SC.BUG_REPORT_INBOX)
            if _current_dirty != self._inbox_last_dirty:
                self.inbox_storage.load(True)
                self._inbox_last_dirty = _current_dirty
            inbox_data = dict(self.inbox_storage.data)

            if not inbox_data:
                return

            transferred_keys = []
            for key, payload in inbox_data.items():
                if not isinstance(payload, dict):
                    continue
                # Idempotentný prenos — enqueue robí soft dedupe podľa hash
                if self.enqueue(payload):
                    transferred_keys.append(key)

            if not transferred_keys:
                return

            # FIX #6: znova načítaj čerstvý snapshot tesne pred mazaním
            # aby sme videli prípadné nové kľúče zapísané pluginom počas transferu
            self.inbox_storage.load(True)

            # Zmaž IBA prenesené kľúče — nikdy whole-namespace clear
            # TOCTOU okno: ak plugin zapíše nový kľúč medzi týmto load(True)
            # a nasledujúcimi __delitem__ volaniami, ten kľúč zostane netknutý.
            # Storage.__delitem__ interne volá save() = full-blob rewrite.
            # Ak by plugin zapísal kľúč medzi dvoma po sebe idúcimi __delitem__
            # volaniami, mohol by byť prepísaný. Pravdepodobnosť je veľmi nízka
            # pri zriedkavých manuálnych reportoch (akceptované v1 — Open Question).
            for key in transferred_keys:
                try:
                    del self.inbox_storage[key]
                except Exception as del_err:
                    debug('BugReportQueueService: drain del key {} failed: {}'.format(
                        key, del_err))

            debug('BugReportQueueService: drain_inbox transferred {} reports'.format(
                len(transferred_keys)))

        except Exception as e:
            debug('BugReportQueueService: drain_inbox error: {}'.format(e))

    # ------------------------------------------------------------------
    # Spracovanie fronty (vzor TraktQueueService.process_queue)
    # ------------------------------------------------------------------

    def process_queue(self):
        """Spracuje hlavnú frontu — volá sa periodicky zo service.py.

        Returns:
            int: Počet úspešne spracovaných reportov.
        """
        if self.is_processing:
            return 0

        now = time()
        if now < self.rate_limit_until:
            return 0
        if now - self.last_process_time < self.PROCESS_INTERVAL:
            return 0

        with self.lock:
            if not self.queue:
                return 0

        self.is_processing = True
        processed_count = 0

        try:
            max_batch = 5
            for _ in range(max_batch):
                request = None
                with self.lock:
                    if self.queue:
                        request = self.queue.popleft()

                if not request:
                    break

                success = self._process_request(request)

                if success is True:
                    processed_count += 1
                    h = request.get('client_dedupe_hash', '')
                    with self.lock:
                        self._queued_hashes.discard(h)
                    debug('BugReportQueueService: Sent report OK')
                else:
                    request['retries'] = request.get('retries', 0) + 1
                    if request['retries'] < self.MAX_RETRIES:
                        debug('BugReportQueueService: Retry {}/{}'.format(
                            request['retries'], self.MAX_RETRIES))
                        with self.lock:
                            self.queue.append(request)
                    else:
                        debug('BugReportQueueService: Moving to deferred after {} retries'.format(
                            self.MAX_RETRIES))
                        request['retries'] = 0
                        request['deferred_at'] = time()
                        with self.lock:
                            self.deferred_queue.append(request)

                sleep(0.5)

            self.last_process_time = time()
            if processed_count > 0:
                self._save_queue()

            return processed_count

        except Exception as e:
            debug('BugReportQueueService: process_queue error: {}'.format(e))
            debug(traceback.format_exc())
            return processed_count
        finally:
            self.is_processing = False

    def process_deferred_queue(self):
        """Spracuje odloženú frontu — volá sa menej často (každých 5 minút).

        Returns:
            int: Počet úspešne spracovaných reportov.
        """
        if self.is_processing:
            return 0

        now = time()
        if now < self.rate_limit_until:
            return 0
        if now - self.last_deferred_process_time < self.DEFERRED_RETRY_INTERVAL:
            return 0

        with self.lock:
            if not self.deferred_queue:
                return 0

        debug('BugReportQueueService: Processing deferred queue ({} items)'.format(
            len(self.deferred_queue)))

        self.is_processing = True
        processed_count = 0

        try:
            max_batch = 10
            for _ in range(max_batch):
                request = None
                with self.lock:
                    if self.deferred_queue:
                        request = self.deferred_queue.popleft()

                if not request:
                    break

                success = self._process_request(request)

                if success is True:
                    processed_count += 1
                    h = request.get('client_dedupe_hash', '')
                    with self.lock:
                        self._queued_hashes.discard(h)
                    debug('BugReportQueueService: Deferred report sent OK')
                else:
                    request['retries'] = request.get('retries', 0) + 1
                    if request['retries'] < self.MAX_DEFERRED_RETRIES:
                        debug('BugReportQueueService: Deferred retry {}/{}'.format(
                            request['retries'], self.MAX_DEFERRED_RETRIES))
                        with self.lock:
                            self.deferred_queue.append(request)
                    else:
                        debug('BugReportQueueService: Dropping deferred report after {} retries'.format(
                            self.MAX_DEFERRED_RETRIES))
                        h = request.get('client_dedupe_hash', '')
                        with self.lock:
                            self._queued_hashes.discard(h)

                sleep(0.5)

            self.last_deferred_process_time = time()
            if processed_count > 0:
                self._save_queue()

            return processed_count

        except Exception as e:
            debug('BugReportQueueService: process_deferred_queue error: {}'.format(e))
            debug(traceback.format_exc())
            return processed_count
        finally:
            self.is_processing = False

    # ------------------------------------------------------------------
    # Interné spracovanie requestu
    # ------------------------------------------------------------------

    def _process_request(self, request):
        """Odošle jeden request cez transport.

        Returns:
            bool: True = úspech (HTTP 200), False = retry.
        """
        try:
            from resources.lib.services.bug_report.transport import send_report
            return send_report(request)
        except Exception as e:
            debug('BugReportQueueService: _process_request error: {}'.format(e))
            return False

    def get_queue_size(self):
        with self.lock:
            return len(self.queue)

    def get_deferred_queue_size(self):
        with self.lock:
            return len(self.deferred_queue)


# Singleton — importovaný zo service.py
bug_report_queue_service = BugReportQueueService()
