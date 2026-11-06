# -*- coding: utf-8 -*-
"""Voliteľný pamäťový profiler pre diagnostiku spotreby RAM doplnku.

Používa štandardný modul ``tracemalloc`` (Python 3.4+). Doplnky v Kodi bežia
ako vlákna v jednom procese a zdieľajú jeden natívny heap, takže OS nástroje
(``dumpsys meminfo``, ``/proc``) nevedia povedať, ktorý modul koľko RAM drží.
``tracemalloc`` to vie — sleduje alokácie priamo v Pythone a zoskupí ich podľa
súboru/riadku.

Profiler je vypnutý (``MEM_PROFILER_ENABLED = False`` v constants.py), pretože
sledovanie alokácií má réžiu (spomalí alokácie, drží traceboky v pamäti).
Zapínať LEN pri diagnostike spotreby RAM.

Výstup ide cez ``info()`` (LOGINFO), aby bol viditeľný aj bez debug logovania.
Hľadaj v logu prefix ``[SC] [MemProfiler]``.
"""
from __future__ import print_function, unicode_literals

import gc

try:
    import tracemalloc
except ImportError:  # Python 2 (Kodi <19) — profiler nie je dostupný
    tracemalloc = None

from resources.lib.common.logger import info


class MemProfiler:
    """Tenký obal nad tracemalloc: TOP alokácie + rast od štartu (leak)."""

    def __init__(self, top_count=15, stack_depth=1):
        # stack_depth=1 = len riadok, kde sa alokovalo (najnižšia réžia).
        # Zvýš na 5–10, ak potrebuješ vidieť, KTO daný riadok zavolal.
        self._top_count = top_count
        self._stack_depth = stack_depth
        self._started = False
        self._baseline = None

    def start(self):
        if self._started:
            return
        if tracemalloc is None:
            info('[MemProfiler] tracemalloc nie je dostupny (Python 2) — vynechavam')
            return
        tracemalloc.start(self._stack_depth)
        self._baseline = tracemalloc.take_snapshot()
        self._started = True
        info('[MemProfiler] spusteny (stack_depth={}, baseline ulozeny)'.format(self._stack_depth))

    def stop(self):
        if self._started and tracemalloc is not None:
            tracemalloc.stop()
        self._started = False
        self._baseline = None

    def _snapshot(self):
        gc.collect()
        snap = tracemalloc.take_snapshot()
        # Odfiltruj šum samotného profilera a import mašinérie.
        return snap.filter_traces((
            tracemalloc.Filter(False, tracemalloc.__file__),
            tracemalloc.Filter(False, '<frozen importlib._bootstrap>'),
            tracemalloc.Filter(False, '<frozen importlib._bootstrap_external>'),
            tracemalloc.Filter(False, '<unknown>'),
        ))

    def log_top(self):
        """Vypíše TOP alokácie zoskupené podľa súboru — kto práve drží pamäť."""
        if not self._started:
            return
        snap = self._snapshot()
        stats = snap.statistics('filename')
        current, peak = tracemalloc.get_traced_memory()
        info('[MemProfiler] ==== TOP {} suborov podla RAM (current={:.1f}MB peak={:.1f}MB) ===='.format(
            self._top_count, current / 1048576.0, peak / 1048576.0))
        for i, stat in enumerate(stats[:self._top_count], 1):
            frame = stat.traceback[0]
            info('[MemProfiler] #{:<2} {:8.1f} KB  {} ({} blokov)'.format(
                i, stat.size / 1024.0, _short(frame.filename), stat.count))

    def log_growth(self):
        """Porovná aktuálny stav s baseline — kladný rast = podozrenie na leak."""
        if not self._started or self._baseline is None:
            return
        snap = self._snapshot()
        stats = snap.compare_to(self._baseline, 'filename')
        grown = [s for s in stats if s.size_diff > 0][:self._top_count]
        if not grown:
            info('[MemProfiler] ==== RAST od startu: ziadny ====')
            return
        info('[MemProfiler] ==== RAST od startu (TOP {}) — sleduj, ci stale stupa ===='.format(len(grown)))
        for stat in grown:
            frame = stat.traceback[0]
            info('[MemProfiler] +{:8.1f} KB  ({:+d} blokov)  {}'.format(
                stat.size_diff / 1024.0, stat.count_diff, _short(frame.filename)))


def _short(path):
    """Skráti absolútnu cestu pre čitateľnosť v logu.

    Náš kód → od ``plugin.video.stream-cinema/...``; cudzí/stdlib kód → posledné
    dve zložky cesty (napr. ``json/decoder.py``), nech je jasné, odkiaľ alokácia je.
    """
    marker = 'plugin.video.stream-cinema'
    idx = path.find(marker)
    if idx != -1:
        return path[idx:]
    parts = path.replace('\\', '/').rsplit('/', 2)
    return '/'.join(parts[-2:]) if len(parts) >= 2 else path


mem_profiler = MemProfiler()
