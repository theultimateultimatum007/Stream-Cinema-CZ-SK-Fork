# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals

import traceback
from time import time

from resources.lib.common.logger import debug
from resources.lib.kodiutils import get_setting_as_int, set_setting, get_setting_as_bool


class TimerService:
    """
    Base class pre všetky services s timer funkcionalitou

    Poskytuje:
    - Interval-based execution
    - Settings persistence pre last_run
    - Monitor/Player state checking
    - Force run capability
    - Enable/disable via settings
    - Automatic error handling
    """

    SERVICE_NAME = "BaseService"
    DEFAULT_INTERVAL = 3600  # sekundy (1 hodina)
    SETTING_ENABLED = None  # Napr. 'system.nextep.enabled'
    SETTING_LAST_RUN = None  # Napr. 'system.nextep.last_run'
    CHECK_PLAYER_STATE = True  # Ak True, service sa nespustí pri prehrávaní

    def __init__(self):
        self.interval = self.DEFAULT_INTERVAL
        self.is_running = False

        # Načítaj last_run zo settings (ak je definované)
        if self.SETTING_LAST_RUN:
            last_run = get_setting_as_int(self.SETTING_LAST_RUN)
            self.last_run = last_run if last_run is not None else time()
        else:
            self.last_run = time()

    def is_enabled(self):
        """
        Skontroluje či je service povolená v settings
        Override v potomkoch pre vlastnú logiku
        """
        if self.SETTING_ENABLED:
            return get_setting_as_bool(self.SETTING_ENABLED)
        return True  # Default: enabled

    def can_run(self, monitor=None, player=None):
        """
        Skontroluje všetky podmienky pre spustenie service

        Args:
            monitor: Monitor instance (voliteľné)
            player: Player instance (voliteľné)

        Returns:
            bool: True ak service môže bežať
        """
        # 1. Check if enabled
        if not self.is_enabled():
            return False

        # 2. Check if already running
        if self.is_running:
            return False

        # 3. Check monitor abort (ak je poskytnutý)
        if monitor and monitor.abortRequested():
            return False

        # 4. Check player state (ak je required)
        if self.CHECK_PLAYER_STATE and player and player.isPlayback():
            return False

        # 5. Check monitor.can_check() (ak je poskytnutý)
        if monitor and hasattr(monitor, 'can_check') and not monitor.can_check():
            return False

        return True

    def should_run(self, force=False):
        """
        Skontroluje či je čas spustiť service na základe intervalu

        Args:
            force: Ak True, ignoruje interval check

        Returns:
            bool: True ak by service mala bežať
        """
        if force:
            return True

        if self.last_run is None:
            return True

        now = time()
        elapsed = now - self.last_run

        return elapsed >= self.interval

    def start(self, force=False, monitor=None, player=None):
        """
        Spustí service s automatickým error handlingom

        Args:
            force: Ak True, ignoruje interval check
            monitor: Monitor instance pre abort checking
            player: Player instance pre playback checking

        Returns:
            bool: True ak service úspešne dobehla
        """
        # Check preconditions
        if not self.can_run(monitor=monitor, player=player):
            return False

        if not self.should_run(force=force):
            return False

        self.is_running = True
        success = False

        try:
            debug('{}: Starting...'.format(self.SERVICE_NAME))

            # Volaj run() metódu
            result = self.run()

            # Update last_run timestamp
            self.last_run = time()

            # Persist do settings (ak je definované)
            if self.SETTING_LAST_RUN:
                set_setting(self.SETTING_LAST_RUN, '{}'.format(int(self.last_run)))

            debug('{}: Finished successfully'.format(self.SERVICE_NAME))
            success = True

            return result if result is not None else success

        except Exception as e:
            debug('{}: Error - {}'.format(self.SERVICE_NAME, e))
            debug('{}: Traceback - {}'.format(self.SERVICE_NAME, traceback.format_exc()))
            return False

        finally:
            self.is_running = False

    def run(self):
        """
        Main service logic - MUSÍ byť overridnutý v potomkoch

        Returns:
            bool alebo None: True/False pre success/failure, None = ignore
        """
        raise NotImplementedError('{}: run() method must be implemented'.format(self.SERVICE_NAME))

    def reset_timer(self):
        """Reset last_run timer - užitočné pri manuálnom triggerovaní"""
        self.last_run = time()
        if self.SETTING_LAST_RUN:
            set_setting(self.SETTING_LAST_RUN, '{}'.format(int(self.last_run)))
