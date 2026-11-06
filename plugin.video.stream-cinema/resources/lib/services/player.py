from __future__ import print_function, unicode_literals

import traceback
from datetime import datetime, timedelta as td
from json import loads
from time import time

from xbmc import Player, Monitor

from resources.lib.common.storage import Storage
from resources.lib.services.settings import settings
from resources.lib.api.sc import Sc
from resources.lib.common.lists import SCKODIItem
from resources.lib.common.logger import debug
from resources.lib.constants import ADDON, ADDON_ID, SC
from resources.lib.gui import home_win, get_cond_visibility
from resources.lib.gui.item import SCUpNext
from resources.lib.gui.skip import Skip
from resources.lib.kodiutils import upnext_signal, sleep, get_setting, get_setting_as_bool


class SCPlayer(Player):
    def __init__(self):
        self.settings = settings
        self.win = home_win
        self.current_time = 0
        self.item = None
        self.is_my_plugin = False
        self.movie = None
        self.my_id = None
        self.total_time = 0
        self.ids = {}
        self.watched = False
        self.scrobbled_final = False  # Flag pre zabránenie duplikátnym scrobble volaniam
        self.up_next = False
        self.skipped_item = None
        self.skip_button = None
        self.skip_time_start = False
        self.skip_time_end = False
        self.skip_start = False

    def onPlayBackStarted(self):
        self.onAVStarted()

    def set_item(self, item=None):
        self.up_next = False
        self.skip_start = False
        # self.item = item
        json_data = self.win.getProperty('SC.play_item')
        # debug('set_item json_data: {}'.format(json_data))  # Príliš veľký JSON
        if not json_data:
            return

        # Získaj item_data a zisti ID nového videa
        item_data = loads(json_data)
        new_item = item_data.get('info')
        new_item_info = new_item.get('info', {})
        new_unique_ids = new_item_info.get('unique_ids', {})
        new_sc_id = new_unique_ids.get('sc')

        # Ak už je movie inicializovaný, skontroluj či je to TEN ISTÝ item
        # (opakované volanie onAVStarted pre ten istý item)
        # Ak je to INÝ item, znamená to novú epizódu → resetuj a pokračuj v inicializácii
        if self.movie is not None and self.my_id == new_sc_id:
            debug('set_item: movie už je inicializovaný pre ten istý item ({}), preskakujem opakovanú inicializáciu'.format(self.my_id))
            return
        elif self.movie is not None and self.my_id != new_sc_id:
            # Nový item (napr. ďalšia epizóda cez UpNext) → vynuluj staré údaje
            debug('set_item: Detekovaný nový item (starý: {}, nový: {}), resetujem movie'.format(self.my_id, new_sc_id))
            self.movie = None
            self.my_id = None
            self.ids = {}
            self.item = None
            self.watched = False
            self.scrobbled_final = False

        self.item = item_data.get('info')
        debug('ITEM: {}'.format(self.item.get('info', {}).get('unique_ids')))
        linfo = item_data.get('strms').get('linfo')

        # VŽDY načítaj ids z Window property (môže byť aktualizované pre novú epizódu)
        ids = self.win.getProperty('{}.ids'.format(ADDON_ID))
        if ids:
            self.ids = loads(ids)
            self.my_id = self.ids.get('sc') if self.ids.get('sc') else None
            debug('set_item: Načítané ids z Window property: {}'.format(self.ids))
        elif not self.ids:
            # Fallback: ak nie je vo Window property a nemáme ich načítané
            debug('set_item: ŽIADNE ids vo Window property!')
            self.ids = {}
            self.my_id = None
        if self.my_id is not None:
            if self.skipped_item is not False and self.skipped_item != self.my_id:
                self.skipped_item = False
            self.win.setProperty('{}.play'.format(ADDON_ID), '1')
            all_item_data = loads(self.win.getProperty(SC.SELECTED_ITEM))
            if SC.NOTIFICATIONS in all_item_data:
                if SC.SKIP_START in all_item_data.get(SC.NOTIFICATIONS, {}):
                    notification = all_item_data.get(SC.NOTIFICATIONS, {})
                    self.skip_time_start = notification.get(SC.SKIP_START, False)
                    self.skip_time_end = notification.get(SC.SKIP_END, False)
                    debug('NOTIFICATIONS set SKIP TIME: {}s to {}s'.format(td(seconds=self.skip_time_start), td(seconds=self.skip_time_end)))
            debug('je to moj plugin')
            self.is_my_plugin = True
            series = self.item['info'].get('season')
            episode = self.item['info'].get('episode')
            self.movie = SCKODIItem(self.my_id, series=series, episode=episode, trakt=self.ids.get('trakt'))
            self.movie.scrobble(self.percent_played(), SCKODIItem.SCROBBLE_START)
            audio = self.getAvailableAudioStreams()
            if len(audio) == 1:
                debug('Nemame na vyber, mame len jednu audio stopu')
                return

            if linfo:
                audio = linfo
            debug('AvailableAudioStreams {}'.format(len(audio)))
            lang1 = get_setting('stream.lang1').lower()
            lang2 = get_setting('stream.lang2').lower()
            if Sc.parental_control_is_active():
                lang1 = get_setting('parental.control.lang1').lower()
                lang2 = get_setting('parental.control.lang2').lower()

            plf = Storage(SC.ITEM_PREFERRED_LANG)
            plf.load(True)
            debug('PREF LANGS: {} / {}'.format(self.my_id, plf.data))
            force_lang = plf.get(self.my_id)

            # Zisti aktuálnu audio stopu pomocou InfoLabel (po spustení videa)
            from resources.lib.kodiutils import get_info_label

            # Počkaj kým player nebude mať dostupné info o audio stope (max 2s)
            current_audio_lang = None
            for attempt in range(20):
                current_audio_lang = get_info_label('VideoPlayer.AudioLanguage')
                if current_audio_lang and current_audio_lang.strip():
                    break
                sleep(100)

            current_audio_lang = current_audio_lang.lower().strip() if current_audio_lang else None
            debug('Aktualna audio stopa (VideoPlayer.AudioLanguage): {}'.format(current_audio_lang))

            force = False
            if force_lang is not None:
                lang = force_lang.lower()
                debug('mame force lang {}'.format(force_lang))
                # Skontroluj či už nie je aktívna
                if current_audio_lang and self._is_same_language(current_audio_lang, lang):
                    debug('Aktualna audio stopa {} uz je force lang, preskakujem zmenu'.format(current_audio_lang))
                    force = True
                else:
                    force = self.try_audio(lang, audio)

            if force is False:
                # Skontroluj či aktuálna už nie je preferovaný jazyk
                if current_audio_lang:
                    # PRIORITA: lang1 > lang2
                    # Ak je aktuálna lang1, super, nič nemeň
                    if self._is_same_language(current_audio_lang, lang1):
                        debug('Aktualna audio stopa {} uz je preferovany jazyk lang1={}, preskakujem zmenu'.format(current_audio_lang, lang1))
                    else:
                        # Aktuálna NIE JE lang1 - skús ju prepnúť na lang1 ak existuje
                        debug('Aktualna audio stopa {} nie je lang1={}, skusam prepnut'.format(current_audio_lang, lang1))
                        if self.try_audio(lang1, audio) is False:
                            # lang1 nieje v streame dostupná
                            # Skontroluj či aktuálna je aspoň lang2
                            if self._is_same_language(current_audio_lang, lang2):
                                debug('lang1={} nie je dostupna, ale aktualna {} je lang2={}, nechavam'.format(lang1, current_audio_lang, lang2))
                            else:
                                # Aktuálna nieje ani lang1 ani lang2, skús lang2
                                debug('Aktualna {} nie je ani lang1={} ani lang2={}, prepínam na lang2'.format(current_audio_lang, lang1, lang2))
                                self.try_audio(lang2, audio)
                else:
                    # Nemáme info o aktuálnej stope, zmeň klasicky
                    debug('Nepodarilo sa zistit aktualnu audio stopu, menime klasicky')
                    if self.try_audio(lang1, audio) is False:
                        self.try_audio(lang2, audio)

            # UP NEXT: Pošli signál čo najskôr po začatí prehrávania (podľa dokumentácie)
            # notification_offset v dátach povie Up Next pluginu kedy má zobraziť popup
            if self.item and self.item['info'].get('episode') is not None:
                if get_cond_visibility('System.hasAddon(service.upnext)'):
                    debug('Up Next addon detekovaný, posielam signál...')
                    try:
                        self.send_up_next()
                        self.up_next = True
                    except Exception:
                        debug('send_up_next ERROR: {}'.format(traceback.format_exc()))
                        pass

    def _is_same_language(self, lang1, lang2):
        """Porovná dva jazykové kódy (napr. 'cz' vs 'ces' vs 'cze')"""
        # Normalizuj jazyky na lowercase
        l1 = lang1.lower().strip()
        l2 = lang2.lower().strip()

        # Priame porovnanie
        if l1 == l2:
            return True

        # Mapy variant jazyka
        lang_map = {
            'sk': ['sk', 'slo', 'slk', 'slovak'],
            'cz': ['cz', 'ces', 'cze', 'czech'],
            'en': ['en', 'eng', 'english'],
            'hu': ['hu', 'hun', 'hungarian'],
            'de': ['de', 'deu', 'ger', 'german'],
        }

        # Skontroluj či oba patria do rovnakej skupiny
        for variants in lang_map.values():
            if l1 in variants and l2 in variants:
                return True

        return False

    def try_audio(self, lang, streams):
        if lang == 'sk':
            language_list = ['slo', 'sk', 'slk', 'SK']
        elif lang == 'cz':
            language_list = ['cze', 'cz', 'ces', 'CZ']
        elif lang == 'en':
            language_list = ['eng', 'en', 'EN']
        else:
            debug("iny jazyk {}".format(lang))
            language_list = [lang.lower(), lang.upper()]

        for i in language_list:
            if i in streams:
                debug("mame audio: {} pre jazyk {}".format(i, lang))
                stream_number = streams.index(i)
                debug("menim audio stopu na {} ({})".format(stream_number, i))
                self.setAudioStream(stream_number)
                # dnotify(lang, '', time=1000, sound=False)
                return True
        return False

    def onAVStarted(self):
        debug('player onAVStarted')
        # 4.5 fix #5: save_last_stream + clear play-request timer NA ZAČIATKU,
        # PRED busy-wait slučkou — pomalý ale úspešný štart musí timer zrušiť
        # skôr než ho service.py stihne vyhodnotiť ako zlyhanie.
        try:
            from resources.lib.services.bug_report.last_stream import save_last_stream
            from resources.lib.common.storage import Storage
            _sel_raw = self.win.getProperty(SC.SELECTED_ITEM)
            if _sel_raw:
                from json import loads as _loads
                save_last_stream(_loads(_sel_raw))
            # Zruš play-request timestamp (cancel fail-timer)
            _play_storage = Storage(SC.BUG_REPORT_PLAY_TS)
            _play_storage['ts'] = None
            debug('BugReport: onAVStarted — play-request timer cleared')
        except Exception:
            pass
        for i in range(0, 500):
            if self.isPlayback():
                break
            else:
                debug('not playing')
                sleep(1000)
        self.set_item()

    def onAVChange(self):
        debug('player onAVChange')
        if self.is_my_plugin is True:
            debug('moj plugin')

    def onPlayBackEnded(self):
        debug('player onPlayBackEnded')
        self.end_playback()

    def onPlayBackStopped(self):
        debug('player onPlayBackStopped')
        self.end_playback()

    def onPlayBackError(self):
        debug('player onPlayBackError')
        # 4.5: okamžitá detekcia zlyhania — vyčisti timer a ponúkni report
        try:
            from resources.lib.common.storage import Storage
            from resources.lib.kodiutils import create_plugin_url
            from resources.lib.gui.dialog import dnotify
            from resources.lib.language import Strings
            _play_storage = Storage(SC.BUG_REPORT_PLAY_TS)
            _play_storage['ts'] = None
            _offer_url = create_plugin_url({
                SC.ACTION: SC.ACTION_BUG_REPORT_OFFER,
                'source': 'live_fail',
            })
            dnotify(
                heading=Strings.txt(Strings.CONTEXT_BUG_REPORT),
                message=Strings.txt(Strings.BUG_REPORT_OFFER),
                sound=False,
            )
            debug('BugReport: onPlayBackError — offer notified, timer cleared')
        except Exception:
            pass
        self.end_playback()

    def onPlayBackPaused(self):
        debug('player onPlayBackPaused')
        # NEvolaj end_playback() pri pauze! Video stále beží.
        # Len scrobble pause ak je to náš plugin
        if self.movie is not None:
            self.movie.scrobble(self.percent_played(), SCKODIItem.SCROBBLE_PAUSE)

    def onPlayBackResumed(self):
        debug('player onPlayBackResumed')
        if self.movie is not None:
            self.movie.scrobble(self.percent_played(), SCKODIItem.SCROBBLE_START)

    def onQueueNextItem(self):
        debug('player onQueueNextItem')

    def onPlayBackSpeedChanged(self, speed):
        debug('player onPlayBackSpeedChanged {}'.format(speed))

    def onPlayBackSeek(self, time, seekOffset):
        debug('player onPlayBackSeek {} {}'.format(time, seekOffset))

    def onPlayBackSeekChapter(self, chapter):
        debug('player onPlayBackSeekChapter {}'.format(chapter))

    def clean(self):
        debug('player SCPlayer Clean')
        #
        self.win.clearProperty('{}.play'.format(ADDON_ID))
        self.win.clearProperty('SC.play_item')
        self.win.clearProperty(SC.SELECTED_ITEM)
        # Vymažeme ids Window property až teraz (nie hneď po načítaní v set_item)
        self.win.clearProperty('{}.ids'.format(ADDON_ID))
        self.win.clearProperty('script.trakt.ids')
        self.current_time = 0
        self.ids = {}
        self.is_my_plugin = False
        self.item = None
        self.movie = None
        self.my_id = None
        self.up_next = False
        self.total_time = 0
        self.watched = False
        self.scrobbled_final = False
        self.skip_time_start = False
        self.skip_time_end = False
        self.skip_start = False

    def end_playback(self):
        self.set_watched()
        self.clean()

    def percent_played(self):
        try:
            return self.current_time / self.total_time * 100
        except Exception:
            return 0

    def set_watched(self):
        if self.is_my_plugin:
            self.win.setProperty('{}.stop'.format(ADDON_ID), '1')
            percent_played = self.percent_played()

            # Pošli scrobble/stop len raz - zabráň duplikátnym volaniam
            # Toto volanie je dôležité pre Trakt - >= 80% automaticky pridá do history
            if not self.scrobbled_final:
                self.movie.scrobble(percent_played, SCKODIItem.SCROBBLE_STOP)
                self.scrobbled_final = True
                debug('scrobble/stop sent with progress {}%'.format(percent_played))
            else:
                debug('scrobble already sent, skipping duplicate call')

            if percent_played > 80:
                play_count = self.movie.get_play_count()
                play_count = int(play_count) + 1 if play_count is not None else 1
                debug('playcount {}'.format(play_count))
                d = datetime.fromtimestamp(time())
                self.movie.set_play_count(play_count, True)
                self.movie.set_last_played(d.strftime('%Y-%m-%d %H:%M:%S'))
            if 3 < percent_played < 80:
                debug('watched {}'.format(self.current_time))
                self.movie.set_watched(self.current_time)

    def send_up_next(self):
        """
        Pošle notifikáciu do Up Next pluginu s info o ďalšej epizóde
        Používa EpisodeCache namiesto API volania
        """
        try:
            # Získaj aktuálnu sezónu a epizódu
            current_season = self.item['info'].get('season')
            current_episode = self.item['info'].get('episode')

            if not current_season or not current_episode:
                debug('send_up_next: Nie je seriál, preskakujem')
                return

            # Získaj ďalšiu epizódu z EpisodeCache
            from resources.lib.services.episode_cache import episode_cache
            next_ep = episode_cache.get_next_episode(self.my_id, current_season, current_episode)

            if not next_ep:
                debug('send_up_next: Žiadna ďalšia epizóda v cache pre {}x{}'.format(current_season, current_episode))
                return

            next_season, next_episode = next_ep
            debug('send_up_next: Našiel som ďalšiu epizódu {}x{}'.format(next_season, next_episode))

            # Vytvor notifikáciu pre Up Next plugin
            # Podľa dokumentácie: https://github.com/im85288/service.upnext/wiki/Integration

            # Current episode info (aktuálne sa prehráva)
            current_info = self.item.get('info', {})
            current_episode_data = {
                'episodeid': '{}-{}-{}'.format(self.my_id, current_season, current_episode),
                'tvshowid': self.my_id,
                'title': current_info.get('title', ''),
                'art': {
                    'thumb': current_info.get('thumb', ''),
                    'tvshow.clearart': current_info.get('clearart', ''),
                    'tvshow.clearlogo': current_info.get('clearlogo', ''),
                    'tvshow.fanart': current_info.get('fanart', ''),
                    'tvshow.landscape': current_info.get('landscape', ''),
                    'tvshow.poster': current_info.get('poster', ''),
                },
                'season': int(current_season),
                'episode': int(current_episode),
                'showtitle': current_info.get('tvshowtitle', current_info.get('originaltitle', '')),
                'plot': current_info.get('plot', ''),
                'playcount': 0,
                'rating': current_info.get('rating', 0),
                'firstaired': current_info.get('aired', ''),
            }

            # Next episode info (ďalšia epizóda)
            # Minimálne údaje - Up Next plugin ich zobrazí
            next_episode_data = {
                'episodeid': '{}-{}-{}'.format(self.my_id, next_season, next_episode),
                'tvshowid': self.my_id,
                'title': 'S{:02d}E{:02d}'.format(int(next_season), int(next_episode)),  # Fallback title
                'art': {
                    'thumb': current_info.get('thumb', ''),  # Použij rovnaký art
                    'tvshow.clearart': current_info.get('clearart', ''),
                    'tvshow.clearlogo': current_info.get('clearlogo', ''),
                    'tvshow.fanart': current_info.get('fanart', ''),
                    'tvshow.landscape': current_info.get('landscape', ''),
                    'tvshow.poster': current_info.get('poster', ''),
                },
                'season': int(next_season),
                'episode': int(next_episode),
                'showtitle': current_info.get('tvshowtitle', current_info.get('originaltitle', '')),
                'plot': '',  # Nemáme plot pre ďalšiu epizódu
                'playcount': 0,
                'rating': 0,
                'firstaired': '',
            }

            # Play info - ako prehrať ďalšiu epizódu
            # POZNÁMKA: Skúšali sme play_url ale UpNext ho nespúšťal
            # Použijeme play_info (callback cez monitor.py)
            play_info = {
                'url': '/Play/{}/{}/{}'.format(self.my_id, next_season, next_episode)
            }

            # Kompletná Up Next notifikácia
            upnext_data = {
                'current_episode': current_episode_data,
                'next_episode': next_episode_data,
                'play_info': play_info,
            }

            # Ak máme skip notification offset, pridaj ho
            selected_item = loads(self.win.getProperty(SC.SELECTED_ITEM))
            if selected_item and SC.NOTIFICATIONS in selected_item:
                notifications = selected_item.get(SC.NOTIFICATIONS, {})
                if SC.SKIP_END_TITLES in notifications:
                    skip_offset = notifications.get(SC.SKIP_END_TITLES)
                    if skip_offset:
                        upnext_data['notification_offset'] = skip_offset
                        debug('send_up_next: Pridávam notification_offset: {}s'.format(skip_offset))

            debug('send_up_next: Posielam notifikáciu do Up Next plugin')
            debug('send_up_next: current_episode: {}'.format(current_episode_data))
            debug('send_up_next: next_episode: {}'.format(next_episode_data))
            debug('send_up_next: play_info: {}'.format(play_info))
            debug('send_up_next: Full upnext_data: {}'.format(upnext_data))

            # Pošli notifikáciu do Up Next plugin
            upnext_signal(ADDON_ID, upnext_data)

            debug('send_up_next: Notifikácia úspešne odoslaná do UpNext addon')

        except Exception as e:
            debug('send_up_next ERR: {}'.format(traceback.format_exc()))

    def run(self):
        debug('START player bg service')
        m = Monitor()
        self.skip_button = Skip("SkipButton.xml", ADDON.getAddonInfo('path'), "default", "1080i")

        while not m.abortRequested():
            # OPTIMALIZÁCIA: Dynamický interval - kratší pri prehrávaní, dlhší pri idle
            # Znižuje CPU záťaž keď sa neprehráva video
            interval = 500 if self.isPlayback() else 2000
            # Abort-aware čakanie namiesto sleep() - okamžité ukončenie slučky pri vypnutí Kodi
            if m.waitForAbort(interval / 1000.0):
                break

            try:
                self.periodical_check()
            except Exception:
                debug('player bg service ERR {}'.format(traceback.format_exc()))
        debug('END player bg service')

    def getTime1(self):  # type: () -> float
        try:
            return self.getTime()
        except Exception:
            return 0

    def isPlayingVideo1(self):  # type: () -> bool
        try:
            return self.isPlayingVideo()
        except Exception:
            return False

    def periodical_check(self):
        if self.skip_button.is_button_visible is True:
            debug('rusim SKIP button Notification')
            self.skip_button.close()
            self.skip_button.set_visibility()

        if not self.isPlayback() or self.is_my_plugin is False:
            return

        self.current_time = self.getTime()
        self.total_time = self.getTotalTime()

        if get_setting_as_bool('plugin.show.skip.button') and self.isSkipTime():
            debug('skip: {} / {} / {}'.format(self.skipped_item, self.my_id, self.skip_start))
            if self.skipped_item == self.my_id and self.skip_start is False:
                self.skipStart()
            else:
                self.skip_button.show_with_callback(self.skipStart)
        elif get_setting_as_bool('plugin.show.skip.button'):
            if self.skip_button.is_button_visible is True:
                debug('rusim SKIP button Notification')
                self.skip_button.close()
                self.skip_button.set_visibility()

        try:
            percent_played = self.current_time / self.total_time * 100
        except Exception:
            percent_played = 0
        # debug('self.watched: {} {}'.format(self.watched, percent_played))
        if percent_played >= 80 and not self.watched:
            self.set_watched()
            self.watched = True

    def isSkipTime(self):
        if self.skip_time_start is False or self.skip_time_end is False:
            return False

        return self.skip_time_start <= self.current_time < self.skip_time_end - 5

    def skipStart(self):
        self.skipped_item = self.my_id
        self.skip_start = True
        self.seekTime(self.skip_time_end)

    def isPlayback(self):  # type: () -> bool
        return self.isPlaying() and self.isPlayingVideo() and self.getTime() >= 0


player = SCPlayer()
