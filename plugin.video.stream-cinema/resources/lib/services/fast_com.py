# -*- coding: utf-8 -*-
"""
Fast.com API service pre Stream Cinema plugin
Získavanie IP informácií z Fast.com (Netflix)
"""

import re
import json
import ssl
import urllib.request
import urllib.error
import time

from resources.lib.kodiutils import debug


class FastComService:
    """Service pre komunikáciu s Fast.com API"""
    
    def __init__(self):
        self.token = None
        self.cache = {}
        self.cache_ttl = 24 * 3600
        
    def get_token(self):
        """
        Získa token pre Fast.com API z HTML stránky
        
        Returns:
            str: Token alebo None
        """
        if self.token:
            return self.token
            
        debug('FastCom: Getting token...')
        
        try:
            # SSL kontext
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            
            # Získame HTML stránku Fast.com
            debug('FastCom: Downloading HTML from https://fast.com')
            request = urllib.request.Request('https://fast.com')
            request.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            response = urllib.request.urlopen(request, timeout=10, context=ctx)
            html_content = response.read().decode('utf-8')
            debug('FastCom: HTML downloaded, size: {} bytes'.format(len(html_content)))
            
            # Hľadáme token v HTML
            debug('FastCom: Searching for token in HTML...')
            token_match = re.search(r'token["\']?\s*[:=]\s*["\']([^"\']+)["\']', html_content)
            
            if not token_match:
                debug('FastCom: Token not found in HTML, searching for JS file...')
                # Skúsime nájsť JS súbor
                js_match = re.search(r'<script\s+src="(/app-[^"]+\.js)"', html_content)
                if js_match:
                    js_url = 'https://fast.com' + js_match.group(1)
                    debug('FastCom: Found JS file: {}'.format(js_url))
                    
                    js_request = urllib.request.Request(js_url)
                    js_request.add_header('User-Agent', 'Mozilla/5.0')
                    js_response = urllib.request.urlopen(js_request, timeout=10, context=ctx)
                    js_content = js_response.read().decode('utf-8')
                    debug('FastCom: JS file downloaded, size: {} bytes'.format(len(js_content)))
                    
                    # Hľadáme token v JS súbore
                    token_match = re.search(r'token["\']?\s*[:=]\s*["\']([^"\']+)["\']', js_content)
            
            if token_match:
                self.token = token_match.group(1)
                debug('FastCom: Token successfully obtained: {}...'.format(self.token[:10]))
                return self.token
            else:
                debug('FastCom: Token not found')
                return None
                
        except Exception as e:
            debug('FastCom: Error getting token: {}'.format(e))
            return None
    
    def get_ip_info(self):
        """
        Získa IP informácie z Fast.com API s cache podľa IP
        
        Returns:
            dict: IP informácie alebo None
        """
        try:
            # Najprv získame našu aktuálnu IP z SC endpointu (VŽDY fresh, bez cache)
            from resources.lib.api.sc import Sc
            try:
                current_ip = Sc.get('/IP')  # Vždy fresh IP, /IP endpoint nebude mať cache
                debug('FastCom: Current IP from SC: {}'.format(current_ip))
            except Exception as e:
                debug('FastCom: Failed to get IP from SC endpoint: {}'.format(e))
                current_ip = None
            
            # Ak máme IP, skontrolujeme cache
            if current_ip and current_ip in self.cache:
                cached_data = self.cache[current_ip]
                cache_age = time.time() - cached_data['timestamp']
                
                if cache_age < self.cache_ttl:
                    debug('FastCom: Using cached data for IP {} (age: {} seconds)'.format(
                        current_ip, int(cache_age)))
                    return cached_data['data']
                else:
                    debug('FastCom: Cache expired for IP {} (age: {} seconds)'.format(
                        current_ip, int(cache_age)))
                    del self.cache[current_ip]
            
            debug('FastCom: Getting fresh IP info from Fast.com...')
            
            # Získame token
            token = self.get_token()
            if not token:
                debug('FastCom: No token available')
                return None
            
            # SSL kontext
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            
            # Volám Fast.com API
            api_url = 'https://api.fast.com/netflix/speedtest/v2?https=true&token={}&urlCount=1'.format(token)
            request = urllib.request.Request(api_url)
            request.add_header('User-Agent', 'Mozilla/5.0')
            response = urllib.request.urlopen(request, timeout=5, context=ctx)
            api_data = json.loads(response.read())
            
            client_info = api_data.get('client', {})
            if client_info:
                debug('FastCom: Full client_info: {}'.format(client_info))
                client_location = client_info.get('location', {})
                
                # Formátujeme dáta pre kompatibilitu s existujúcim kódom
                ip_info = {
                    'ip': client_info.get('ip', 'N/A'),
                    'isp': client_info.get('isp', 'N/A'),
                    'city': client_location.get('city', 'N/A'),
                    'country': client_location.get('country', 'N/A'),
                    'c': client_location.get('country', 'N/A')[:2].upper(),  # Kód krajiny
                    'a': str(client_info.get('asn', 'N/A'))  # ASN ako string
                }
                
                debug('FastCom: IP info obtained: {}, {}, {}, {} (ASN: {})'.format(
                    ip_info['ip'], ip_info['isp'], ip_info['city'], ip_info['country'], ip_info['a']
                ))
                
                # Uložíme do cache ak máme IP
                if current_ip:
                    self.cache[current_ip] = {
                        'data': ip_info,
                        'timestamp': time.time()
                    }
                    debug('FastCom: Cached data for IP {}'.format(current_ip))
                
                return ip_info
                
        except Exception as e:
            debug('FastCom: Error getting IP info: {}'.format(e))
        
        return None
    
    def clear_cache(self):
        """Vyčistí cache"""
        self.cache = {}
        debug('FastCom: Cache cleared')
    
    def get_cache_info(self):
        """Vráti informácie o cache pre debugging"""
        info = {
            'entries': len(self.cache),
            'ips': list(self.cache.keys()),
            'ttl': self.cache_ttl
        }
        return info


# Singleton instance
_fastcom_instance = None

def get_fastcom_service():
    """Získa singleton inštanciu FastComService"""
    global _fastcom_instance
    if _fastcom_instance is None:
        _fastcom_instance = FastComService()
    return _fastcom_instance
