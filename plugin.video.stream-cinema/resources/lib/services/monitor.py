import traceback

from xbmc import Monitor as KMonitor
from resources.lib.common.logger import debug
from resources.lib.common.storage import KodiViewModeDb
from resources.lib.constants import ADDON_ID
from resources.lib.kodiutils import encode, decode, exec_build_in, create_plugin_url
from resources.lib.gui import home_win
from resources.lib.services.player import player
from resources.lib.api.kraska import getKraInstance, PROXY_SESSION_PROP, RENEWED_URL_PROP

from json import loads


class Monitor(KMonitor):
    SORT_ASC = 1
    SORT_DESC = 2

    SORT_METHOD_NONE = 0
    SORT_METHOD_RATING = 17
    SORT_METHOD_MPAA = 31
    SORT_METHOD_TITLE = 29
    SORT_METHOD_YEAR = 16
    SORT_METHOD_DATE_ADDED = 40

    def __init__(self):
        self.win = home_win
        self.is_screensaver = False
        self.is_DPMS = False
        self.is_scanning = False
        self.is_cleaning = False
        self.sort_method = self.SORT_METHOD_NONE
        self.sort_order = self.SORT_ASC
        self.last_url = None
        self.filter = {}
        self.callback = {
            'Player.OnAVStart': self.PlayerOnAVStart,
            'System.OnSleep': self.onSleep,
            'System.OnWake': self.onWake,
        }

    def onSettingsChanged(self):
        debug('monitor onSettingsChanged')
        # Priebezna zaloha settings.xml - kopiruje sa len validny subor,
        # takze pripadne poskodenie sa do zalohy neprenesie (debounce 30s)
        try:
            from resources.lib.common.settings_backup import backup_settings
            backup_settings()
        except Exception:
            debug('settings backup err: {}'.format(traceback.format_exc()))

    def onScreensaverActivated(self):
        debug('monitor onScreensaverActivated')
        self.is_screensaver = True

    def onScreensaverDeactivated(self):
        debug('monitor onScreensaverDeactivated')
        self.is_screensaver = False

    def onDPMSActivated(self):
        debug('monitor onDPMSActivated')
        self.is_DPMS = True

    def onDPMSDeactivated(self):
        debug('monitor onDPMSDeactivated')
        self.is_DPMS = False

    def onScanStarted(self, library):
        debug('monitor onScanStarted {}'.format(library))
        self.is_scanning = True

    def onScanFinished(self, library):
        debug('monitor onScanFinished {}'.format(library))
        self.is_scanning = False

    def onCleanStarted(self, library):
        debug('monitor onCleanStarted {}'.format(library))
        self.is_cleaning = True
        pass

    def onCleanFinished(self, library):
        debug('monitor onCleanFinished {}'.format(library))
        self.is_cleaning = False
        pass

    def onSleep(self, data):
        self.is_DPMS = True

    def onWake(self, data):
        self.is_DPMS = False

    def PlayerOnAVStart(self, data):
        debug('Monitor PlayerOnAVStart')
        # player.set_item(loads(data).get('item'))

    def helper_session_expired(self, data):
        """service.sc.helper oznamil, ze stream session vyprsala. Ak ide o poslednu
        session, ktoru sme vyziadali, obnovi resolve a novu URL ulozi do
        RENEWED_URL_PROP. Samotne prepnutie prehravaca rieši player.
        """
        try:
            session_id = loads(data).get('session_id')
            last = self.win.getProperty(PROXY_SESSION_PROP)
            if not last or not session_id:
                return
            last = loads(last)
            if last.get('session_id') != session_id:
                debug('session_expired pre neaktualnu session, ignorujem')
                return
            url = getKraInstance().resolve_via_proxy(last.get('ident'), last.get('server'), background=True)
            if url:
                self.win.setProperty(RENEWED_URL_PROP, url)
                debug('session obnovena po session_expired')
        except Exception:
            debug('session_expired obnova zlyhala: {}'.format(traceback.format_exc()))

    def onNotification(self, sender, method, data):
        debug('monitor onNotification {} {} {}'.format(decode(sender), decode(method), decode(data)))
        if method in self.callback:
            debug('callback for {}'.format(method))
            self.callback[method](data)
        # if sender == 'xbmc' and method == 'Player.OnAVStart':
            # debug('monitor Player.OnAVChange, set item to: {}'.format(loads(data).get('item')))
            # player.set_item(loads(data).get('item'))
        if sender == 'service.sc.helper.SIGNAL' and method == 'Other.session_expired':
            self.helper_session_expired(data)
        if sender == 'xbmc' and method == 'System.OnSleep':
            self.is_DPMS = True
        if sender == 'xbmc' and method == 'System.OnWake':
            self.is_DPMS = False
        if sender == 'upnextprovider.SIGNAL' and method == 'Other.{}_play_action'.format(ADDON_ID):
            # UpNext callback - UpNext triggeruje ďalšiu epizódu cez play_info
            from base64 import b64decode
            debug('Monitor: UpNext play_action callback')

            # KĽÚČOVÉ: Vymaž autoplay_done flag aby continuous playback fungoval
            # Keď UpNext triggeruje ďalšiu epizódu, chceme aby pri ďalšom použití
            # zoznamu epizód (po skončení tejto epizódy) auto-play znova fungoval
            autoplay_done_key = '{}.last_series.autoplay_done'.format(ADDON_ID)
            self.win.clearProperty(autoplay_done_key)
            debug('Monitor: Cleared autoplay_done for continuous UpNext playback')

            # BEZPEČNOSŤ: Zastav aktuálne video pred spustením nového
            # Použijeme PlayMedia priamo - Kodi automaticky zastaví staré video
            # a spustí nové (bez dvoch busydialogov ktoré spôsobujú crash)
            debug('Monitor: Spúšťam novú epizódu (Kodi automaticky zastaví staré video)')
            exec_build_in('PlayMedia({})'.format(create_plugin_url(loads(b64decode(data)))))
            pass
        # if sender == ADDON_ID and method == 'Other.List.Sort':
        #     from base64 import b64decode
        #     info = loads(b64decode(data))
        #     debug('new List.Sort: method: {} order {} url: {}'.format(info['m'], info['o'], info['u']))
        #     self.sort_method = info['m']
        #     self.sort_order = info['o']
        #     self.last_url = info['u']
        #     self.filter = info['f']

    def periodical_check(self):
        return
        try:
            kv = KodiViewModeDb()
            sort = kv.get_sort(self.last_url)
            if sort is None:
                sort = (0, 1)
        except Exception:
            debug('ERR: {}'.format(traceback.format_exc()))
            sort = (0, 1)
        # debug("{}/{} => {}/{} | {}".format(sort[0], sort[1], self.sort_method, self.sort_order, self.last_url))
        if self.last_url and (sort[0] != self.sort_method or sort[1] != self.sort_order):
            debug('============ refresh {} ============'.format(self.last_url))
            # container_refresh()

    def can_check(self):
        return not self.is_screensaver and not self.is_DPMS and not player.isPlayback()


monitor = Monitor()
