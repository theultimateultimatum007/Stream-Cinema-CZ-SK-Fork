# -*- coding: utf-8 -*-
"""
Bug report payload builder.

Zodpovedný za zostavenie JSON tela reportu presne podľa Backend Contract.
INVARIANT: token / chsum / heslo sa NIKDY neobjavia v payloade.
           username sa pridá IBA ak include_username=True.
"""

from __future__ import print_function, unicode_literals


def build_payload(category, description, include_username, include_log,
                  stream_ctx, system_info, log_text):
    """Zostav payload podľa Backend Contract (spec r. 58-78).

    Args:
        category (str): Jedna z BUG_CAT_* konštánt (napr. 'stream_broken').
        description (str): Voľný popis chyby.
        include_username (bool): Priložiť kra.sk meno? (predvolene False).
        include_log (bool): Priložiť redigovaný log? (predvolene True).
        stream_ctx (dict|None): Výstup collector.collect_stream(), alebo None.
        system_info (dict): Výstup collector.collect_system().
        log_text (str|None): Redigovaný log tail, alebo None.

    Returns:
        dict: Payload pripravený na POST — bez tokenu/chsum/hesla.
    """
    _log_text = log_text if (include_log and log_text) else ''
    _log_lines = len(_log_text.splitlines())
    # Log zakódujeme (zlib + base64), aby ho WAF (Cloudflare) neblokoval kvôli
    # vzorom v texte. Backend dekóduje: gzuncompress(base64_decode(text)).
    if _log_text:
        from resources.lib.services.bug_report.redact import encode_log
        _log_encoded = encode_log(_log_text)
        _log_encoding = 'zlib+base64'
    else:
        _log_encoded = ''
        _log_encoding = 'none'
    payload = {
        'category': category,
        'description': description,
        'include_username': bool(include_username),
        'system': dict(system_info) if system_info else {},
        'stream': dict(stream_ctx) if stream_ctx else {'source': 'none'},
        'log': {
            'included': bool(include_log),
            # Log je vždy redigovaný pred priložením (redact.redact_log).
            'redacted': True,
            # 'zlib+base64' = text je zakódovaný (anti-WAF); 'none' = prázdny.
            'encoding': _log_encoding,
            'lines': _log_lines,
            'text': _log_encoded,
        },
    }

    # username len ak používateľ výslovne súhlasí
    if include_username:
        from resources.lib.kodiutils import get_setting
        payload['username'] = get_setting('kraska.user') or ''
    else:
        # Pole je prítomné ale prázdne — backend vie rozlíšiť stav
        payload['username'] = ''

    # client_dedupe_hash musí byť v payloade aby ho backend mohol použiť
    if stream_ctx and 'client_dedupe_hash' in stream_ctx:
        payload['client_dedupe_hash'] = stream_ctx['client_dedupe_hash']
    else:
        # Zostav hash priamo z dostupných polí
        from resources.lib.services.bug_report.collector import build_dedupe_hash
        media_id = (stream_ctx or {}).get('media_id', '')
        payload['client_dedupe_hash'] = build_dedupe_hash(category, media_id, description)

    return payload
