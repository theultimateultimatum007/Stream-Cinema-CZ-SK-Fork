# -*- coding: utf-8 -*-
"""
Bug Report — redakcia logu a tail [SC]/[SC:S] riadkov + všetkých ERROR/FATAL
záznamov (aj bez [SC] markera), vrátane celých viacriadkových tracebackov.

Žiadne citlivé údaje (username, tokeny, cesty) nesmú opustiť zariadenie
v tele reportu. Tento modul ich nahradí za '***' predtým, ako sa log
pridá do payloadu.
"""
from __future__ import print_function, unicode_literals

import os
import re

from resources.lib.kodiutils import (
    get_app_name,
    get_setting,
    translate_path,
)


# Regex pre filtrovanie SC riadkov logu. Pokrýva:
#   [SC]                 — plugin proces (logger.APP='SC')
#   [SC:S]               — background service proces (service.py:13)
#   [sc.helper]          — SC helper addon (service.sc.helper) HTTP/proxy logy
#   [service.sc.helper]  — SC helper addon (plný addon id pri štarte)
# IGNORECASE kvôli rozdielnemu casingu (SC vs sc.helper).
_RE_SC_LINE = re.compile(r'\[(?:SC(?::S)?|(?:service\.)?sc\.helper)\] ', re.IGNORECASE)

# Začiatok nového Kodi log záznamu — timestamp na začiatku fyzického riadku,
# napr. '2024-01-01 10:00:01.000 T:1234 DEBUG <general>: ...'. Pokračovacie
# riadky viacriadkovej správy (traceback) timestamp NEMAJÚ.
_RE_LOG_ENTRY_START = re.compile(r'^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}')

# Úroveň log záznamu (prvé slovo za timestampom a voliteľným T:<id>),
# napr. '... T:1234 ERROR <general>: ...'. Casing sa medzi Kodi verziami líši
# (Kodi 21 na macOS loguje malými: 'error'), preto matchujeme case-insensitive
# a hodnotu porovnávame veľkými. Slúži na zachytenie VŠETKÝCH chýb (aj bez [SC]
# markera) — cudzie tracebacky, Kodi Python error reporty.
_RE_LOG_LEVEL = re.compile(
    r'^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}\.\d+\s+(?:T:\S+\s+)?([A-Za-z]+)\b')

# Úrovne, ktoré považujeme za chybu a chceme ich v reporte celé.
_ERROR_LEVELS = ('ERROR', 'FATAL', 'SEVERE')


def _filter_sc_lines(text):
    """Zachová [SC] a chybové (ERROR/FATAL) záznamy vrátane pokračovaní.

    Kodi loguje viacriadkovú správu (napr. traceback.format_exc() alebo vlastný
    Python error report) ako JEDEN záznam: prvý fyzický riadok má timestamp +
    úroveň (+ prípadný [SC] marker), ďalšie riadky (napr. 'File "...", line N',
    typ a text výnimky) marker ani timestamp NEMAJÚ. Filter len podľa markera by
    trace orezal na prvý riadok — preto sledujeme, či sme vnútri zachovávaného
    záznamu, a pokračovacie riadky priložíme celé.

    Zachovávame:
    - [SC]/[SC:S]/[sc.helper] záznamy (diagnostika pluginu),
    - záznamy s úrovňou ERROR/FATAL bez ohľadu na prefix (aj cudzie chyby) —
      aby boli v logu viditeľné VŠETKY errory.

    Args:
        text (str): surový obsah log súboru.

    Returns:
        list[str]: vyfiltrované riadky (zachované záznamy aj s pokračovaniami).
    """
    kept = []
    keep_block = False
    for line in text.splitlines():
        if _RE_SC_LINE.search(line):
            # [SC]/[SC:S]/[sc.helper] záznam — zachovaj a otvor blok.
            kept.append(line)
            keep_block = True
        elif _RE_LOG_ENTRY_START.match(line):
            # Nový log záznam — rozhodni podľa úrovne (chyby ponechávame vždy).
            level_match = _RE_LOG_LEVEL.match(line)
            level = level_match.group(1).upper() if level_match else ''
            if level in _ERROR_LEVELS:
                kept.append(line)
                keep_block = True
            else:
                keep_block = False
        elif keep_block:
            # Pokračovací riadok predošlého zachovaného záznamu (traceback atď.).
            kept.append(line)
    return kept


def tail_sc_log(cap_bytes=None, max_lines=None):
    """Načíta log súbor, vyfiltruje len [SC]/[SC:S] riadky a vráti ich tail.

    Args:
        cap_bytes (int): maximálny počet bajtov výstupu (default z SC.BUG_REPORT_LOG_CAP_BYTES).
        max_lines (int|None): voliteľný strop na počet riadkov; None = bez stropu
            (jediný reálny limit je cap_bytes). Ponechané kvôli spätnej kompat.

    Returns:
        str: redigovaný tail logu alebo prázdny reťazec pri chybe.
    """
    from resources.lib.constants import SC

    if cap_bytes is None:
        cap_bytes = SC.BUG_REPORT_LOG_CAP_BYTES

    try:
        log_path = translate_path('special://logpath/')
        app_name = get_app_name()
        log_file = os.path.join(log_path, '{}.log'.format(app_name.lower()))

        try:
            f = open(log_file, 'r', encoding='utf-8', errors='ignore')
        except TypeError:
            # Python 2 — open nepodporuje encoding parameter
            import io
            f = io.open(log_file, 'r', encoding='utf-8', errors='ignore')

        try:
            text = f.read()
        finally:
            f.close()
    except Exception:
        return ''

    # Filtrovanie — zachovaj [SC]/[SC:S]/[sc.helper] záznamy vrátane ich
    # viacriadkových pokračovaní (celé tracebacky).
    lines = _filter_sc_lines(text)

    # Voliteľný strop na počet riadkov (default None = bez stropu).
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[-max_lines:]

    result = '\n'.join(lines)

    # Cap na cap_bytes (UTF-8)
    encoded = result.encode('utf-8', errors='replace')
    if len(encoded) > cap_bytes:
        encoded = encoded[-cap_bytes:]
        # Obnov validný UTF-8 — orež od začiatku kým nie je validný
        result = encoded.decode('utf-8', errors='ignore')

    return result


def redact_log(text):
    """Rediguje citlivé údaje v log texte.

    Nahradí nasledujúce za '***':
    - kra.sk username (get_setting('kraska.user'))
    - hodnoty nastavení kraska.token, kraska.chsum, system.auth_token
    - query parametre krt=, token=, session_id=, chsum= a ich hodnoty
    - segmenty ciest obsahujúce home adresár alebo meno používateľa

    Args:
        text (str): surový log text.

    Returns:
        str: redigovaný text.
    """
    if not text:
        return text

    result = text

    # --- kra.sk username ---
    try:
        username = get_setting('kraska.user')
        if username:
            result = result.replace(username, '***')
    except Exception:
        pass

    # --- hodnoty tokenov zo settings ---
    for setting_key in ('kraska.token', 'kraska.chsum', 'system.auth_token'):
        try:
            val = get_setting(setting_key)
            if val:
                result = result.replace(val, '***')
        except Exception:
            pass

    # --- query parametre: krt=, token=, session_id=, chsum= ---
    # Nahradzuje hodnotu za *** ale zachová meno parametra (pre čitateľnosť).
    result = re.sub(
        r'((?:^|[&?;,\s])(?:krt|token|session_id|chsum)=)[^\s&;,\'"]+',
        r'\1***',
        result,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    # --- home adresár a user segmenty ciest ---
    result = _redact_paths(result)

    return result


def _redact_paths(text):
    """Nahradí home-dir a user-name segmenty ciest za '***'."""
    try:
        # /home/<user>/... alebo /Users/<user>/...
        text = re.sub(
            r'(/(?:home|Users)/)[^/\s\'"]+',
            r'\1***',
            text,
        )
        # /storage/emulated/0/Android/data/<package>/...
        text = re.sub(
            r'(/storage/emulated/\d+/Android/data/)[^/\s\'"]+',
            r'\1***',
            text,
        )
        # Windows cesty: C:\Users\<user>\
        text = re.sub(
            r'((?:[A-Za-z]:\\|\\\\)Users\\)[^\\\s\'"]+',
            r'\1***',
            text,
        )
    except Exception:
        pass
    return text


def encode_log(text):
    """Zakóduje (zlib + base64) už redigovaný log.

    Dôvod: WAF (napr. Cloudflare) blokuje request, lebo v surovom logu sú
    "podozrivé" vzory (cesty, URL, stack traces, SQL-podobné reťazce). Po
    zlib+base64 je log len reťazec [A-Za-z0-9+/=] a žiadne WAF pravidlo sa
    netrafí. NIE je to šifrovanie (log je už redigovaný, bez tajomstiev),
    len zakódovanie + kompresia.

    Backend dekóduje: base64_decode -> zlib inflate
    (PHP: gzuncompress(base64_decode($text))).

    Args:
        text (str): redigovaný log text.

    Returns:
        str: ASCII base64 reťazec (alebo '' pri prázdnom vstupe).
    """
    if not text:
        return ''
    import base64
    import zlib
    raw = text.encode('utf-8') if not isinstance(text, bytes) else text
    return base64.b64encode(zlib.compress(raw, 9)).decode('ascii')


def decode_log(encoded):
    """Spätné dekódovanie encode_log (pre testy / lokálne overenie)."""
    if not encoded:
        return ''
    import base64
    import zlib
    raw = encoded.encode('ascii') if not isinstance(encoded, bytes) else encoded
    return zlib.decompress(base64.b64decode(raw)).decode('utf-8', errors='ignore')
