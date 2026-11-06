# -*- coding: utf-8 -*-
"""
Bug report transport — odošle payload na backend endpoint.

NESMIE používať Sc.post() — zahadzuje HTTP status (sc.py:132) a Http.request
prehĺta HTTPError (system.py:71-73), takže non-200 JSON vyzerá ako úspech.
Namiesto toho volá Http.post() priamo a číta res.status_code == 200.

INVARIANT: kra.sk token ide IBA v hlavičke X-AUTH-TOKEN (cez Sc.headers()),
           NIKDY v tele payloadu.
"""

from __future__ import print_function, unicode_literals

from resources.lib.common.logger import debug
from resources.lib.api.sc import Sc
from resources.lib.system import Http
from resources.lib.constants import SC


def send_report(payload, timeout=None):
    """Odošle bug report payload POST-om na backend.

    Získa URL + default params cez Sc.prepare(), pridá token ako hlavičku
    X-AUTH-TOKEN, odošle Json body. Úspech = striktne HTTP 200.
    Akákoľvek výnimka (offline, timeout, parse error) → vráti False.

    Args:
        payload (dict): Zostavený report payload (bez tokenu v tele).
        timeout (int|float|None): Timeout v sekundách pre requests.
                                   None = použije Http.TIMEOUT default (10 s).
                                   Hybrid volá s SC.BUG_REPORT_SYNC_TIMEOUT (~5 s).

    Returns:
        bool: True ak server vrátil HTTP 200, inak False.
    """
    try:
        sorted_values, url = Sc.prepare(params={}, path=SC.REPORT_BUG_PATH)
        kwargs = {
            'params': sorted_values,
            'json': payload,
            'headers': Sc.headers(),
        }
        if timeout is not None:
            kwargs['timeout'] = timeout

        res = Http.post(url, **kwargs)
        success = (res.status_code == 200)
        debug('BugReport: transport POST {} → {}'.format(url, res.status_code))
        return success
    except Exception as e:
        debug('BugReport: transport exception → False: {}'.format(e))
        return False
