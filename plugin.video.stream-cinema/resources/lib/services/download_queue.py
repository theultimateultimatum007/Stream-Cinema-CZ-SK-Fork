# -*- coding: utf-8 -*-
"""
Download Queue Service - fronta pre sťahovanie na pozadí

Sťahovania sa neodmietajú, ale zaradia sa do fronty a service ich spracováva
na pozadí (max MAX_CONCURRENT súčasne, zvyšok čaká vo fronte). Prebieha retry
s backoffom, stav sa dá pozrieť v dialógu fronty (Nastavenia → Fronta sťahovania).

Architektúra (rovnaký vzor ako trakt_queue / bug_report queue):
- PLUGIN proces: enqueue() + dialóg fronty → zapisuje IBA 'inbox' a 'commands'
- SERVICE proces: process_queue() v hlavnej slücke → výhradne spravuje 'jobs',
  drainuje inbox/commands, spúšťa worker thread-y
- Storage (SQLite) je zdieľaný medzi procesmi, sync cez mark_dirty/get_dirty
  (kontrakt viz common/storage.py - service si svoje zápisy neoznačuje dirty,
  plugin číta jobs vždy cez load(True))
"""

from __future__ import print_function, unicode_literals

import threading
import traceback
from time import time
from uuid import uuid4

from resources.lib.common.logger import debug
from resources.lib.common.storage import Storage, mark_dirty, get_dirty

QUEUE_STORAGE = 'download_queue'


class DownloadQueueService:
    MAX_QUEUE_SIZE = 50   # max počet aktívnych jobov (pending + downloading)
    MAX_CONCURRENT = 3    # max súčasných sťahovaní
    MAX_RETRIES = 3       # max pokusov na job
    RETRY_DELAY = 60      # backoff (s) pred ďalším pokusom
    KEEP_HISTORY = 20     # koľko hotových/chybových jobov držať v histórii

    STATUS_PENDING = 'pending'
    STATUS_DOWNLOADING = 'downloading'
    STATUS_DONE = 'done'
    STATUS_ERROR = 'error'

    def __init__(self):
        self.lock = threading.Lock()
        self.storage = Storage(QUEUE_STORAGE)
        self.workers = {}      # job_id -> Thread
        self._cancelled = set()  # job_id s bežiacim workerom, ktoré sa majú zrušiť
        self._last_dirty = None

    # ------------------------------------------------------------------
    # PLUGIN strana (zápis len do inbox/commands, čítanie jobs)
    # ------------------------------------------------------------------

    def enqueue(self, url, dest, name):
        """Zaradí sťahovanie do fronty (volá plugin proces).

        Returns:
            str: 'added' | 'duplicate' | 'full'
        """
        try:
            with self.lock:
                self.storage.load(True)  # fresh read - dáta píše service proces
                inbox = self.storage.get('inbox') or []
                jobs = self.storage.get('jobs') or []

                job = {
                    'id': uuid4().hex,
                    'url': url,
                    'dest': dest,
                    'name': name,
                    'status': self.STATUS_PENDING,
                    'retries': 0,
                    'next_retry_at': 0,
                    'added_at': time(),
                    'started_at': None,
                    'finished_at': None,
                    'error': None,
                }

                if self._is_duplicate(job, inbox + jobs):
                    debug('DownloadQueue: duplicate - {}'.format(name))
                    return 'duplicate'

                if self._active_count(jobs) + len(inbox) >= self.MAX_QUEUE_SIZE:
                    debug('DownloadQueue: fronta je plná - {}'.format(name))
                    return 'full'

                inbox.append(job)
                self.storage['inbox'] = inbox

            mark_dirty(QUEUE_STORAGE)
            debug('DownloadQueue: enqueued {} (inbox: {})'.format(name, len(inbox)))
            return 'added'
        except Exception:
            debug('DownloadQueue: enqueue err: {}'.format(traceback.format_exc()))
            return 'full'

    def get_queue(self):
        """Vráti kópiu aktuálnej fronty jobov (pre dialóg)."""
        try:
            with self.lock:
                self.storage.load(True)
                return list(self.storage.get('jobs') or [])
        except Exception:
            debug('DownloadQueue: get_queue err: {}'.format(traceback.format_exc()))
            return []

    def _push_command(self, command):
        """Pošle manažmentový príkaz service procesu (clear/remove)."""
        try:
            with self.lock:
                self.storage.load(True)
                commands = self.storage.get('commands') or []
                commands.append(command)
                self.storage['commands'] = commands
            mark_dirty(QUEUE_STORAGE)
            debug('DownloadQueue: command {} - {}'.format(command.get('op'), command.get('id')))
            return True
        except Exception:
            debug('DownloadQueue: push command err: {}'.format(traceback.format_exc()))
            return False

    # ------------------------------------------------------------------
    # SERVICE strana (výhradný správca 'jobs')
    # ------------------------------------------------------------------

    def process_queue(self):
        """Hlavné spracovanie fronty - volá service loop každých ~5 s."""
        try:
            self._resync_if_dirty()
            with self.lock:
                self._drain_inbox()
                self._drain_commands()
                self._start_workers()
        except Exception:
            debug('DownloadQueue: process err: {}'.format(traceback.format_exc()))

    def _resync_if_dirty(self):
        """Force-reload storage pri zmene cross-process markera."""
        dirty = get_dirty(QUEUE_STORAGE)
        if dirty != self._last_dirty:
            with self.lock:
                self.storage.load(True)
                self._last_dirty = dirty
                debug('DownloadQueue: resync (dirty={})'.format(dirty))

    def _drain_inbox(self):
        """Presunie nové joby z inboxu (plugin) do jobs (service)."""
        inbox = self.storage.get('inbox') or []
        if not inbox:
            return
        self.storage['inbox'] = []
        jobs = self.storage.get('jobs') or []
        added = 0
        for job in inbox:
            if self._is_duplicate(job, jobs):
                debug('DownloadQueue: inbox duplicate zahodený - {}'.format(job.get('name')))
                continue
            if self._active_count(jobs) >= self.MAX_QUEUE_SIZE:
                debug('DownloadQueue: inbox job zahodený - fronta plná')
                continue
            jobs.append(job)
            added += 1
        self._save_jobs(jobs)
        if added:
            debug('DownloadQueue: drained {} jobov z inboxu'.format(added))

    def _drain_commands(self):
        """Spracuje manažmentové príkazy z pluginu (clear/remove)."""
        commands = self.storage.get('commands') or []
        if not commands:
            return
        self.storage['commands'] = []
        jobs = self.storage.get('jobs') or []
        for cmd in commands:
            op = cmd.get('op')
            if op == 'clear_finished':
                jobs = [j for j in jobs
                        if j.get('status') in (self.STATUS_PENDING, self.STATUS_DOWNLOADING)]
            elif op == 'clear_all':
                for j in jobs:
                    if j.get('status') == self.STATUS_DOWNLOADING:
                        self._cancelled.add(j.get('id'))
                jobs = []
            elif op == 'remove' and cmd.get('id'):
                for j in jobs:
                    if j.get('id') == cmd.get('id') and j.get('status') == self.STATUS_DOWNLOADING:
                        self._cancelled.add(j.get('id'))
                jobs = [j for j in jobs if j.get('id') != cmd.get('id')]
            debug('DownloadQueue: command {} spracovaný'.format(op))
        self._save_jobs(jobs)

    def _start_workers(self):
        """Spustí workery pre pending joby do limitu MAX_CONCURRENT.

        Zároveň obnoví 'downloading' joby bez živého workera (reštart Kodi
        alebo umretý thread) - download() má resume, takže pokračuje od pozície.
        """
        for jid in list(self.workers.keys()):
            if not self.workers[jid].is_alive():
                del self.workers[jid]

        jobs = self.storage.get('jobs') or []
        now = time()
        changed = False
        active = len(self.workers)

        for job in jobs:
            status = job.get('status')
            jid = job.get('id')

            if status == self.STATUS_DOWNLOADING and jid not in self.workers:
                job['status'] = self.STATUS_PENDING
                job['next_retry_at'] = now + self.RETRY_DELAY
                changed = True
                debug('DownloadQueue: stale job obnovený do fronty - {}'.format(job.get('name')))
                continue

            if status == self.STATUS_PENDING and active < self.MAX_CONCURRENT \
                    and (job.get('next_retry_at') or 0) <= now:
                job['status'] = self.STATUS_DOWNLOADING
                job['started_at'] = now
                worker = threading.Thread(target=self._worker, args=(dict(job),))
                worker.daemon = True
                self.workers[jid] = worker
                worker.start()
                active += 1
                changed = True
                debug('DownloadQueue: worker start - {}'.format(job.get('name')))

        if changed:
            self._save_jobs(jobs)

    def _worker(self, job):
        """Worker thread - stiahne jeden job a updatne jeho stav."""
        from resources.lib.language import Strings

        jid = job['id']
        name = job.get('name')
        try:
            from resources.lib.kodiutils import download
            debug('DownloadQueue: sťahujem {} -> {}'.format(name, job.get('dest')))
            download(job['url'], job['dest'], name,
                     abort_check=lambda: jid in self._cancelled)
            self._update_job(jid, status=self.STATUS_DONE, finished_at=time(), error=None)
            self._notify(Strings.txt(Strings.DOWNLOAD_QUEUE),
                         '{}: {}'.format(Strings.txt(Strings.DOWNLOAD_FINISHED), name))
            debug('DownloadQueue: hotovo - {}'.format(name))
        except Exception as e:
            debug('DownloadQueue: worker err {}: {}'.format(name, traceback.format_exc()))
            self._retry_or_fail(jid, '{}'.format(e))
        finally:
            self._cancelled.discard(jid)

    def _update_job(self, jid, **updates):
        """Thread-safe update jobu podľa id. False ak job neexistuje (zrušený)."""
        with self.lock:
            jobs = self.storage.get('jobs') or []
            for job in jobs:
                if job.get('id') == jid:
                    job.update(updates)
                    self._save_jobs(jobs)
                    return True
            debug('DownloadQueue: job {} už neexistuje, update ignorovaný'.format(jid))
            return False

    def _retry_or_fail(self, jid, error):
        """Po chybe naplánuje retry, alebo označí job ako error."""
        from resources.lib.language import Strings

        failed_name = None
        with self.lock:
            jobs = self.storage.get('jobs') or []
            for job in jobs:
                if job.get('id') == jid:
                    retries = (job.get('retries') or 0) + 1
                    job['retries'] = retries
                    job['error'] = error
                    if retries <= self.MAX_RETRIES:
                        job['status'] = self.STATUS_PENDING
                        job['next_retry_at'] = time() + self.RETRY_DELAY
                        debug('DownloadQueue: retry {} ({}/{}) o {}s'.format(
                            job.get('name'), retries, self.MAX_RETRIES, self.RETRY_DELAY))
                    else:
                        job['status'] = self.STATUS_ERROR
                        job['finished_at'] = time()
                        failed_name = job.get('name')
                        debug('DownloadQueue: zlyhalo {} - {}'.format(failed_name, error))
                    break
            self._save_jobs(jobs)
        if failed_name:
            self._notify(Strings.txt(Strings.DOWNLOAD_QUEUE),
                         '{}: {}'.format(Strings.txt(Strings.DOWNLOAD_FAILED), failed_name))

    def _save_jobs(self, jobs):
        """Uloží jobs a ostriha históriu hotových/chybových jobov."""
        finished = sorted(
            [j for j in jobs if j.get('status') in (self.STATUS_DONE, self.STATUS_ERROR)],
            key=lambda j: j.get('finished_at') or 0)
        excess = len(finished) - self.KEEP_HISTORY
        if excess > 0:
            drop = set(j.get('id') for j in finished[:excess])
            jobs = [j for j in jobs if j.get('id') not in drop]
        self.storage['jobs'] = jobs

    @staticmethod
    def _active_count(jobs):
        return len([j for j in jobs
                    if j.get('status') in (DownloadQueueService.STATUS_PENDING,
                                           DownloadQueueService.STATUS_DOWNLOADING)])

    @staticmethod
    def _is_duplicate(job, jobs):
        for j in jobs:
            if j.get('dest') == job.get('dest') and j.get('name') == job.get('name') \
                    and j.get('status') in (DownloadQueueService.STATUS_PENDING,
                                            DownloadQueueService.STATUS_DOWNLOADING):
                return True
        return False

    @staticmethod
    def _notify(heading, message):
        try:
            from resources.lib.gui.dialog import dnotify
            dnotify(heading, message, time=5000, sound=False)
        except Exception:
            debug('DownloadQueue: notify err: {}'.format(traceback.format_exc()))


# Module-level singleton (rovnaký vzor ako trakt_queue_service) - každý proces
# (plugin aj service) má svoju inštanciu, dáta sa zdieľajú cez Storage.
download_queue_service = DownloadQueueService()


def show_queue_dialog():
    """Dialóg fronty sťahovania - zoznam jobov so stavmi + možnosti správy.

    Volá sa z pluginu (Nastavenia → Fronta sťahovania). Zmeny sa posielajú
    service procesu cez commands, takže dialóg nikdy nepíše do 'jobs'.
    """
    from resources.lib.gui.dialog import dselect, dyesno
    from resources.lib.language import Strings

    svc = download_queue_service
    while True:
        jobs = svc.get_queue()
        items = []
        acts = []

        if any(j.get('status') in (svc.STATUS_DONE, svc.STATUS_ERROR) for j in jobs):
            items.append(Strings.txt(Strings.DOWNLOAD_QUEUE_CLEAR_FINISHED))
            acts.append(('cmd', {'op': 'clear_finished'}))
        if jobs:
            items.append(Strings.txt(Strings.DOWNLOAD_QUEUE_CLEAR_ALL))
            acts.append(('cmd', {'op': 'clear_all'}))

        status_txt = {
            svc.STATUS_PENDING: Strings.txt(Strings.DOWNLOAD_STATUS_PENDING),
            svc.STATUS_DOWNLOADING: Strings.txt(Strings.DOWNLOAD_STATUS_DOWNLOADING),
            svc.STATUS_DONE: Strings.txt(Strings.DOWNLOAD_STATUS_DONE),
            svc.STATUS_ERROR: Strings.txt(Strings.DOWNLOAD_STATUS_ERROR),
        }
        for job in jobs:
            label = '[{}] {}'.format(status_txt.get(job.get('status'), '?'), job.get('name'))
            retries = job.get('retries') or 0
            if retries:
                label += ' ({}/{})'.format(retries, svc.MAX_RETRIES)
            items.append(label)
            acts.append(('job', job))

        if not jobs:
            items.append(Strings.txt(Strings.DOWNLOAD_QUEUE_EMPTY))
            acts.append(None)

        pos = dselect(items, heading=Strings.txt(Strings.DOWNLOAD_QUEUE))
        if pos < 0 or pos >= len(acts) or acts[pos] is None:
            return

        kind, payload = acts[pos]
        if kind == 'cmd':
            svc._push_command(payload)
        elif kind == 'job':
            if dyesno(Strings.txt(Strings.DOWNLOAD_QUEUE_REMOVE), payload.get('name')):
                svc._push_command({'op': 'remove', 'id': payload.get('id')})
