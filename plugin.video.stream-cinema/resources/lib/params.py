from __future__ import print_function, unicode_literals

import sys
from resources.lib.kodiutils import params as decode


class Params:
    def __init__(self):
        # Inicializácia prázdnych atribútov
        self.handle = -1
        self.orig_args = ''
        self.args = {}
        self.resume = False
        self.all = []
        self.url = None
        # Načítaj args pri vytvorení
        self.refresh()

    def refresh(self):
        """
        Znovu načíta argumenty z sys.argv
        DÔLEŽITÉ pre reuselanguageinvoker=true - volaj pred každým requestom!
        """
        self.handle = int(sys.argv[1]) if len(sys.argv) > 1 else -1
        self.orig_args = sys.argv[2] if len(sys.argv) > 2 else ''
        self.args = decode(sys.argv[2]) if len(sys.argv) > 2 else {}
        self.resume = sys.argv[3][7:] != 'false' if len(sys.argv) > 3 else False
        self.all = sys.argv
        self.url = None


params = Params()
