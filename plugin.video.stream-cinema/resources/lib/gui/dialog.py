import xbmcgui
import xbmc
from resources.lib.system import SYSTEM_VERSION


def dialog():
    return xbmcgui.Dialog()


def dtextviewer(heading, text):
    dialog().textviewer(heading, text)


def dyesno(heading='heading', message='message', yeslabel=None, nolabel=None, autoclose=None):
    # Použij KODI built-in lokalizované stringy pre tlačítka
    # ID 107 = "Yes", ID 106 = "No"
    if yeslabel is None:
        yeslabel = xbmc.getLocalizedString(107)
    if nolabel is None:
        nolabel = xbmc.getLocalizedString(106)

    if autoclose is not None:
        autoclose = autoclose * 1000
    else:
        autoclose = 0
    if SYSTEM_VERSION > 18:
        return dialog().yesno(heading=heading, message=message, nolabel=nolabel, yeslabel=yeslabel,
                              autoclose=autoclose)
    return dialog().yesno(heading=heading, line1=message, nolabel=nolabel, yeslabel=yeslabel,
                          autoclose=autoclose)


def dok(heading, message=None):
    if SYSTEM_VERSION > 18:
        return dialog().ok(heading=heading, message=message)
    return dialog().ok(heading=heading, line1=message)


def dinfo(list_item):
    return dialog().info(list_item)


def dnotify(heading, message, icon=xbmcgui.NOTIFICATION_INFO, time=5000, sound=True):
    return dialog().notification(heading, message, icon, time, sound)


def dprogressgb():
    return xbmcgui.DialogProgressBG()


def dselect(list_item, heading='', use_details=False):
    return dialog().select(heading, list_item, useDetails=use_details)


def dinput(heading=None, default='', type=xbmcgui.INPUT_ALPHANUM):
    return dialog().input(heading=heading, defaultt=default, type=type)


def dprogress():
    return xbmcgui.DialogProgress()
