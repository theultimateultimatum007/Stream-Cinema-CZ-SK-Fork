from resources.lib.common.logger import info
from resources.lib.kodiutils import create_plugin_url, container_update
from resources.lib.params import params

info('START : [{}]'.format(params.all))
if len(params.all) > 2 and params.all[3]:
    plugin_url = create_plugin_url({'url': '/Search/search-people?ms=1&id=search-people&search={}'.format(params.all[3])})
    container_update(plugin_url, True)
else:
    import xbmc
    from resources.lib.constants import ADDON_ID

    xbmc.executebuiltin('RunAddon({})'.format(ADDON_ID))
