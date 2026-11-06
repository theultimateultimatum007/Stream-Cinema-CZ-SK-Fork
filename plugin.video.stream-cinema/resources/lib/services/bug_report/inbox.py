# -*- coding: utf-8 -*-
"""
Bug report inbox — zapis z plugin procesu do SQLite inbox.

Plugin proces a service proces nezdieľajú pamäť. Táto funkcia zapíše
payload do SQLite Storage pod UUID kľúč. Service proces ho zdvihne
cez BugReportQueueService.drain_inbox() v nasledujúcom cykle.

PREČO UUID (nie client_dedupe_hash) ako kľúč:
  Dva odlišné reporty so zhodným (category, media_id, description) by
  s hash-kľúčom tichto prepísali seba navzájom ešte pred drainom —
  napr. retry po prechodnom zlyhaní. Dedupe sa rieši pri enqueue do
  internej fronty (BugReportQueueService.enqueue), NIE na úrovni inboxu.

Sieťové volanie sa tu NEVYKONÁVA.
"""

from __future__ import print_function, unicode_literals

import uuid

from resources.lib.common.logger import debug
from resources.lib.common.storage import Storage, mark_dirty
from resources.lib.constants import SC


def enqueue_report(payload):
    """Zapíše report payload do cross-process SQLite inbox.

    Args:
        payload (dict): Zostavený report payload (výstup build_payload).

    Returns:
        str: UUID kľúč pod ktorým bol report uložený.
    """
    storage = Storage(SC.BUG_REPORT_INBOX)
    key = uuid.uuid4().hex
    storage[key] = payload
    mark_dirty(SC.BUG_REPORT_INBOX)
    debug('BugReport: inbox enqueued key={}'.format(key))
    return key
