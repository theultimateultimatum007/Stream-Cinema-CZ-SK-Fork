from resources.lib.common.logger import debug
from resources.lib.constants import ADDON_ID
from resources.lib.kodiutils import get_setting, set_setting, get_setting_as_bool, get_setting_as_int
from resources.lib.kodiutils import addon as addon_utils
import xbmcaddon
import xbmc


class Settings(xbmc.Monitor):
    addon = None

    def __init__(self):
        pass

    def onSettingsChanged(self):
        self.refresh()

    def refresh(self):
        pass

    def get_setting(self, key):
        return get_setting(key)

    def set_setting(self, key, val):
        return set_setting(key, val)

    def get_setting_as_int(self, key):
        return get_setting_as_int(key)

    def get_setting_as_bool(self, key):
        return get_setting_as_bool(key)


settings = Settings()
