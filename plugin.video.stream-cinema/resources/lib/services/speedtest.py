# -*- coding: utf-8 -*-
"""
Speedtest service pre Stream Cinema plugin
Vylepšená verzia speedtest funkcionality
"""

import time
import re
import ssl
import socket
import urllib.request
import urllib.error
from urllib.parse import urlparse
from collections import deque

from resources.lib.kodiutils import debug, microtime
from resources.lib.system import Http
from resources.lib.api.sc import Sc


class SpeedTestService:
    """Service pre meranie rýchlosti pripojenia"""
    
    def __init__(self):
        self.hosts = ['b01', 'l01']
        
    def run_speedtest(self, ident='15VFNFJrCKHn'):
        """
        Spustí speedtest na všetkých hostoch
        
        Args:
            ident: Identifikátor streamu pre získanie URL
            
        Returns:
            tuple: (smin, smax, durmin, isp_data, best_server)
        """
        from resources.lib.api.kraska import getKraInstance
        from resources.lib.kodiutils import get_isp
        
        # Získame ISP info
        isp = get_isp()
        if not isp:
            isp = {}
            
        # Získame URL pre test
        kr = getKraInstance()
        url = kr.resolve(ident)
        
        smin = 999999999
        smax = 0
        durmin = 999999999
        best_server = None
        
        # Testujeme na všetkých hostoch s timeoutom 1s
        for host in self.hosts:
            test_url = re.sub(r':\/\/([^.]+)', '://{}'.format(host), url)
            debug('speedtest URL {}'.format(test_url))

            speed, duration = self.calculate_speed(test_url, timeout=1.0)
            debug('speedtest host {} speed: {} bps, duration: {:.2f}s'.format(host, speed, duration))
            
            # Sledujeme najlepší server (najrýchlejší)
            if speed > 0 and (best_server is None or speed > isp.get(best_server, 0)):
                best_server = host
            
            smin = min(speed, smin)
            smax = max(speed, smax)
            durmin = min(duration, durmin)
            isp.update({host: speed})
        
        debug('speedtest min/max {}/{} bps'.format(smin, smax))
        debug('speedtest results: {}'.format(isp))
        debug('speedtest best server: {} with {} bps'.format(best_server, isp.get(best_server, 0) if best_server else 0))
        
        # Odoslanie štatistík
        try:
            stats_response = Sc.post('/Stats/speedtest', json=isp)
            debug('Speed stats response: {}'.format(stats_response))
        except Exception as e:
            debug('Failed to send speedtest stats: {}'.format(e))
        
        return smin, smax, durmin, isp, best_server
    
    def calculate_speed(self, url, chunk_size=None, timeout=1.0):
        """
        Vypočíta rýchlosť sťahovania z danej URL

        Args:
            url: URL pre test
            chunk_size: Veľkosť chunku pre sťahovanie (default: 4MB)
            timeout: Timeout pre request v sekundách (default: 1.0s)

        Returns:
            tuple: (speed_bps, duration_seconds)
        """
        if chunk_size is None:
            chunk_size = 4 * 1024 * 1024  # 4MB chunks

        try:
            # Použijeme Http class z projektu s timeoutom
            response = Http.get(url, stream=True, timeout=timeout)
            total_length = int(response.headers.get('content-length', 0))

            start = microtime()

            # Sťahujeme po chunkoch s ochranou proti timeout
            start_time = time.time()
            for _ in response.iter_content(chunk_size):
                # Kontrola timeout aj počas sťahovania
                if time.time() - start_time > timeout:
                    debug('speedtest timeout during download')
                    break

            end = microtime()

            # Vypočítame trvanie v sekundách
            duration = (end - start) / 1000.0

            # Vypočítame rýchlosť v bitoch za sekundu
            if duration > 0:
                speed_bps = int(total_length / duration * 8)
            else:
                speed_bps = 0

            return speed_bps, duration

        except Exception as e:
            debug('Error calculating speed for {}: {}'.format(url, e))
            return 0, 0
    
    def calculate_speed_optimized(self, url, duration=10, timeout=1.0):
        """
        Optimalizovaný test rýchlosti - kontinuálne čítanie po dobu 'duration' sekúnd

        Args:
            url: URL pre test
            duration: Trvanie testu v sekundách
            timeout: Timeout pre request v sekundách (default: 1.0s)

        Returns:
            dict: Výsledky testu
        """
        chunk_size = 256 * 1024  # 256KB chunks

        total_bytes = 0
        start_time = time.time()
        chunk_count = 0
        speed_samples = deque(maxlen=100)  # Limit 100 vzoriek pre ochranu pamäte
        last_sample_time = start_time
        last_sample_bytes = 0

        try:
            # Vytvoríme SSL kontext ktorý ignoruje certifikáty
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            # Otvoríme spojenie s timeoutom
            request = urllib.request.Request(url)
            request.add_header('User-Agent', 'KODI Stream Cinema SpeedTest/1.0')
            connection = urllib.request.urlopen(request, timeout=timeout, context=ctx)
            
            while (time.time() - start_time) < duration:
                # Čítame kontinuálne
                data = connection.read(chunk_size)

                if not data or len(data) == 0:
                    # Koniec súboru - skúsime znovu otvoriť s timeoutom
                    connection.close()
                    connection = urllib.request.urlopen(request, timeout=timeout, context=ctx)
                    continue
                
                bytes_downloaded = len(data)
                total_bytes += bytes_downloaded
                chunk_count += 1
                
                # Vzorkovanie rýchlosti každých 0.5 sekundy
                current_time = time.time()
                time_diff = current_time - last_sample_time
                
                if time_diff >= 0.5:
                    bytes_diff = total_bytes - last_sample_bytes
                    if bytes_diff > 0 and time_diff > 0:
                        instant_speed = bytes_diff / time_diff
                        # Filtrujeme nerealistické hodnoty (max 10 Gbps)
                        if instant_speed < 1250000000:
                            speed_samples.append(instant_speed)
                    
                    last_sample_time = current_time
                    last_sample_bytes = total_bytes
            
            connection.close()
            
        except Exception as e:
            debug('Error in optimized speedtest: {}'.format(e))
        
        # Výpočet výsledkov
        total_time = time.time() - start_time
        
        if total_bytes > 0 and total_time > 0.1:
            avg_speed = total_bytes / total_time
            
            if speed_samples:
                # Odstránime outliers
                sorted_samples = sorted(speed_samples)
                trim_count = max(1, len(sorted_samples) // 10)
                if len(sorted_samples) > 2:
                    trimmed = sorted_samples[trim_count:-trim_count] if trim_count < len(sorted_samples)//2 else sorted_samples
                else:
                    trimmed = sorted_samples
                
                if trimmed:
                    max_speed = max(trimmed)
                    min_speed = min(trimmed)
                else:
                    max_speed = avg_speed
                    min_speed = avg_speed
            else:
                max_speed = avg_speed
                min_speed = avg_speed
            
            # Meranie latencie
            latency = None
            try:
                parsed = urlparse(url)
                host = parsed.hostname
                if host:
                    latency_start = time.time()
                    socket.getaddrinfo(host, None)
                    latency = (time.time() - latency_start) * 1000  # ms
            except Exception:
                pass
            
            return {
                'avg_speed': avg_speed * 8,  # Konvertujeme na bity/s
                'max_speed': max_speed * 8,
                'min_speed': min_speed * 8,
                'total_bytes': total_bytes,
                'total_time': total_time,
                'chunk_count': chunk_count,
                'chunk_size': chunk_size,
                'latency': latency
            }
        
        return None


# Singleton instance
_speedtest_instance = None

def get_speedtest_service():
    """Získa singleton inštanciu SpeedTestService"""
    global _speedtest_instance
    if _speedtest_instance is None:
        _speedtest_instance = SpeedTestService()
    return _speedtest_instance
