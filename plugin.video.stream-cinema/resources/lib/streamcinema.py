# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals

import traceback

import xbmcgui
import xbmcplugin
import xbmc
from json import dumps, loads

from resources.lib.common.kodivideocache import set_kodi_cache_size
from resources.lib.debug import performance
from resources.lib.intro import intro
from resources.lib.kodiutils import params, container_refresh, urlencode, container_update, create_plugin_url, \
    exec_build_in, get_setting, update_addon, set_setting_as_bool, notify, get_setting_as_bool
from resources.lib.router import Router
from resources.lib.common.logger import info, debug
from resources.lib.common.lists import List, SCKODIItem
from resources.lib.constants import SORT_METHODS, SC, GUI, ADDON_ID, ADDON, CACHE_ENABLED, CACHE_MENU_ENABLED
from resources.lib.api.sc import Sc
from resources.lib.gui import cur_win, home_win
from resources.lib.gui.dialog import dok, dinput, dselect, dyesno, dnotify
from resources.lib.gui.item import SCItem, get_history_item_name, list_hp, SCLDir, SCUpNext, UserCancelledException
from resources.lib.common.storage import Storage, KodiViewModeDb, preferred_lang_list
from resources.lib.language import Strings
from resources.lib.params import params
from resources.lib.services.next_episodes import NextEp
from resources.lib.gui_cache import get_language_code


class Scinema:
    def __init__(self):
        self.args = params.args
        self.items_pinned = []
        self.items = []
        self.response = []
        self.succeeded = False
        self.update_listing = False
        self.cache_to_disc = False
        self.url = '/'
        self.payload = None
        self.storage = Storage('scinema')
        self.send_end = False
        self.listType = None
        self.last_response_filter = None  # Filter data z poslednej API odpovede

    def run(self):

        if SC.ITEM_URL in self.args:
            self.url = self.args.get(SC.ITEM_URL)

        # REMOVED: Redirect počas playbacku už nie je potrebný s reuselanguageinvoker=true
        # Umožňuje používateľom prepínať epizódy počas prehrávania
        # Titulky sa načítavajú automaticky cez setSubtitles() v gui/item.py
        # if self.url == '/' and xbmc.Player().isPlayingVideo() and home_win.getProperty('{}.play'.format(ADDON_ID)):
        #     container_update('special://home', True)
        #     self.succeeded = False
        #     self.end_of_directory()
        #     return

        if SC.ITEM_URL in self.args and self.args.get(SC.ITEM_URL).startswith('http'):
            self.args.update({SC.ITEM_ACTION: SC.ACTION_PLAY_URL})

        info('Start: {} [{}]'.format(str(self.args), self.url))

        if 'title' in self.args:
            home_win.setProperty('SCTitle', self.args.get('title'))
        else:
            home_win.clearProperty('SCTitle')

        if SC.ACTION in self.args:
            exit_code = self.action()
            if exit_code is True:
                return
        elif 'play' in self.args:
            '''
            stara URL zo SC CS&SK pre play aby fungovala kniznica
            '''
            self.url = self.args.get('play')
            self.call_url_and_response()
        else:
            self.call_url_and_response()
        self.end()

    def action(self):
        action = self.args.get(SC.ITEM_ACTION)
        if action == SC.ACTION_PLAY_URL:
            self.play_url(self.args.get(SC.ITEM_URL))
            self.succeeded = True
        elif action == SC.ACTION_CMD:
            self.action_cmd()
        elif action == 'intro':
            intro(2, True)
        elif action == SC.ACTION_PIN:
            self.action_pin()
        elif action == SC.ACTION_CSEARCH:
            self.action_csearch()
        elif action == 'search_new':
            self.action_search_new()
        elif action == 'search_from_history':
            self.action_search_from_history()
        elif action == 'search_edit':
            self.action_search_edit()
        elif action == 'search_delete':
            self.action_search_delete()
        elif action == 'search_clear_all':
            self.action_search_clear_all()
        elif action == SC.ACTION_LAST:
            self.action_last()
        elif action == 'nextep':
            self.action_next_ep()
        elif action == 'update_nextep':
            self.action_update_next_ep()
            return True
        elif action == 'search_next_episodes':
            self.action_search_next_episodes()
        elif action == SC.ACTION_DEBUG:
            from resources.lib.kodiutils import check_set_debug

            check_set_debug(True)
        elif action == SC.ACTION_DOWNLOAD:
            self.url = self.args.get(SC.ITEM_DOWNLOAD)
            self.call_url_and_response()
        elif action == SC.ACTION_DOWNLOAD_QUEUE:
            from resources.lib.services.download_queue import show_queue_dialog
            show_queue_dialog()
            return True
        elif action == SC.ACTION_FILTER:
            self.action_filter()
            return True
        elif action == SC.ACTION_LOAD_SAVED_FILTER:
            self.action_load_saved_filter()
            return True
        elif action == SC.ACTION_DELETE_SAVED_FILTER:
            self.action_delete_saved_filter()
            return True
        elif action == SC.ACTION_EDIT_SAVED_FILTER:
            self.action_edit_saved_filter()
            return True
        elif action == SC.ACTION_RENAME_SAVED_FILTER:
            self.action_rename_saved_filter()
            return True
        elif action == SC.ACTION_BUFFER:
            set_kodi_cache_size()
        elif action == SC.ACTION_ANDROID:
            self.action_android()
        elif action == SC.ACTION_ADD2HP:
            self.action_add2hp()
        elif action == SC.ACTION_DEL2HP:
            self.action_add2hp(True)
        elif action == SC.ACTION_ADD_CUSTOM_FILTER:
            self.action_add_custom_filter()
        elif action == SC.ACTION_DEL_CUSTOM_FILTER:
            self.action_add_custom_filter(True)
        elif action == SC.ACTION_REMOVE_FROM_LIST:
            self.action_remove_from_list()
        elif action == SC.ACTION_UPDATE_ADDON:
            update_addon()
        elif 'trakt.' in action:
            from resources.lib.trakt.Trakt import trakt
            trakt.action(action, self)
            return True
        elif action in ['add_to_library', 'add_to_library_sub']:
            lib = List(SC.ITEM_LIBRARY)
            lib.add(self.args.get(SC.ITEM_ID))
            if action == 'add_to_library_sub':
                sub = List(SC.ITEM_LIBRARY_SUB)
                sub.add(self.args.get(SC.ITEM_ID))
            Router.refresh()
        elif action == 'remove_from_sub':
            lib = List(SC.ITEM_LIBRARY)
            lib.add(self.args.get(SC.ITEM_ID), True)
            if action == 'remove_from_sub':
                sub = List(SC.ITEM_LIBRARY_SUB)
                sub.add(self.args.get(SC.ITEM_ID), True)
            Router.refresh()
        elif action == 'autocomplet':
            from resources.lib.services.autocomplete import Autocomplete
            Autocomplete(self.args)
            return True
        elif action == SC.ACTION_DEL_PREFERRED_LANGUAGE:
            del preferred_lang_list[self.args.get(SC.ITEM_ID)]
            Router.refresh()
            return
        elif action == SC.ACTION_SET_PREFERRED_LANGUAGE:
            lang_list = Sc.get('/Lang/{}'.format(self.args.get(SC.ITEM_ID)))
            debug('parametre: {} / langs: {}'.format(self.args, lang_list))
            ret = dselect(lang_list, Strings.txt(Strings.CONTEXT_ADD_PREF_LANG))
            if ret > -1:
                st = preferred_lang_list
                st[self.args.get(SC.ITEM_ID)] = lang_list[ret]
                debug('znovelene: {} / {}'.format(ret, st[self.args.get(SC.ITEM_ID)]))
                Router.refresh()
            return
        elif action == SC.ACTION_HIDE_HP_ITEM:
            self.action_hide_hp_item()
        elif action == SC.ACTION_RESET_HIDDEN:
            self.action_reset_hidden()
        elif action == SC.ACTION_BUG_REPORT:
            self.action_bug_report()
            return True
        elif action == SC.ACTION_BUG_REPORT_OFFER:
            self.action_bug_report_offer()
            return True
        else:
            info('Neznama akcia: {}'.format(action))
        return False

    def action_remove_from_list(self):
        st = List(self.args[SC.ITEM_PAGE])
        st.add(self.args[SC.ITEM_ID], True)
        Router.refresh()
        pass

    def action_android(self):
        st = List('android')
        st.add(self.args)

    def action_add2hp(self, remove=False):
        st = list_hp
        del self.args[SC.ACTION]
        if remove is False:
            label = dinput('Zadaj vlastny nazov', self.args[SC.ITEM_ID])
            if label == '':
                label = self.args[SC.ITEM_ID]
            self.args[SC.ITEM_ID] = label

        st.add(self.args, remove_only=remove)
        if remove is True:
            Router.refresh()

    def action_hide_hp_item(self):
        """Skryje položku z HP pridaním do zoznamu skrytých"""
        item_id = self.args.get(SC.ITEM_ID)
        if not item_id:
            return

        hidden_items = self.storage.get('hidden_hp_items') or []
        if item_id not in hidden_items:
            hidden_items.append(item_id)
            self.storage['hidden_hp_items'] = hidden_items

        Router.refresh()

    def action_reset_hidden(self):
        """Obnoví všetky skryté položky na HP"""
        self.storage['hidden_hp_items'] = []
        from resources.lib.gui.dialog import dok
        dok(ADDON.getLocalizedString(30331), ADDON.getLocalizedString(30332))
        Router.refresh()

    def action_bug_report(self):
        """Otvorí wizard na nahlasovanie chýb.

        Zdroj stream kontextu:
        - 'live_fail'   — play-request timestamp v Storage ešte aktívny (selhanie)
        - 'last_played' — media_id z args sedí s uloženým last_stream kontextom
        - 'none'        — inak (napr. Tools vstup)
        """
        from resources.lib.services.bug_report.last_stream import load_last_stream
        from resources.lib.services.bug_report.wizard import BugReportWizard
        from resources.lib.common.storage import Storage
        import time as _time

        source = 'none'
        stream_ctx = None

        # Zistí či ide o live_fail (play-request timestamp stále žije)
        try:
            play_storage = Storage(SC.BUG_REPORT_PLAY_TS)
            play_storage.load(True)
            ts = play_storage.get('ts')
            if ts is not None:
                elapsed = _time.time() - float(ts)
                if 0 < elapsed < SC.BUG_REPORT_FAIL_TIMEOUT * 2:
                    source = 'live_fail'
                    stream_ctx = play_storage.get('stream_ctx') or {}
        except Exception:
            pass

        # Fallback: skús last_played podľa media_id z args
        if source == 'none':
            try:
                last = load_last_stream()
                if last:
                    arg_media_id = self.args.get(SC.ITEM_ID)
                    last_media_id = last.get('media_id')
                    if arg_media_id and last_media_id and str(arg_media_id) == str(last_media_id):
                        source = 'last_played'
                        stream_ctx = last
                    elif last:
                        # Ak nie je media_id zhoda, ponúkni last_played bez zhody
                        source = 'last_played'
                        stream_ctx = last
            except Exception:
                pass

        wizard = BugReportWizard(stream_ctx=stream_ctx, source=source)
        # Systémové dialógy (xbmcgui.Dialog) — funguje v každom skine / verzii.
        wizard.run()

    def action_bug_report_offer(self):
        """Handler auto-ponuky z notifikácie (onPlayBackError / fail-timeout).

        Otvára wizard s kontextom live_fail ak je dostupný.
        """
        from resources.lib.services.bug_report.last_stream import load_last_stream
        from resources.lib.services.bug_report.wizard import BugReportWizard
        from resources.lib.common.storage import Storage
        import time as _time

        source_arg = self.args.get('source', 'live_fail')

        stream_ctx = None
        source = source_arg if source_arg in ('live_fail', 'last_played', 'none') else 'live_fail'

        # Načítaj stream kontext z play storage (live_fail)
        if source == 'live_fail':
            try:
                play_storage = Storage(SC.BUG_REPORT_PLAY_TS)
                play_storage.load(True)
                stream_ctx = play_storage.get('stream_ctx') or {}
            except Exception:
                pass

        if stream_ctx is None:
            try:
                stream_ctx = load_last_stream() or {}
            except Exception:
                stream_ctx = {}

        wizard = BugReportWizard(stream_ctx=stream_ctx or None, source=source)
        # Systémové dialógy (xbmcgui.Dialog) — funguje v každom skine / verzii.
        wizard.run()

    def action_add_custom_filter(self, remove=False):
        if SC.ITEM_PAGE in self.args:
            st = List(SC.TXT_CUSTOM_FORMAT.format(self.args[SC.ITEM_PAGE]))
        else:
            st = List(SC.TXT_CUSTOM_FORMAT.format(self.url))

        cfg = {
            SC.ITEM_URL: '',
            SC.ITEM_TITLE: '',
        }
        if remove is False:
            label = dinput('Zadaj nazov polozky')
            if label == '':
                label = self.args[SC.ITEM_ID]
            cfg[SC.ITEM_TITLE] = label

            url = dinput('Zadaj url pre [B]plugin[/B] z https://stream-cinema.online/filter', '')
            if url == '':
                return False
            cfg[SC.ITEM_URL] = url
        else:
            cfg.update({
                SC.ITEM_URL: self.args[SC.ITEM_URL],
                SC.ITEM_TITLE: self.args[SC.ITEM_TITLE],
            })

        st.add(cfg, remove_only=remove)
        if remove is True:
            Router.refresh()

    def action_last(self):
        lid = get_history_item_name(self.args.get(SC.ITEM_ID))
        st = List(lid)
        if len(st.get()) > 0:
            self.url = '/Last'
            self.payload = {"ids": dumps(st.get())}
            self.call_url_and_response()
        else:
            if SC.ITEM_WIDGET not in self.args:
                dok(Strings.txt(Strings.EMPTY_HISTORY_H1), Strings.txt(Strings.EMPTY_HISTORY_L1))

    def action_next_ep(self):
        st = NextEp().get()
        if len(st) > 0:
            self.url = '/Last?nextep=1'
            self.payload = dict(ids=dumps(st))
            self.call_url_and_response()
        else:
            pass

    def action_update_next_ep(self):
        st = NextEp()
        st.update_items()

    def action_cmd(self):
        url = self.args.get('url')
        if url.startswith('cmd://'):
            cmd = url[6:]
            info('CMD: {}'.format(cmd))
            # Polozka s cmd:// je directory item - handle treba uvolnit
            # PRED vykonanim prikazu (succeeded=False, nejde o listing),
            # inak GetDirectory caka donekonecna a busy spinner nezmizne
            self.end_of_directory()
            exec_build_in(cmd)

    def action_force_select_stream(self):
        pass

    def action_pin(self):
        pinned = self.get_pinned()
        if pinned and self.args.get(SC.ITEM_ID) in pinned:
            info('remove')
            del pinned[self.args.get(SC.ITEM_ID)]
        else:
            info('add')
            pinned.update({self.args.get(SC.ITEM_ID): True})
        self.set_pinned(pinned)
        Router.refresh()

    def action_csearch(self):
        """
        Zobrazí históriu vyhľadávania namiesto promptu
        """
        _id = self.args.get(SC.ITEM_ID)
        # Zobraz históriu ako menu items
        self._show_search_history(_id)

    def _show_search_history(self, search_type):
        """
        Zobrazí históriu vyhľadávania ako KODI directory listing

        Args:
            search_type: ID typu vyhľadávania (napr. 'search-movies', 'fdocu', 'fanime')
        """
        from resources.lib.storage.search_history import SearchHistory
        from datetime import datetime

        history = SearchHistory(search_type)
        items_list = history.get_all()

        # Získaj filter_params z args (ak existujú - pre filter search)
        filter_params = self.args.get('filter_params')

        # 1. Pridaj "Nové vyhľadávanie" ako prvú položku
        new_search_data = {
            'type': 'action',
            'title': '[B]{}[/B]'.format(ADDON.getLocalizedString(30300)),
            SC.ITEM_ACTION: 'search_new',
            SC.ITEM_ID: search_type,
        }
        # Pridaj filter_params ak existujú (pre filter search)
        if filter_params:
            new_search_data['filter_params'] = filter_params

        new_search_item = SCItem(new_search_data)
        self.items.append(new_search_item.get())

        # 2. Pridaj položky histórie
        for item in items_list:
            query = item['query']
            timestamp = item['timestamp']

            debug('_show_search_history: Creating history item for query="{}"'.format(query))

            history_item_data = {
                'type': 'action',
                'title': query,
                SC.ITEM_ACTION: 'search_from_history',
                SC.ITEM_ID: search_type,
                'search': query,
                'info': {
                    'plot': self._format_timestamp(timestamp)
                }
            }
            debug('_show_search_history: history_item_data = {}'.format(history_item_data))
            # Pridaj filter_params ak existujú (pre filter search)
            if filter_params:
                history_item_data['filter_params'] = filter_params

            history_item = SCItem(history_item_data)
            self.items.append(history_item.get())

        # Pošli items do KODI
        if len(self.items) > 0:
            xbmcplugin.addDirectoryItems(params.handle, self.items)

        self.succeeded = True
        self.end_of_directory()

    def _format_timestamp(self, timestamp):
        """
        Konvertuje unix timestamp na čitateľný formát

        Args:
            timestamp: Unix timestamp (int)

        Returns:
            str: Formátovaný dátum (napr. "Posledné: 15.10.2025 20:45")
        """
        from datetime import datetime
        dt = datetime.fromtimestamp(timestamp)
        date_str = dt.strftime('%d.%m.%Y %H:%M')
        return ADDON.getLocalizedString(30309).format(date=date_str)

    def action_search_new(self):
        """
        Zobrazí input prompt pre nové vyhľadávanie
        """
        _id = self.args.get(SC.ITEM_ID)
        filter_params = self.args.get('filter_params')

        home_win.setProperty('SC.search', '{}'.format(_id))
        search = dinput('', '', xbmcgui.INPUT_TYPE_TEXT)
        home_win.clearProperty('SC.search')

        if search == '':
            # Používateľ zrušil prompt - vráť sa do histórie vyhľadávania
            # Použijeme replace=True aby sme nahradili search_new v navigation stacku
            search_history_data = {
                SC.ITEM_ACTION: SC.ACTION_CSEARCH,
                SC.ITEM_ID: _id
            }
            # Pridaj filter_params ak existujú (pre filter search)
            if filter_params:
                search_history_data['filter_params'] = filter_params

            search_history_url = create_plugin_url(search_history_data)
            container_update(search_history_url, replace=True)
            return

        # Pridaj do histórie
        from resources.lib.storage.search_history import SearchHistory
        history = SearchHistory(_id)
        history.add(search)

        # Vykonaj vyhľadávanie - zisti či je to filter search alebo regular search
        if filter_params:
            # Filter search pre /FDocu alebo /FAnime
            self._perform_filter_search(_id, search, filter_params)
        else:
            # Regular search
            self._perform_search(_id, search)

    def action_search_from_history(self):
        """
        Vyhľadá zo zvolenej položky histórie

        VOLÁ SA: Pri kliknutí na položku histórie (hlavná akcia)
        """
        _id = self.args.get(SC.ITEM_ID)
        query = self.args.get('search')
        filter_params = self.args.get('filter_params')

        # Aktualizuj timestamp (posunie na vrch histórie)
        from resources.lib.storage.search_history import SearchHistory
        history = SearchHistory(_id)
        history.add(query)  # add() automaticky aktualizuje timestamp ak existuje

        # Vykonaj vyhľadávanie - zisti či je to filter search alebo regular search
        if filter_params:
            # Filter search pre /FDocu alebo /FAnime
            self._perform_filter_search(_id, query, filter_params)
        else:
            # Regular search
            self._perform_search(_id, query)

    def action_search_edit(self):
        """
        Upraví položku z histórie

        VOLÁ SA: Context menu → "Upraviť"
        """
        _id = self.args.get(SC.ITEM_ID)
        old_query = self.args.get('search')

        # Zobraz input s predvyplneným textom
        new_query = dinput(ADDON.getLocalizedString(30307), old_query, xbmcgui.INPUT_TYPE_TEXT)

        if not new_query or new_query == old_query:
            return  # Cancel alebo rovnaký text

        # Aktualizuj históriu
        from resources.lib.storage.search_history import SearchHistory
        history = SearchHistory(_id)
        history.edit(old_query, new_query)

        # Refresh histórie vyhľadávania (zobraz aktualizovanú históriu)
        Router.refresh()

    def action_search_delete(self):
        """
        Vymaže položku z histórie

        VOLÁ SA: Context menu → "Vymazať"
        """
        from resources.lib.gui.dialog import dyesno

        _id = self.args.get(SC.ITEM_ID)
        query = self.args.get('search')

        # Confirm dialog
        heading = ADDON.getLocalizedString(30303)
        message = ADDON.getLocalizedString(30305).format(query=query)
        if not dyesno(heading, message):
            return

        # Vymaž z histórie
        from resources.lib.storage.search_history import SearchHistory
        history = SearchHistory(_id)
        history.delete(query)

        # Refresh
        Router.refresh()

    def action_search_clear_all(self):
        """
        Vymaže celú históriu

        VOLÁ SA: Context menu → "Vymazať všetko"
        """
        from resources.lib.gui.dialog import dyesno

        _id = self.args.get(SC.ITEM_ID)

        # Confirm dialog
        heading = ADDON.getLocalizedString(30304)
        message = ADDON.getLocalizedString(30306)
        if not dyesno(heading, message):
            return

        # Vymaž celú históriu
        from resources.lib.storage.search_history import SearchHistory
        history = SearchHistory(_id)
        history.clear()

        # Refresh
        Router.refresh()

    def _perform_search(self, search_id, query):
        """
        Vykoná vyhľadávanie (pôvodná logika z action_csearch)

        Args:
            search_id: ID typu vyhľadávania
            query: Vyhľadávací text
        """
        # Ulož do listu (kompatibilita so starou logikou)
        st = List(search_id)
        st.add(query)

        debug('SEARCH: _ID "{}" search for "{}"'.format(search_id, query))

        # Vytvor base URL bez query parametrov
        self.url = '/Search/{}'.format(search_id)

        # Priprav parametre pre Sc.get() - pošli ich ako params dict, NIE v URL
        # Toto zabezpečí správne spracovanie v sc.py prepare() metóde
        search_params = {'search': query, SC.ITEM_ID: search_id}
        if search_id.startswith('search-people'):
            search_params.update({'ms': '1'})

        debug('SEARCH: URL "{}" with params: {}'.format(self.url, search_params))

        # Volaj API s parametrami
        try:
            self.response = Sc.get(self.url, params=search_params)
        except:
            debug('CALL URL ERR: {}'.format(traceback.format_exc()))
            self.response = {}

        if 'msgERROR' in self.response.get('system', {}):
            self.msg_error()
            # Vráť sa do histórie vyhľadávania
            search_history_url = create_plugin_url({
                SC.ITEM_ACTION: SC.ACTION_CSEARCH,
                SC.ITEM_ID: search_id
            })
            container_update(search_history_url, replace=True)
            return

        # Parse response a zobraz výsledky
        # NEPOUŽÍVAME Router.go() - zobrazíme výsledky bez pridania do navigation stacku
        # Takto "back" pôjde priamo do histórie vyhľadávania
        self.parse_response()

    def _perform_filter_search(self, search_id, query, filter_params):
        """
        Vykoná filter-based vyhľadávanie pre /FDocu a /FAnime

        Args:
            search_id: ID typu vyhľadávania (napr. 'fdocu', 'fanime')
            query: Vyhľadávací text
            filter_params: JSON string s predvyplnenými filter parametrami zo servera
        """
        from resources.lib.api.filter import filter_api

        debug('FILTER_SEARCH: _ID "{}" search for "{}" with filter_params: {}'.format(
            search_id, query, filter_params))

        # Parse filter_params (príde ako JSON string z URL)
        try:
            if isinstance(filter_params, str):
                filter_dict = loads(filter_params)
            else:
                filter_dict = filter_params
        except:
            debug('FILTER_SEARCH: Error parsing filter_params: {}'.format(traceback.format_exc()))
            filter_dict = {}

        # Pridaj search query do filter parametrov
        filter_dict['s'] = query

        debug('FILTER_SEARCH: Merged filter params: {}'.format(filter_dict))

        # Volaj Filter API
        try:
            # Spoj include/exclude parametre pred volaním API
            api_params = self._merge_include_exclude_params(filter_dict)
            debug('FILTER_SEARCH: Calling /Filter with merged params: {}'.format(api_params))

            self.response = filter_api.get_filtered(api_params)

            # Ulož stream-related filter parametre pre použitie pri výbere streamov
            stream_prefs = self._extract_stream_preferences(filter_dict)
            if stream_prefs:
                home_win.setProperty(SC.STREAM_FILTER_PREFS, dumps(stream_prefs))
                debug('FILTER_SEARCH: Saved stream preferences to Window property: {}'.format(stream_prefs))
            else:
                home_win.clearProperty(SC.STREAM_FILTER_PREFS)
                debug('FILTER_SEARCH: Cleared stream preferences from Window property')

        except:
            debug('FILTER_SEARCH: Error calling filter API: {}'.format(traceback.format_exc()))
            self.response = {}

        if 'msgERROR' in self.response.get('system', {}):
            self.msg_error()
            # Vráť sa do histórie vyhľadávania
            search_history_url = create_plugin_url({
                SC.ITEM_ACTION: SC.ACTION_CSEARCH,
                SC.ITEM_ID: search_id,
                'filter_params': filter_params
            })
            container_update(search_history_url, replace=True)
            return

        # Parse response a zobraz výsledky
        # NEPOUŽÍVAME Router.go() - zobrazíme výsledky bez pridania do navigation stacku
        # Takto "back" pôjde priamo do histórie vyhľadávania
        self.parse_response()

    def action_search_next_episodes(self):
        NextEp().run(True)

    def action_filter(self):
        """
        Zobrazí pokročilý filter dialog a aplikuje vybrané filtre
        """
        from resources.lib.gui.filter_dialog import show_filter_dialog
        from resources.lib.api.filter import filter_api
        from resources.lib.storage.filter_storage import filter_storage
        from resources.lib.kodiutils import slugify

        debug('action_filter: Opening filter dialog for URL: {}'.format(self.url))

        # Získaj existujúce filter parametre z Window property (zdieľané medzi requestmi)
        current_filter = {}
        filter_json = home_win.getProperty('SC.FilterContext.Last')
        if filter_json:
            try:
                api_filter = loads(filter_json)
                debug('action_filter: Načítané filter data z Window property: {}'.format(api_filter))
                current_filter = self._extract_filter_params(api_filter)
                debug('action_filter: Extrahované filter parametre: {}'.format(current_filter))
            except Exception as e:
                debug('action_filter: Chyba pri načítaní filtra z Window property: {}'.format(e))
        else:
            debug('action_filter: Žiadne filter data v Window property, otváram prázdny filter')

        # Zobraz filter dialog s predvyplnenými hodnotami
        filter_params, save_filter = show_filter_dialog(current_filter=current_filter)

        if filter_params:
            debug('action_filter: Filter applied with params: {}'.format(filter_params))

            # Ak chce používateľ uložiť filter
            if save_filter:
                filter_name = dinput(ADDON.getLocalizedString(30244))
                if filter_name:
                    # Konvertuj názov na slug (bez diakritiky)
                    filter_slug = slugify(filter_name)
                    debug('action_filter: Saving filter "{}" as slug "{}"'.format(filter_name, filter_slug))
                    # Ulož s originálnym názvom pre zobrazenie
                    filter_storage.save_filter(filter_slug, filter_params, display_name=filter_name)
                    debug('action_filter: Filter saved as slug "{}", display_name "{}"'.format(filter_slug, filter_name))

            # Aplikuj filter - zavolaj Filter API
            try:
                # Spoj include/exclude parametre pred odoslaním
                api_params = self._merge_include_exclude_params(filter_params)
                debug('action_filter: Calling filter API with merged params: {}'.format(api_params))
                self.response = filter_api.get_filtered(api_params)
                debug('action_filter: API response received: {} items'.format(
                    len(self.response.get('menu', [])) if isinstance(self.response, dict) else 'unknown'))

                # Ulož stream-related filter parametre pre použitie pri výbere streamov
                stream_prefs = self._extract_stream_preferences(filter_params)
                if stream_prefs:
                    home_win.setProperty(SC.STREAM_FILTER_PREFS, dumps(stream_prefs))
                    debug('action_filter: Saved stream preferences to Window property: {}'.format(stream_prefs))
                else:
                    # Ak nie sú žiadne stream preferences, vyčisti Window property
                    home_win.clearProperty(SC.STREAM_FILTER_PREFS)
                    debug('action_filter: Cleared stream preferences from Window property')

                self.succeeded = True
                self.parse_response()

                # DÔLEŽITÉ: Zavolaj end() aby sa zobrazili výsledky
                self.end()

            except Exception as e:
                debug('action_filter: Error calling filter API: {}'.format(e))
                import traceback
                debug('action_filter: Traceback: {}'.format(traceback.format_exc()))
                dok('Chyba', 'Nepodarilo sa načítať filtrovaný obsah')
                self.end_of_directory()
        else:
            debug('action_filter: Filter cancelled by user')
            # Užívateľ zrušil dialog - jednoducho ukončíme request
            # Plugin sa ukončí a používateľ zostane na aktuálnej stránke
            self.end_of_directory()

    def action_load_saved_filter(self):
        """
        Načíta a aplikuje uložený filter
        """
        from resources.lib.api.filter import filter_api
        from resources.lib.storage.filter_storage import filter_storage

        # Použijeme 'name' namiesto 'filter_name' (name je v whitelist)
        filter_slug = self.args.get('name')

        if not filter_slug:
            debug('action_load_saved_filter: No name provided in args: {}'.format(self.args))
            dok('Chyba', 'Chýba názov filtra')
            return

        debug('action_load_saved_filter: Loading filter "{}"'.format(filter_slug))

        # Načítaj filter params
        filter_params = filter_storage.get_filter(filter_slug)

        if not filter_params:
            debug('action_load_saved_filter: Filter "{}" not found'.format(filter_slug))
            dok('Chyba', 'Filter "{}" nebol nájdený'.format(filter_slug))
            return

        # Aplikuj filter
        try:
            debug('action_load_saved_filter: Calling filter API with params: {}'.format(filter_params))
            self.response = filter_api.get_filtered(filter_params)
            debug('action_load_saved_filter: API response received: {} items'.format(
                len(self.response.get('menu', [])) if isinstance(self.response, dict) else 'unknown'))

            # Ulož stream-related filter parametre pre použitie pri výbere streamov
            stream_prefs = self._extract_stream_preferences(filter_params)
            if stream_prefs:
                home_win.setProperty(SC.STREAM_FILTER_PREFS, dumps(stream_prefs))
                debug('action_load_saved_filter: Saved stream preferences to Window property: {}'.format(stream_prefs))
            else:
                home_win.clearProperty(SC.STREAM_FILTER_PREFS)
                debug('action_load_saved_filter: Cleared stream preferences from Window property')

            self.succeeded = True
            self.parse_response()
            self.end()

        except Exception as e:
            debug('action_load_saved_filter: Error calling filter API: {}'.format(e))
            import traceback
            debug('action_load_saved_filter: Traceback: {}'.format(traceback.format_exc()))
            dok('Chyba', 'Nepodarilo sa načítať filtrovaný obsah')
            self.end_of_directory()

    def action_delete_saved_filter(self):
        """
        Vymaže uložený filter
        """
        from resources.lib.storage.filter_storage import filter_storage

        # Použijeme 'name' namiesto 'filter_name' (name je v whitelist)
        filter_slug = self.args.get('name')
        if not filter_slug:
            debug('action_delete_saved_filter: No name provided')
            return

        debug('action_delete_saved_filter: Deleting filter "{}"'.format(filter_slug))

        # Vymaž filter
        if filter_storage.delete_filter(filter_slug):
            debug('action_delete_saved_filter: Filter "{}" deleted successfully'.format(filter_slug))
            Router.refresh()
        else:
            debug('action_delete_saved_filter: Failed to delete filter "{}"'.format(filter_slug))
            dok('Chyba', 'Nepodarilo sa vymazať filter')

    def action_edit_saved_filter(self):
        """
        Otvorí filter dialog pre editáciu uloženého filtra
        """
        from resources.lib.gui.filter_dialog import show_filter_dialog
        from resources.lib.api.filter import filter_api
        from resources.lib.storage.filter_storage import filter_storage

        filter_slug = self.args.get('name')
        if not filter_slug:
            debug('action_edit_saved_filter: No name provided')
            return

        debug('action_edit_saved_filter: Editing filter "{}"'.format(filter_slug))

        # Načítaj existujúce filter parametre
        filter_params = filter_storage.get_filter(filter_slug)
        if not filter_params:
            debug('action_edit_saved_filter: Filter "{}" not found'.format(filter_slug))
            dok('Chyba', 'Filter "{}" nebol nájdený'.format(filter_slug))
            return

        # Otvor filter dialog s predvyplnenými hodnotami
        new_filter_params, save_filter = show_filter_dialog(current_filter=filter_params)

        if new_filter_params:
            debug('action_edit_saved_filter: Filter edited with new params: {}'.format(new_filter_params))

            # Ulož zmeny (zachovaj pôvodný display name)
            display_name = filter_storage.get_display_name(filter_slug)
            filter_storage.save_filter(filter_slug, new_filter_params, display_name=display_name)
            debug('action_edit_saved_filter: Filter "{}" updated successfully'.format(filter_slug))

            # Aplikuj editovaný filter
            try:
                api_params = self._merge_include_exclude_params(new_filter_params)
                debug('action_edit_saved_filter: Calling filter API with merged params: {}'.format(api_params))
                self.response = filter_api.get_filtered(api_params)
                debug('action_edit_saved_filter: API response received: {} items'.format(
                    len(self.response.get('menu', [])) if isinstance(self.response, dict) else 'unknown'))

                # Ulož stream-related filter parametre pre použitie pri výbere streamov
                stream_prefs = self._extract_stream_preferences(new_filter_params)
                if stream_prefs:
                    home_win.setProperty(SC.STREAM_FILTER_PREFS, dumps(stream_prefs))
                    debug('action_edit_saved_filter: Saved stream preferences to Window property: {}'.format(stream_prefs))
                else:
                    home_win.clearProperty(SC.STREAM_FILTER_PREFS)
                    debug('action_edit_saved_filter: Cleared stream preferences from Window property')

                self.succeeded = True
                self.parse_response()
                self.end()

            except Exception as e:
                debug('action_edit_saved_filter: Error calling filter API: {}'.format(e))
                import traceback
                debug('action_edit_saved_filter: Traceback: {}'.format(traceback.format_exc()))
                dok('Chyba', 'Nepodarilo sa načítať filtrovaný obsah')
                self.end_of_directory()
        else:
            debug('action_edit_saved_filter: Edit cancelled by user')
            # Užívateľ zrušil editáciu - jednoducho ukončíme request
            # Plugin sa ukončí a používateľ zostane na aktuálnej stránke
            self.end_of_directory()

    def action_rename_saved_filter(self):
        """
        Premenuje uložený filter
        """
        from resources.lib.storage.filter_storage import filter_storage

        filter_slug = self.args.get('name')
        if not filter_slug:
            debug('action_rename_saved_filter: No name provided')
            return

        debug('action_rename_saved_filter: Renaming filter "{}"'.format(filter_slug))

        # Získaj aktuálny display name
        current_name = filter_storage.get_display_name(filter_slug)
        if not current_name:
            debug('action_rename_saved_filter: Filter "{}" not found'.format(filter_slug))
            dok('Chyba', 'Filter "{}" nebol nájdený'.format(filter_slug))
            return

        # Zobraz input dialog s aktuálnym názvom
        new_name = dinput('Zadaj nový názov filtra', current_name)
        if not new_name or new_name == current_name:
            debug('action_rename_saved_filter: Rename cancelled or same name')
            return

        debug('action_rename_saved_filter: Renaming "{}" to "{}"'.format(current_name, new_name))

        # Premenuj filter
        if filter_storage.rename_filter(filter_slug, new_name):
            debug('action_rename_saved_filter: Filter renamed successfully')
            Router.refresh()
        else:
            debug('action_rename_saved_filter: Failed to rename filter')
            dok('Chyba', 'Nepodarilo sa premenovať filter')

    def msg_error(self):
        if SC.ITEM_WIDGET in self.args:
            debug('Mame error hlasku, ale sme z widgetu, tak ju nezobrazujeme')
            return

        if 'msgERROR' in self.response.get('system', {}):
            debug('ERR REPOSNSE: {}'.format(self.response))
            data = self.response.get('system').get('msgERROR')
            if isinstance(data, dict):
                lang = get_language_code()
                i18n = data.get('i18n', {})
                if lang not in i18n:
                    debug('err pre jazyk {} nemame, tak nastavujem cs'.format(lang))
                    lang = SC.DEFAULT_LANG
                dok(Strings.txt(Strings.SYSTEM_H1), '{}'.format(data['i18n'][lang]))
                pass
            else:
                dok(Strings.txt(Strings.SYSTEM_H1), '{}'.format(data))
        else:
            debug('ERROR response: {}'.format(self.response))
            dok(Strings.txt(Strings.SYSTEM_H1), Strings.txt(Strings.SYSTEM_API_ERROR_L1))

    def pinned_key(self):
        return SC.TXT_PINNED.format(self.url)

    def get_pinned(self):
        pinned = self.storage.get(self.pinned_key())
        if not pinned:
            pinned = {}
        return pinned

    def set_pinned(self, data):
        info('new pined {} for {}'.format(data, self.pinned_key()))
        self.storage[self.pinned_key()] = data

    def call_url_and_response(self):
        # Optimalizácia: Pre menu requests skontroluj MenuCache PRED API callom
        # Ak je menu cache zakázaná globálne, preskočiť túto optimalizáciu
        # Vylúč /Play/ endpointy, ktoré vracajú streamy namiesto menu
        is_play_endpoint = self.url.startswith('/Play/')

        if CACHE_ENABLED and CACHE_MENU_ENABLED and self.payload is None and not is_play_endpoint:
            from resources.lib.services.menu_cache_server import menu_cache_server

            # Skús získať cached menu (len pre GET requests, nie POST)
            cached = menu_cache_server.get_cached_menu(self.url, max_age=300)

            if cached and cached.get('count', 0) > 0:
                # Cache HIT - preskočiť API call úplne!
                from time import time
                age = time() - cached['timestamp']
                debug('MenuCache HIT in call_url_and_response for {} ({} items, age: {:.0f}s) - skipping API call'.format(
                    self.url, cached['count'], age))

                # Použij cached response pre parse
                self.response = cached.get('raw_response', {})
                self.parse_response()
                return
        elif not (CACHE_ENABLED and CACHE_MENU_ENABLED):
            debug('MenuCache disabled by config (CACHE_ENABLED={}, CACHE_MENU_ENABLED={})'.format(CACHE_ENABLED, CACHE_MENU_ENABLED))

        # Cache MISS alebo POST request → volaj API normálne
        self.call_url()
        self.parse_response()

    def call_url(self):
        try:
            if self.payload is not None:
                debug('POST DATA: {}'.format(self.payload))
                self.response = Sc.post(self.url, data=self.payload)
            else:
                self.response = Sc.get(self.url)
        except:
            debug('CALL URL ERR: {}'.format(traceback.format_exc()))
            self.response = {}

    def parse_response(self):
        if SC.ITEM_SYSTEM in self.response:
            self.system()

        # Ulož filter data z API odpovede pre neskoršie použitie
        # Filter je top-level kľúč v API odpovedi (nie v system)
        if 'filter' in self.response:
            self.last_response_filter = self.response['filter']
            debug('parse_response: Uložené filter data z API: {}'.format(self.last_response_filter))

            # Ulož do Window property aby bol dostupný v ďalších requestoch
            # Použijeme jednu globálnu property pre posledný filter
            home_win.setProperty('SC.FilterContext.Last', dumps(self.last_response_filter))
            debug('parse_response: Uložené do Window property SC.FilterContext.Last')

        if SC.ITEM_MENU in self.response:
            self.list()
        elif SC.ITEM_STRMS in self.response:
            return self.play()
        else:
            self.msg_error()

    def pinned_hp(self):
        st = list_hp
        for itm in st.get():
            info('HP item: {}'.format(itm))
            item = SCItem({'type': SC.ITEM_HPDIR, 'title': itm.get(SC.ITEM_ID), 'url': itm.get(SC.ITEM_URL)})
            if item.visible:
                info('Pridavam item na HP: {}'.format(itm.get(SC.ITEM_ID)))
                item.li().setProperty('SpecialSort', GUI.TOP)
                self.items_pinned.append(item.get())

    def _has_unknown_mu_ids(self, filter_data):
        """
        Kontroluje, či filter obsahuje 'mu' IDs, ktoré nie sú v lokálnych facetoch

        Args:
            filter_data (dict): Filter data z API response

        Returns:
            bool: True ak obsahuje neznáme IDs (napr. herci), False inak
        """
        if not isinstance(filter_data, dict):
            return False

        mu_values = filter_data.get('mu')
        if not mu_values:
            return False  # Žiadne mu IDs → filter je OK

        # Konvertuj na list ak je to scalar
        if not isinstance(mu_values, list):
            mu_values = [mu_values]

        # Načítaj facets z cache (s TTL 1 deň)
        try:
            from resources.lib.api.filter import filter_api
            facets = filter_api.get_facets()

            # Vytvor set všetkých známych IDs (žánre + krajiny + hardcoded TAGs)
            known_ids = set()

            # Pridaj žánre
            for genre in facets.get('genres', []):
                known_ids.add(int(genre['id']))

            # Pridaj krajiny
            for country in facets.get('countries', []):
                known_ids.add(int(country['id']))

            # Pridaj hardcoded TAGs (Anime, Koncert) - tieto sú v filter dialogu
            # ale nie sú v facetoch zo servera
            known_ids.add(70393)  # Anime TAG
            known_ids.add(69801)  # Koncert TAG

            debug('_has_unknown_mu_ids: Loaded {} known facet IDs (genres + countries + hardcoded TAGs)'.format(len(known_ids)))

            # Skontroluj každé mu ID
            for mu_id in mu_values:
                # Odstráň '!' prefix ak existuje (exclude hodnoty)
                mu_id_str = str(mu_id)
                if mu_id_str.startswith('!'):
                    mu_id_clean = int(mu_id_str[1:])
                else:
                    mu_id_clean = int(mu_id)

                # Ak ID nie je v známych facetoch, znamená to že je to herec/neznámy typ
                if mu_id_clean not in known_ids:
                    debug('_has_unknown_mu_ids: Found unknown mu ID: {} (not in genres/countries)'.format(mu_id_clean))
                    return True

            debug('_has_unknown_mu_ids: All mu IDs are known (in genres/countries)')
            return False

        except Exception as e:
            debug('_has_unknown_mu_ids: Error checking mu IDs: {}'.format(e))
            # Pri chybe lepšie nezobrazovať filter (safe fallback)
            return True

    def pinned_custom(self):
        # Starý systém - manuálne custom filtre (URL-based)
        st = List(SC.TXT_CUSTOM_FORMAT.format(self.url))
        for itm in st.get():
            debug('custom item: {}'.format(itm))
            cfg = {
                SC.ITEM_TYPE: SC.ITEM_CUSTOM_FILTER,
                SC.ITEM_TITLE: itm.get(SC.ITEM_TITLE),
                SC.ITEM_URL: itm.get(SC.ITEM_URL),
                'self_url': self.url,
            }
            item = SCItem(cfg)
            if item.visible:
                item.li().setProperty('SpecialSort', GUI.TOP)
                self.items_pinned.append(item.get())

        # Nový systém - uložené filtre cez filter_storage
        # Zobrazuj len na HP (hlavnej stránke), ale NIE keď sú zobrazené výsledky z filter API
        # Filter výsledky majú self.url == '/' ale obsahujú 'filter' v response s meta dátami
        is_filter_result = (
            self.url == '/' and
            'filter' in self.response and
            isinstance(self.response.get('filter'), dict) and
            'meta' in self.response.get('filter', {})
        )

        if self.url == '/' and not is_filter_result:
            # Pridaj rýchle vyhľadávanie na vrch homepage
            debug('pinned_custom: Adding quick search items to HP')

            # Načítaj zoznam skrytých položiek
            hidden_items = self.storage.get('hidden_hp_items') or []

            # Rýchle vyhľadávanie filmov
            if 'search-movies' not in hidden_items:
                quick_search_movies_cfg = {
                    SC.ITEM_TYPE: 'action',
                    SC.ITEM_TITLE: '[B]{}[/B]'.format(ADDON.getLocalizedString(30322)),
                    SC.ITEM_ACTION: 'search_new',
                    SC.ITEM_ID: 'search-movies',
                }
                quick_search_movies_item = SCItem(quick_search_movies_cfg)
                if quick_search_movies_item.visible:
                    quick_search_movies_item.li().setProperty('SpecialSort', GUI.TOP)
                    self.items_pinned.append(quick_search_movies_item.get())

            # Rýchle vyhľadávanie seriálov
            if 'search-series' not in hidden_items:
                quick_search_series_cfg = {
                    SC.ITEM_TYPE: 'action',
                    SC.ITEM_TITLE: '[B]{}[/B]'.format(ADDON.getLocalizedString(30323)),
                    SC.ITEM_ACTION: 'search_new',
                    SC.ITEM_ID: 'search-series',
                }
                quick_search_series_item = SCItem(quick_search_series_cfg)
                if quick_search_series_item.visible:
                    quick_search_series_item.li().setProperty('SpecialSort', GUI.TOP)
                    self.items_pinned.append(quick_search_series_item.get())

            from resources.lib.storage.filter_storage import filter_storage

            saved_filters = filter_storage.get_all_filters()
            debug('pinned_custom: Found {} saved filters for HP'.format(len(saved_filters)))

            # filter_slug je kľúč (slug bez diakritiky), filter_params sú parametre filtra
            for filter_slug, filter_params in saved_filters.items():
                # Preskočiť skryté filtre
                if 'filter:{}'.format(filter_slug) in hidden_items:
                    continue

                # Získaj display názov (originál s diakritikou)
                display_name = filter_storage.get_display_name(filter_slug)
                debug('pinned_custom: Adding saved filter slug="{}", display="{}"'.format(filter_slug, display_name))

                cfg = {
                    SC.ITEM_TYPE: SC.ITEM_SAVED_FILTER,
                    SC.ITEM_TITLE: '[COLOR yellow]{}[/COLOR]'.format(display_name),  # Zobrazíme originálny názov
                    SC.ITEM_ACTION: SC.ACTION_LOAD_SAVED_FILTER,
                    'name': filter_slug,  # URL bude obsahovať slug
                }
                item = SCItem(cfg)
                if item.visible:
                    item.li().setProperty('SpecialSort', GUI.TOP)
                    self.items_pinned.append(item.get())
        elif is_filter_result:
            debug('pinned_custom: Skipping saved filters - this is a filter result, not HP')

    def list(self):
        """
        Zobrazí menu items
        OPTIMALIZÁCIA: MenuCache sa už skontroloval v call_url_and_response()
        """
        self.succeeded = True

        pinned = self.get_pinned()
        hidden = self.storage.get('h-{}'.format(self.url))
        self.pinned_custom()
        if self.url == '/':
            info('Mame HP, skontrolujeme pripnute polozky')
            self.pinned_hp()

        # Pridaj "Pokročilý filter" ak API vracia filter data (ale nie pri listoch, sériách a epizódach)
        # Detekcia list views:
        # - self.payload is not None → POST request s IDs (Trakt.tv, Recently watched, Tips)
        # - self.listType is not None → system.listType indikuje list (napr. 'trakt', 'history')
        # - of='list' v filter data → list view (napr. Trakt.tv history)
        # - mu obsahuje neznáme IDs → filter obsahuje herci/neznáme typy (filter dialog ich nepodporuje)
        # - setContent='episodes' alebo 'seasons' → výpis sérií/epizód (filter je tu zbytočný)
        filter_data = self.response.get('filter', {})
        is_list_view = (
            filter_data.get('of') == 'list' if isinstance(filter_data, dict) else False
        )
        has_unknown_mu = self._has_unknown_mu_ids(filter_data)

        # Detekcia výpisu sérií/epizód cez setContent
        system_data = self.response.get(SC.ITEM_SYSTEM, {})
        content_type = system_data.get('setContent', '')
        is_series_or_episodes = content_type in ('episodes', 'seasons')

        should_show_filter = (
            'filter' in self.response and      # API vracia filter data
            self.payload is None and            # Nie je POST request s IDs
            self.listType is None and           # Nie je nastavený listType
            not is_list_view and                # Nie je of=list (list view)
            not has_unknown_mu and              # Neobsahuje neznáme mu IDs (herci)
            not is_series_or_episodes           # Nie je výpis sérií/epizód
        )

        if should_show_filter:
            debug('Pridavam polozku "Pokrocily filter" - API obsahuje filter data (URL: {})'.format(self.url))
            filter_item = SCItem({
                'type': 'action',
                'title': ADDON.getLocalizedString(30200),
                SC.ITEM_ACTION: SC.ACTION_FILTER
            })
            if filter_item.visible:
                # Nastav SpecialSort na TOP aby bol vždy na začiatku
                filter_item.li().setProperty('SpecialSort', GUI.TOP)
                self.items_pinned.append(filter_item.get())
        else:
            if 'filter' not in self.response:
                debug('Preskakujem "Pokrocily filter" - API neobsahuje filter data (URL: {})'.format(self.url))
            elif self.payload is not None:
                debug('Preskakujem "Pokrocily filter" - payload je POST request s IDs (list view, URL: {})'.format(self.url))
            elif self.listType is not None:
                debug('Preskakujem "Pokrocily filter" - listType je nastaveny na "{}" (list view, URL: {})'.format(
                    self.listType, self.url))
            elif is_list_view:
                debug('Preskakujem "Pokrocily filter" - of=list v filter data (list view, URL: {})'.format(self.url))
            elif has_unknown_mu:
                debug('Preskakujem "Pokrocily filter" - mu obsahuje neznáme IDs (herci/TAGs nie v facetoch, URL: {})'.format(self.url))
            elif is_series_or_episodes:
                debug('Preskakujem "Pokrocily filter" - setContent="{}" (výpis sérií/epizód, URL: {})'.format(content_type, self.url))

        # Pridaj statické pinned items NAJPRV (homepage items, custom filtre, filter button)
        if len(self.items_pinned) > 0:
            xbmcplugin.addDirectoryItems(params.handle, self.items_pinned)

        # Použij batch processing pre postupné zobrazovanie
        BATCH_SIZE = 20
        batch = []
        dynamic_pinned = []  # Dynamicky pripnuté položky z menu (cez action_pin)

        for i in self.response.get(SC.ITEM_MENU):
            item = SCItem(i)

            if item.visible:
                # info('pin {} {}'.format(pinned, i.get(SC.ITEM_URL)))
                if pinned is not None and i.get(SC.ITEM_URL) and pinned.get(i.get(SC.ITEM_URL)):
                    item.li().setProperty('SpecialSort', GUI.TOP)
                    info('TOP {}'.format(item.li().getProperty('SpecialSort')))
                    dynamic_pinned.append(item.get())
                    item.visible = False

                if hidden is not None and hidden.get(item.li().getLabel()):
                    item.visible = False

            if item.visible:
                batch.append(item.get())

                # Pridaj po dávkach pre progresívne zobrazovanie
                if len(batch) >= BATCH_SIZE:
                    self.items.extend(batch)
                    # OPTIMALIZÁCIA: Pridaj batch do KODI hneď (progresívne renderovanie)
                    xbmcplugin.addDirectoryItems(params.handle, batch)
                    batch = []

        # Pridaj dynamicky pripnuté položky (z menu loopu) hneď po statických pinned items
        if len(dynamic_pinned) > 0:
            info('Pridavam {} dynamicky pripnutych poloziek'.format(len(dynamic_pinned)))
            xbmcplugin.addDirectoryItems(params.handle, dynamic_pinned)
            self.items.extend(dynamic_pinned)

        # Zvyšné items
        if batch:
            self.items.extend(batch)
            xbmcplugin.addDirectoryItems(params.handle, batch)

    def play(self):
        try:
            item = SCItem(self.response)
            url, li, status, selected = item.get()
            if SC.ACTION in self.args and SC.ACTION_DOWNLOAD in self.args[SC.ACTION]:
                filename = selected.get('stream_info', {}).get('filename')
                if filename is None:
                    dok(Strings.txt(Strings.RESOLVE_ERROR_H1), Strings.txt(Strings.RESOLVE_ERROR_L1))
                    return
                dest = get_setting('download.path')
                if not dest:
                    dnotify(Strings.txt(Strings.CONTEXT_DOWNLOAD), Strings.txt(Strings.DOWNLOAD_NO_PATH))
                    return
                from resources.lib.services.download_queue import download_queue_service
                result = download_queue_service.enqueue(url, dest, filename)
                if result == 'added':
                    dnotify(Strings.txt(Strings.CONTEXT_DOWNLOAD), Strings.txt(Strings.DOWNLOAD_QUEUED))
                elif result == 'duplicate':
                    dnotify(Strings.txt(Strings.CONTEXT_DOWNLOAD), Strings.txt(Strings.DOWNLOAD_ALREADY_QUEUED))
                else:
                    dnotify(Strings.txt(Strings.CONTEXT_DOWNLOAD), Strings.txt(Strings.DOWNLOAD_QUEUE_FULL))
                return
            debug('----------------------------------------------------------------------------------------------------')
            debug('play url: {}'.format(self.url))
            # debug('play selected: {}'.format(dumps(selected)))  # Príliš veľký JSON
            # debug('play response: {}'.format(dumps(self.response)))
            # debug('play item: {}'.format(li))
            debug('----------------------------------------------------------------------------------------------------')
            # Pridaj play URL (/Play/<id>) do stream kontextu pre bug report —
            # dostane ho live_fail (anchor nižšie) aj last_played (cez SELECTED_ITEM).
            if isinstance(selected, dict):
                selected['play_url'] = self.url
                home_win.setProperty(SC.SELECTED_ITEM, dumps(selected))
            self.response['strms'] = selected
            home_win.setProperty('SC.play_item', dumps(self.response))
            # 4.4 — play-request anchor (fix #4): perzistuj cross-process pre fail-timeout
            # a live_fail stream kontext. Musí byť TU kde je 'selected' resolvnutý.
            try:
                import time as _time
                from resources.lib.common.storage import Storage, mark_dirty
                _play_storage = Storage(SC.BUG_REPORT_PLAY_TS)
                _play_storage.update({
                    'ts': _time.time(),
                    'media_id': selected.get('media_id') or selected.get('id') or '',
                    'stream_ctx': selected,
                })
                mark_dirty(SC.BUG_REPORT_PLAY_TS)
                debug('BugReport: play-request anchor set media_id={}'.format(
                    _play_storage['media_id']))
            except Exception:
                pass
            if params.handle == -1:
                debug('HANDLE -1')
                xbmc.Player().play(url, li)
            else:
                debug('HANDLE {}'.format(params.handle))
                self.succeeded = True
                self.cache_to_disc = False
                xbmcplugin.setResolvedUrl(params.handle, True, li)
                self.end_of_directory()
        except UserCancelledException as e:
            # Používateľ zrušil výber streamu - korektné ukončenie bez chyby
            debug('play: User cancelled stream selection: {}'.format(e))
            if params.handle != -1:
                # Dôležité: False flag signalizuje KODI že to nebola chyba, len zrušenie
                xbmcplugin.setResolvedUrl(params.handle, False, xbmcgui.ListItem())
            self.end_of_directory()
        except:
            # Skutočná chyba
            info("ERR: {}".format(str(traceback.format_exc())))
            self.end_of_directory()

    def play_url(self, url, li=None):
        info('playUrl: {} / {}'.format(url, li))
        xbmc.Player().play(url, listitem=li)

    def end_of_directory(self):
        if self.send_end:
            return
        self.send_end = True

        info('endOfDirectory s: {} u: {} c: {}'.format(self.succeeded, self.update_listing, self.cache_to_disc))
        xbmcplugin.endOfDirectory(params.handle, succeeded=self.succeeded, updateListing=self.update_listing,
                                  cacheToDisc=self.cache_to_disc)

    def end(self):
        if self.send_end:
            return

        # Items sú už pridané cez batch processing v list()
        # Už nie je potrebné ich pridávať tu

        self.end_of_directory()
        if SC.ITEM_SYSTEM in self.response:
            self.system_after()

    def notify(self, filter):
        return
        try:
            plugin_url = 'plugin://{}/{}'.format(ADDON_ID, params.orig_args if params.orig_args else '')
            kv = KodiViewModeDb()
            sort = kv.get_sort(plugin_url)
            if sort is not None:
                j = dumps({'m': sort[0], 'o': sort[1], 'u': plugin_url, 'f': filter}).encode()
            else:
                j = dumps({'m': 0, 'o': 1, 'u': plugin_url, 'f': filter}).encode()
            from base64 import b64encode
            data = b64encode(j).decode()
            notify(sender=ADDON_ID, message='List.Sort', data=data)
        except:
            debug('notify List.Sort ERR: {}'.format(traceback.format_exc()))
            pass

    def system(self):
        # if 'filter' in self.response:
        #     self.notify(self.response.get('filter', {}))
        # else:
        #     self.notify({})

        data = self.response.get(SC.ITEM_SYSTEM, {})
        if 'setContent' in data:
            xbmcplugin.setContent(params.handle, data['setContent'])

        if 'setPluginCategory' in data:
            xbmcplugin.setPluginCategory(params.handle, data['setPluginCategory'])

        if 'addSortMethod' in data:
            # info('add sort method {}'.format(SORT_METHODS[data['addSortMethod']]))
            xbmcplugin.addSortMethod(params.handle, SORT_METHODS[data['addSortMethod']])

        if 'addSortMethods' in data:
            for method in data['addSortMethods']:
                # info('add sort method {}'.format(SORT_METHODS[method]))
                try:
                    if method in SORT_METHODS:
                        xbmcplugin.addSortMethod(params.handle, SORT_METHODS[method])
                except:
                    pass

        if 'SetSortMethod' in data:
            #method = SORT_METHODS[int(data.get('SetSortMethod'))]
            # info('set sort method {}'.format(method))
            #xbmc.executebuiltin('Container.SetSortMethod(%d)' % method)
            pass

        if 'setPluginFanart' in data:
            tmp = data.get('setPluginFanart')
            image = tmp.get('image', None)
            color1 = tmp.get('color1', None)
            xbmcplugin.setPluginFanart(params.handle, image=image, color1=color1)

        if 'addCustomFilter' in data:
            item = SCItem({
                'type': 'add_custom_filter',
                'title': '[B]+[/B]   ADD',
                SC.ITEM_ACTION: SC.ACTION_ADD_CUSTOM_FILTER
            })
            item.li().setProperty('SpecialSort', GUI.BOTTOM)
            self.items.append(item.get())

        if 'listType' in data:
            params.args.update({'listType': data['listType']})
            self.listType = data['listType']

    def system_after(self):
        data = self.response.get(SC.ITEM_SYSTEM, {})
        if 'setContent' in data: # and get_setting_as_bool('gui.views.enabled'):
            xbmcplugin.setContent(params.handle, data['setContent'])
            # view_mode = data["setContent"].lower()
            # view_code = settings.get_setting_int('gui.views.{0}'.format(view_mode))
            # if view_code > 0:
            #     xbmc.executebuiltin("Container.SetViewMode(%d)" % view_code)

        if 'SetSortMethod' in data:
            #method = SORT_METHODS[int(data.get('SetSortMethod'))]
            #xbmc.executebuiltin('Container.SetSortMethod(%d)' % method)
            pass

        if SC.ITEM_FOCUS in data:
            try:
                control = cur_win.getControl(cur_win.getFocusId())
                control.selectItem(int(data[SC.ITEM_FOCUS]))
            except:
                pass

        check_last_key = '{}.last_series'.format(ADDON_ID)
        autoplay_done_key = '{}.last_series.autoplay_done'.format(ADDON_ID)

        # Získaj item_id z checkLast (funguje aj pre sezóny aj epizódy)
        check_last = data.get('checkLast')
        item_id = int(check_last.get('id', 0)) if check_last else 0

        if item_id > 0:
            win_last_series = home_win.getProperty(check_last_key)
            autoplay_done = home_win.getProperty(autoplay_done_key)

            # Ak je to INÝ seriál ALEBO sme sa vrátili do seriálu (last_series bolo vymazané), vymaž autoplay_done flag
            if win_last_series == '' or (win_last_series != '' and win_last_series != str(item_id)):
                debug('Auto-play: Clearing autoplay_done (last_series={}, current={})'.format(win_last_series, item_id))
                home_win.clearProperty(autoplay_done_key)
                autoplay_done = ''

            # Vždy ulož aktuálny seriál ID
            home_win.setProperty(check_last_key, str(item_id))
            debug('Auto-play: last_series={} current={} autoplay_done={}'.format(win_last_series, item_id, autoplay_done))

            # AUTO-PLAY logika - spustí sa LEN ak je zapnuté nastavenie
            if get_setting_as_bool('stream.autoplay.episode'):
                stop = home_win.getProperty('{}.stop'.format(ADDON_ID))

                ki = SCKODIItem(int(item_id))
                last_ep = ki.get_last_ep()

                debug('Auto-play: stop={} last_ep={} autoplay_done={}'.format(stop, last_ep, autoplay_done))

                # JEDNODUCHÁ LOGIKA: Spusti auto-play ak:
                # 1. Seriál je rozpozeraný (last_ep existuje)
                # 2. Auto-play ešte NEBOL spustený (autoplay_done == '')
                # 3. Stop flag nie je nastavený
                if last_ep and autoplay_done == '' and (stop is None or stop == ''):
                    debug('Auto-play: Triggering for series {} at S{}E{}'.format(item_id, last_ep[0], last_ep[1]))
                    try:
                        # Použijeme EpisodeCache namiesto API volania
                        from resources.lib.services.episode_cache import episode_cache

                        current_season = int(last_ep[0])
                        current_episode = int(last_ep[1])

                        # Získaj ďalšiu epizódu z cache
                        next_ep = episode_cache.get_next_episode(item_id, current_season, current_episode)

                        if next_ep:
                            next_season, next_episode = next_ep
                            debug('NEXT EP z cache: S{}E{}'.format(next_season, next_episode))

                            # Vytvor URL pre ďalšiu epizódu
                            # Format: /Play/{show_id}/{season}/{episode}
                            play_url = '/Play/{}/{}/{}'.format(item_id, next_season, next_episode)

                            debug('NEXT EP URL: {}'.format(play_url))

                            # Vytvor plugin URL a spusti prehrávanie
                            cmd = 'PlayMedia({})'.format(create_plugin_url({SC.ITEM_URL: play_url}))

                            debug('Auto-play: Executing: {}'.format(cmd))
                            # Nastav autoplay_done flag PRED spustením prehrávania
                            home_win.setProperty(autoplay_done_key, '1')
                            exec_build_in(cmd)
                        else:
                            debug('NEXT EP: Ziadna dalsia epizoda v cache')
                    except:
                        debug('Auto-play error: {}'.format(traceback.format_exc()))
                        pass
                else:
                    debug('Auto-play: SKIPPED - last_ep={} autoplay_done={} stop={}'.format(last_ep, autoplay_done, stop))
        else:
            home_win.clearProperty(check_last_key)
        # upraceme po sebe
        home_win.clearProperty('{}.stop'.format(ADDON_ID))

    def _extract_filter_params(self, api_filter):
        """
        Extrahuje relevantné filter parametre z API odpovede

        Args:
            api_filter (dict): Filter data z API (system.filter)

        Returns:
            dict: Len relevantné parametre pre filter dialog (bez pagination a meta dát)
        """
        if not api_filter or not isinstance(api_filter, dict):
            return {}

        # Zoznam relevantných filter parametrov (ktoré môže používateľ meniť)
        relevant_params = [
            'typ',      # Typ obsahu (film/seriál)
            'q',        # Kvalita (SD, 720p, 1080p, 4K, 8K)
            'la',       # Jazyk (SK, CZ, EN)
            'HDR',      # HDR (0=bez, 1=aj, 2=len)
            'DV',       # Dolby Vision (0=bez, 1=aj, 2=len)
            'atmos',    # Dolby Atmos (1=len atmos)
            'hevc',     # HEVC codec (1=bez HEVC)
            'ste',      # 3D stereoscopic (1=bez 3D)
            'dub',      # Dabing (0=bez, 1=s dabingom)
            'tit',      # Titulky (0=bez, 1=s titulkami)
            'r',        # Rating range (>70, 60:80, <50)
            'y',        # Year range (>2020, 2015:2023, <2010)
            's',        # Search query (fulltextové vyhľadávanie)
            'mu',       # URL ID (žánre, TAGy, herci, krajiny - univerzálny)
            'co',       # Countries (array of IDs)
            'ge',       # Genres (backward compatibility, preferuj 'mu')
            'ca',       # Cast (array of IDs)
            'of',       # Order field (datum, rating, year, quality)
            'od',       # Order direction (asc, desc)
            'm',        # MPAA rating (vekové hranice)
            'kwd',      # Keywords
            'b',        # Bitrate
            'f',        # Filesize
        ]

        # Vyfiltruj len relevantné parametre
        extracted = {}
        for key in relevant_params:
            if key in api_filter and api_filter[key] is not None:
                # Špeciálne ošetrenie pre filesize - konvertuj B → MB
                if key == 'f':
                    # Filesize je v API v B, ale filter dialog používa MB
                    extracted[key] = self._convert_filesize_bytes_to_mb(api_filter[key])
                    debug('_extract_filter_params: {} = {} (converted from B to MB)'.format(key, extracted[key]))
                else:
                    extracted[key] = api_filter[key]
                    debug('_extract_filter_params: {} = {}'.format(key, api_filter[key]))

        # Špeciálne ošetrenie pre multiselect polia (mu, co, ge, ca)
        # Server ich môže vrátiť ako string alebo array
        for multi_key in ['mu', 'co', 'ge', 'ca']:
            if multi_key in extracted:
                value = extracted[multi_key]
                # Ak je to string (JSON encoded alebo číselný string), dekóduj/konvertuj
                if isinstance(value, str):
                    try:
                        from json import loads as json_loads
                        decoded = json_loads(value)
                        if isinstance(decoded, list):
                            value = decoded
                        elif isinstance(decoded, (int, float)):
                            # Server vrátil jeden parameter ako string číslo (napr. '70393')
                            # JSON dekódoval ho na číslo, konvertuj na list
                            value = [int(decoded)]
                            debug('_extract_filter_params: Converted single numeric value to list: {} -> {}'.format(
                                extracted[multi_key], value))
                    except:
                        # Nie je JSON - možno číselný string (napr. '70393')
                        # Skús konvertovať na int a daj do listu
                        try:
                            value = [int(value)]
                            debug('_extract_filter_params: Converted string to int list: {} -> {}'.format(
                                extracted[multi_key], value))
                        except (ValueError, TypeError):
                            pass
                elif isinstance(value, (int, float)):
                    # Ak je to priamo číslo (nie string), konvertuj na list
                    value = [int(value)]
                    debug('_extract_filter_params: Converted numeric value to list: {} -> {}'.format(
                        extracted[multi_key], value))

                # Rozdeľ include/exclude hodnoty pre 'mu' parameter
                # Filter dialog má samostatné polia pre include (mu) a exclude (mu_exclude)
                if isinstance(value, list):
                    positive_values = []
                    negative_values = []

                    for v in value:
                        v_str = str(v)
                        if v_str.startswith('!'):
                            # Odstráň '!' prefix a konvertuj na int
                            try:
                                negative_values.append(int(v_str[1:]))
                            except (ValueError, TypeError):
                                debug('_extract_filter_params: Invalid exclude ID: {}'.format(v_str))
                        else:
                            # Konvertuj na int
                            try:
                                positive_values.append(int(v_str))
                            except (ValueError, TypeError):
                                debug('_extract_filter_params: Invalid include ID: {}'.format(v_str))

                    # Nastav include hodnoty (len ak nie sú prázdne)
                    if positive_values:
                        extracted[multi_key] = positive_values
                        debug('_extract_filter_params: {} include values: {}'.format(multi_key, positive_values))
                    elif multi_key in extracted:
                        # Žiadne include hodnoty, odstráň parameter
                        del extracted[multi_key]

                    # Nastav exclude hodnoty pre 'mu' ako samostatný parameter 'mu_exclude'
                    if multi_key == 'mu' and negative_values:
                        extracted['mu_exclude'] = negative_values
                        debug('_extract_filter_params: mu_exclude values: {}'.format(negative_values))

        return extracted

    def _convert_filesize_bytes_to_mb(self, value_str):
        """
        Konvertuje filesize range z B na MB pre použitie v filter dialogu

        Args:
            value_str: Range hodnota v B (napr. "<50000000000")

        Returns:
            str: Range hodnota v MB (napr. "<50000")
        """
        from resources.lib.gui.filter_dialog import _convert_filesize_range_from_bytes
        return _convert_filesize_range_from_bytes(value_str)

    def _extract_stream_preferences(self, filter_params):
        """
        Extrahuje stream-related filter parametre pre použitie pri výbere streamov

        Args:
            filter_params (dict): Filter parametre z dialogu

        Returns:
            dict: Len stream-related parametre (bitrate, filesize, hevc, ste, HDR, DV, atmos, q, la, dub, tit)
        """
        if not filter_params or not isinstance(filter_params, dict):
            return {}

        # Zoznam stream-related parametrov
        stream_params = [
            'b',        # Bitrate range
            'f',        # Filesize range (v B)
            'hevc',     # HEVC codec (1=exclude)
            'ste',      # 3D stereoscopic (1=exclude)
            'HDR',      # HDR (0=bez, 1=aj, 2=len)
            'DV',       # Dolby Vision (0=bez, 1=aj, 2=len)
            'atmos',    # Dolby Atmos (1=len atmos)
            'q',        # Max kvalita
            'la',       # Preferovaný jazyk
            'dub',      # Dabing (1=len s dabingom)
            'tit',      # Titulky (1=len s titulkami)
        ]

        # Vyfiltruj len stream-related parametre
        extracted = {}
        for key in stream_params:
            if key in filter_params:
                extracted[key] = filter_params[key]
                debug('_extract_stream_preferences: {} = {}'.format(key, filter_params[key]))

        return extracted

    def _merge_include_exclude_params(self, filter_params):
        """
        Spoj include a exclude parametre do jedného 'mu' parametra s '!' prefixom

        Args:
            filter_params (dict): Filter parametre z dialogu

        Returns:
            dict: Filter parametre pripravené pre API (s spojenými mu/mu_exclude)
        """
        merged = dict(filter_params)  # Copy

        # Spoj 'mu' a 'mu_exclude' do jedného 'mu' parametra
        if 'mu' in merged or 'mu_exclude' in merged:
            include_ids = merged.get('mu', [])
            exclude_ids = merged.get('mu_exclude', [])

            # Vytvor finálny list: include IDs + exclude IDs s '!' prefixom
            final_mu = []

            # Pridaj include IDs (bez zmeny)
            if isinstance(include_ids, list):
                final_mu.extend([int(v) for v in include_ids])
            elif include_ids:
                final_mu.append(int(include_ids))

            # Pridaj exclude IDs s '!' prefixom
            if isinstance(exclude_ids, list):
                for v in exclude_ids:
                    final_mu.append('!{}'.format(int(v)))
            elif exclude_ids:
                final_mu.append('!{}'.format(int(exclude_ids)))

            # Nastav finálny 'mu' parameter
            if final_mu:
                merged['mu'] = final_mu
                debug('_merge_include_exclude_params: Merged mu = {}'.format(final_mu))
            elif 'mu' in merged:
                del merged['mu']

            # Odstráň 'mu_exclude' (už je spojený do 'mu')
            if 'mu_exclude' in merged:
                del merged['mu_exclude']

        return merged


class Stream:
    def __init__(self, data, parent=None):
        self.data = data
        self.parent = parent

    def select_stream(self):
        strms = self.data.get('strms')
        return strms.get(0)

    def run(self):
        file = self.select_stream()
        info('Vybrany stream: {}'.format(file))
        item = SCItem(self.data)
        # xbmcplugin.setResolvedUrl(params.handle, True, item)
        pass


class Resolve:
    def __init__(self, data):
        self.data = data
