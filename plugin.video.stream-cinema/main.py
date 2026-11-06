# -*- coding: utf-8 -*-
import time
import traceback
import xbmc

try:
    xbmc._set_log_level(1)
except:
    pass


from resources.lib.streamcinema import Scinema
from resources.lib.common.logger import info
from resources.lib.kodiutils import refresh_addon
from resources.lib.params import params

try:
    # DÔLEŽITÉ: Refresh params pre reuselanguageinvoker=true
    # Bez tohto by sa použili staré args z predchádzajúceho volania
    params.refresh()
    # DÔLEŽITÉ: Refresh Addon inštancie pre reuselanguageinvoker=true
    # Bez tohto by get_setting vracal staré hodnoty - nastavenia zapísané
    # iným invokerom (napr. setup wizard v service) by plugin nevidel
    refresh_addon()

    start = time.time()
    Scinema().run()
    end = time.time()
    info('{0} took {1:.2f}ms'.format('ALL', (end - start) * 1000))
except:

    info('-----------------------------------------------------------------')
    info('main error [{}]'.format(str(traceback.format_exc())))
    info('-----------------------------------------------------------------')
    pass
