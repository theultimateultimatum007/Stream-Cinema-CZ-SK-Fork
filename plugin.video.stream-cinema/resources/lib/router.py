# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals

from resources.lib.common.logger import debug


class Router:
    """
    Centralizovaný Router pre navigáciu v plugine

    Poskytuje:
    - Čisté API pre navigáciu (go, replace, back)
    - Automatické vytváranie plugin URLs
    - Type-safe routing s parametrami
    - Debugging support
    """

    @staticmethod
    def go(url, **kwargs):
        """
        Naviguj na danú URL (pridá novú položku do histórie)

        Args:
            url: Cieľová URL (napr. '/Movies', '/Play/123')
            **kwargs: Ďalšie parametre pre URL (napr. action='search', page=2)

        Example:
            Router.go('/Movies')
            Router.go('/Search', action='search', query='matrix')
            Router.go('/Play/123', selectStream=True)
        """
        from resources.lib.kodiutils import container_update

        plugin_url = Router.get_url(url, **kwargs)
        debug('Router.go: {}'.format(plugin_url))
        container_update(plugin_url, replace=False)

    @staticmethod
    def replace(url, **kwargs):
        """
        Nahraď aktuálnu URL novou (neprináša novú položku do histórie)

        Args:
            url: Cieľová URL
            **kwargs: Ďalšie parametre pre URL

        Example:
            Router.replace('/Movies')  # Nahradí aktuálnu stránku filmami
        """
        from resources.lib.kodiutils import container_update

        plugin_url = Router.get_url(url, **kwargs)
        debug('Router.replace: {}'.format(plugin_url))
        container_update(plugin_url, replace=True)

    @staticmethod
    def back():
        """
        Návrat späť v histórii (ako stlačenie Back tlačidla)

        Example:
            Router.back()
        """
        from resources.lib.kodiutils import exec_build_in

        debug('Router.back')
        exec_build_in('Action(Back)')

    @staticmethod
    def refresh():
        """
        Obnoví aktuálny container (reload súčasnej stránky)

        Example:
            Router.refresh()  # Po označení ako pozreté, atď.
        """
        from resources.lib.kodiutils import container_refresh

        debug('Router.refresh')
        container_refresh()

    @staticmethod
    def get_url(url, **kwargs):
        """
        Vytvor plugin URL z relatívnej URL a parametrov

        Args:
            url: Relatívna URL (napr. '/Movies', '/Play/123')
            **kwargs: Ďalšie parametre (action, page, query, atď.)

        Returns:
            str: Kompletná plugin URL (plugin://plugin.video.sc.lite/?url=/Movies&...)

        Example:
            Router.get_url('/Movies')
            # -> 'plugin://plugin.video.sc.lite/?url=%2FMovies'

            Router.get_url('/Search', action='search', query='matrix')
            # -> 'plugin://plugin.video.sc.lite/?url=%2FSearch&action=search&query=matrix'
        """
        from resources.lib.kodiutils import create_plugin_url

        # Priprav parametre - url je povinná
        params = {'url': url}
        params.update(kwargs)

        return create_plugin_url(params)

    @staticmethod
    def play(url, **kwargs):
        """
        Spusti prehrávanie videa

        Args:
            url: Video URL alebo ID
            **kwargs: Ďalšie parametre

        Example:
            Router.play('/Play/123')
        """
        from resources.lib.kodiutils import exec_build_in

        plugin_url = Router.get_url(url, **kwargs)
        debug('Router.play: {}'.format(plugin_url))
        exec_build_in('PlayMedia({})'.format(plugin_url))

    @staticmethod
    def run_plugin(url, **kwargs):
        """
        Spusti plugin v pozadí (bez navigácie UI)

        Args:
            url: Plugin URL alebo relatívna URL
            **kwargs: Ďalšie parametre

        Example:
            Router.run_plugin('/action', action='mark_watched', id='123')
        """
        from resources.lib.kodiutils import run_plugin

        plugin_url = Router.get_url(url, **kwargs)
        debug('Router.run_plugin: {}'.format(plugin_url))
        run_plugin(plugin_url)
