from __future__ import print_function, unicode_literals

import json
import re
import time
from json import dumps, loads

import xbmcvfs
from xbmcgui import ListItem

from resources.lib.api.kraska import Kraska, ResolveException, HelperException, getKraInstance
from resources.lib.api.sc import Sc
from resources.lib.common.lists import List, SCKODIItem
from resources.lib.common.logger import info, debug as log_debug
from resources.lib.common.storage import preferred_lang_list
from resources.lib.constants import ADDON_ID, SC, GUI, MENU_ICON_BASE, MENU_ICON_STYLES
from resources.lib.debug import try_catch
from resources.lib.gui import get_cond_visibility as gcv, home_win
from resources.lib.gui.dialog import dselect, dok
from resources.lib.kodiutils import create_plugin_url, convert_bitrate, get_setting_as_bool, get_setting_as_int, \
    get_setting, get_info_label, get_system_platform, decode, make_nfo_content, translate_path, make_legal_filename, \
    microtime, get_isp, set_setting
from resources.lib.language import Strings
from resources.lib.params import params
from resources.lib.services.settings import settings
from resources.lib.gui_cache import get_language_code

list_item = ListItem
list_hp = List('HP')

# Regex pre SCLDir.translate_path (sc://config(setting.name) odkazy v ceste)
_SC_PATH_RE = re.compile(r'sc://(?P<typ>[^\(]+)\((?P<param1>[^\s,\)]+)\)')


class UserCancelledException(Exception):
    """Výnimka vyhodená keď používateľ zruší výber streamu"""
    pass


def parental_history():
    return get_setting_as_bool('parental.control.enabled')  # and get_setting_as_bool('parental.control.history')


def get_history_item_name(item):
    return 'p-{}'.format(item) if parental_history() else item


def menu_icon_style_art(art):
    """Prepne menu ikonky zo servera na štýl zvolený v nastavení plugin.menu.icons.

    Server posiela neon sadu (MENU_ICON_BASE + '<nazov>.png'), ostatné štýly
    ležia na serveri v podpriečinku '<styl>/'. Ostatné obrázky (postery, fanart)
    ostávajú nezmenené. Nastavenie sa číta až pri prvej nájdenej menu ikonke.
    """
    style = None
    out = {}
    for key, url in art.items():
        name = url[len(MENU_ICON_BASE):] if hasattr(url, 'startswith') and url.startswith(MENU_ICON_BASE) else ''
        if name and '/' not in name:
            if style is None:
                idx = get_setting_as_int('plugin.menu.icons') or 0
                style = MENU_ICON_STYLES[idx] if 0 <= idx < len(MENU_ICON_STYLES) else ''
            if style:
                url = '{}{}/{}'.format(MENU_ICON_BASE, style, name)
        out[key] = url
    return out


class SCItem:
    def __init__(self, data):
        self.item = None
        self.visible = False
        if SC.ITEM_TYPE in data:
            self.item_by_type(data)
        elif SC.ITEM_STRMS in data:
            info('PLAY ITEM')
            self.item = SCPlayItem(data)
        else:
            info('Neznama polozka {}'.format(str(data)))

    def item_by_type(self, data):
        item_type = data.get(SC.ITEM_TYPE, None)
        if item_type == SC.ITEM_DIR:
            self.item = SCDir(data)
        elif item_type == SC.ITEM_VIDEO:
            self.item = SCVideo(data)
        elif item_type == SC.ITEM_HPDIR:
            self.item = SCHPDir(data)
        elif item_type == SC.ITEM_CUSTOM_FILTER:
            self.item = SCCustomFilterDir(data)
        elif item_type == SC.ITEM_SAVED_FILTER:
            self.item = SCSavedFilterDir(data)
        elif item_type == SC.ITEM_CMD:
            self.item = SCCmd(data)
        elif item_type == SC.ITEM_ACTION:
            self.item = SCAction(data)
        elif item_type == SC.ITEM_NEXT:
            self.item = SCNext(data)
        elif item_type == 'ldir':
            self.item = SCLDir(data)
        elif item_type == 'add_custom_filter':
            self.item = SCAction(data)
        else:
            info('Nepodporovana polozka {} {}'.format(item_type, data))

        try:
            self.visible = self.item.visible()
        except:
            pass

    def li(self):
        return self.item.item

    def get(self):
        return self.item.get()


class SCBaseItem:
    def __init__(self, data, debug=False):
        self.item = list_item(offscreen=False)
        self.data = data
        self.info_set = False
        self.info = {}
        self.debug = debug

        # Pre i18n_info musíme najprv spracovať info (kde je title) a až potom nastaviť URL
        if SC.ITEM_INFO in data:
            self.set_info()
        elif SC.ITEM_I18N_INFO in data:
            self._set_info(self.i18n_info({}))
        elif SC.ITEM_TITLE in data:
            # Fallback ak nie je info ani i18n_info
            title_value = data.get(SC.ITEM_TITLE)
            log_debug('SCBaseItem: Setting label from title field: "{}"'.format(title_value))
            self.item.setLabel(title_value)
            log_debug('SCBaseItem: Label set to: "{}"'.format(self.item.getLabel()))

        if SC.ITEM_URL in data:
            url = create_plugin_url(data)
            self.item.setPath(url)

        if SC.ITEM_ART in data:
            self.set_art()
        elif SC.ITEM_I18N_ART in data:
            self.set_i18n_art()

        if 'cast' in data:
            self.set_cast()

        if 'unique_ids' in data:
            self.set_unique_ids()

        if 'stream_info' in data:
            self.set_stream_info()

    @try_catch('set_stream_info')
    def set_stream_info(self):
        from resources.lib.kodiutils import set_listitem_stream_info
        stream_info = self.data.get('stream_info')
        for key in stream_info:
            if key in ('video', 'audio'):
                set_listitem_stream_info(self.item, key, stream_info.get(key))

        if 'fvideo' in stream_info:
            # log_debug('FVIDEO: {}'.format(stream_info['fvideo']))
            self.item.setProperty('video', stream_info['fvideo'])

        if 'faudio' in stream_info:
            self.item.setProperty('audio', stream_info['faudio'])

    @try_catch('set_unique_ids')
    def set_unique_ids(self):
        from resources.lib.kodiutils import set_listitem_unique_ids
        set_listitem_unique_ids(self.item, self.data.get('unique_ids'))

    @try_catch('set_cast')
    def set_cast(self):
        from resources.lib.kodiutils import set_listitem_cast
        set_listitem_cast(self.item, self.data.get('cast', []))

    @try_catch('set_art')
    def set_art(self):
        self.item.setArt(menu_icon_style_art(self.data.get(SC.ITEM_ART, {})))

    @try_catch('set_i18n_art')
    def set_i18n_art(self):
        i18n = self.data.get(SC.ITEM_I18N_ART)
        lang = get_language_code()
        if lang not in i18n:
            log_debug('jazyk {} nemame, tak nastavujem cs'.format(lang))
            lang = SC.DEFAULT_LANG
        # log_debug('jazyk {}'.format(lang))
        self.item.setArt(i18n.get(lang))

    @try_catch('_set_info')
    def _set_info(self, item_info):
        # if self.debug:
        #     log_debug('set_info {}'.format(item_info))  # Príliš veľký JSON
        self.info.update(item_info)
        try:
            if SC.ITEM_TITLE in item_info:
                title = '{}'.format(item_info.get(SC.ITEM_TITLE))
                self.item.setLabel(title)

            if self.data.get('play'):
                if 'otitle' in item_info:
                    item_info.update({SC.ITEM_TITLE: item_info['otitle']})
                    del item_info['otitle']

                if 'epname' in item_info:
                    item_info.update({SC.ITEM_TITLE: item_info['epname']})
                    del item_info['epname']
            else:
                if 'epname' in item_info:
                    del item_info['epname']

                if 'otitle' in item_info:
                    del item_info['otitle']

            for i, e in enumerate(item_info):
                # log_debug('set info {} {}'.format(i, e))
                self.item.setProperty(e, '{}'.format(item_info[e]))

            if item_info.get('mediatype', '') == 'season' and item_info.get('episode'):
                item = SCKODIItem(self.data.get(SC.ITEM_ID))
                data = item.data
                # API moze poslat pocet epizod ako string
                total_episodes = int(item_info.get('episode') or 0)
                watched = len(data.get('series:{}'.format(item_info.get('season')), {}))
                log_debug('Mame seriu {} s {}/{} epizodami'.format(item_info.get('season'), watched, total_episodes))
                if watched >= total_episodes:
                    item_info.update({'playcount': '1'})

            from resources.lib.kodiutils import set_listitem_info
            set_listitem_info(self.item, 'video', item_info)
            self.item.setProperty('original_title', item_info.get('originaltitle') or '')
            self.info_set = True
        except Exception as e:
            import traceback
            info('-----------------------------------------------------------------')
            info('set info error [{}]'.format(str(traceback.format_exc())))
            info('-----------------------------------------------------------------')

    @try_catch('set_info')
    def set_info(self):
        item_info = self.data.get(SC.ITEM_INFO, {})
        if SC.ITEM_I18N_INFO in self.data:
            item_info = self.i18n_info(item_info)

        # Ak title existuje v top-level data (nie v info), pridaj ho do item_info
        if SC.ITEM_TITLE in self.data and SC.ITEM_TITLE not in item_info:
            item_info[SC.ITEM_TITLE] = self.data.get(SC.ITEM_TITLE)
            log_debug('set_info: Added title from top-level data: "{}"'.format(item_info[SC.ITEM_TITLE]))

        self._set_info(item_info)

    @try_catch('i18n_info')
    def i18n_info(self, item_info=None):
        if item_info is None:
            item_info = {}
        i18n = self.data.get(SC.ITEM_I18N_INFO)
        lang = get_language_code()
        if lang not in i18n:
            log_debug('jazyk {} nemame, tak nastavujem cs'.format(lang))
            lang = SC.DEFAULT_LANG
        item_info.update(i18n.get(lang))
        return item_info

    @try_catch('get')
    def get(self):
        if self.info_set is False:
            self._set_info({SC.MEDIA_TYPE: SC.MEDIA_TYPE_VIDEO})
        return self.item.getPath(), self.item, True

    @try_catch('visible')
    def visible(self):
        visible = True
        if SC.ITEM_VISIBLE in self.data:
            visible = gcv(self.data.get(SC.ITEM_VISIBLE))

        return visible


class SCStreamSelect(SCBaseItem):
    def __init__(self, data):
        SCBaseItem.__init__(self, data)
        label2 = ''
        strm_nfo = data.get('stream_info', {})
        titulky = True if [x for x in (strm_nfo.get('langs') or '') if '+tit' in x] else False

        if 'bitrate' in data:
            label2 += 'bitrate: [B]{}[/B]'.format(convert_bitrate(int(data.get('bitrate'))))
        if 'linfo' in data:
            label2 += '   audio: [B][UPPERCASE]{}[/UPPERCASE][/B]'.format(', '.join(data['linfo']))
            if titulky:
                label2 += ', [B]+tit[/B]'

        if 'grp' in strm_nfo:
            label2 += '   grp: [B]{}[/B]'.format(strm_nfo['grp'])

        if 'src' in strm_nfo:
            label2 += '   src: [B]{}[/B]'.format(strm_nfo['src'])

        if 'video' in strm_nfo and 'aspect' in strm_nfo['video'] and 'ratio' in strm_nfo['video']:
            label2 += '   asp: [B]{}[/B]'.format(strm_nfo['video']['ratio'])

        if SC.ITEM_URL in data:
            url = data.get(SC.ITEM_URL)
            self.item.setPath(url)
        if SC.ITEM_PROVIDER in data:
            self.item.setProperty(SC.ITEM_PROVIDER, data.get(SC.ITEM_PROVIDER))
        if SC.ITEM_SUBS in data:
            self.item.setProperty(SC.ITEM_SUBS, data.get(SC.ITEM_SUBS))
        if SC.ITEM_ID in data:
            self.item.setProperty(SC.ITEM_ID, data.get('id'))
        self.item.setLabel2(label2)


class SCDirContext:
    def __init__(self):
        pass


class SCLDir(SCBaseItem):
    def __init__(self, data):
        SCBaseItem.__init__(self, data)
        if SC.ITEM_URL in data:
            url = self.translate_path(data[SC.ITEM_URL])
            self.item.setPath(url)

    def translate_path(self, path):
        found = _SC_PATH_RE.search(path)
        if found.group('typ') == 'config':
            path = make_legal_filename(translate_path(get_setting(found.group('param1'))))
        return path


class SCDir(SCBaseItem):
    build_ctx = True

    def __init__(self, data):
        SCBaseItem.__init__(self, data)
        self.lib = List(SC.ITEM_LIBRARY)
        item_id = self.data.get(SC.ITEM_ID)
        if item_id and item_id in self.lib.get():
            label = "[COLOR red]*[/COLOR] {0}".format(self.item.getLabel())
            self.item.setLabel(label)

        if SC.ITEM_URL in data:
            url = create_plugin_url(data)
            self.item.setPath(url)
        if self.build_ctx:
            self.make_ctx()

    def make_ctx(self):
        context_menu = []

        if 'listType' in params.args:
            context_menu.append([Strings.txt(Strings.CONTEXT_REMOVE), 'RunPlugin({})'.format(create_plugin_url({
                SC.ACTION: SC.ACTION_REMOVE_FROM_LIST,
                SC.ITEM_ID: self.data.get(SC.ITEM_ID),
                SC.ITEM_PAGE: get_history_item_name(self.data.get('lid'))
            }))])

        item_id = self.data.get(SC.ITEM_URL)
        # log_debug('ITEM: {}'.format(item_id))
        if 0 and item_id and get_setting('tvshow.library.path'):

            if item_id and item_id in self.lib.get():
                log_debug('Uz je v kniznici s odberom')
                context_menu.append(
                    (Strings.txt(Strings.CONTEXT_REMOVE_FROM_SUB), 'RunPlugin({})'.format(create_plugin_url({
                        SC.ITEM_ACTION: SC.ACTION_REMOVE_FROM_SUBSCRIPTION,
                        SC.ITEM_ID: item_id
                    }))))
            else:
                log_debug('Este nieje v odbere')
                context_menu.append(
                    (Strings.txt(Strings.CONTEXT_ADD_TO_LIBRARY_WITH_SUB), 'RunPlugin({})'.format(create_plugin_url({
                        SC.ITEM_ACTION: SC.ACTION_ADD_TO_LIBRARY_WITH_SUBSCRIPTION,
                        SC.ITEM_ID: item_id
                    }))))

            context_menu.append((Strings.txt(Strings.CONTEXT_ADD_TO_LIBRARY), 'RunPlugin({})'.format(create_plugin_url({
                SC.ITEM_ACTION: SC.ACTION_ADD_TO_LIBRARY,
                SC.ITEM_ID: self.data.get(item_id)
            }))))

        if params.args.get('url'):
            context_menu.append((Strings.txt(Strings.CONTEXT_PIN_UNPIN), 'RunPlugin({})'.format(create_plugin_url({
                SC.ITEM_ACTION: SC.ACTION_PIN,
                SC.ITEM_URL: params.args.get(SC.ITEM_URL),
                SC.ITEM_ID: self.data.get(SC.ITEM_URL)
            }))))

            if get_system_platform() == 'android':
                context_menu.append(
                    (Strings.txt(Strings.CONTEXT_ADD_TO_ANDROID_TV), 'RunPlugin({})'.format(create_plugin_url({
                        SC.ITEM_ACTION: SC.ACTION_ANDROID,
                        SC.ITEM_URL: self.data.get(SC.ITEM_URL),
                        SC.ITEM_ID: self.item.getLabel()
                    }))))

            context_menu.append((Strings.txt(Strings.CONTEXT_PIN_TO_HP), 'RunPlugin({})'.format(create_plugin_url({
                SC.ITEM_ACTION: SC.ACTION_ADD2HP,
                SC.ITEM_URL: self.data.get(SC.ITEM_URL),
                SC.ITEM_ID: self.item.getLabel()
            }))))

        if get_setting_as_bool('stream.autoselect'):
            # log_debug('data: {}'.format(self.data))
            mediatype = self.data.get(SC.ITEM_INFO, {}).get('mediatype')
            if mediatype == 'tvshow' or mediatype == 'movie':
                item_id = self.data.get(SC.ITEM_ID)
                st = preferred_lang_list
                if st.get(item_id) is not None:
                    context_menu.append((Strings.txt(Strings.CONTEXT_DEL_PREF_LANG).format(st[item_id]),
                                         'RunPlugin({})'.format(create_plugin_url({
                                             SC.ITEM_ACTION: SC.ACTION_DEL_PREFERRED_LANGUAGE,
                                             SC.ITEM_ID: self.data.get(SC.ITEM_ID)
                                         }))))
                else:
                    context_menu.append(
                        (Strings.txt(Strings.CONTEXT_ADD_PREF_LANG), 'RunPlugin({})'.format(create_plugin_url({
                            SC.ITEM_ACTION: SC.ACTION_SET_PREFERRED_LANGUAGE,
                            SC.ITEM_ID: self.data.get(SC.ITEM_ID)
                        }))))

        if context_menu:
            self.item.addContextMenuItems(context_menu)


class SCHPDir(SCDir):
    def __init__(self, data):
        SCDir.__init__(self, data)

    def make_ctx(self):
        from resources.lib.constants import ADDON

        context_menu = [
            (Strings.txt(Strings.CONTEXT_REMOVE), 'RunPlugin({})'.format(create_plugin_url({
                SC.ITEM_ACTION: SC.ACTION_DEL2HP,
                SC.ITEM_URL: self.data.get(SC.ITEM_URL),
                SC.ITEM_ID: self.item.getLabel()
            }))),
            (ADDON.getLocalizedString(30330), 'RunPlugin({})'.format(create_plugin_url({
                SC.ITEM_ACTION: SC.ACTION_HIDE_HP_ITEM,
                SC.ITEM_ID: 'hp:{}'.format(self.data.get(SC.ITEM_URL))
            })))
        ]

        self.item.addContextMenuItems(context_menu)


class SCCustomFilterDir(SCDir):
    def __init__(self, data):
        SCDir.__init__(self, data)

    def make_ctx(self):
        context_menu = [('Remove custom item', 'RunPlugin({})'.format(create_plugin_url({
            SC.ITEM_ACTION: SC.ACTION_DEL_CUSTOM_FILTER,
            SC.ITEM_URL: self.data.get(SC.ITEM_URL),
            SC.ITEM_TITLE: self.item.getLabel(),
            SC.ITEM_PAGE: self.data.get('self_url')
        })))]

        self.item.addContextMenuItems(context_menu)


class SCSavedFilterDir(SCDir):
    """
    Saved filter item - uložený filter z filter_storage
    """
    def __init__(self, data):
        # Najprv zavolaj parent init
        SCDir.__init__(self, data)

        # Vytvor URL pre saved filter aj keď nemáme SC.ITEM_URL kľúč
        # Použijeme action a 'name' (name je už v whitelist)
        if SC.ITEM_URL not in data and SC.ITEM_ACTION in data:
            url_params = {
                SC.ITEM_ACTION: data.get(SC.ITEM_ACTION),
                'name': data.get('name')  # 'name' obsahuje slug (bez diakritiky)
            }
            url = create_plugin_url(url_params)
            self.item.setPath(url)

    def make_ctx(self):
        from resources.lib.constants import ADDON

        context_menu = [
            ('Editovať filter', 'RunPlugin({})'.format(create_plugin_url({
                SC.ITEM_ACTION: SC.ACTION_EDIT_SAVED_FILTER,
                'name': self.data.get('name')
            }))),
            ('Premenovať filter', 'RunPlugin({})'.format(create_plugin_url({
                SC.ITEM_ACTION: SC.ACTION_RENAME_SAVED_FILTER,
                'name': self.data.get('name')
            }))),
            ('Vymazať filter', 'RunPlugin({})'.format(create_plugin_url({
                SC.ITEM_ACTION: SC.ACTION_DELETE_SAVED_FILTER,
                'name': self.data.get('name')
            }))),
            (ADDON.getLocalizedString(30330), 'RunPlugin({})'.format(create_plugin_url({
                SC.ITEM_ACTION: SC.ACTION_HIDE_HP_ITEM,
                SC.ITEM_ID: 'filter:{}'.format(self.data.get('name'))
            })))
        ]

        self.item.addContextMenuItems(context_menu)


class SCNext(SCDir):
    def __init__(self, data):
        self.build_ctx = False
        SCDir.__init__(self, data)
        self.item.setProperty('SpecialSort', GUI.BOTTOM)


class SCNFO(SCBaseItem):
    ITEMS_XML = [
        'title',
        'originaltitle',
        'sorttitle',
        'plot',
        'runtime',
        'mpaa',
        'genre',
        'country',
        'director',
        'year',
        'studio',
        'trailer',
        'dateadded',
    ]

    XML_ITEM = '\n<{0}>{1}</{0}>'
    XML_ACTOR = '<actor><name>{name:}</name><role>{role:}</role><order>{order:}</order><thumb>{thumbnail:}</thumb></actor>'
    XML_THUMB = '<thumb aspect="{0}">{1}</thumb>'
    XML_MOVIE = '<movie>{}</movie>'
    DEFAULT_ACTOR = {'name': '', 'role': '', 'order': '', 'thumbnail': ''}

    def __init__(self, data):
        SCBaseItem.__init__(self, data)

    def xml(self):
        out = []

        for pos, item in enumerate(self.info):
            if item in self.ITEMS_XML:
                if isinstance(self.info[item], list):
                    out.append(self.XML_ITEM.format(decode(item), ' / '.join(self.info[item])))
                else:
                    out.append(self.XML_ITEM.format(decode(item), decode(self.info[item])))

        for actor in self.data.get('cast', {}):
            d = self.DEFAULT_ACTOR.copy()
            d.update(actor)
            out.append(self.XML_ACTOR.format(**d))

        i18n = self.data.get(SC.ITEM_I18N_ART)
        lang = get_language_code()
        if lang not in i18n:
            lang = SC.DEFAULT_LANG

        art = i18n.get(lang)
        for pos, item in enumerate(art):
            out.append(self.XML_THUMB.format(item, art[item]))

        return decode(self.XML_MOVIE.format(''.join(out)))

    def nfo(self):
        typ = self.data.get(SC.ITEM_INFO, {}).get('mediatype', 'movie')
        typ = typ if typ == 'movie' else 'tvshow'
        return make_nfo_content(self.data, typ)


class SCVideo(SCBaseItem):
    def __init__(self, data):
        trakt = data['unique_ids']['trakt'] if 'unique_ids' in data and 'trakt' in data['unique_ids'] else None
        self.movie = SCKODIItem(data.get(SC.ITEM_ID), series=data.get('info', {}).get('season'),
                                episode=data.get('info', {}).get('episode'), trakt=trakt)
        internal_info = {}
        play_count = self.movie.get_play_count()
        if play_count is not None and int(play_count) > 0:
            internal_info.update({'playcount': play_count})
        last_played = self.movie.get_last_played()
        if last_played:
            internal_info.update({'lastplayed': last_played})
        if internal_info != {}:
            # log_debug('update info: {}'.format(internal_info))
            data.setdefault(SC.ITEM_INFO, {}).update(internal_info)

        SCBaseItem.__init__(self, data)
        self.set_properties()
        self.gen_context()

    def get(self):
        if self.info_set is False:
            self._set_info({SC.MEDIA_TYPE: SC.MEDIA_TYPE_VIDEO})
        return self.item.getPath(), self.item, False

    def set_properties(self):
        self.item.setContentLookup(False)
        self.item.setProperty('IsPlayable', 'true')
        item_info = self.data.get(SC.ITEM_INFO, {})
        if 'duration' in item_info:
            duration = item_info.get('duration')
            resume_time = self.movie.get(self._key('watched'))
            if resume_time and 0 < resume_time < duration:
                from resources.lib.kodiutils import set_listitem_resume_point
                set_listitem_resume_point(self.item, resume_time, duration)

    def gen_context(self):
        menu = []

        if 'listType' in params.args:
            menu.append([Strings.txt(Strings.CONTEXT_REMOVE), 'RunPlugin({})'.format(create_plugin_url({
                SC.ACTION: SC.ACTION_REMOVE_FROM_LIST,
                SC.ITEM_ID: self.data.get(SC.ITEM_ID),
                SC.ITEM_PAGE: get_history_item_name(self.data.get('lid'))
            }))])

        if get_setting('download.path'):
            menu.append([Strings.txt(Strings.CONTEXT_DOWNLOAD), 'RunPlugin({})'.format(create_plugin_url({
                SC.ACTION: SC.ACTION_DOWNLOAD,
                SC.ACTION_DOWNLOAD: self.data.get(SC.ITEM_URL),
            }))])

        menu.append([Strings.txt(Strings.CONTEXT_SELECT_STREAM), 'PlayMedia({})'.format(create_plugin_url({
            SC.ACTION_SELECT_STREAM: '1',
            SC.ITEM_URL: self.data.get(SC.ITEM_URL),
        }))])

        if get_setting_as_bool('stream.autoselect'):
            mediatype = self.data.get(SC.ITEM_INFO, {}).get('mediatype')
            if mediatype == 'tvshow' or mediatype == 'movie':
                item_id = self.data.get(SC.ITEM_ID)
                st = preferred_lang_list
                if st.get(item_id) is not None:
                    menu.append((Strings.txt(Strings.CONTEXT_DEL_PREF_LANG).format(st[item_id]),
                                 'RunPlugin({})'.format(create_plugin_url({
                                     SC.ITEM_ACTION: SC.ACTION_DEL_PREFERRED_LANGUAGE,
                                     SC.ITEM_ID: self.data.get(SC.ITEM_ID)
                                 }))))
                else:
                    menu.append((Strings.txt(Strings.CONTEXT_ADD_PREF_LANG), 'RunPlugin({})'.format(create_plugin_url({
                        SC.ITEM_ACTION: SC.ACTION_SET_PREFERRED_LANGUAGE,
                        SC.ITEM_ID: self.data.get(SC.ITEM_ID)
                    }))))

        if self.data.get(SC.ITEM_INFO, {}).get('trailer'):
            menu.append(['Trailer', 'PlayMedia({})'.format(self.data.get(SC.ITEM_INFO, {}).get('trailer'))])

        # Bug report — veľké dáta sa predávajú cez SELECTED_ITEM Window property (vzor ~96/435)
        # nie cez URL parametre, aby sa nepresiahol limit dĺžky URL
        menu.append([Strings.txt(Strings.CONTEXT_BUG_REPORT), 'RunPlugin({})'.format(create_plugin_url({
            SC.ACTION: SC.ACTION_BUG_REPORT,
            SC.ITEM_ID: self.data.get(SC.ITEM_ID),
            SC.ITEM_URL: self.data.get(SC.ITEM_URL),
        }))])

        self.item.addContextMenuItems(items=menu)

    def _key(self, name):
        nfo = self.data.get(SC.ITEM_INFO)
        if 'season' in nfo:
            return '{}:{}:{}'.format(name, nfo.get('season'), nfo.get('episode'))
        return name


class SCCmd(SCBaseItem):
    def __init__(self, data):
        data.update({SC.ACTION: SC.CMD})
        SCBaseItem.__init__(self, data)


class SCAction(SCBaseItem):
    def __init__(self, data):
        SCBaseItem.__init__(self, data)
        self.item.setPath(create_plugin_url(data))
        # Pridaj context menu pre search history položky
        if data.get(SC.ITEM_ACTION) == 'search_from_history':
            self.make_search_history_ctx()
        # Pridaj context menu pre quick search položky na HP
        elif data.get(SC.ITEM_ACTION) == 'search_new' and data.get(SC.ITEM_ID) in ['search-movies', 'search-series']:
            self.make_quick_search_ctx()

    def make_quick_search_ctx(self):
        """Vytvorí context menu pre quick search položku na HP"""
        from resources.lib.constants import ADDON

        context_menu = [
            (ADDON.getLocalizedString(30330), 'RunPlugin({})'.format(create_plugin_url({
                SC.ITEM_ACTION: SC.ACTION_HIDE_HP_ITEM,
                SC.ITEM_ID: self.data.get(SC.ITEM_ID)
            })))
        ]

        self.item.addContextMenuItems(context_menu)

    def make_search_history_ctx(self):
        """Vytvorí context menu pre search history položku"""
        from resources.lib.constants import ADDON

        context_menu = [
            (ADDON.getLocalizedString(30302), 'RunPlugin({})'.format(create_plugin_url({
                SC.ITEM_ACTION: 'search_edit',
                SC.ITEM_ID: self.data.get(SC.ITEM_ID),
                'search': self.data.get('search')
            }))),
            (ADDON.getLocalizedString(30303), 'RunPlugin({})'.format(create_plugin_url({
                SC.ITEM_ACTION: 'search_delete',
                SC.ITEM_ID: self.data.get(SC.ITEM_ID),
                'search': self.data.get('search')
            }))),
            (ADDON.getLocalizedString(30304), 'RunPlugin({})'.format(create_plugin_url({
                SC.ITEM_ACTION: 'search_clear_all',
                SC.ITEM_ID: self.data.get(SC.ITEM_ID)
            })))
        ]

        self.item.addContextMenuItems(context_menu)


class SCPlayItem(SCBaseItem):
    QUALITY_LIST = {
        'SD': 1,
        '720p': 2,
        '1080p': 3,
        '3D-SBS': 3,
        '4K': 4,
        '8K': 5
    }

    # Optimálne bitrate hodnoty pre sweet spot scoring
    OPTIMAL_BITRATE = {
        'SD':    {'optimal': 2.5,  'min_good': 1.5,  'max_good': 4,   'tolerance': 1.5},
        '720p':  {'optimal': 6.5,  'min_good': 4,    'max_good': 10,  'tolerance': 3},
        '1080p': {'optimal': 12.5, 'min_good': 8,    'max_good': 20,  'tolerance': 5},
        '4K':    {'optimal': 32.5, 'min_good': 20,   'max_good': 50,  'tolerance': 15},
        '8K':    {'optimal': 100,  'min_good': 60,   'max_good': 150, 'tolerance': 50}
    }

    # Rýchlostné pásma pre adaptáciu na pomalý internet
    SPEED_TIERS = [
        {'min': 0,   'max': 5,   'max_quality': 'SD',    'target_bitrate_factor': 0.7},
        {'min': 5,   'max': 10,  'max_quality': '720p',  'target_bitrate_factor': 0.75},
        {'min': 10,  'max': 25,  'max_quality': '1080p', 'target_bitrate_factor': 0.8},
        {'min': 25,  'max': 50,  'max_quality': '4K',    'target_bitrate_factor': 0.85},
        {'min': 50,  'max': 999, 'max_quality': '8K',    'target_bitrate_factor': 0.9}
    ]

    # Jazyk je dominantné kritérium - váhy musia byť vyššie než súčet
    # všetkých video bonusov (kvalita 5 + bitrate 11 + adaptácia 3 + kodek 5
    # + HDR 1 ~ 25), aby stream s preferovaným jazykom VŽDY porazil stream
    # bez neho; video skóre rozhoduje len medzi rovnakou jazykovou zhodou
    LANG_PRIMARY_WEIGHT = 100
    LANG_SECONDARY_WEIGHT = 50
    # Explicitný stream filter (dialóg) musí prebiť aj jazykovú váhu
    FILTER_PENALTY = 200

    # Default preferované kodeky (ak užívateľ nemá nastavené vlastné)
    DEFAULT_CODEC_PREFERENCE = 'hevc|h264|h265|av1|vc1|mpeg4|xvid'

    # Video kodeky (pre rozlíšenie od audio kodekov)
    VIDEO_CODECS = ['hevc', 'h264', 'h265', 'av1', 'vc1', 'mpeg4', 'mpeg2', 'xvid', 'divx', 'vp9', 'vp8']

    def _get_codec_preference_score(self, codec):
        """
        Vypočíta skóre pre kodek na základe poradia v preferovaných kodekoch.

        Používa nastavenie 'stream.adv.whitelist.codec' alebo default hodnotu.
        Poradie v zozname určuje prioritu - prvý kodek = najvyššie skóre.

        Args:
            codec: Názov kodeku (napr. 'hevc', 'h264')

        Returns:
            float: Skóre 0-5, kde 5 je najpreferovanejší kodek
        """
        if not codec:
            return 0

        codec_lower = codec.lower()

        # Načítaj preferované kodeky z nastavení
        codec_pref = get_setting('stream.adv.whitelist.codec')
        if not codec_pref or codec_pref.strip() == '':
            codec_pref = self.DEFAULT_CODEC_PREFERENCE

        # Rozdeľ kodeky podľa |
        preferred_codecs = [c.strip().lower() for c in codec_pref.split('|') if c.strip()]

        # Filtruj len video kodeky (ignoruj audio kodeky ako ac3, aac, atď.)
        video_preferred = [c for c in preferred_codecs if c in self.VIDEO_CODECS]

        # Ak kodek nieje v zozname, vráť 0
        if codec_lower not in video_preferred:
            log_debug('Codec {} nie je v preferovanych kodekoch (video only: {})'.format(codec, video_preferred))
            return 0

        # Vypočítaj skóre podľa poradia (prvý = najvyššie)
        # Prvý kodek: +5, druhý: +4, tretí: +3, atď., minimum +1
        position = video_preferred.index(codec_lower)
        max_score = 5
        score = max(1, max_score - position)

        log_debug('Codec {} preference score: {} (position: {} in {})'.format(
            codec, score, position, video_preferred))

        return score

    def _get_speed_tier(self, internet_speed_mbps):
        """
        Určí rýchlostné pásmo na základe rýchlosti internetu používateľa.

        Args:
            internet_speed_mbps: Rýchlosť internetu v Mbps

        Returns:
            dict: Speed tier slovník alebo None ak nie je nájdený
        """
        for tier in self.SPEED_TIERS:
            if tier['min'] <= internet_speed_mbps < tier['max']:
                return tier
        # Fallback na najvyššie pásmo ak je rýchlosť mimo rozsahu
        return self.SPEED_TIERS[-1]

    def _calculate_bitrate_score(self, bitrate_mbps, quality, internet_speed_mbps):
        """
        Vypočíta skóre pre bitrate pomocou Gaussovej krivky (sweet spot scoring).

        Args:
            bitrate_mbps: Bitrate streamu v Mbps
            quality: Kvalita streamu ('SD', '720p', '1080p', '4K', '8K')
            internet_speed_mbps: Rýchlosť internetu používateľa v Mbps

        Returns:
            float: Skóre 0-10, kde 10 je optimálne
        """
        import math

        # Ak bitrate presahuje 80% kapacity internetu, je to kritické zlyhanie
        usable_speed = internet_speed_mbps * 0.8
        if bitrate_mbps > usable_speed:
            penalty_factor = (bitrate_mbps - usable_speed) / usable_speed
            # Čím väčšie prekročenie, tým väčší trest (exponenciálny)
            score = max(0, 10 - (penalty_factor * 20))
            log_debug('Bitrate {} Mbps prekracuje kapacitu {} Mbps, score: {:.2f}'.format(
                bitrate_mbps, usable_speed, score))
            return score

        # Získaj optimálne hodnoty pre danú kvalitu
        if quality not in self.OPTIMAL_BITRATE:
            log_debug('Neznama kvalita {}, pouzivam SD'.format(quality))
            quality = 'SD'

        optimal_config = self.OPTIMAL_BITRATE[quality]
        optimal = optimal_config['optimal']
        tolerance = optimal_config['tolerance']
        min_good = optimal_config['min_good']
        max_good = optimal_config['max_good']

        # Gaussova krivka: score = 10 * exp(-((x - optimal)^2) / (2 * tolerance^2))
        distance = bitrate_mbps - optimal
        gaussian_score = 10 * math.exp(-(distance ** 2) / (2 * tolerance ** 2))

        # Bonus ak je bitrate v "dobrom rozsahu"
        if min_good <= bitrate_mbps <= max_good:
            gaussian_score = min(10, gaussian_score + 1)
            log_debug('Bitrate {} Mbps je v dobrom rozsahu [{}, {}], bonus +1'.format(
                bitrate_mbps, min_good, max_good))

        log_debug('Bitrate score: {} Mbps pre {} (optimal: {} Mbps) => score: {:.2f}'.format(
            bitrate_mbps, quality, optimal, gaussian_score))

        return gaussian_score

    def _apply_slow_internet_adaptation(self, quality, bitrate_mbps, internet_speed_mbps, current_score):
        """
        Aplikuje dodatočnú adaptáciu pre používateľov s pomalým internetom.

        Args:
            quality: Kvalita streamu ('SD', '720p', '1080p', '4K', '8K')
            bitrate_mbps: Bitrate streamu v Mbps
            internet_speed_mbps: Rýchlosť internetu používateľa v Mbps
            current_score: Aktuálne skóre streamu

        Returns:
            float: Upravené skóre po aplikácii slow internet adaptácie
        """
        # Získaj speed tier pre používateľa
        tier = self._get_speed_tier(internet_speed_mbps)
        if not tier:
            log_debug('Slow internet adaptation: Tier not found, skipping')
            return current_score

        tier_max_quality = tier['max_quality']
        target_bitrate_factor = tier['target_bitrate_factor']

        log_debug('Slow internet adaptation: User tier: {} Mbps -> max quality: {}, target factor: {}'.format(
            internet_speed_mbps, tier_max_quality, target_bitrate_factor))

        # Penalty ak stream prekračuje odporúčanú kvalitu pre tento tier
        if quality in self.QUALITY_LIST and tier_max_quality in self.QUALITY_LIST:
            quality_level = self.QUALITY_LIST[quality]
            max_quality_level = self.QUALITY_LIST[tier_max_quality]

            if quality_level > max_quality_level:
                # Progresívna penalta: -2 za každý level nad odporúčanou kvalitou
                quality_penalty = (quality_level - max_quality_level) * 2
                current_score -= quality_penalty
                log_debug('Slow internet adaptation: Quality {} exceeds recommended {} for tier, penalty: -{}'.format(
                    quality, tier_max_quality, quality_penalty))

        # Vypočítaj cieľový bitrate pre tento tier
        # Používame target_bitrate_factor z tieru (napr. 0.75 pre 5-10 Mbps tier)
        target_bitrate = internet_speed_mbps * target_bitrate_factor

        # Bonus ak je bitrate blízko cieľového bitrate pre tier
        bitrate_distance = abs(bitrate_mbps - target_bitrate)
        if bitrate_distance < target_bitrate * 0.3:  # Do 30% od cieľového bitrate
            # Čím bližšie k cieľovému bitrate, tým väčší bonus (max +3)
            bonus = 3 * (1 - (bitrate_distance / (target_bitrate * 0.3)))
            current_score += bonus
            log_debug('Slow internet adaptation: Bitrate {} Mbps je blizko cieloveho {} Mbps, bonus: +{:.2f}'.format(
                bitrate_mbps, target_bitrate, bonus))

        # Dodatočná penalta ak bitrate presahuje 90% kapacity (varovanie pred bufferovaním)
        warning_threshold = internet_speed_mbps * 0.9
        if bitrate_mbps > warning_threshold:
            warning_penalty = 5
            current_score -= warning_penalty
            log_debug('Slow internet adaptation: Bitrate {} Mbps presahuje warning threshold {} Mbps, penalty: -{}'.format(
                bitrate_mbps, warning_threshold, warning_penalty))

        return current_score

    def __init__(self, data, resolve=True):
        self.input = data
        self.streams = []
        self.selected = None
        self.params = params.args
        self.hls = '#EXTM3U\n'
        item_info = self.input.get(SC.ITEM_INFO)
        if item_info is None:
            item_info = {}
        item_info.update({'play': True})

        SCBaseItem.__init__(self, item_info, debug=True)
        if resolve:
            self.resolve()

    @try_catch('get')
    def get(self):
        return self.item.getPath(), self.item, True, self.selected

    @try_catch('build_hls')
    def build_hls(self):
        # NOTE: This method is currently unused (no call sites).
        # If reactivated, it needs per-stream provider routing.
        kr = getKraInstance()
        for pos, s in enumerate(self.streams):
            ident = s.get('xxx')
            log_debug('STREAM: {} => {}'.format(ident, s))
            url = kr.resolve(ident)
            sinfo = s.get('stream_info', {}).get('video', {})
            self.hls += '\n#EXT-X-STREAM-INF:BANDWIDTH={},RESOLUTION={}x{}'.format(s.get('bitrate'),
                                                                                   sinfo.get('width', 0),
                                                                                   sinfo.get('height', 0))
            self.hls += '\n{}\n'.format(url)
        log_debug('HLS: {}'.format(self.hls))
        filename = make_legal_filename('special://profile/input.m3u8')
        fs = xbmcvfs.File(filename, 'w')
        fs.write(self.hls)
        fs.close()

    @try_catch('speedtest')
    def speedtest(self, isp, ident='15VFNFJrCKHn'):
        from resources.lib.services.speedtest import get_speedtest_service
        
        # Použijeme novú speedtest service
        speedtest_service = get_speedtest_service()
        smin, smax, durmin, isp_data, best_server = speedtest_service.run_speedtest(ident)
        
        # Aktualizujeme ISP dáta
        if isp_data:
            isp.update(isp_data)
        
        # Uložíme nastavenia ako predtým
        set_setting('stream.adv.speedtest', smin)
        set_setting('stream.adv.speedtest.asn', isp.get('a', 'N/A'))
        set_setting('stream.adv.speedtest.last', int(time.time()))
        
        # Uložíme najlepší server
        if best_server:
            set_setting('stream.adv.speedtest.best_server', best_server)
            log_debug('Saved best server: {}'.format(best_server))
        
        return (smin, smax, durmin)

    # calculate_speed funkcia bola presunutá do speedtest service

    @try_catch('ISP')
    def isp(self):
        return get_isp()

    @try_catch('filter')
    def filter(self):
        speedtest_last = get_setting_as_int('stream.adv.speedtest.last')
        now = time.time()
        force = True if speedtest_last is None or (speedtest_last + (24 * 3600 * 2)) < now else False

        isp = self.isp()
        asn = get_setting('stream.adv.speedtest.asn')
        asn_changed = str(isp.get('a')) != str(asn)
        wrong_speed = get_setting_as_int('stream.adv.speedtest') < 1
        log_debug('Force: {} ASN: {} / {} [{}] / SPEED: {} [{}]'.format(force, asn, isp.get('a'), asn_changed,
                                                                    get_setting_as_int('stream.adv.speedtest'),
                                                                    wrong_speed))
        if force is True or (get_setting_as_int('stream.max.bitrate') == 100 and (asn_changed or wrong_speed)):
            smin, smax, dur = self.speedtest(isp)
            log_debug('smin {} / smax {} / dur {}'.format(smin, smax, dur))

        # Načítaj stream filter preferences z Window property (ak existujú)
        self.stream_prefs = {}
        stream_prefs_json = home_win.getProperty(SC.STREAM_FILTER_PREFS)
        if stream_prefs_json:
            try:
                self.stream_prefs = loads(stream_prefs_json)
                log_debug('SCPlayItem.filter: Loaded stream preferences: {}'.format(self.stream_prefs))
            except Exception as e:
                log_debug('SCPlayItem.filter: Error loading stream preferences: {}'.format(e))
                self.stream_prefs = {}
        else:
            log_debug('SCPlayItem.filter: No stream preferences found')

        # @todo autoselect / filtrovanie nechcenych streamov
        if not get_setting_as_bool('stream.autoselect') \
                or SC.ACTION_SELECT_STREAM in self.params or SC.ACTION_DOWNLOAD in self.params:
            log_debug('nieje autoselect, alebo je vynuteny vyber streamu alebo download')
            return

        if get_setting_as_bool('stream.autoselect'):

            lang1 = get_setting('stream.lang1').lower()
            lang2 = get_setting('stream.lang2').lower()
            if Sc.parental_control_is_active():
                lang1 = get_setting('parental.control.lang1').lower()
                lang2 = get_setting('parental.control.lang2').lower()

            score = {pos: 0 for pos, s in enumerate(self.streams)}
            for pos, s in enumerate(self.streams):
                log_debug('-----------------------------------------------------------------------------------------------')
                log_debug('stream: bitrate: {} quality: {} lang: {}'.format(s.get('bitrate', 0), s.get('quality', 'N/A'),
                                                                        s.get('linfo', 'N/A')))
                self.video_score(score, pos, s)

                stream_info = s.get('stream_info', {})
                # Normalizacia - linfo moze byt None a kody musia byt lowercase,
                # inak TypeError/miss zhodi cely autoselect do manualneho vyberu
                linfo = [str(x).lower() for x in (s.get('linfo') or [])]
                if lang1 in linfo:
                    score = self.audio_score(lang1, pos, score, stream_info, self.LANG_PRIMARY_WEIGHT)
                elif lang2 in linfo:
                    score = self.audio_score(lang2, pos, score, stream_info, self.LANG_SECONDARY_WEIGHT)
                else:
                    log_debug('Nemame primarny, ani sekundarny jazyk')

                log_debug('-----------------------------------------------------------------------------------------------')
                log_debug('final score: {}'.format(score[pos]))

            score = {k: v for k, v in sorted(score.items(), key=lambda item: item[1], reverse=True)}

            # Ak nie sú žiadne streamy alebo všetky boli vyfiltrované, pokračuj bez auto-select
            if not score:
                log_debug('autoselect: Žiadne streamy na výber (všetky vyfiltrované alebo prázdny zoznam)')
                return

            sel = list(score.keys())[0]
            log_debug('score: {} / {}'.format(score, sel))
            self.selected = self.streams[sel]

            # Detailné info o automaticky vybranom streame (s error handling)
            try:
                log_debug('===============================================================================')
                log_debug('AUTOSELECT: Vybraný stream (index {}):'.format(sel))
                log_debug('  Quality: {}'.format(self.selected.get('quality', 'N/A')))

                # Bitrate - s bezpečným konvertovaním
                try:
                    bitrate_val = int(self.selected.get('bitrate', 0))
                    log_debug('  Bitrate: {} ({} Mbps)'.format(
                        convert_bitrate(bitrate_val),
                        round(bitrate_val / 1e6, 2)))
                except (ValueError, TypeError):
                    log_debug('  Bitrate: N/A')

                # Video kodek
                stream_info = self.selected.get('stream_info', {})
                video_info = stream_info.get('video', {})
                vcodec = video_info.get('codec', 'N/A')
                log_debug('  Video codec: {}'.format(vcodec))
                log_debug('  Resolution: {}x{}'.format(
                    video_info.get('width', 'N/A'),
                    video_info.get('height', 'N/A')))

                # Audio jazyky
                linfo = self.selected.get('linfo', [])
                log_debug('  Audio languages: {}'.format(', '.join(linfo) if linfo else 'N/A'))

                # Filesize - s bezpečným konvertovaním
                try:
                    filesize = int(self.selected.get('size', 0))
                    if filesize > 0:
                        filesize_gb = round(filesize / (1024**3), 2)
                        log_debug('  Filesize: {} GB'.format(filesize_gb))
                except (ValueError, TypeError):
                    pass

                # Finálne skóre
                final_score = score[sel]
                log_debug('  Final score: {:.2f}'.format(final_score))

                # Dodatočné info ak existuje
                if 'grp' in stream_info:
                    log_debug('  Group: {}'.format(stream_info.get('grp')))
                if 'src' in stream_info:
                    log_debug('  Source: {}'.format(stream_info.get('src')))

                log_debug('===============================================================================')
            except Exception as e:
                log_debug('AUTOSELECT: Error logging stream details: {}'.format(str(e)))
                log_debug('===============================================================================')

            self.streams = [self.selected]
            return

        log_debug('autoselect nic nevybral, tak nechame usera vybrat')

    def _parse_range_filter(self, range_str):
        """
        Parsuje range filter (>5000, <10000, 5000:10000)
        Returns: {'type': 'gt'|'lt'|'range', 'value': int | 'min': int, 'max': int}
        """
        if not range_str:
            return None

        range_str = str(range_str).strip()

        if range_str.startswith('>'):
            try:
                return {'type': 'gt', 'value': int(float(range_str[1:].strip()))}
            except (ValueError, TypeError):
                return None
        elif range_str.startswith('<'):
            try:
                return {'type': 'lt', 'value': int(float(range_str[1:].strip()))}
            except (ValueError, TypeError):
                return None
        elif ':' in range_str:
            parts = range_str.split(':')
            if len(parts) == 2:
                try:
                    return {'type': 'range', 'min': int(float(parts[0].strip())), 'max': int(float(parts[1].strip()))}
                except (ValueError, TypeError):
                    return None

        return None

    def _check_range_filter(self, value, range_filter):
        """
        Kontroluje, či hodnota splňa range filter
        Args:
            value: hodnota na kontrolu (int)
            range_filter: dict z _parse_range_filter
        Returns: True ak hodnota splňa filter, False inak
        """
        if not range_filter:
            return True

        if range_filter['type'] == 'gt':
            return value > range_filter['value']
        elif range_filter['type'] == 'lt':
            return value < range_filter['value']
        elif range_filter['type'] == 'range':
            return range_filter['min'] <= value <= range_filter['max']

        return True

    def video_score(self, score, pos, s):
        megabit = 1e6
        speed = get_setting_as_int('stream.adv.speedtest')
        internet_speed_mbps = 100  # Default pre users bez speedtestu

        if speed > 0:
            internet_speed_mbps = speed / megabit
            log_debug('Internet speed z speedtestu: {} Mbps'.format(internet_speed_mbps))
        else:
            max_bitrate_setting = get_setting_as_int('stream.max.bitrate')
            if max_bitrate_setting < 100:
                internet_speed_mbps = max_bitrate_setting
                log_debug('Internet speed z nastavenia: {} Mbps'.format(internet_speed_mbps))

        quality = s.get('quality', 'SD')
        max_quality = get_setting('stream.max.quality')
        log_debug('qualita {} vs {} | {} >= {}'.format(quality, max_quality, self.QUALITY_LIST.get(max_quality, 0),
                                                   self.QUALITY_LIST.get(quality, 0)))

        # Quality scoring (zachovávame existujúci systém)
        if quality in self.QUALITY_LIST:
            if max_quality == '-':
                score[pos] += self.QUALITY_LIST[quality]
                log_debug('quality point 1: {} / {}'.format(self.QUALITY_LIST[quality], score[pos]))
            elif max_quality in self.QUALITY_LIST and self.QUALITY_LIST[max_quality] >= self.QUALITY_LIST[quality]:
                w = self.QUALITY_LIST[max_quality] - (self.QUALITY_LIST[max_quality] - self.QUALITY_LIST[quality] - 1)
                score[pos] += w
                log_debug('quality point 2: {} / {}'.format(w, score[pos]))
            else:
                log_debug('nehodnotime rozlisenie 1')
        else:
            log_debug('nehodnotime rozlisenie 2')

        # NOVÝ: Sweet spot bitrate scoring s Gaussovou krivkou
        bitrate = int(s.get('bitrate', 0))
        bitrate_mbps = bitrate / megabit

        # Použijeme nový sweet spot scoring systém
        bitrate_score = self._calculate_bitrate_score(bitrate_mbps, quality, internet_speed_mbps)
        score[pos] += bitrate_score
        log_debug('Sweet spot bitrate scoring: {} Mbps -> score: {:.2f} / total: {}'.format(
            bitrate_mbps, bitrate_score, score[pos]))

        # NOVÝ: Slow internet adaptation (Phase 2)
        # Aplikujeme dodatočné úpravy skóre pre používateľov s pomalým internetom
        score[pos] = self._apply_slow_internet_adaptation(quality, bitrate_mbps, internet_speed_mbps, score[pos])
        log_debug('Po slow internet adaptation: total score: {}'.format(score[pos]))

        stream_info = s.get('stream_info', {})
        video = stream_info.get('video', {})
        vcodec = video.get('codec')

        # NOVÝ: Preferované kodeky - vždy sa používajú (aj mimo stream.adv)
        # Poradie v nastavení určuje prioritu (prvý = najvyššie skóre)
        codec_score = self._get_codec_preference_score(vcodec)
        score[pos] += codec_score
        log_debug('Codec preference scoring: {} -> +{} / total: {}'.format(vcodec, codec_score, score[pos]))

        # Blacklist kodekov (len ak je stream.adv zapnuté)
        if get_setting_as_bool('stream.adv'):
            if vcodec and vcodec in get_setting('stream.adv.blacklist.codec'):
                score[pos] -= 10
                log_debug('blacklist codec {} / {}'.format(vcodec, score[pos]))

            if get_setting_as_bool('stream.adv.exclude.3d') and '3D' in quality:
                score[pos] -= 10
                log_debug('penalize 3D content {}'.format(score[pos]))

            if get_setting_as_bool('stream.adv.exclude.hdr') and stream_info.get('HDR'):
                score[pos] -= 10
                log_debug('penalize HDR content {}'.format(score[pos]))

            if get_setting_as_bool('stream.adv.prefer.hdr') and stream_info.get('HDR'):
                score[pos] += 1
                log_debug('prefer HDR {}'.format(score[pos]))

        # Aplikuj stream filter preferences (ak existujú)
        if hasattr(self, 'stream_prefs') and self.stream_prefs:
            log_debug('Applying stream filter preferences: {}'.format(self.stream_prefs))

            # Bitrate filter (v kbps, potrebuje konverziu na bps)
            if 'b' in self.stream_prefs:
                bitrate_filter_kbps = self._parse_range_filter(self.stream_prefs['b'])
                if bitrate_filter_kbps:
                    # Konvertuj kbps na bps (bitrate filter je v kbps, stream bitrate je v bps)
                    stream_bitrate_kbps = bitrate / 1000  # Convert bps to kbps
                    if not self._check_range_filter(stream_bitrate_kbps, bitrate_filter_kbps):
                        score[pos] -= self.FILTER_PENALTY
                        log_debug('Stream filter: Bitrate {} kbps outside filter range {} / {}'.format(
                            stream_bitrate_kbps, self.stream_prefs['b'], score[pos]))

            # Filesize filter (v B)
            if 'f' in self.stream_prefs:
                stream_filesize = s.get('size', 0)  # Filesize v B
                if stream_filesize > 0:
                    filesize_filter = self._parse_range_filter(self.stream_prefs['f'])
                    if filesize_filter and not self._check_range_filter(stream_filesize, filesize_filter):
                        score[pos] -= self.FILTER_PENALTY
                        log_debug('Stream filter: Filesize {} B outside filter range {} / {}'.format(
                            stream_filesize, self.stream_prefs['f'], score[pos]))

            # HEVC Codec filter (hevc=1 means exclude HEVC)
            if 'hevc' in self.stream_prefs and int(self.stream_prefs['hevc']) == 1:
                if vcodec and 'hevc' in vcodec.lower():
                    score[pos] -= self.FILTER_PENALTY
                    log_debug('Stream filter: HEVC codec excluded / {}'.format(score[pos]))

            # 3D/Stereoscopic filter (ste=1 means exclude 3D)
            if 'ste' in self.stream_prefs and int(self.stream_prefs['ste']) == 1:
                if '3D' in quality:
                    score[pos] -= self.FILTER_PENALTY
                    log_debug('Stream filter: 3D content excluded / {}'.format(score[pos]))

            # HDR filter (HDR: 0=exclude, 1=both, 2=only)
            if 'HDR' in self.stream_prefs:
                hdr_pref = int(self.stream_prefs['HDR'])
                has_hdr = stream_info.get('HDR', False)
                if hdr_pref == 0 and has_hdr:
                    score[pos] -= self.FILTER_PENALTY
                    log_debug('Stream filter: HDR excluded / {}'.format(score[pos]))
                elif hdr_pref == 2 and not has_hdr:
                    score[pos] -= self.FILTER_PENALTY
                    log_debug('Stream filter: Non-HDR excluded (only HDR wanted) / {}'.format(score[pos]))

            # Dolby Vision filter (DV: 0=exclude, 1=both, 2=only)
            if 'DV' in self.stream_prefs:
                dv_pref = int(self.stream_prefs['DV'])
                has_dv = stream_info.get('DV', False)
                if dv_pref == 0 and has_dv:
                    score[pos] -= self.FILTER_PENALTY
                    log_debug('Stream filter: Dolby Vision excluded / {}'.format(score[pos]))
                elif dv_pref == 2 and not has_dv:
                    score[pos] -= self.FILTER_PENALTY
                    log_debug('Stream filter: Non-DV excluded (only DV wanted) / {}'.format(score[pos]))

            # Dolby Atmos filter (atmos=1 means only Atmos)
            if 'atmos' in self.stream_prefs and int(self.stream_prefs['atmos']) == 1:
                has_atmos = stream_info.get('Atmos', False) or stream_info.get('atmos', False)
                if not has_atmos:
                    score[pos] -= self.FILTER_PENALTY
                    log_debug('Stream filter: Non-Atmos excluded (only Atmos wanted) / {}'.format(score[pos]))

            # Max Quality filter (q)
            if 'q' in self.stream_prefs and self.stream_prefs['q']:
                max_quality_filter = self.stream_prefs['q']
                if quality in self.QUALITY_LIST and max_quality_filter in self.QUALITY_LIST:
                    if self.QUALITY_LIST[quality] > self.QUALITY_LIST[max_quality_filter]:
                        score[pos] -= self.FILTER_PENALTY
                        log_debug('Stream filter: Quality {} exceeds max {} / {}'.format(quality, max_quality_filter, score[pos]))

        return score

    def audio_score(self, lang1, pos, score, stream_info, weight=3):
        if get_setting_as_bool('stream.adv') and 'streams' in stream_info:
            force_lang = preferred_lang_list.get(self.data.get('id'))
            ascore = {apos: 0 for apos, _ in enumerate(stream_info['streams'])}
            for apos, track in enumerate(stream_info['streams']):
                try:
                    acodec, channels, lang = track
                    channels = int(channels or 0)
                except (ValueError, TypeError):
                    # Neocakavany tvar audio stopy nesmie zhodit cely autoselect
                    log_debug(' - preskakujem neplatnu audio stopu: {}'.format(track))
                    continue
                lang = str(lang).lower()

                if force_lang is not None and force_lang.lower() == lang:
                    ascore[apos] += 1000
                    log_debug('FORCE lang: {}'.format(force_lang.lower()))

                log_debug(' - lang {}/{}'.format(lang, lang1))
                if acodec in get_setting('stream.adv.whitelist.codec'):
                    log_debug(' - audio whitelist acodec {}'.format(acodec))
                    ascore[apos] += 1

                if acodec in get_setting('stream.adv.blacklist.codec'):
                    log_debug(' - audio blacklist acodec {}'.format(acodec))
                    ascore[apos] -= 10

                if lang == lang1:
                    if get_setting_as_bool('stream.adv.audio.channels') and channels > 3:
                        # Bonus za viackanalove audio (5.1 -> +3, 7.1 -> +5)
                        weight = weight + (channels - 3)
                    log_debug(' - audio adv prefered lang {} => {}'.format(lang1, weight))
                    ascore[apos] += weight
            ascore = {k: v for k, v in sorted(ascore.items(), key=lambda item: item[1], reverse=True)}
            sel = list(ascore.keys())[0]
            score[pos] += ascore[sel]
            log_debug('audio score: {} -> {} / {}'.format(ascore, sel, score[pos]))
        else:
            score[pos] += weight
            log_debug('audio basic prefered lang {} => {} / {}'.format(lang1, weight, score[pos]))

        return score

    def _get_resolve_data(self, res):
        """Common pre-resolve: load stream prefs, call SC API, extract ident."""
        stream_prefs_for_api = {}
        stream_prefs_json = home_win.getProperty(SC.STREAM_FILTER_PREFS)
        if stream_prefs_json:
            try:
                stream_prefs_for_api = loads(stream_prefs_json)
                log_debug('SCPlayItem: stream prefs: {}'.format(stream_prefs_for_api))
            except Exception as e:
                log_debug('SCPlayItem: Error loading stream prefs: {}'.format(e))
                stream_prefs_for_api = {}

        resp = Sc.get(res.getPath(), params=stream_prefs_for_api)
        log_debug('-=-=-= RESOLVE: {}'.format(json.dumps(resp)))
        version = resp.get('version')
        if version is None:
            log_debug('SCPlayItem: Backend nevratil version, resp keys: {}'.format(list(resp.keys())))
            dok(Strings.txt(Strings.RESOLVE_ERROR_H1), Strings.txt(Strings.RESOLVE_ERROR_L1))
            raise BaseException
        version_key = 'v{}'.format(version)
        version_value = resp.get(version_key)
        if not version_value:
            log_debug('SCPlayItem: Key {} missing, resp keys: {}'.format(version_key, list(resp.keys())))
            dok(Strings.txt(Strings.RESOLVE_ERROR_H1), Strings.txt(Strings.RESOLVE_ERROR_L1))
            raise BaseException

        ident = '{}:{}'.format(version_key, version_value)
        log_debug('SCPlayItem: resolved ident: {}'.format(ident))
        return ident

    @staticmethod
    def _kraska_subs_ident(subs):
        """Vytiahne kra.sk ident titulkov z hodnoty tvaru '.../file/<ident>'.

        Backend posiela titulky ako URL, z ktorej sa ident získa oddelením na
        '/file/'. Ak hodnota tento tvar nemá (napr. neúplná/iná), vráti None —
        titulky sa preskočia namiesto pádu (predtým IndexError na part[1]).

        Args:
            subs (str): hodnota ITEM_SUBS property.

        Returns:
            str | None: ident titulkov alebo None ak tvar nesedí.
        """
        if not subs:
            return None
        part = subs.split('/file/')
        if len(part) > 1 and part[1]:
            return part[1]
        return None

    def resolve(self):
        data = self.data
        if SC.ITEM_URL in data:
            del (data[SC.ITEM_URL])
        self.streams = self.input.get(SC.ITEM_STRMS)

        # Debug: Kontrola streamov
        log_debug('resolve: Loaded {} streams from input'.format(len(self.streams) if self.streams else 0))
        if not self.streams or len(self.streams) == 0:
            log_debug('resolve: ERROR - No streams available! input keys: {}'.format(self.input.keys() if self.input else 'None'))
            raise BaseException  # Žiadne streamy = chyba

        self.filter()

        items = []
        matrix = []
        for s in self.streams:
            log_debug('ideme vytvorit listItems zo streamov')
            s.update(data)
            itm = SCStreamSelect(s)
            x = itm.get()
            title_items = [
                '[B]{}[/B] - '.format(s.get(SC.ITEM_LANG)),
                '[B]{}[/B] '.format(s.get(SC.ITEM_QUALITY)),
                '{} '.format(s.get(SC.ITEM_SIZE)),
                '{}{}'.format(s.get(SC.ITEM_VIDEO_INFO), s.get(SC.ITEM_AUDIO_INFO)),
            ]
            matrix.append(title_items)
            items.append(x[1])
        # matrix = make_table(matrix)
        # info('matrix: {}'.format(matrix))
        for i, itm in enumerate(items):
            itm.setProperty('old_title', itm.getLabel())
            itm.setLabel(' '.join(matrix[i]))

        if len(items) > 1 or SC.ACTION_SELECT_STREAM in self.params or SC.ACTION_DOWNLOAD in self.params:
            pos = dselect(items, heading=items[0].getProperty('old_title'), use_details=True)
            # info('post: {} | {}'.format(pos, json.dumps(self.data)))
            if pos is False or pos == -1:
                raise UserCancelledException('User cancelled stream selection')
            res = items[pos]
            self.selected = self.streams[pos]
        elif len(items) == 1:
            res = items[0]
            self.selected = self.streams[0] if self.selected is None else self.selected
        else:
            raise UserCancelledException('No streams available')

        url = res.getPath()
        # Bug report: ulož skutočný stream resolve URL (res.getPath()) do
        # vybraného streamu. Pre epizódy je to /ws2/<token>/<streamId> s
        # REÁLNYM ID prehrávaného streamu; pre filmy iný path. Ukladáme TU,
        # pred proxy resolve (premenná 'url' sa nižšie prepíše na proxy URL).
        try:
            if isinstance(self.selected, dict):
                self.selected['stream_url'] = url
        except Exception:
            pass
        provider = res.getProperty(SC.ITEM_PROVIDER)
        if provider == SC.PROVIDER_KRASKA:
            ident = self._get_resolve_data(res)
            kr = getKraInstance()
            try:
                log_debug('resolving ident {} via kraska proxy'.format(ident))
                url = kr.resolve_via_proxy(ident, get_setting('stream.adv.speedtest.best_server') or None)
            except HelperException:
                # chybovy dialog uz zobrazil ensure_helper_running
                raise BaseException
            except ResolveException as e:
                dok(Strings.txt(Strings.RESOLVE_ERROR_H1), Strings.txt(Strings.RESOLVE_ERROR_L1))
                raise BaseException
            except:
                raise BaseException
            if res.getProperty(SC.ITEM_SUBS):
                # Titulky sú voliteľné — ich zlyhanie NESMIE zhodiť prehrávanie
                # (video URL je už vyriešené vyššie).
                try:
                    sub_ident = self._kraska_subs_ident(res.getProperty(SC.ITEM_SUBS))
                    if sub_ident:
                        log_debug('loading subtitles via kraska')
                        sub_url = kr.resolve(sub_ident)
                        if sub_url:
                            self.item.setSubtitles([sub_url])
                    else:
                        log_debug('subtitles: hodnota nema ocakavany /file/ tvar, preskakujem')
                except Exception as e:
                    log_debug('subtitles load zlyhalo, pokracujem bez nich: {}'.format(e))

        info('resolve: {}'.format(url))
        if 'lid' in data:
            lid = 'p-{}'.format(data.get('lid')) if parental_history() else data.get('lid')
            st = List(lid, max_items=20)
            st.add(res.getProperty(SC.ITEM_ID))
        self.item.setPath(url)
        self.item.setLabel(res.getProperty('original_title'))
        # home_win.setProperty('SC-lite-item', '{}'.format(res.getProperty(SC.ITEM_ID)))
        home_win.setProperty(SC.SELECTED_ITEM, '{}'.format(dumps(self.selected)))

        # Nastav unique_ids - skontroluj obe lokácie (top level aj v info)
        unique_ids = None
        if 'unique_ids' in self.input.get(SC.ITEM_INFO, {}):
            unique_ids = self.input.get(SC.ITEM_INFO).get('unique_ids')
            log_debug('SCPlayItem: unique_ids found in info: {}'.format(unique_ids))
        elif 'unique_ids' in self.input:
            unique_ids = self.input.get('unique_ids')
            log_debug('SCPlayItem: unique_ids found at top level: {}'.format(unique_ids))

        if unique_ids:
            home_win.setProperty('script.trakt.ids', '{}'.format(dumps(unique_ids)))
            home_win.setProperty('{}.ids'.format(ADDON_ID), '{}'.format(dumps(unique_ids)))
            log_debug('SCPlayItem: Set Window property {}.ids: {}'.format(ADDON_ID, unique_ids))
        else:
            log_debug('SCPlayItem: WARNING - No unique_ids found! SCPlayer.my_id will be None')


class SCUpNext:
    def __init__(self, data):
        self.data = data
        self.out = {}
        self.play_item = SCPlayItem(data, resolve=False)
        self.build()

    def build_cur(self):
        tvshowid = self.data.get('info', {}).get('id')
        return dict(
            episodeid='{}-{}-{}'.format(tvshowid, get_info_label('VideoPlayer.Season'), get_info_label('VideoPlayer'
                                                                                                       '.Episode')),
            tvshowid=tvshowid,
            title=get_info_label('Player.Title'),
            art={
                'tvshow.fanart': get_info_label('ListItem.Art(tvshow.fanart)'),
                'tvshow.poster': get_info_label('ListItem.Art(tvshow.poster)'),
            },
            season=get_info_label('VideoPlayer.Season'),
            episode=get_info_label('VideoPlayer.Episode'),
            showtitle=get_info_label('VideoPlayer.TVShowTitle'),
            plot=get_info_label('VideoPlayer.Plot'),
            playcount=0,
            rating=0,
            firstaired='',
        )

    def build(self):
        item = self.play_item.item
        tvshowid = self.data.get('info', {}).get('id')
        next_episode = dict(
            episodeid='{}-{}-{}'.format(tvshowid, item.getProperty('season'), item.getProperty('episode')),
            tvshowid=tvshowid,
            title=item.getLabel(),
            art={
                'thumb': item.getArt('thumb'),
                'tvshow.clearart': item.getArt('clearart'),
                'tvshow.clearlogo': item.getArt('clearlogo'),
                'tvshow.fanart': item.getArt('fanart'),
                'tvshow.poster': item.getArt('poster'),
            },
            season=item.getProperty('season'),
            episode=item.getProperty('episode'),
            showtitle=item.getProperty('showtitle'),
            plot=item.getProperty('plot'),
            playcount=0,
            rating=0,
            firstaired='',
            # runtime=''
        )
        play_info = {
            SC.ITEM_URL: '{}'.format(self.data.get('info', {}).get(SC.ITEM_URL))
        }
        self.out = dict(
            current_episode=self.build_cur(),
            next_episode=next_episode,
            # play_url=item.getPath()
            play_info=play_info
        )
        selected_item = home_win.getProperty(SC.SELECTED_ITEM)
        log_debug('selected_item: {}'.format(selected_item))
        if selected_item:
            selected_item = loads(selected_item)

            log_debug('CURRENT: {}'.format(selected_item))

            notifications = selected_item.get(SC.NOTIFICATIONS, {})
            if SC.SKIP_END_TITLES in notifications and notifications.get(SC.SKIP_END_TITLES) is not None:
                self.out.update({'notification_offset': notifications.get(SC.SKIP_END_TITLES, None)})
        log_debug('next_info: {}'.format(self.out))
        pass

    def get(self):
        return self.out
