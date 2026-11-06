# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals

import sys

import xbmcplugin
import xbmcaddon

python_version = sys.version_info[0]
PY2 = python_version == 2
PY3 = python_version == 3
try:
    HANDLE = int(sys.argv[1])
except:
    HANDLE = -1

ADDON_ID = 'plugin.video.stream-cinema'
ADDON = xbmcaddon.Addon(id=ADDON_ID)
BASE_URL = 'https://stream-cinema.online/kodi'
API_VERSION = '2.0'

# Cache konfigurácia - pre testovanie nových položiek nastaviť na False
CACHE_ENABLED = True  # Hlavný prepínač pre všetky cache
CACHE_API_ENABLED = True  # API cache (Sc.get() v sc.py)
CACHE_MENU_ENABLED = True  # Menu cache (MenuCacheServer v streamcinema.py)
CACHE_STATIC_MENU_ENABLED = True  # Static menu cache (menu.json súbor)

# Pamäťový profiler (tracemalloc) — LEN pre diagnostiku spotreby RAM doplnku!
# Má réžiu (spomalí alokácie), preto default False. Pri zapnutí vypisuje do logu
# (prefix "[SC] [MemProfiler]") TOP alokácie a rast pamäte od štartu (leak).
MEM_PROFILER_ENABLED = False  # True = zapni profilovanie pamäte v background service
MEM_PROFILER_INTERVAL = 60  # sekundy medzi výpismi (násobok 5s slučky service)

# Menu ikonky zo servera: neon sada je priamo v MENU_ICON_BASE, ostatné štýly
# v podpriečinku. Poradie = hodnoty enum nastavenia plugin.menu.icons (settings16.xml).
MENU_ICON_BASE = 'https://stream-cinema.online/images/menu/'
MENU_ICON_STYLES = ('', 'kino', 'retro', 'ilustracia', 'blockbuster')


class GUI:
    BOTTOM = 'bottom'
    TOP = 'top'


class SC:
    ACTION = 'action'
    ACTION_ADD2HP = 'add2hp'
    ACTION_ADD_CUSTOM_FILTER = 'add_custom_filter'
    ACTION_ADD_TO_LIBRARY = 'add_to_library'
    ACTION_ADD_TO_LIBRARY_WITH_SUBSCRIPTION = 'add_to_library_sub'
    ACTION_ANDROID = 'android'
    ACTION_BUFFER = 'buffer'
    ACTION_CMD = 'cmd'
    ACTION_CSEARCH = 'csearch'
    ACTION_DEBUG = 'debug'
    ACTION_DEL2HP = 'del2hp'
    ACTION_DEL_CUSTOM_FILTER = 'del_custom_filter'
    ACTION_DEL_PREFERRED_LANGUAGE = 'sel_preferred_language'
    ACTION_DOWNLOAD = 'down'
    ACTION_DOWNLOAD_QUEUE = 'download_queue'
    ACTION_FILTER = 'filter'
    ACTION_LOAD_SAVED_FILTER = 'load_saved_filter'
    ACTION_DELETE_SAVED_FILTER = 'delete_saved_filter'
    ACTION_EDIT_SAVED_FILTER = 'edit_saved_filter'
    ACTION_RENAME_SAVED_FILTER = 'rename_saved_filter'
    ACTION_LAST = 'last'
    ACTION_PIN = 'pin'
    ACTION_PLAY_URL = 'playUrl'
    ACTION_REMOVE_FROM_LIST = 'remove_from_list'
    ACTION_REMOVE_FROM_SUBSCRIPTION = 'remove_from_sub'
    ACTION_SELECT_STREAM = 'selectStream'
    ACTION_SET_PREFERRED_LANGUAGE = 'set_preferred_language'
    ACTION_UPDATE_ADDON = 'update_addon'
    ACTION_HIDE_HP_ITEM = 'hide_hp_item'
    ACTION_RESET_HIDDEN = 'reset_hidden'
    ACTION_BUG_REPORT = 'bug_report'
    ACTION_BUG_REPORT_OFFER = 'bug_report_offer'
    BUG_REPORT_QUEUE = 'bug_report_queue'
    BUG_REPORT_INBOX = 'bug_report_inbox'
    BUG_REPORT_LAST_STREAM = 'bug_report_last_stream'
    BUG_REPORT_PLAY_TS = 'bug_report_play'
    BUG_CAT_STREAM_BROKEN = 'stream_broken'
    BUG_CAT_STREAM_MISMATCH = 'stream_mismatch'
    BUG_CAT_AV_SYNC = 'av_sync'
    BUG_CAT_GENERAL = 'general'
    BUG_REPORT_LOG_CAP_BYTES = 256 * 1024
    BUG_REPORT_FAIL_TIMEOUT = 60
    BUG_REPORT_SYNC_TIMEOUT = 5
    REPORT_BUG_PATH = '/ReportBug'
    CMD = 'cmd'
    DEFAULT_LANG = 'cs'
    ITEM_ACTION = 'action'
    ITEM_ART = 'art'
    ITEM_AUDIO_INFO = 'ainfo'
    ITEM_BITRATE = 'bitrate'
    ITEM_CMD = 'cmd'
    ITEM_CUSTOM_FILTER = 'custom'
    ITEM_SAVED_FILTER = 'saved_filter'
    ITEM_DIR = 'dir'
    ITEM_DOWNLOAD = 'down'
    ITEM_FOCUS = 'focus'
    ITEM_HPDIR = 'hpdir'
    ITEM_I18N_ART = 'i18n_art'
    ITEM_I18N_INFO = 'i18n_info'
    ITEM_ID = 'id'
    ITEM_IDENT = 'ident'
    ITEM_INFO = 'info'
    ITEM_LIBRARY = 'library'
    ITEM_LIBRARY_SUB = 'library_sub'
    ITEM_LANG = 'lang'
    ITEM_MENU = 'menu'
    ITEM_NEXT = 'next'
    ITEM_PAGE = 'page'
    ITEM_PREFERRED_LANG = 'pref_lang.{}'
    ITEM_PROVIDER = 'provider'
    ITEM_QUALITY = 'quality'
    ITEM_SIZE = 'size'
    ITEM_STRMS = 'strms'
    ITEM_SUBS = 'subs'
    ITEM_SYSTEM = 'system'
    ITEM_TITLE = 'title'
    ITEM_TYPE = 'type'
    ITEM_URL = 'url'
    ITEM_UIDS = 'unique_ids'
    ITEM_VIDEO = 'video'
    ITEM_VIDEO_INFO = 'vinfo'
    ITEM_VISIBLE = 'visible'
    ITEM_WIDGET = 'widget'
    MEDIA_TYPE = 'mediatype'
    MEDIA_TYPE_AUDIO = 'audio'
    MEDIA_TYPE_EPISODE = 'episode'
    MEDIA_TYPE_FILE = 'file'
    MEDIA_TYPE_SEASON = 'season'
    MEDIA_TYPE_TV_SHOW = 'tvshow'
    MEDIA_TYPE_VIDEO = 'video'
    NEXT = 'next'
    NEXT_EP_TIME_NOTIFICATION = 'next_ep_notify'
    NOTIFICATIONS = 'notifications'
    NOTIFICATIONS_PROPS = 'SC:NOTIFICATIONS'
    PROVIDER = 'kraska'
    PROVIDER_KRASKA = 'kraska'
    RUN_PLUGIN = 'RunPlugin({})'
    SELECTED_ITEM = 'SC:selected'
    STREAM_FILTER_PREFS = 'SC:stream_filter_prefs'
    SKIP_END = 'skip_end'
    SKIP_END_TITLES = 'skip_end_titles'
    SKIP_START = 'skip_start'
    TXT_PINNED = 'p-{}'
    TXT_CUSTOM_FORMAT = 'custom-{}'
    TRAKT_CACHE_WATCHET_ACTIVITY = 'SC:watched:activity'
    BCK_FILE = 'sc.json'


class HTTP:
    TIMEOUT = 10
    GET = 'get'
    POST = 'post'
    HEAD = 'head'
    OPTION = 'option'
    PUT = 'put'
    DELETE = 'delete'
    PATCH = 'patch'


class KodiDbMap:
    MyVideos = {16: 99, 17: 107, 18: 116, 19: 119, 20: 120, 21: 121}
    MyMusic = {16: 56, 17: 60, 18: 72, 19: 82, 20: 82, 21: 82}
    Textures = {16: 13, 17: 13, 18: 13, 19: 13, 20: 13, 21: 13}
    Addons = {16: 20, 17: 27, 18: 27, 19: 33, 20: 33, 21: 33}
    ViewModes = {16: 6, 17: 6, 18: 6, 19: 6, 20: 6, 21: 6}


SORT_METHODS = {
    14: xbmcplugin.SORT_METHOD_ALBUM,
    15: xbmcplugin.SORT_METHOD_ALBUM_IGNORE_THE,
    11: xbmcplugin.SORT_METHOD_ARTIST,
    13: xbmcplugin.SORT_METHOD_ARTIST_IGNORE_THE,
    42: xbmcplugin.SORT_METHOD_BITRATE,
    40: xbmcplugin.SORT_METHOD_CHANNEL,
    17: xbmcplugin.SORT_METHOD_COUNTRY,
    3: xbmcplugin.SORT_METHOD_DATE,
    21: xbmcplugin.SORT_METHOD_DATEADDED,
    43: xbmcplugin.SORT_METHOD_DATE_TAKEN,
    6: xbmcplugin.SORT_METHOD_DRIVE_TYPE,
    8: xbmcplugin.SORT_METHOD_DURATION,
    24: xbmcplugin.SORT_METHOD_EPISODE,
    5: xbmcplugin.SORT_METHOD_FILE,
    34: xbmcplugin.SORT_METHOD_FULLPATH,
    16: xbmcplugin.SORT_METHOD_GENRE,
    1: xbmcplugin.SORT_METHOD_LABEL,
    35: xbmcplugin.SORT_METHOD_LABEL_IGNORE_FOLDERS,
    2: xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE,
    36: xbmcplugin.SORT_METHOD_LASTPLAYED,
    38: xbmcplugin.SORT_METHOD_LISTENERS,
    30: xbmcplugin.SORT_METHOD_MPAA_RATING,
    0: xbmcplugin.SORT_METHOD_NONE,
    37: xbmcplugin.SORT_METHOD_PLAYCOUNT,
    23: xbmcplugin.SORT_METHOD_PLAYLIST_ORDER,
    28: xbmcplugin.SORT_METHOD_PRODUCTIONCODE,
    22: xbmcplugin.SORT_METHOD_PROGRAM_COUNT,
    4: xbmcplugin.SORT_METHOD_SIZE,
    29: xbmcplugin.SORT_METHOD_SONG_RATING,
    32: xbmcplugin.SORT_METHOD_STUDIO,
    33: xbmcplugin.SORT_METHOD_STUDIO_IGNORE_THE,
    9: xbmcplugin.SORT_METHOD_TITLE,
    10: xbmcplugin.SORT_METHOD_TITLE_IGNORE_THE,
    7: xbmcplugin.SORT_METHOD_TRACKNUM,
    39: xbmcplugin.SORT_METHOD_UNSORTED,
    19: xbmcplugin.SORT_METHOD_VIDEO_RATING,
    31: xbmcplugin.SORT_METHOD_VIDEO_RUNTIME,
    26: xbmcplugin.SORT_METHOD_VIDEO_SORT_TITLE,
    27: xbmcplugin.SORT_METHOD_VIDEO_SORT_TITLE_IGNORE_THE,
    25: xbmcplugin.SORT_METHOD_VIDEO_TITLE,
    20: xbmcplugin.SORT_METHOD_VIDEO_USER_RATING,
    18: xbmcplugin.SORT_METHOD_VIDEO_YEAR
}

if PY2:
    SORT_METHODS_INVERT = {v: k for k, v in SORT_METHODS.iteritems()}
else:
    SORT_METHODS_INVERT = {v: k for k, v in SORT_METHODS.items()}
