# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals

import requests
import xbmc
from email.utils import parsedate_to_datetime

from resources.lib.constants import HTTP
from resources.lib.kodiutils import get_system_platform, get_app_name, addon
from resources.lib.language import get_language_code
from resources.lib.common.logger import info, debug

SYSTEM_BUILD_VERSION = xbmc.getInfoLabel("System.BuildVersion")
SYSTEM_VERSION = int(SYSTEM_BUILD_VERSION.split(".")[0])
SYSTEM_LANG_CODE = get_language_code()


def user_agent(system=True):
    if system is False or not hasattr(xbmc, 'getUserAgent'):

        version = SYSTEM_BUILD_VERSION
        sp = version.find(' ')
        if sp > 0:
            version = version[:sp]

        platform = get_system_platform()
        app = get_app_name()

        if platform == 'linux':
            useragent = '{}/{} (X11; U; Linux i686)'
        elif platform == 'android':
            useragent = '{}/{} (Linux; Android)'
        elif platform == 'windows':
            useragent = '{}/{} (Windows; U; Windows NT)'
        elif platform == 'ios':
            useragent = '{}/{} (iPhone; CPU iPhone OS like Mac OS X)'
        elif platform == 'osx':
            useragent = '{}/{} (Macintosh; Intel Mac OS X)'
        else:
            useragent = '{}/{} (X11; U; Unknown i686)'
        useragent = useragent.format(app, version)
    else:
        useragent = xbmc.getUserAgent()

    return '{0} ({1}; ver{2})'.format(
        useragent,
        SYSTEM_LANG_CODE,
        addon.getAddonInfo('version')
    )


def get_app_log():
    return get_app_name()


class Http:
    @staticmethod
    def request(method, url, timeout=HTTP.TIMEOUT, **kwargs):
        # info('URL {}'.format(url))
        ret = Http.req().request(
            method=method,
            url=url,
            timeout=timeout,
            **kwargs
        )
        # info('url req head: {}'.format(ret.request.headers))
        # info('url res head: {}'.format(ret.headers))
        debug('Http url: {}'.format(ret.url))
        try:
            ret.raise_for_status()
        except requests.exceptions.HTTPError as e:
            ret = e.response

        return ret

    @staticmethod
    def req():
        return requests

    @staticmethod
    def get(url, **kwargs):
        return Http.request(HTTP.GET, url, **kwargs)

    @staticmethod
    def post(url, **kwargs):
        return Http.request(HTTP.POST, url, **kwargs)

    @staticmethod
    def head(url, **kwargs):
        return Http.request(HTTP.HEAD, url, **kwargs)

    @staticmethod
    def delete(url, **kwargs):
        return Http.request(HTTP.DELETE, url, **kwargs)

    @staticmethod
    def put(url, **kwargs):
        return Http.request(HTTP.PUT, url, **kwargs)

    @staticmethod
    def patch(url, **kwargs):
        return Http.request(HTTP.PATCH, url, **kwargs)

    @staticmethod
    def get_newer(url, current_time=None, **kwargs):
        """
        Stiahne obsah len ak je novší ako current_time

        Args:
            url: URL adresa na stiahnutie
            current_time: datetime objekt pre porovnanie (optional)
            **kwargs: Ďalšie argumenty pre get() request

        Returns:
            tuple: (response, last_modified_datetime) alebo (None, last_modified_datetime)
                   - response je None ak je obsah starší ako current_time
                   - last_modified_datetime je None ak server neposkytuje Last-Modified header

        Použitie:
            response, mod_time = Http.get_newer(url, last_download_time)
            if response:
                # Máme nový obsah
                file_put_contents(path, response.content)
            else:
                # Obsah je starý, nepotrebujeme ho sťahovať
        """
        try:
            # HEAD request pre získanie Last-Modified headeru
            debug('Http.get_newer: Checking Last-Modified for {}'.format(url))
            head_response = Http.head(url, **kwargs)

            # Ak server neposkytuje Last-Modified header, stiahni normálne
            if 'last-modified' not in head_response.headers:
                debug('Http.get_newer: No Last-Modified header, downloading normally')
                return Http.get(url, **kwargs), None

            # Parse Last-Modified headeru
            url_time_str = head_response.headers['last-modified']
            url_datetime = parsedate_to_datetime(url_time_str)
            debug('Http.get_newer: Server Last-Modified: {}'.format(url_datetime))

            # Ak nemáme current_time alebo je obsah novší, stiahni ho
            if not current_time:
                debug('Http.get_newer: No current_time provided, downloading')
                return Http.get(url, **kwargs), url_datetime

            if url_datetime > current_time:
                debug('Http.get_newer: Content is newer ({} > {}), downloading'.format(
                    url_datetime, current_time))
                return Http.get(url, **kwargs), url_datetime

            # Obsah je starý, vráť None
            debug('Http.get_newer: Content is not newer ({} <= {}), skipping download'.format(
                url_datetime, current_time))
            return None, url_datetime

        except Exception as e:
            debug('Http.get_newer: Error - {}, falling back to normal GET'.format(e))
            # Pri chybe stiahni normálne
            return Http.get(url, **kwargs), None


class Sess(Http):
    @staticmethod
    def req():
        return requests.Session

