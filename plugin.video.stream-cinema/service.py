# DÔLEŽITÉ: kontrola integrity settings.xml MUSÍ prebehnúť pred importom
# modulov, ktoré si pri inicializácii čítajú nastavenia (kodiutils a spol.)
# - poškodený súbor sa obnoví zo zálohy a až potom sa načíta
from resources.lib.common.settings_backup import ensure_settings_integrity
ensure_settings_integrity()

from resources.lib.intro import intro
from resources.lib.kodiutils import get_kodi_version, get_screen_width, get_screen_height, \
    get_app_name, get_uuid
from resources.lib.common import logger
from resources.lib.services.service import service

logger.APP = 'SC:S'
logger.info("Start sw: [{}] kodi ver: [{}] screen [{}x{}] uuid: [{}]".format(get_app_name(), get_kodi_version(),
                                                                      get_screen_width(), get_screen_height(),
                                                                      get_uuid()))

intro()
service.run()
