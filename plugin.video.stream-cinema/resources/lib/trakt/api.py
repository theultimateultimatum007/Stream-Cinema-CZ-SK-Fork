# -*- coding: utf-8 -*-
"""
Trakt API wrapper - high-level API pre Trakt.tv endpointy
"""

from typing import Optional, Dict, List, Any
from datetime import datetime

from resources.lib.common.logger import debug


class AuthApi:
    """OAuth autentifikačné endpointy"""

    def __init__(self, http_client):
        self.http = http_client

    def device_code(self, client_id: str) -> Optional[Dict[str, Any]]:
        """
        Získa device code pre OAuth device flow

        Args:
            client_id: Trakt API client ID

        Returns:
            Dict s device_code, user_code, verification_url, expires_in, interval
        """
        data = {'client_id': client_id}
        return self.http.post('/oauth/device/code', data, authenticated=False)

    def device_token(self,
                     device_code: str,
                     client_id: str,
                     client_secret: str) -> Optional[Dict[str, Any]]:
        """
        Vymení device code za access token

        Args:
            device_code: Device code z device_code()
            client_id: Trakt API client ID
            client_secret: Trakt API client secret

        Returns:
            Dict s access_token, refresh_token, expires_in, created_at, token_type, scope
        """
        data = {
            'code': device_code,
            'client_id': client_id,
            'client_secret': client_secret
        }
        return self.http.post('/oauth/device/token', data, authenticated=False)


class SyncApi:
    """Sync endpointy pre watched history a playback"""

    def __init__(self, http_client):
        self.http = http_client

    def last_activities(self) -> Optional[Dict[str, Any]]:
        """GET /sync/last_activities - Posledné aktivity používateľa"""
        return self.http.get('/sync/last_activities')

    def watched_shows(self, extended: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        """GET /sync/watched/shows - Sledované seriály"""
        params = {'extended': extended} if extended else None
        return self.http.get('/sync/watched/shows', params)

    def watched_movies(self, extended: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        """GET /sync/watched/movies - Sledované filmy"""
        params = {'extended': extended} if extended else None
        return self.http.get('/sync/watched/movies', params)

    def playback_movies(self) -> Optional[List[Dict[str, Any]]]:
        """GET /sync/playback/movies - Nedopozerané filmy (in progress)"""
        return self.http.get('/sync/playback/movies')

    def playback_episodes(self) -> Optional[List[Dict[str, Any]]]:
        """GET /sync/playback/episodes - Nedopozerané epizódy (in progress)"""
        return self.http.get('/sync/playback/episodes')

    def add_to_history(self, items: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        POST /sync/history - Pridá položky do watch history

        Args:
            items: Dict s movies alebo shows/episodes na pridanie
                   Formát: {'movies': [...], 'shows': [...], 'episodes': [...]}

        Returns:
            Dict s added/not_found counts
        """
        return self.http.post('/sync/history', items)

    def remove_from_history(self, items: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """POST /sync/history/remove - Odstráni položky z watch history"""
        return self.http.post('/sync/history/remove', items)

    def history_shows(self,
                      start_at: Optional[datetime] = None,
                      end_at: Optional[datetime] = None,
                      page: int = 1,
                      limit: int = 50) -> Optional[List[Dict[str, Any]]]:
        """
        GET /sync/history/shows - História sledovaných seriálov

        Args:
            start_at: Začiatok obdobia (None = všetko)
            end_at: Koniec obdobia (None = po súčasnosť)
            page: Číslo stránky
            limit: Počet položiek na stránku

        Returns:
            List history záznamov
        """
        params = {'page': page, 'limit': limit, 'type': 'shows'}
        if start_at:
            params['start_at'] = start_at.isoformat()
        if end_at:
            params['end_at'] = end_at.isoformat()

        return self.http.get('/sync/history', params)

    def history_movies(self,
                       start_at: Optional[datetime] = None,
                       end_at: Optional[datetime] = None,
                       page: int = 1,
                       limit: int = 50) -> Optional[List[Dict[str, Any]]]:
        """GET /sync/history/movies - História sledovaných filmov"""
        params = {'page': page, 'limit': limit, 'type': 'movies'}
        if start_at:
            params['start_at'] = start_at.isoformat()
        if end_at:
            params['end_at'] = end_at.isoformat()

        return self.http.get('/sync/history', params)


class UsersApi:
    """User profile a lists endpointy"""

    def __init__(self, http_client):
        self.http = http_client

    def settings(self) -> Optional[Dict[str, Any]]:
        """GET /users/settings - Nastavenia aktuálneho používateľa"""
        return self.http.get('/users/settings')

    def lists(self, username: str = 'me') -> Optional[List[Dict[str, Any]]]:
        """GET /users/{username}/lists - Zoznamy používateľa"""
        return self.http.get(f'/users/{username}/lists')

    def list_items(self, username: str, list_id: str) -> Optional[List[Dict[str, Any]]]:
        """GET /users/{username}/lists/{id}/items - Položky v zozname"""
        return self.http.get(f'/users/{username}/lists/{list_id}/items')

    def watchlist(self, username: str = 'me') -> Optional[List[Dict[str, Any]]]:
        """GET /users/{username}/watchlist - Watchlist používateľa"""
        return self.http.get(f'/users/{username}/watchlist')

    def friends(self, username: str = 'me') -> Optional[List[Dict[str, Any]]]:
        """GET /users/{username}/friends - Priatelia používateľa"""
        return self.http.get(f'/users/{username}/friends')

    def following(self, username: str = 'me') -> Optional[List[Dict[str, Any]]]:
        """GET /users/{username}/following - Sledované osoby"""
        return self.http.get(f'/users/{username}/following')


class ShowsApi:
    """TV shows endpointy"""

    def __init__(self, http_client):
        self.http = http_client

    def season(self, show_id: int, season_number: int) -> Optional[List[Dict[str, Any]]]:
        """
        GET /shows/{id}/seasons/{season} - Info o sezóne

        Returns:
            List epizód v sezóne
        """
        return self.http.get(f'/shows/{show_id}/seasons/{season_number}')

    def episode(self,
                show_id: int,
                season: int,
                episode: int,
                extended: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        GET /shows/{id}/seasons/{season}/episodes/{episode} - Info o epizóde

        Args:
            show_id: Trakt show ID
            season: Číslo sezóny
            episode: Číslo epizódy
            extended: 'full' pre viac info

        Returns:
            Dict s episode info
        """
        params = {'extended': extended} if extended else None
        return self.http.get(f'/shows/{show_id}/seasons/{season}/episodes/{episode}', params)


class ScrobbleApi:
    """Scrobble endpointy pre tracking playback"""

    def __init__(self, http_client):
        self.http = http_client

    def start(self,
              item_type: str,
              item_id: int,
              progress: float,
              **kwargs) -> Optional[Dict[str, Any]]:
        """
        POST /scrobble/start - Začne scrobble

        Args:
            item_type: 'movie' alebo 'episode'
            item_id: Trakt ID
            progress: Progress v percentách (0-100)
            **kwargs: Dodatočné data (napr. season, episode pre epizódy)

        Returns:
            Dict s scrobble info
        """
        data = {
            item_type: {'ids': {'trakt': item_id}},
            'progress': float(progress)
        }
        data.update(kwargs)
        return self.http.post('/scrobble/start', data)

    def pause(self,
              item_type: str,
              item_id: int,
              progress: float,
              **kwargs) -> Optional[Dict[str, Any]]:
        """POST /scrobble/pause - Pozastaví scrobble"""
        data = {
            item_type: {'ids': {'trakt': item_id}},
            'progress': float(progress)
        }
        data.update(kwargs)
        return self.http.post('/scrobble/pause', data)

    def stop(self,
             item_type: str,
             item_id: int,
             progress: float,
             **kwargs) -> Optional[Dict[str, Any]]:
        """POST /scrobble/stop - Zastaví scrobble"""
        data = {
            item_type: {'ids': {'trakt': item_id}},
            'progress': float(progress)
        }
        data.update(kwargs)
        return self.http.post('/scrobble/stop', data)


class TraktApi:
    """
    Hlavná Trakt API trieda - agreguje všetky API moduly
    """

    def __init__(self, http_client):
        """
        Args:
            http_client: TraktHttpClient inštancia
        """
        self.http = http_client
        self.auth = AuthApi(http_client)
        self.sync = SyncApi(http_client)
        self.users = UsersApi(http_client)
        self.shows = ShowsApi(http_client)
        self.scrobble = ScrobbleApi(http_client)
