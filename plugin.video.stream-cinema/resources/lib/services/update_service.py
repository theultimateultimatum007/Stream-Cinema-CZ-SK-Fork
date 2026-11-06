# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals

from resources.lib.services.timer_service import TimerService
from resources.lib.constants import ADDON, BASE_URL, API_VERSION
from resources.lib.common.logger import debug
from resources.lib.system import Http
from resources.lib.kodiutils import notify

try:
    from packaging import version as pkg_version
except ImportError:
    # Fallback pre staršie KODI verzie bez packaging library
    pkg_version = None


class UpdateService(TimerService):
    """
    Service pre automatickú kontrolu aktualizácií addonu

    Funkcie:
    - Automatická kontrola každú hodinu
    - Porovnávanie verzií (semantic versioning)
    - Notifikácia používateľa o dostupnej aktualizácii
    - Hotfix detection
    - Changelog zobrazenie (voliteľné)
    """

    SERVICE_NAME = "UpdateService"
    DEFAULT_INTERVAL = 3600  # Kontroluj každú hodinu

    def __init__(self):
        super(UpdateService, self).__init__()
        self.current_version = ADDON.getAddonInfo('version')
        self.latest_version = None
        self.update_url = None
        debug('UpdateService: Initialized with current version {}'.format(self.current_version))

    def run(self):
        """Skontroluje dostupnosť aktualizácie"""
        try:
            debug('UpdateService: Checking for updates...')
            latest_version, update_info = self._get_latest_version()

            if not latest_version:
                debug('UpdateService: Could not retrieve latest version')
                return

            self.latest_version = latest_version
            debug('UpdateService: Current: {} | Latest: {}'.format(
                self.current_version, self.latest_version))

            if self._is_newer(self.latest_version, self.current_version):
                debug('UpdateService: New version available: {}'.format(self.latest_version))
                self._notify_update(self.latest_version, update_info)
            else:
                debug('UpdateService: No update available (up to date)')

        except Exception as e:
            debug('UpdateService: Error checking for updates: {}'.format(e))

    def _get_latest_version(self):
        """
        Získa najnovšiu verziu z API

        Returns:
            tuple: (version_string, update_info_dict) alebo (None, None)
        """
        try:
            # API endpoint pre verziu (príklad - upraviť podľa skutočného API)
            api_url = '{}/version?api={}'.format(BASE_URL, API_VERSION)
            debug('UpdateService: Fetching version from {}'.format(api_url))

            response = Http.get(api_url, timeout=5)

            if response.status_code == 200:
                data = response.json()

                # Formát očakávanej odpovede:
                # {
                #     "version": "2.0.5",
                #     "changelog": "- Fix bug\n- Add feature",
                #     "critical": false,
                #     "download_url": "https://..."
                # }

                version_str = data.get('version')
                update_info = {
                    'changelog': data.get('changelog', ''),
                    'critical': data.get('critical', False),
                    'download_url': data.get('download_url', ''),
                }

                debug('UpdateService: Retrieved version {}'.format(version_str))
                return version_str, update_info

            else:
                debug('UpdateService: API returned status {}'.format(response.status_code))
                return None, None

        except Exception as e:
            debug('UpdateService: Error fetching version: {}'.format(e))
            return None, None

    def _is_newer(self, latest, current):
        """
        Porovná verzie (semantic versioning)

        Args:
            latest: Najnovšia verzia (string)
            current: Aktuálna verzia (string)

        Returns:
            bool: True ak je latest novšia

        Poznámka:
            - Podporuje formát X.Y.Z (napr. 2.0.5)
            - Používa packaging library ak je dostupná
            - Fallback na jednoduchú string comparison
        """
        try:
            if pkg_version:
                # Použij packaging library pre správne semantic versioning
                return pkg_version.parse(latest) > pkg_version.parse(current)
            else:
                # Fallback: Porovnaj ako tuples (2, 0, 5) > (2, 0, 4)
                latest_parts = tuple(int(x) for x in latest.split('.'))
                current_parts = tuple(int(x) for x in current.split('.'))
                return latest_parts > current_parts

        except Exception as e:
            debug('UpdateService: Error comparing versions: {}'.format(e))
            # Pri chybe použij string comparison (nie úplne správne ale bezpečné)
            return latest > current

    def _notify_update(self, version, update_info):
        """
        Upozorní používateľa na dostupnú aktualizáciu

        Args:
            version: Nová verzia (string)
            update_info: Dict s informáciami o aktualizácii
        """
        try:
            # Priprav správu
            title = 'Aktualizácia k dispozícii'
            message = 'Verzia {} je dostupná'.format(version)

            # Ak je critical update, zmeň tón správy
            if update_info.get('critical'):
                title = 'DÔLEŽITÁ AKTUALIZÁCIA'
                message = 'Verzia {} - Kritická aktualizácia!'.format(version)
                debug('UpdateService: CRITICAL update detected!')

            # Zobraz notifikáciu
            notify(title, message, time=5000)
            debug('UpdateService: User notified about version {}'.format(version))

            # Voliteľne: Zobraz changelog (implementovať podľa potreby)
            # if update_info.get('changelog'):
            #     self._show_changelog(update_info['changelog'])

        except Exception as e:
            debug('UpdateService: Error showing notification: {}'.format(e))

    def _show_changelog(self, changelog):
        """
        Zobrazí changelog v dialógu (voliteľné)

        Args:
            changelog: Text changelogu
        """
        try:
            from resources.lib.gui.dialog import dok
            dok('Changelog', changelog)
        except Exception as e:
            debug('UpdateService: Error showing changelog: {}'.format(e))

    def check_now(self):
        """
        Okamžitá kontrola aktualizácie (bez čakania na interval)

        Použitie:
            update_service = UpdateService()
            update_service.check_now()
        """
        debug('UpdateService: Manual update check triggered')
        self.last_run = None  # Reset last_run aby sa spustilo okamžite
        self.start()


# Singleton instance
update_service = UpdateService()
