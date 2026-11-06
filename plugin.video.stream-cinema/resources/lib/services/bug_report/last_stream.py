# -*- coding: utf-8 -*-
"""
Bug Report — persistencia kontextu posledného úspešne prehraného streamu.

save_last_stream() musí byť volané na ZAČIATKU onAVStarted, PRED busy-wait
slučkou (player.py:239–245) — aby pomalý ale úspešný štart nevystrelil
false-positive ponuku (viď plán fix #5).

Volanie týchto funkcií z player.onAVStarted zabezpečuje worker-integration,
nie tento modul.
"""
from __future__ import print_function, unicode_literals

from resources.lib.common.storage import Storage
from resources.lib.constants import SC


def save_last_stream(stream_ctx):
    """Uloží kontext posledného streamu do perzistentného Storage.

    Args:
        stream_ctx (dict): stream kontext zo collect_stream() alebo z
            SELECTED_ITEM Window property.
    """
    try:
        storage = Storage(SC.BUG_REPORT_LAST_STREAM)
        storage['stream'] = stream_ctx
    except Exception:
        pass


def load_last_stream():
    """Načíta kontext posledného streamu z perzistentného Storage.

    Returns:
        dict | None: uložený stream kontext alebo None ak nie je k dispozícii.
    """
    try:
        storage = Storage(SC.BUG_REPORT_LAST_STREAM)
        return storage.get('stream')
    except Exception:
        return None
