from __future__ import print_function, unicode_literals

import time
import traceback

from resources.lib.api.kraska import getKraInstance
from resources.lib.common.android import AndroidTv
from resources.lib.common.logger import debug
from resources.lib.constants import ADDON, ADDON_ID, MEM_PROFILER_ENABLED, MEM_PROFILER_INTERVAL
from resources.lib.gui.dialog import dtextviewer, dnotify
from resources.lib.language import Strings
from resources.lib.kodiutils import set_setting, get_uuid, get_setting, exec_build_in, get_setting_as_bool, \
    update_addon, clean_textures
from resources.lib.services.monitor import monitor
from resources.lib.services.player import player
from resources.lib.services.next_episodes import NextEp
from resources.lib.services.menu_cache_server import menu_cache_server
from resources.lib.services.mem_profiler import mem_profiler


class Service:
    next_ep = None
    monitor = None
    player = None
    trakt = None
    atv = None
    startup_time = None
    trakt_sync_ready = False
    last_trakt_check = 0

    # Minimálny čas (v sekundách) od štartu pred prvým Trakt syncom
    # 30s - dá zariadeniu čas na inicializáciu
    TRAKT_SYNC_STARTUP_DELAY = 30

    # Minimálny odstup medzi Trakt kontrolami (last_activities) - hlavná
    # slučka beží každých 5 s, ale API netreba kontrolovať tak často
    TRAKT_CHECK_INTERVAL = 120

    # Oneskorenie (v sekundách) pred kontrolou SC Helpera po štarte.
    # Beží v samostatnom threade, aby na slabších CPU neblokoval štart Kodi.
    HELPER_CHECK_STARTUP_DELAY = 30

    def __init__(self):
        set_setting('system.ver', ADDON.getAddonInfo('version'))
        get_uuid()
        if get_setting('androidtv.path'):
            self.atv = AndroidTv()
        self.startup_time = time.time()

    def run(self):
        debug('START SERVICE....................................................................')
        if MEM_PROFILER_ENABLED:
            mem_profiler.start()
        _last_mem_log = 0
        last_changelog = get_setting('system.changelog')

        update_addon()

        # Kraska prihlásenie + user_info presunuté do samostatného daemon vlákna.
        # Sieťový request na api.kra.sk môže pri DNS/SSL/sieťovom probléme uviaznuť
        # (aj napriek timeoutu) a NESMIE blokovať štart hlavnej service slučky
        # (NextEp, Trakt, helper, mem profiler). Rovnaký vzor ako check_helper_on_startup.
        from threading import Thread
        kraska_thread = Thread(target=self.kraska_startup)
        kraska_thread.daemon = True
        kraska_thread.start()

        debug('SERVICE init: kraska vlakno spustene, pokracujem')

        if last_changelog != ADDON.getAddonInfo('version'):
            debug('SYSTEM.CHANGELOG: {}'.format(ADDON.getAddonInfo('changelog')))
            set_setting('system.changelog', '{}'.format(ADDON.getAddonInfo('version')))
            dtextviewer('', ADDON.getAddonInfo('changelog'))
        debug('SERVICE init: changelog OK')

        if get_setting_as_bool('system.autoexec'):
            try:
                exec_build_in('ActivateWindow(videos,plugin://{})'.format(ADDON_ID))
            except Exception:
                pass
        debug('SERVICE init: autoexec OK')

        # POZN.: check_user() (volá user_info → sieť) presunuté do kraska_startup vlákna.

        # if get_setting_as_bool('system.ws.remote.enable'):
        #     ws = websocket.WS()
        #     ws.reconnect()

        self.next_ep = NextEp()
        debug('SERVICE init: NextEp OK')

        # clean_textures() presunuté do daemon vlákna — TexturesDb().clean() (SQLite) môže
        # visieť na DB zámku, keď UI thread práve číta artwork (navigácia používateľa),
        # a NESMIE blokovať štart hlavnej service slučky.
        ct = Thread(target=clean_textures)
        ct.daemon = True
        ct.start()
        debug('SERVICE init: clean_textures vo vlakne, vstupujem do hlavnej slucky')

        # MenuCacheServer sa inicializuje automaticky pri prvom použití (lazy loading)
        # Voliteľne: Preheat homepage cache pre lepší UX
        # try:
        #     debug('MenuCacheServer: Preheating homepage cache...')
        #     menu_cache_server.run()
        # except:
        #     debug('MenuCacheServer preheat error: {}'.format(traceback.format_exc()))
        #     pass

        # Spusti player thread
        w = Thread(target=player.run)
        w.start()

        # Kontrola SC Helpera po štarte - samostatný daemon thread s oneskorením,
        # aby na slabších CPU neblokoval/nespomaľoval štart Kodi
        h = Thread(target=self.check_helper_on_startup)
        h.daemon = True
        h.start()

        # Per-media_id cooldown — zabraňuje opakovanej ponuke pre ten istý stream
        _bug_offer_cooldown = set()

        # Cross-process dirty-marker gating (viz storage.mark_dirty/get_dirty) —
        # force-reload (load(True)) sa vykoná IBA pri zmene markera od poslednej
        # videnej hodnoty. None zaručuje 1 počiatočný load(True) hneď pri štarte
        # service (get_dirty vždy vráti hodnotu odlišnú od None, aj keď marker
        # ešte nikdy nebol nastavený). Per-cycle Storage(...) re-inštanciácia
        # (load(force=False) resync cez _storage_cache) OSTÁVA nedotknutá nižšie.
        _play_ts_last_dirty = None

        while not monitor.abortRequested():
            # 4.6: fail-timeout vyhodnotenie (fix #4) — v KAŽDOM cykle (nie periodical_check)
            # Musí bežať aj počas pokusu o štart (periodical_check early-returnuje)
            try:
                from resources.lib.common.storage import Storage, get_dirty
                from resources.lib.constants import SC
                _play_storage = Storage(SC.BUG_REPORT_PLAY_TS)
                _current_dirty = get_dirty(SC.BUG_REPORT_PLAY_TS)
                if _current_dirty != _play_ts_last_dirty:
                    _play_storage.load(True)
                    _play_ts_last_dirty = _current_dirty
                _ts = _play_storage.get('ts')
                if _ts is not None:
                    _elapsed = time.time() - float(_ts)
                    _media_id = _play_storage.get('media_id') or ''
                    if _elapsed > SC.BUG_REPORT_FAIL_TIMEOUT and _media_id not in _bug_offer_cooldown:
                        from resources.lib.gui.dialog import dnotify
                        from resources.lib.language import Strings
                        dnotify(
                            heading=Strings.txt(Strings.CONTEXT_BUG_REPORT),
                            message=Strings.txt(Strings.BUG_REPORT_OFFER),
                            sound=False,
                        )
                        _bug_offer_cooldown.add(_media_id)
                        _play_storage['ts'] = None
                        debug('BugReport: fail-timeout offer fired for media_id={}'.format(_media_id))
            except Exception:
                debug('bug report fail-timeout err: {}'.format(traceback.format_exc()))

            # 5.1: drain bug report inbox + spracuj frontu na pozadí
            try:
                from resources.lib.services.bug_report.queue import bug_report_queue_service
                bug_report_queue_service.drain_inbox()
                bug_report_queue_service.process_queue()
                bug_report_queue_service.process_deferred_queue()
            except Exception:
                debug('bug report queue err: {}'.format(traceback.format_exc()))

            # Download queue - spracuj frontu sťahovaní (inbox, príkazy, workery)
            try:
                from resources.lib.services.download_queue import download_queue_service
                download_queue_service.process_queue()
            except Exception:
                debug('download queue err: {}'.format(traceback.format_exc()))

            try:
                self.periodical_check()
            except Exception as e:
                debug('error: {}'.format(traceback.format_exc()))

            # Pamäťový profiler — periodický výpis TOP alokácií + rastu (leak).
            # Aktívne len pri MEM_PROFILER_ENABLED, inak nulová réžia.
            if MEM_PROFILER_ENABLED and (time.time() - _last_mem_log) >= MEM_PROFILER_INTERVAL:
                _last_mem_log = time.time()
                try:
                    mem_profiler.log_top()
                    mem_profiler.log_growth()
                except Exception:
                    debug('mem profiler err: {}'.format(traceback.format_exc()))

            # Abort-aware čakanie namiesto chunkovaného sleep() - okamžité
            # ukončenie hlavnej slučky pri vypnutí Kodi (rovnaký monitor
            # objekt ako v podmienke while, žiadny duplicitný abort-check).
            if monitor.waitForAbort(5):
                break

    def kraska_startup(self):
        """Úvodné Kraska prihlásenie + user_info v samostatnom daemon vlákne.

        Sieťový request na api.kra.sk (get_token/user_info/login/check_user) môže pri
        DNS/SSL/sieťovom probléme uviaznuť aj napriek nastavenému timeoutu. V daemon
        vlákne to neblokuje štart hlavnej service slučky; vlákno sa ukončí s Kodi.
        """
        kr = getKraInstance()
        try:
            if kr.username and kr.password:
                kr.get_token()
                kr.user_info()
        except Exception:
            debug('Kraska login error: {}'.format(traceback.format_exc()))
            try:
                kr.login()
            except Exception:
                debug('Kraska re-login failed: {}'.format(traceback.format_exc()))

        if get_setting('kraska.user'):
            try:
                getKraInstance().check_user()
            except Exception:
                debug('check_user err: {}'.format(traceback.format_exc()))

    def check_helper_on_startup(self):
        """Skontroluje SC Helper po štarte; ak nebeží, skúsi ho reštartnúť.

        Beží v samostatnom daemon threade s oneskorením (rovnaký vzor ako
        Trakt sync delay), aby kontrola nezaťažila štart Kodi na slabších CPU.
        """
        # Abort-aware čakanie - pri ukončení Kodi sa thread hneď skončí
        if monitor.waitForAbort(self.HELPER_CHECK_STARTUP_DELAY):
            return
        try:
            kr = getKraInstance()
            port = kr.check_and_restart_helper()
            if port:
                debug('startup check: sc.helper bezi na porte {}'.format(port))
            else:
                debug('startup check: sc.helper sa nepodarilo nastartovat')
                dnotify(Strings.txt(Strings.HELPER_ERROR_H1),
                        Strings.txt(Strings.HELPER_START_FAILED_L1))
        except Exception:
            debug('startup helper check err: {}'.format(traceback.format_exc()))

    def periodical_check(self):
        if monitor.can_check():
            # try:
            #     player.periodical_check()
            # except:
            #     debug('player err: {}'.format(traceback.format_exc()))
            #     pass

            try:
                monitor.periodical_check()
            except Exception:
                debug('monitor err: {}'.format(traceback.format_exc()))
                pass

            try:
                if self.atv:
                    self.atv.run()
            except Exception:
                debug('android tv err: {}'.format(traceback.format_exc()))
                pass

            # TRAKT SYNC - inteligentné spustenie s delayom po štarte
            if get_setting('trakt.user'):
                try:
                    # Kontrola: Prešiel dostatok času od štartu?
                    if not self.trakt_sync_ready:
                        elapsed = time.time() - self.startup_time
                        if elapsed >= self.TRAKT_SYNC_STARTUP_DELAY:
                            self.trakt_sync_ready = True
                            debug('Trakt sync READY after {} seconds from startup'.format(int(elapsed)))
                        else:
                            # Ešte nie je čas, počkaj
                            remaining = int(self.TRAKT_SYNC_STARTUP_DELAY - elapsed)
                            # Log len pri prvom volaní (elapsed < 10s) alebo každú minútu
                            if elapsed < 10 or int(elapsed) % 60 == 0:
                                debug('Trakt sync DELAYED: {} seconds remaining (waiting for system to settle)'.format(remaining))
                            # Preskočiť Trakt sync tento cyklus, ale nechaj bežať NextEp a ostatné
                            # Nevracaj sa hore, len preskočiť Trakt sync

                    # Ak je Trakt sync pripravený, skús ho spustiť
                    # (max raz za TRAKT_CHECK_INTERVAL - šetrí Trakt API)
                    if self.trakt_sync_ready \
                            and (time.time() - self.last_trakt_check) >= self.TRAKT_CHECK_INTERVAL:
                        from resources.lib.trakt.Trakt import trakt
                        # Dodatočná kontrola: Je systém v idle stave?
                        # Monitor už kontroluje screensaver, DPMS a playback v can_check()
                        if trakt.can_check():
                            self.last_trakt_check = time.time()
                            trakt.check_trakt()
                        else:
                            debug('Trakt sync skipped: system busy or player active')
                except Exception:
                    debug('trakt err: {}'.format(traceback.format_exc()))
                    pass

            try:
                # NextEp používa TimerService API
                self.next_ep.start(monitor=monitor, player=player)
            except Exception:
                debug('nextep err: {}'.format(traceback.format_exc()))
                pass

            # TRAKT QUEUE - spracuj pending scrobble/sync requesty na pozadí
            # Beží aj počas prehrávania (na pozadí, neblokuje)
            try:
                from resources.lib.services.trakt_queue import trakt_queue_service
                processed = trakt_queue_service.process_queue()
                if processed > 0:
                    debug('TraktQueue: Processed {} requests'.format(processed))

                # Spracuj aj odloženú frontu (menej často)
                deferred_processed = trakt_queue_service.process_deferred_queue()
                if deferred_processed > 0:
                    debug('TraktQueue: Processed {} deferred requests'.format(deferred_processed))
            except Exception:
                debug('trakt queue err: {}'.format(traceback.format_exc()))
                pass


service = Service()
