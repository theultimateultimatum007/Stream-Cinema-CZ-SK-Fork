# -*- coding: utf-8 -*-
"""
Trakt HTTP klient - wrapper nad system.Http s Trakt-špecifickou logikou
"""

from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, asdict
import threading
import time
from datetime import datetime, timedelta, timezone

from resources.lib.system import Http
from resources.lib.common.logger import debug
from resources.lib.gui.dialog import dnotify, dprogress
from resources.lib.constants import ADDON
import xbmcgui


@dataclass
class TraktToken:
    """Trakt OAuth token štruktúra"""
    access_token: str
    refresh_token: str
    expires_in: int
    created_at: int
    token_type: str = 'bearer'
    scope: str = 'public'


class TraktHttpClient:
    """
    HTTP klient pre Trakt API s automatickou autentifikáciou a token refresh.
    Používa existujúci Http klient zo system.py.
    """

    BASE_URL = 'https://api.trakt.tv'
    API_VERSION = '2'

    def __init__(self,
                 client_id: str,
                 client_secret: str,
                 token_callback: Callable[[], Optional[TraktToken]],
                 save_token_callback: Callable[[TraktToken], None],
                 max_retries: int = 3,
                 retry_delay: float = 1.0):
        """
        Args:
            client_id: Trakt API client ID
            client_secret: Trakt API client secret
            token_callback: Funkcia ktorá vráti aktuálny TraktToken alebo None
            save_token_callback: Funkcia na uloženie nového tokenu
            max_retries: Maximálny počet pokusov pre server errors
            retry_delay: Základné oneskorenie pre retry (sekundy)
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_callback = token_callback
        self.save_token_callback = save_token_callback
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._token_lock = threading.Lock()
        self._refreshing = False
        self._cached_token: Optional[TraktToken] = None  # In-memory cache

    def set_token(self, token: TraktToken) -> None:
        """
        Nastaví token do in-memory cache

        Args:
            token: TraktToken na uloženie do cache
        """
        self._cached_token = token
        debug('TRAKT: Token cached in memory')

    def get(self,
            endpoint: str,
            params: Optional[Dict[str, Any]] = None,
            authenticated: bool = True,
            _retry_count: int = 0) -> Optional[Dict[str, Any]]:
        """
        GET request na Trakt API

        Args:
            endpoint: API endpoint (napr. '/sync/watched/shows')
            params: Query parametre
            authenticated: Či požiadavka vyžaduje autentifikáciu
            _retry_count: Interný počítadlo retry pokusov

        Returns:
            JSON response ako dict alebo None pri chybe
        """
        url = self.BASE_URL + endpoint
        headers = self._build_headers(authenticated)

        try:
            response = Http.get(url, headers=headers, params=params)
            return self._handle_response(
                response,
                lambda: self.get(endpoint, params, authenticated, _retry_count + 1),
                _retry_count
            )
        except Exception as e:
            debug(f'TRAKT GET {endpoint} error: {e}')
            return None

    def post(self,
             endpoint: str,
             data: Optional[Dict[str, Any]] = None,
             authenticated: bool = True,
             _retry_count: int = 0) -> Optional[Dict[str, Any]]:
        """
        POST request na Trakt API

        Args:
            endpoint: API endpoint
            data: JSON data na odoslanie
            authenticated: Či požiadavka vyžaduje autentifikáciu
            _retry_count: Interný počítadlo retry pokusov

        Returns:
            JSON response ako dict alebo None pri chybe
        """
        url = self.BASE_URL + endpoint
        headers = self._build_headers(authenticated)

        try:
            response = Http.post(url, headers=headers, json=data)
            return self._handle_response(
                response,
                lambda: self.post(endpoint, data, authenticated, _retry_count + 1),
                _retry_count
            )
        except Exception as e:
            debug(f'TRAKT POST {endpoint} error: {e}')
            return None

    def put(self,
            endpoint: str,
            data: Optional[Dict[str, Any]] = None,
            authenticated: bool = True,
            _retry_count: int = 0) -> Optional[Dict[str, Any]]:
        """PUT request na Trakt API"""
        url = self.BASE_URL + endpoint
        headers = self._build_headers(authenticated)

        try:
            response = Http.put(url, headers=headers, json=data)
            return self._handle_response(
                response,
                lambda: self.put(endpoint, data, authenticated, _retry_count + 1),
                _retry_count
            )
        except Exception as e:
            debug(f'TRAKT PUT {endpoint} error: {e}')
            return None

    def delete(self,
               endpoint: str,
               authenticated: bool = True,
               _retry_count: int = 0) -> Optional[Dict[str, Any]]:
        """DELETE request na Trakt API"""
        url = self.BASE_URL + endpoint
        headers = self._build_headers(authenticated)

        try:
            response = Http.delete(url, headers=headers)
            return self._handle_response(
                response,
                lambda: self.delete(endpoint, authenticated, _retry_count + 1),
                _retry_count
            )
        except Exception as e:
            debug(f'TRAKT DELETE {endpoint} error: {e}')
            return None

    def _build_headers(self, authenticated: bool = True) -> Dict[str, str]:
        """
        Vytvorí HTTP hlavičky pre Trakt API request

        Args:
            authenticated: Či pridať Authorization header

        Returns:
            Dict s hlavičkami
        """
        headers = {
            'Content-Type': 'application/json',
            'trakt-api-version': self.API_VERSION,
            'trakt-api-key': self.client_id
        }

        if authenticated:
            # Skús použiť cached token, inak zavolaj callback
            token = self._cached_token if self._cached_token else self.token_callback()

            if token:
                # Preventívny token refresh ak expiruje čoskoro
                if self._is_token_expiring(token):
                    debug('TRAKT: Token expiruje čoskoro, preventívny refresh')
                    self._refresh_token()
                    # Po refreshi použijeme cached token
                    token = self._cached_token

                if token:
                    headers['Authorization'] = f'Bearer {token.access_token}'

        return headers

    def _handle_response(self,
                        response,
                        retry_func: Callable,
                        retry_count: int = 0) -> Optional[Dict[str, Any]]:
        """
        Spracuje HTTP response a handluje rôzne status kódy

        Args:
            response: requests Response objekt
            retry_func: Funkcia na retry request po token refresh
            retry_count: Aktuálny počet pokusov

        Returns:
            JSON response ako dict alebo None
        """
        debug(f'TRAKT: HTTP {response.status_code} {response.url}')

        # Success
        if 200 <= response.status_code < 300:
            try:
                return response.json() if response.content else {}
            except Exception as e:
                debug(f'TRAKT: JSON parsing error: {e}')
                return None

        # Unauthorized - skús token refresh a retry
        if response.status_code == 401:
            debug('TRAKT: HTTP 401 Unauthorized, trying token refresh')
            if self._refresh_token():
                debug('TRAKT: Token refreshed, retrying request')
                return retry_func()  # Retry pôvodný request
            else:
                debug('TRAKT: Token refresh failed')
                return None

        # Not found
        if response.status_code == 404:
            debug('TRAKT: HTTP 404 Not Found')
            return None

        # Rate limit - vrátime error objekt bez blocking dialógu
        # TraktQueueService to spracuje na pozadí
        if response.status_code == 429:
            # Skús získať Retry-After header (môže byť v sekundách alebo HTTP date)
            retry_after = response.headers.get('Retry-After')
            if retry_after and retry_after.isdigit():
                wait_time = int(retry_after)
                debug(f'TRAKT: HTTP 429 Rate Limited, server žiada čakať {wait_time}s')
            else:
                wait_time = 60  # Default 60s ak server neposkytne Retry-After
                debug(f'TRAKT: HTTP 429 Rate Limited, default wait {wait_time}s')

            # Vrátime špeciálny objekt pre TraktQueueService
            return {
                'rate_limited': True,
                'retry_after': wait_time,
                'status_code': 429
            }

        # Server error - vrátime None, TraktQueueService to zretryuje
        if response.status_code >= 500:
            debug(f'TRAKT: HTTP {response.status_code} Server Error')
            return None

        # Iné chyby
        debug(f'TRAKT: HTTP {response.status_code} {response.text[:200]}')
        return None

    def _refresh_token(self) -> bool:
        """
        Refreshne OAuth token

        Returns:
            True ak refresh bol úspešný, inak False
        """
        with self._token_lock:
            # Double-check pattern - možno iný thread už refreshol
            if self._refreshing:
                debug('TRAKT: Token refresh už prebieha, čakám...')
                time.sleep(0.5)
                return True

            self._refreshing = True

            try:
                token = self.token_callback()
                if not token:
                    debug('TRAKT: Žiaden token na refresh')
                    return False

                debug('TRAKT: Refreshing token...')

                # POST na /oauth/token
                url = f'{self.BASE_URL}/oauth/token'
                data = {
                    'refresh_token': token.refresh_token,
                    'client_id': self.client_id,
                    'client_secret': self.client_secret,
                    'redirect_uri': 'urn:ietf:wg:oauth:2.0:oob',
                    'grant_type': 'refresh_token'
                }

                headers = {
                    'Content-Type': 'application/json',
                    'trakt-api-version': self.API_VERSION,
                    'trakt-api-key': self.client_id
                }

                response = Http.post(url, headers=headers, json=data)

                if response.status_code == 200:
                    new_token_data = response.json()
                    new_token = TraktToken(**new_token_data)

                    # Ulož nový token do cache a do storage
                    self._cached_token = new_token
                    self.save_token_callback(new_token)
                    debug('TRAKT: Token successfully refreshed')
                    return True
                elif response.status_code == 400:
                    # HTTP 400 = invalid_grant - refresh token je neplatný/expirovaný
                    try:
                        error_data = response.json()
                        error_type = error_data.get('error', 'unknown')
                        error_desc = error_data.get('error_description', 'Unknown error')
                        debug(f'TRAKT: Token refresh failed - {error_type}: {error_desc}')

                        if error_type == 'invalid_grant':
                            # Refresh token je neplatný - vymažeme ho a notifikujeme používateľa
                            debug('TRAKT: Refresh token is invalid/expired, clearing authorization')
                            self._cached_token = None
                            # Zavolaj callback na vymazanie tokenu
                            from resources.lib.kodiutils import set_setting
                            set_setting('trakt.authorization', '')

                            # Zobraz notifikáciu používateľovi
                            dnotify('Trakt.tv',
                                   ADDON.getLocalizedString(30321),  # "Autorizácia expirovala, prihláste sa znova"
                                   xbmcgui.NOTIFICATION_WARNING,
                                   8000)
                    except Exception as e:
                        debug(f'TRAKT: Error parsing 400 response: {e}')

                    return False
                else:
                    debug(f'TRAKT: Token refresh failed: HTTP {response.status_code}')
                    try:
                        debug(f'TRAKT: Response body: {response.text[:500]}')
                    except:
                        pass
                    return False

            except Exception as e:
                debug(f'TRAKT: Token refresh exception: {e}')
                return False
            finally:
                self._refreshing = False

    def _is_token_expiring(self, token: TraktToken) -> bool:
        """
        Kontroluje či token čoskoro expiruje (< 2 dni)

        Args:
            token: TraktToken na kontrolu

        Returns:
            True ak token expiruje o menej ako 2 dni
        """
        expires_at = datetime.fromtimestamp(token.created_at + token.expires_in, tz=timezone.utc)
        threshold = datetime.now(timezone.utc) + timedelta(days=2)

        # Debug log pre sledovanie expirácie
        remaining = expires_at - datetime.now(timezone.utc)
        debug('TRAKT: Token expires in {} days, {} hours'.format(
            remaining.days, remaining.seconds // 3600))

        return expires_at < threshold

    def _wait_with_progress(self, wait_time: int, reason: str) -> bool:
        """
        Počká zadaný čas s progress dialogom a odpočítavaním

        Args:
            wait_time: Počet sekúnd na čakanie
            reason: Dôvod čakania ('rate_limit' alebo 'server_error')

        Returns:
            True ak čakanie prebehlo úspešne, False ak používateľ zrušil
        """
        # Texty podľa dôvodu
        if reason == 'rate_limit':
            title = ADDON.getLocalizedString(30317)  # "Trakt.tv Rate Limit"
            message = ADDON.getLocalizedString(30318)  # "Rate limit dosiahnutý, čakám {seconds}s..."
        else:  # server_error
            title = ADDON.getLocalizedString(30319)  # "Trakt.tv Server Error"
            message = ADDON.getLocalizedString(30320)  # "Chyba servera, opakujem za {seconds}s..."

        dialog = dprogress()
        dialog.create(title, message.format(seconds=wait_time))

        start_time = time.time()
        while True:
            elapsed = time.time() - start_time
            remaining = wait_time - elapsed

            if remaining <= 0:
                dialog.close()
                return True

            # Check if user canceled
            if dialog.iscanceled():
                debug('TRAKT: User canceled retry wait')
                dialog.close()
                return False

            # Update progress
            progress = int(elapsed / wait_time * 100)
            dialog.update(progress, message.format(seconds=int(remaining)))

            time.sleep(0.5)  # Update každých 0.5s
