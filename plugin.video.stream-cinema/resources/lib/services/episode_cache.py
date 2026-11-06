# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals

from time import time
from resources.lib.common.storage import Storage
from resources.lib.common.logger import debug


class EpisodeCache:
    """
    Cache pre epizódy a sezóny seriálov

    Ukladá zoznam epizód pre každú sezónu, aby sa nemuselo volať API
    pre zistenie ďalšej epizódy (Up Next funkcionalita)

    Cache je rozdelená podľa filter nastavení (dub/tit/all), pretože rôzne
    nastavenia zobrazujú rôzne epizódy

    Formát:
    {
        'show_123_dub1': {  # _dub1 = filter suffix (dub=1)
            'seasons': [1, 2, 3, 4, 5, ...],  # Zoznam čísel sezón
            'season_1': {
                'episodes': [1, 2, 3, 4, 5, ...],  # Zoznam čísel epizód
                'timestamp': 1234567890,
                'count': 5
            },
            'season_2': {...}
        }
    }
    """

    CACHE_EXPIRY = 86400  # 24 hodín

    def __init__(self):
        self.storage = Storage('episode_cache')
        debug('EpisodeCache: Initialized')

    def _get_filter_suffix(self):
        """
        Vytvorí suffix pre cache kľúč na základe aktuálnych filter nastavení

        Returns:
            str: Suffix ako '_dub1' alebo '_dub1_tit1' atď.
        """
        from resources.lib.kodiutils import get_setting_as_bool
        from resources.lib.api.sc import Sc

        suffix_parts = []

        # Dabing filter
        parental_control = Sc.parental_control_is_active()
        if get_setting_as_bool('stream.dubed') or (parental_control and get_setting_as_bool('parental.control.dubed')):
            suffix_parts.append('dub1')

        # Titulky filter
        if not parental_control and get_setting_as_bool('stream.dubed.titles'):
            suffix_parts.append('tit1')

        # Spojíme
        if suffix_parts:
            return '_' + '_'.join(suffix_parts)
        return ''

    def save_season_episodes(self, show_id, season, episodes, is_season_list=False):
        """
        Uloží zoznam epizód pre danú sezónu, alebo zoznam sezón

        Args:
            show_id: ID seriálu (napr. '123' alebo 'breaking-bad')
            season: Číslo sezóny (int) alebo None ak je is_season_list=True
            episodes: List čísel epizód [1, 2, 3, ...] alebo list objektov s 'episode'
            is_season_list: True ak episodes obsahuje sezóny namiesto epizód
        """
        try:
            # Pridaj filter suffix do kľúča
            filter_suffix = self._get_filter_suffix()
            show_key = 'show_{}{}'.format(show_id, filter_suffix)

            # Získaj aktuálne data pre show
            show_data = self.storage.get(show_key) or {}

            if is_season_list:
                # Ukladáme zoznam sezón
                season_numbers = []
                if episodes:  # episodes obsahuje sezóny
                    for s in episodes:
                        if isinstance(s, dict):
                            s_num = s.get('season') or s.get('number') or s.get('info', {}).get('season')
                            if s_num:
                                season_numbers.append(int(s_num))
                        elif isinstance(s, (int, str)):
                            season_numbers.append(int(s))

                # Zoraď sezóny
                season_numbers.sort()

                # Ulož zoznam sezón
                show_data['seasons'] = season_numbers
                show_data['seasons_timestamp'] = time()

                debug('EpisodeCache: Saved {} seasons for show={}{}'.format(
                    len(season_numbers), show_id, filter_suffix))

            else:
                # Ukladáme epizódy pre sezónu
                season_key = 'season_{}'.format(season)

                # Extrahuj čísla epizód
                episode_numbers = []
                if episodes:
                    for ep in episodes:
                        if isinstance(ep, dict):
                            # Ak je to dict, hľadaj 'episode' alebo 'number' kľúč
                            ep_num = ep.get('episode') or ep.get('number') or ep.get('info', {}).get('episode')
                            if ep_num:
                                episode_numbers.append(int(ep_num))
                        elif isinstance(ep, (int, str)):
                            # Ak je to už číslo
                            episode_numbers.append(int(ep))

                # Zoraď epizódy
                episode_numbers.sort()

                # Ulož season data
                show_data[season_key] = {
                    'episodes': episode_numbers,
                    'timestamp': time(),
                    'count': len(episode_numbers)
                }

                debug('EpisodeCache: Saved {} episodes for show={}{}, season={}'.format(
                    len(episode_numbers), show_id, filter_suffix, season))

            # Ulož do storage
            self.storage[show_key] = show_data

        except Exception as e:
            debug('EpisodeCache: Error saving episodes: {}'.format(e))

    def get_next_episode(self, show_id, season, episode, allow_lazy_load=True):
        """
        Vráti ďalšiu epizódu pre daný seriál/sezónu/epizódu

        Automaticky prechádza na ďalšiu sezónu ak je aktuálna sezóna dokončená.
        Použije zoznam sezón ak je dostupný.

        Args:
            show_id: ID seriálu
            season: Číslo sezóny (int)
            episode: Číslo epizódy (int)
            allow_lazy_load: Povoliť lazy loading z API (default: True)

        Returns:
            tuple: (season, episode) ďalšej epizódy alebo None ak neexistuje
        """
        try:
            # Pridaj filter suffix
            filter_suffix = self._get_filter_suffix()
            show_key = 'show_{}{}'.format(show_id, filter_suffix)
            season_key = 'season_{}'.format(season)

            # Získaj data pre show
            show_data = self.storage.get(show_key)
            if not show_data:
                debug('EpisodeCache: No cache for show={}{}'.format(show_id, filter_suffix))

                if not allow_lazy_load:
                    debug('EpisodeCache: Lazy loading DISABLED, returning None')
                    return None

                # LAZY LOAD: Cache pre show neexistuje vôbec, načítaj aktuálnu sezónu z API
                debug('EpisodeCache: Lazy loading cache for show {} (first time access)...'.format(show_id))
                from resources.lib.services.menu_cache_server import menu_cache_server
                season_url = '/FGet/{}/{}'.format(show_id, season)
                menu_cache_server._prepare_menu(season_url, episodes_only=True)

                # Skús znova načítať show_data
                show_data = self.storage.get(show_key)
                if not show_data:
                    debug('EpisodeCache: Failed to lazy load cache for show {}'.format(show_id))
                    return None

                debug('EpisodeCache: Lazy load successful for show {}'.format(show_id))

            # Získaj data pre sezónu
            season_data = show_data.get(season_key)
            if not season_data:
                debug('EpisodeCache: No cache for show={}{}, season={}'.format(show_id, filter_suffix, season))

                if not allow_lazy_load:
                    debug('EpisodeCache: Lazy loading DISABLED, returning None')
                    return None

                # LAZY LOAD: Cache pre aktuálnu sezónu neexistuje, načítaj ju z API
                debug('EpisodeCache: Lazy loading cache for current season {}...'.format(season))
                from resources.lib.services.menu_cache_server import menu_cache_server
                season_url = '/FGet/{}/{}'.format(show_id, season)
                # episodes_only=True → nebudeme vytvárať SCItem (len detekcia epizód)
                menu_cache_server._prepare_menu(season_url, episodes_only=True)

                # Skús znova načítať cache
                show_data = self.storage.get(show_key)
                if show_data:
                    season_data = show_data.get(season_key)

                if not season_data:
                    debug('EpisodeCache: Failed to lazy load cache for season {}'.format(season))
                    return None

                debug('EpisodeCache: Lazy load successful for season {}'.format(season))

            # Skontroluj expiráciu
            age = time() - season_data.get('timestamp', 0)
            if age > self.CACHE_EXPIRY:
                debug('EpisodeCache: Cache expired for show={}{}, season={} (age: {}s)'.format(
                    show_id, filter_suffix, season, age))

                if not allow_lazy_load:
                    debug('EpisodeCache: Lazy loading DISABLED, returning None')
                    return None

                # LAZY LOAD: Cache expirovala, obnoviť ju z API
                debug('EpisodeCache: Refreshing expired cache for season {}...'.format(season))
                from resources.lib.services.menu_cache_server import menu_cache_server
                season_url = '/FGet/{}/{}'.format(show_id, season)
                menu_cache_server._prepare_menu(season_url, episodes_only=True)

                # Skús znova načítať cache
                show_data = self.storage.get(show_key)
                if show_data:
                    season_data = show_data.get(season_key)

                if not season_data:
                    debug('EpisodeCache: Failed to refresh expired cache for season {}'.format(season))
                    return None

                debug('EpisodeCache: Cache refresh successful for season {}'.format(season))

            # Získaj zoznam epizód
            episodes = season_data.get('episodes', [])
            if not episodes:
                return None

            # Ignoruj špeciálne epizódy (S0Exx alebo SxxE0)
            current_episode = int(episode)
            current_season = int(season)
            if current_season == 0 or current_episode == 0:
                debug('EpisodeCache: Skipping special episode S{}E{} (not tracked)'.format(current_season, current_episode))
                return None

            # VALIDÁCIA: Skontroluj či aktuálna epizóda je v cache
            if current_episode not in episodes:
                debug('EpisodeCache: Current episode {}x{} NOT in cache (filter mismatch?) - epizóda nemá dabing/titulky podľa filter nastavení'.format(
                    season, current_episode))
                debug('EpisodeCache: Cache obsahuje len: {}'.format(episodes))
                # Aktuálna epizóda nie je v cache → pravdepodobne ju užívateľ pozerá manuálne
                # alebo má iné filter nastavenia ako keď sa cache vytvárala
                # V tomto prípade NEMÔŽEME spoľahlivo určiť ďalšiu epizódu zo cache
                return None

            # Nájdi ďalšiu epizódu v aktuálnej sezóne
            for ep_num in episodes:
                if ep_num > current_episode:
                    # Našli sme ďalšiu epizódu v tejto sezóne
                    debug('EpisodeCache: Next episode for show={}{}, S{}E{} is S{}E{}'.format(
                        show_id, filter_suffix, season, episode, season, ep_num))
                    return (season, ep_num)

            # Žiadna ďalšia epizóda v aktuálnej sezóne → skús ďalšiu sezónu
            debug('EpisodeCache: No more episodes in season {}, looking for next season'.format(season))

            # Použij zoznam sezón ak existuje
            seasons_list = show_data.get('seasons', [])

            # PRELOAD: Aktuálna epizóda je posledná v sezóne, načítaj cache pre ďalšiu sezónu
            if allow_lazy_load:
                debug('EpisodeCache: Current episode is LAST in season, preloading next season cache...')
                self._preload_next_season(show_id, season, seasons_list)
            else:
                debug('EpisodeCache: Preloading DISABLED (lazy loading off)')
            if seasons_list:
                # Zoraďme pre istotu
                seasons_list = sorted(seasons_list)
                # Nájdi aktuálnu sezónu v zozname
                try:
                    current_idx = seasons_list.index(season)
                    # Skús ďalšiu sezónu v zozname
                    if current_idx + 1 < len(seasons_list):
                        next_season = seasons_list[current_idx + 1]
                        next_season_key = 'season_{}'.format(next_season)
                        next_season_data = show_data.get(next_season_key)

                        if next_season_data:
                            next_episodes = next_season_data.get('episodes', [])
                            if next_episodes:
                                # Prvá epizóda ďalšej sezóny
                                next_ep = next_episodes[0]
                                debug('EpisodeCache: Next episode for show={}{}, S{}E{} is S{}E{} (from seasons list)'.format(
                                    show_id, filter_suffix, season, episode, next_season, next_ep))
                                return (next_season, next_ep)
                except ValueError:
                    # Aktuálna sezóna nie je v zozname, skúsime fallback
                    pass

            # Fallback: skús sekvenčne ďalšiu sezónu (season + 1)
            next_season_key = 'season_{}'.format(season + 1)
            next_season_data = show_data.get(next_season_key)

            if next_season_data:
                next_episodes = next_season_data.get('episodes', [])
                if next_episodes:
                    # Prvá epizóda ďalšej sezóny
                    next_ep = next_episodes[0]
                    debug('EpisodeCache: Next episode for show={}{}, S{}E{} is S{}E{} (fallback sequential)'.format(
                        show_id, filter_suffix, season, episode, season + 1, next_ep))
                    return (season + 1, next_ep)

            # Žiadna ďalšia epizóda
            debug('EpisodeCache: No next episode for show={}{}, S{}E{}'.format(show_id, filter_suffix, season, episode))
            return None

        except Exception as e:
            debug('EpisodeCache: Error getting next episode: {}'.format(e))
            return None

    def has_cache(self, show_id, season):
        """
        Skontroluje či existuje cache pre danú sezónu

        Returns:
            bool: True ak existuje platná cache
        """
        try:
            filter_suffix = self._get_filter_suffix()
            show_key = 'show_{}{}'.format(show_id, filter_suffix)
            season_key = 'season_{}'.format(season)

            show_data = self.storage.get(show_key)
            if not show_data:
                return False

            season_data = show_data.get(season_key)
            if not season_data:
                return False

            # Skontroluj expiráciu
            age = time() - season_data.get('timestamp', 0)
            return age <= self.CACHE_EXPIRY

        except Exception:
            return False

    def _preload_next_season(self, show_id, current_season, seasons_list):
        """
        Pre-načíta cache pre ďalšiu sezónu ak ešte neexistuje

        Volá sa keď je aktuálna epizóda posledná v sezóne, aby MenuCacheServer
        načítal dáta z API pre ďalšiu sezónu ešte pred dokončením aktuálnej epizódy.

        Args:
            show_id: ID seriálu
            current_season: Aktuálna sezóna (int)
            seasons_list: Zoznam všetkých sezón [1, 2, 3, ...]
        """
        try:
            # Urči číslo ďalšej sezóny
            next_season = None

            # Priorita: použij zoznam sezón ak existuje
            if seasons_list:
                seasons_list = sorted(seasons_list)
                try:
                    current_idx = seasons_list.index(current_season)
                    if current_idx + 1 < len(seasons_list):
                        next_season = seasons_list[current_idx + 1]
                        debug('EpisodeCache: Next season from list: {}'.format(next_season))
                except ValueError:
                    pass

            # Fallback: sekvenčne ďalšia sezóna
            if next_season is None:
                next_season = current_season + 1
                debug('EpisodeCache: Next season (fallback sequential): {}'.format(next_season))

            # Skontroluj či už existuje cache pre ďalšiu sezónu
            if self.has_cache(show_id, next_season):
                debug('EpisodeCache: Cache for S{} already exists, skip preload'.format(next_season))
                return

            # Cache neexistuje → zavolaj MenuCacheServer aby ju vytvoril
            debug('EpisodeCache: Preloading cache for S{} from API...'.format(next_season))

            from resources.lib.services.menu_cache_server import menu_cache_server
            # Vytvor URL pre ďalšiu sezónu (formát: /FGet/show_id/season)
            season_url = '/FGet/{}/{}'.format(show_id, next_season)

            # Zavolaj MenuCacheServer aby načítal a spracoval menu pre túto sezónu
            # MenuCacheServer automaticky detekuje epizódy a naplní EpisodeCache
            # episodes_only=True → nebudeme vytvárať SCItem (len detekcia epizód)
            menu_cache_server._prepare_menu(season_url, episodes_only=True)

            debug('EpisodeCache: Preload completed for S{}'.format(next_season))

        except Exception as e:
            debug('EpisodeCache: Error preloading next season: {}'.format(e))
            import traceback
            debug('EpisodeCache: Traceback: {}'.format(traceback.format_exc()))

    def invalidate(self, show_id=None, season=None):
        """
        Invaliduje cache pre všetky filter varianty

        Args:
            show_id: ID seriálu (None = vymaž všetko)
            season: Číslo sezóny (None = vymaž celý show)
        """
        try:
            if show_id is None:
                # Vymaž všetko
                self.storage.clear()
                debug('EpisodeCache: All cache invalidated')
            elif season is None:
                # Vymaž celý show pre všetky filter varianty
                # Možné suffixes: '', '_dub1', '_dub1_tit1'
                suffixes = ['', '_dub1', '_dub1_tit1']
                for suffix in suffixes:
                    show_key = 'show_{}{}'.format(show_id, suffix)
                    if show_key in self.storage:
                        del self.storage[show_key]
                debug('EpisodeCache: Cache invalidated for show={} (all filters)'.format(show_id))
            else:
                # Vymaž konkrétnu sezónu pre všetky filter varianty
                suffixes = ['', '_dub1', '_dub1_tit1']
                season_key = 'season_{}'.format(season)
                for suffix in suffixes:
                    show_key = 'show_{}{}'.format(show_id, suffix)
                    show_data = self.storage.get(show_key)
                    if show_data and season_key in show_data:
                        del show_data[season_key]
                        self.storage[show_key] = show_data
                debug('EpisodeCache: Cache invalidated for show={}, season={} (all filters)'.format(show_id, season))

        except Exception as e:
            debug('EpisodeCache: Error invalidating cache: {}'.format(e))


# Singleton instance
episode_cache = EpisodeCache()
