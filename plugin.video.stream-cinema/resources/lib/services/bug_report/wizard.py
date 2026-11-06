# -*- coding: utf-8 -*-
"""
BugReportWizard — čistý Python controller pre wizard na nahlasovanie chýb.

Tento modul je UNIT-TESTOVATEĽNÝ bez xbmcgui.WindowXMLDialog.
Všetka business logika (validácia, preview, submit) žije tu.
BugReportDialog (gui/bug_report_dialog.py) je tenký UI obal ktorý deleguje sem.

Decision A (plán §2): Hybrid submit — najprv rýchly synchrónny POST,
pri zlyhaní fallback do perzistentného inbox pre background drain.
Decision B1 (plán §2): Tenký dialóg + controller (nie monolit).
"""
from __future__ import print_function, unicode_literals

from resources.lib.common.logger import debug
from resources.lib.constants import SC

# Kroky wizardu
STEP_CATEGORY = 1
STEP_CONTEXT = 2
STEP_DESCRIPTION = 3
STEP_CONFIRM = 4

_STEP_COUNT = 4


class BugReportWizard(object):
    """Controller pre 4-krokový bug report wizard.

    Stav:
        category (str|None): zvolená kategória (jedna z SC.BUG_CAT_*)
        description (str): voľný popis chyby
        include_username (bool): priložiť kra.sk meno (default False)
        include_log (bool): priložiť redigovaný log (default True)
        step (int): aktuálny krok 1-4
        stream_ctx (dict|None): stream kontext predaný pri inštanciácii
        source (str): 'live_fail' | 'last_played' | 'none'
    """

    def __init__(self, stream_ctx=None, source='none'):
        """Inicializuje controller wizardu.

        Args:
            stream_ctx (dict|None): Stream kontext z kollektora alebo None.
            source (str): Zdroj kontextu — 'live_fail' | 'last_played' | 'none'.
        """
        self.category = None
        self.description = ''
        self.include_username = False
        self.include_log = True
        self.step = STEP_CATEGORY
        self.stream_ctx = stream_ctx
        self.source = source
        self._system_info = None  # lazy-loaded pri submit/preview

    # ------------------------------------------------------------------
    # Navigácia krokmi
    # ------------------------------------------------------------------

    def next_step(self):
        """Postúpi na nasledujúci krok (max STEP_CONFIRM)."""
        if self.step < _STEP_COUNT:
            self.step += 1
            debug('BugReport: wizard.next_step -> {}'.format(self.step))

    def prev_step(self):
        """Vráti sa na predošlý krok (min STEP_CATEGORY)."""
        if self.step > STEP_CATEGORY:
            self.step -= 1
            debug('BugReport: wizard.prev_step -> {}'.format(self.step))

    def set_category(self, cat_id):
        """Nastaví kategóriu a resetuje popis pri zmene."""
        if cat_id != self.category:
            self.category = cat_id
            debug('BugReport: wizard.set_category -> {}'.format(cat_id))

    # ------------------------------------------------------------------
    # Validácia
    # ------------------------------------------------------------------

    def validate(self):
        """Validuje aktuálny stav wizardu.

        Popis je POVINNÝ iba pre kategóriu 'general' (SC.BUG_CAT_GENERAL).
        Pre ostatné kategórie je voliteľný.

        Returns:
            list[str]: Zoznam lokalizovaných chybových hlášok.
                       Prázdny zoznam = validácia prešla.
        """
        errors = []
        if self.category == SC.BUG_CAT_GENERAL:
            if not self.description or not self.description.strip():
                from resources.lib.language import Strings
                errors.append(Strings.txt(Strings.BUG_REPORT_DESCRIBE_REQUIRED))
        return errors

    # ------------------------------------------------------------------
    # Pomocné metódy pre UI
    # ------------------------------------------------------------------

    def get_categories(self):
        """Vráti zoznam kategórií pre zobrazenie v UI.

        Returns:
            list[tuple]: Každý prvok je (cat_id, label, sublabel).
        """
        from resources.lib.language import Strings
        return [
            (
                SC.BUG_CAT_STREAM_BROKEN,
                Strings.txt(Strings.BUG_CAT_STREAM_BROKEN),
                '',
            ),
            (
                SC.BUG_CAT_STREAM_MISMATCH,
                Strings.txt(Strings.BUG_CAT_STREAM_MISMATCH),
                '',
            ),
            (
                SC.BUG_CAT_AV_SYNC,
                Strings.txt(Strings.BUG_CAT_AV_SYNC),
                '',
            ),
            (
                SC.BUG_CAT_GENERAL,
                Strings.txt(Strings.BUG_CAT_GENERAL),
                '',
            ),
        ]

    def get_step_indicator(self):
        """Vráti text indikátora kroku pre zobrazenie v title bare.

        Returns:
            str: Napr. '1 / 4'
        """
        return '{} / {}'.format(self.step, _STEP_COUNT)

    def get_context_preview(self):
        """Vráti textový náhľad auto-zbieraného kontextu pre krok 2.

        Returns:
            str: Ľudsky čitateľný prehľad zbieraných dát.
        """
        lines = []
        sys_info = self._get_system_info()
        lines.append('Platform: {platform}  Kodi: {kodi_ver}  Plugin: {plugin_ver}'.format(
            **sys_info))
        lines.append('Device: {device_name}  Skin: {skin}'.format(**sys_info))
        lines.append('UID: {uid}'.format(**sys_info))

        if self.stream_ctx and self.source != 'none':
            sc = self.stream_ctx
            lines.append('')
            lines.append('Stream source: {}'.format(self.source))
            lines.append('Quality: {}  Codec: {}  {}x{}'.format(
                sc.get('quality', ''), sc.get('codec', ''),
                sc.get('width', 0), sc.get('height', 0)))
            lines.append('Media: {}  S{}E{}'.format(
                sc.get('media_title', ''),
                sc.get('season', 0), sc.get('episode', 0)))

        return '\n'.join(lines)

    # ------------------------------------------------------------------
    # Preview (krok 4) — presne to čo sa odošle
    # ------------------------------------------------------------------

    def build_preview(self):
        """Zostaví textový náhľad presne odosielaného obsahu.

        Redigovaný log sa zobrazí iba ak include_log=True.
        Username sa zobrazí iba ak include_username=True.

        Returns:
            str: Ľudsky čitateľný preview payload-u.
        """
        lines = []
        lines.append('Category: {}'.format(self.category or ''))
        lines.append('Description: {}'.format(self.description or ''))

        if self.include_username:
            try:
                from resources.lib.kodiutils import get_setting
                uname = get_setting('kraska.user') or ''
            except Exception:
                uname = '(unavailable)'
            lines.append('Username: {}'.format(uname))
        else:
            lines.append('Username: (not included)')

        sys_info = self._get_system_info()
        lines.append('')
        lines.append('[System]')
        lines.append('  Platform: {platform}  Kodi: {kodi_ver}  Plugin: {plugin_ver}'.format(
            **sys_info))

        if self.stream_ctx:
            sc = self.stream_ctx
            lines.append('')
            lines.append('[Stream]')
            lines.append('  Source: {}  Quality: {}  Codec: {}'.format(
                self.source, sc.get('quality', ''), sc.get('codec', '')))
            from resources.lib.services.bug_report.collector import (
                extract_play_id, extract_stream_id)
            _purl = sc.get('play_url', '')
            _surl = sc.get('stream_url', '')
            _mid = sc.get('media_id') or sc.get('id') or extract_play_id(_purl)
            _sid = sc.get('stream_id') or extract_stream_id(_surl)
            if _mid:
                lines.append('  Media ID: {}'.format(_mid))
            if _sid:
                lines.append('  Stream ID: {}'.format(_sid))
            if _purl:
                lines.append('  Play URL: {}'.format(_purl))
            if _surl:
                lines.append('  Stream URL: {}'.format(_surl))

        lines.append('')
        if self.include_log:
            from resources.lib.services.bug_report.redact import tail_sc_log, redact_log
            raw = tail_sc_log()
            redacted = redact_log(raw)
            lines.append('[Log] ({} chars)'.format(len(redacted)))
            # Zobraz len posledných 500 znakov v náhľade (úspora miesta)
            preview_log = redacted[-500:] if len(redacted) > 500 else redacted
            lines.append(preview_log)
        else:
            lines.append('[Log] (not included)')

        return '\n'.join(lines)

    # ------------------------------------------------------------------
    # Submit — hybrid Decision A
    # ------------------------------------------------------------------

    def submit(self):
        """Odošle report. Hybrid: rýchly synchrónny POST, pri zlyhaní inbox.

        1. Zostaví payload cez build_payload().
        2. Pokúsi sa o rýchly synchrónny POST (SC.BUG_REPORT_SYNC_TIMEOUT ~5s).
        3. HTTP 200 → notifikácia "Report odoslaný, ďakujeme".
        4. Akékoľvek zlyhanie → enqueue_report(payload) + notifikácia "zaradené do fronty".
        """
        debug('BugReport: wizard.submit start category={} step={}'.format(
            self.category, self.step))
        try:
            payload = self._build_payload()
        except Exception as e:
            debug('BugReport: wizard.submit build_payload failed: {}'.format(e))
            self._notify_error()
            return

        try:
            from resources.lib.services.bug_report.transport import send_report
            sent = send_report(payload, timeout=SC.BUG_REPORT_SYNC_TIMEOUT)
        except Exception as e:
            debug('BugReport: wizard.submit transport exception: {}'.format(e))
            sent = False

        if sent:
            debug('BugReport: wizard.submit sent OK (HTTP 200)')
            self._notify_sent()
        else:
            debug('BugReport: wizard.submit fallback to inbox')
            try:
                from resources.lib.services.bug_report.inbox import enqueue_report
                enqueue_report(payload)
            except Exception as e:
                debug('BugReport: wizard.submit enqueue failed: {}'.format(e))
            self._notify_queued()

    # ------------------------------------------------------------------
    # Natívny fallback tok (Fáza 3.4)
    # ------------------------------------------------------------------

    def run_native_fallback(self):
        """Spustí wizard cez SYSTÉMOVÉ dialógy (xbmcgui.Dialog).

        Toto je PRIMÁRNY tok wizardu — žiadny skin XML, funguje v každom skine
        a na každej Kodi verzii. Zdieľa rovnaký controller (payload/redakcia/
        submit/validácia).

        Tok: kategória -> popis -> voľby (meno/log) -> náhľad -> potvrdenie.

        Returns:
            bool: True ak používateľ dokončil a odoslal, False ak zrušil.
        """
        from resources.lib.gui.dialog import (
            dselect, dyesno, dinput, dtextviewer, dok)
        from resources.lib.language import Strings

        title = Strings.txt(Strings.CONTEXT_BUG_REPORT)

        # 1) Výber kategórie
        cats = self.get_categories()
        idx = dselect([label for (_id, label, _sub) in cats], heading=title)
        if idx < 0:
            return False
        self.set_category(cats[idx][0])

        # 2) Popis (POVINNÝ iba pre 'general'). Kodi klávesnica vracia '' pri
        #    zrušení AJ pri prázdnom vstupe — nedajú sa rozlíšiť. Pri prázdnom
        #    popise pre 'general' ukážeme chybu a dáme jeden pokus navyše, potom
        #    tok zrušíme (žiadne nekonečné opakovanie).
        attempts = 0
        while True:
            desc = dinput(
                heading=Strings.txt(Strings.BUG_REPORT_DESCRIBE),
                default=self.description,
            )
            self.description = desc or ''
            errors = self.validate()
            if not errors:
                break
            dok(heading=title, message=errors[0])
            attempts += 1
            if attempts >= 2:
                return False

        # 3) Diagnostiku (kra.sk meno + log + systém + stream) priložíme
        #    AUTOMATICKY — používateľov sa na to nepýtame (menej krokov,
        #    menej zmätku pre netechnických používateľov).
        self.include_username = True
        self.include_log = True

        # 4) Potvrdenie odoslania — PRED náhľadom. Netechnickí používatelia sa
        #    nemusia vedieť preklikať z náhľadu späť k odoslaniu, takže samotné
        #    odoslanie spravíme ako prvé.
        if not dyesno(
            heading=title,
            message=Strings.txt(Strings.BUG_REPORT_CONFIRM_SEND),
            yeslabel=Strings.txt(Strings.BUG_REPORT_BTN_SEND),
            nolabel=Strings.txt(Strings.BUG_REPORT_BTN_CANCEL),
        ):
            return False

        self.submit()

        # 5) Náhľad odoslaného obsahu (informačný — report je už odoslaný, takže
        #    aj keď sa používateľ na náhľade „zasekne", nič sa nestratí).
        dtextviewer(
            heading=Strings.txt(Strings.BUG_REPORT_PREVIEW_H1),
            text=self.build_preview(),
        )
        return True

    # Primárny vstupný bod (alias — názov 'run' je výstižnejší ako 'fallback')
    run = run_native_fallback

    # ------------------------------------------------------------------
    # Privátne pomocné metódy
    # ------------------------------------------------------------------

    def _get_system_info(self):
        """Lazy-load system info — cache-uje výsledok v _system_info."""
        if self._system_info is None:
            try:
                from resources.lib.services.bug_report.collector import collect_system
                self._system_info = collect_system()
            except Exception:
                self._system_info = {
                    'plugin_ver': '', 'kodi_ver': '', 'platform': '',
                    'uid': '', 'skin': '', 'lang': '', 'device_name': '',
                }
        return self._system_info

    def _build_payload(self):
        """Zostaví kompletný payload vrátane zberu stream kontextu a logu."""
        from resources.lib.services.bug_report.collector import collect_stream
        from resources.lib.services.bug_report.payload import build_payload

        sys_info = self._get_system_info()

        # Stream kontext — pre stream kategórie zbierame, pre general nie
        is_stream_cat = self.category in (
            SC.BUG_CAT_STREAM_BROKEN,
            SC.BUG_CAT_STREAM_MISMATCH,
            SC.BUG_CAT_AV_SYNC,
        )
        if is_stream_cat and self.stream_ctx is not None:
            stream_ctx = collect_stream(self.source, self.stream_ctx)
        elif is_stream_cat:
            stream_ctx = collect_stream('none', None)
        else:
            stream_ctx = collect_stream('none', None)

        # Log tail
        log_text = None
        if self.include_log:
            from resources.lib.services.bug_report.redact import tail_sc_log, redact_log
            raw = tail_sc_log()
            log_text = redact_log(raw)

        return build_payload(
            category=self.category,
            description=self.description,
            include_username=self.include_username,
            include_log=self.include_log,
            stream_ctx=stream_ctx,
            system_info=sys_info,
            log_text=log_text,
        )

    def _notify_sent(self):
        """Zobrazí notifikáciu o úspešnom odoslaní."""
        try:
            from resources.lib.gui.dialog import dnotify
            from resources.lib.language import Strings
            dnotify(
                heading=Strings.txt(Strings.CONTEXT_BUG_REPORT),
                message=Strings.txt(Strings.BUG_REPORT_SENT),
            )
        except Exception as e:
            debug('BugReport: _notify_sent failed: {}'.format(e))

    def _notify_queued(self):
        """Zobrazí notifikáciu o zaradení do fronty."""
        try:
            from resources.lib.gui.dialog import dnotify
            from resources.lib.language import Strings
            dnotify(
                heading=Strings.txt(Strings.CONTEXT_BUG_REPORT),
                message=Strings.txt(Strings.BUG_REPORT_QUEUED),
            )
        except Exception as e:
            debug('BugReport: _notify_queued failed: {}'.format(e))

    def _notify_error(self):
        """Zobrazí notifikáciu pri internej chybe (napr. build_payload zlyhá)."""
        try:
            from resources.lib.gui.dialog import dnotify
            import xbmcgui
            from resources.lib.language import Strings
            dnotify(
                heading=Strings.txt(Strings.CONTEXT_BUG_REPORT),
                message='Error building report',
                icon=xbmcgui.NOTIFICATION_ERROR,
            )
        except Exception as e:
            debug('BugReport: _notify_error failed: {}'.format(e))
