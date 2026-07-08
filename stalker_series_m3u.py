#!/usr/bin/env python3
"""
Stalker Portal → M3U Converter (Series only - Spanish & French)
Basado en ingeniería inversa del protocolo Stalker/MAG
"""
import requests
import json
import logging
import re
import sys
from typing import Optional, List, Dict
from urllib.parse import urljoin

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

class StalkerToM3U:
    def __init__(self, portal_url: str, mac: str, timezone: str = "Europe/Paris"):
        self.portal_url = portal_url.rstrip('/')
        self.mac = mac.upper()
        self.timezone = timezone
        self.token = ""
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 4 rev: 2116 Mobile Safari/533.3",
            "X-User-Agent": "Model: MAG250; Link: Ethernet"
        })
        # Detectar la ruta base del portal
        self.base_path = self._detect_base_path()

    def _detect_base_path(self) -> str:
        """Detecta si el portal usa /c/, /stalker_portal/, o raíz"""
        test_paths = [
            f"{self.portal_url}/c/",
            f"{self.portal_url}/stalker_portal/c/",
            f"{self.portal_url}/",
        ]
        for path in test_paths:
            try:
                r = self.session.get(path, timeout=10)
                if r.status_code == 200 and ('PORTAL' in r.text or 'reset' in r.text or 'handshake' in r.text):
                    logger.info(f"Portal detectado en: {path}")
                    return path
            except:
                continue
        # Por defecto asumimos /c/
        return f"{self.portal_url}/c/"

    def _api_request(self, params: dict) -> Optional[dict]:
        """Hace una request a la API del portal"""
        params["JsHttpRequest"] = "1-xml"
        
        # Construir cookies
        cookies = {
            "mac": self.mac,
            "stb_lang": "es",
            "timezone": self.timezone,
        }
        if self.token:
            cookies["token"] = self.token
        
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        
        try:
            r = self.session.get(
                self.base_path,
                params=params,
                cookies=cookies,
                headers=headers,
                timeout=15
            )
            # Intentar parsear JSON (el portal a veces responde con HTML que contiene JSON)
            if r.text.strip().startswith('{'):
                return r.json()
            # Buscar JSON dentro del HTML
            json_match = re.search(r'\{.*"js".*\}', r.text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            logger.warning(f"Respuesta no-JSON: {r.text[:200]}")
            return None
        except Exception as e:
            logger.error(f"Error en API request: {e}")
            return None

    def authenticate(self) -> bool:
        """Flujo completo de autenticación: handshake → get_profile → do_auth"""
        logger.info("Iniciando autenticación...")
        
        # Paso 1: Handshake
        logger.info("Paso 1/3: Handshake...")
        resp = self._api_request({"type": "stb", "action": "handshake", "token": ""})
        if resp and "js" in resp:
            js = resp["js"]
            if isinstance(js, dict) and "token" in js:
                self.token = js["token"]
                logger.info(f"  Token obtenido: {self.token[:20]}...")
            else:
                logger.info("  Token aceptado (sin nuevo token)")
        
        if not self.token:
            logger.error("No se pudo obtener token en handshake")
            return False
        
        # Paso 2: Get Profile
        logger.info("Paso 2/3: Obteniendo perfil...")
        profile_params = {
            "type": "stb",
            "action": "get_profile",
            "stb_type": "MAG250",
            "ver": "ImageDescription: 0.2.16-250; ImageDate: 18 Mar 2013; PORTAL version: 4.9.9; API Version: 328; STB API version: 134",
            "device_id": "",
            "device_id2": "",
            "signature": "",
            "not_valid_token": "False",
            "auth_second_step": "False",
            "hd": "True",
            "num_banks": "1",
            "image_version": "216",
            "hw_version": "1.7-BD-00"
        }
        resp = self._api_request(profile_params)
        if resp and resp.get("js"):
            logger.info("  Perfil obtenido correctamente")
        else:
            logger.warning("  Perfil no disponible, continuando...")
        
        # Paso 3: Do Auth (login)
        logger.info("Paso 3/3: Autenticando...")
        auth_params = {
            "type": "stb",
            "action": "do_auth",
            "login": "",
            "password": "",
            "device_id": "",
            "device_id2": ""
        }
        resp = self._api_request(auth_params)
        if resp:
            logger.info(f"  Auth response: {resp.get('text', 'OK')}")
        else:
            logger.warning("  Auth sin respuesta JSON, puede que ya esté autenticado")
        
        logger.info("Autenticación completada.")
        return True

    def get_series_categories(self) -> List[Dict]:
        """Obtiene las categorías de series (Video Club)"""
        logger.info("Obteniendo categorías de series...")
        
        # Intentar primero con type=vod&action=get_categories
        resp = self._api_request({"type": "vod", "action": "get_categories"})
        categories = []
        
        if resp and "js" in resp:
            data = resp["js"]
            if isinstance(data, list):
                for cat in data:
                    cat_id = cat.get("id")
                    cat_name = cat.get("title", cat.get("name", ""))
                    categories.append({"id": cat_id, "title": cat_name, "type": "series"})
            elif isinstance(data, dict) and "data" in data:
                for cat in data["data"]:
                    cat_id = cat.get("id")
                    cat_name = cat.get("title", cat.get("name", ""))
                    categories.append({"id": cat_id, "title": cat_name, "type": "series"})
        
        if categories:
            logger.info(f"  Encontradas {len(categories)} categorías VOD")
        else:
            logger.info("  No se encontraron categorías VOD")
        
        return categories

    def get_genres(self) -> List[Dict]:
        """Obtiene los géneros disponibles"""
        resp = self._api_request({"type": "vod", "action": "get_genres"})
        genres = []
        if resp and "js" in resp:
            data = resp["js"]
            if isinstance(data, list):
                genres = [{"id": g.get("id"), "title": g.get("title", g.get("name", ""))} for g in data]
            elif isinstance(data, dict) and "data" in data:
                genres = [{"id": g.get("id"), "title": g.get("title", g.get("name", ""))} for g in data["data"]]
        return genres

    def get_series_in_category(self, category_id: str, max_pages: int = 10) -> List[Dict]:
        """Obtiene todas las series en una categoría (paginado)"""
        all_items = []
        
        for page in range(1, max_pages + 1):
            params = {
                "type": "vod",
                "action": "get_ordered_list",
                "category_id": category_id,
                "p": page
            }
            resp = self._api_request(params)
            
            if not resp or "js" not in resp:
                break
            
            js = resp["js"]
            data = js.get("data", []) if isinstance(js, dict) else []
            
            if not data:
                break
            
            # Verificar si son series (is_series == "1")
            for item in data:
                if str(item.get("is_series", "0")) == "1":
                    all_items.append(item)
            
            # Verificar si hay más páginas
            total_items = int(js.get("total_items", 0))
            if page * len(data) >= total_items:
                break
        
        return all_items

    def create_stream_link(self, cmd: str) -> Optional[str]:
        """Crea un enlace de stream a partir de un cmd"""
        if cmd.startswith("http"):
            return cmd
        
        resp = self._api_request({
            "type": "vod",
            "action": "create_link",
            "cmd": cmd
        })
        
        if resp and "js" in resp:
            stream_cmd = resp["js"].get("cmd", "")
            if stream_cmd:
                # Limpiar prefijo ffmpeg si existe
                stream_cmd = re.sub(r'^ffmpeg\s*', '', stream_cmd).strip()
                if not stream_cmd.startswith("http"):
                    stream_cmd = f"{self.portal_url}/{stream_cmd.lstrip('/')}"
                return stream_cmd
        return None

    def get_seasons(self, movie_id: str) -> List[Dict]:
        """Obtiene las temporadas de una serie"""
        seasons = []
        page = 1
        while True:
            params = {
                "type": "vod",
                "action": "get_ordered_list",
                "movie_id": movie_id,
                "season_id": "0",
                "episode_id": "0",
                "p": page
            }
            resp = self._api_request(params)
            if not resp or "js" not in resp:
                break
            
            data = resp["js"].get("data", [])
            if not data:
                break
            seasons.extend(data)
            
            total = int(resp["js"].get("total_items", 0))
            if page * len(data) >= total:
                break
            page += 1
        return seasons

    def get_episodes(self, movie_id: str, season_id: str) -> List[Dict]:
        """Obtiene los episodios de una temporada"""
        episodes = []
        page = 1
        while True:
            params = {
                "type": "vod",
                "action": "get_ordered_list",
                "movie_id": movie_id,
                "season_id": season_id,
                "episode_id": "0",
                "p": page
            }
            resp = self._api_request(params)
            if not resp or "js" not in resp:
                break
            
            data = resp["js"].get("data", [])
            if not data:
                break
            episodes.extend(data)
            
            total = int(resp["js"].get("total_items", 0))
            if page * len(data) >= total:
                break
            page += 1
        return episodes

    def detect_language(self, name: str, desc: str = "") -> str:
        """Detecta el idioma de una serie por su nombre y descripción"""
        text = f"{name} {desc}".lower()
        
        # Palabras clave español
        es_keywords = [
            'español', 'espanol', 'spanish', 'castellano', 'latino', 'subtitulado',
            'es', 'spa', 'sub es', 'audio es', 'doblado al español'
        ]
        # Palabras clave francés
        fr_keywords = [
            'français', 'francais', 'french', 'vf', 'vostfr', 'version française',
            'fr', 'fra', 'sub fr', 'audio fr', 'dublado en francés', 'dublado en frances'
        ]
        
        has_es = any(kw in text for kw in es_keywords)
        has_fr = any(kw in text for kw in fr_keywords)
        
        if has_es and has_fr:
            return "both"
        elif has_es:
            return "es"
        elif has_fr:
            return "fr"
        return "unknown"

    def generate_m3u(self, output_file: str = "series_es_fr.m3u"):
        """Genera el archivo M3U con las series en español y francés"""
        logger.info(f"\n{'='*60}")
        logger.info("GENERANDO LISTA M3U DE SERIES (ESPAÑOL Y FRANCÉS)")
        logger.info(f"{'='*60}\n")
        
        # Autenticar
        if not self.authenticate():
            logger.error("Fallo en autenticación. Abortando.")
            return
        
        # Obtener categorías
        categories = self.get_series_categories()
        if not categories:
            logger.warning("No se encontraron categorías. Intentando buscar todas las series...")
            # Si no hay categorías, intentar obtener géneros
            genres = self.get_genres()
            if genres:
                for g in genres:
                    categories.append({"id": g["id"], "title": g["title"], "type": "series"})
        
        if not categories:
            # Último recurso: buscar con category_id=0
            categories = [{"id": "0", "title": "Todas", "type": "series"}]
        
        # Recolectar series
        all_series = []
        for cat in categories:
            logger.info(f"Procesando categoría: {cat['title']} (ID: {cat['id']})")
            series = self.get_series_in_category(cat["id"])
            for s in series:
                s["_category"] = cat["title"]
                all_series.append(s)
            logger.info(f"  → {len(series)} series encontradas")
        
        logger.info(f"\nTotal de series encontradas: {len(all_series)}")
        
        if not all_series:
            logger.error("No se encontraron series. Revisa la conexión al portal.")
            return
        
        # Filtrar por español y francés
        es_series = []
        fr_series = []
        unknown_series = []
        
        for s in all_series:
            name = s.get("name", s.get("title", ""))
            desc = s.get("descr", s.get("description", s.get("txt", "")))
            lang = self.detect_language(name, desc)
            
            if lang == "es" or lang == "both":
                es_series.append(s)
            if lang == "fr" or lang == "both":
                fr_series.append(s)
            if lang == "unknown":
                unknown_series.append(s)
        
        logger.info(f"\nSeries en español: {len(es_series)}")
        logger.info(f"Series en francés: {len(fr_series)}")
        logger.info(f"Series sin idioma detectado: {len(unknown_series)}")
        
        # Preguntar si incluir las desconocidas
        if unknown_series:
            include_unknown = input(f"\n¿Incluir las {len(unknown_series)} series sin idioma detectado? (s/N): ").strip().lower()
            if include_unknown == 's':
                es_series.extend(unknown_series)
                fr_series.extend(unknown_series)
                logger.info("Series desconocidas incluidas.")
        
        # Generar M3U
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("#EXTM3U\n")
            f.write(f"#PLAYLIST: Series Stalker Portal (ES/FR)\n")
            f.write(f"#GENERATED: StalkerToM3U Converter\n")
            f.write(f"#MAC: {self.mac}\n")
            f.write(f"#PORTAL: {self.portal_url}\n\n")
            
            # Escribir series en español
            f.write("# --- SERIES EN ESPAÑOL ---\n")
            for s in es_series:
                name = s.get("name", s.get("title", "Sin nombre"))
                movie_id = s.get("id", "")
                cat = s.get("_category", "")
                f.write(f'#EXTINF:-1 tvg-id="{movie_id}" tvg-lang="es" group-title="Series ES - {cat}",{name}\n')
                # Para series, el stream se resuelve por temporada/episodio
                # Pero ponemos un placeholder
                cmd = s.get("cmd", "")
                if cmd and not cmd.startswith("http"):
                    stream_url = self.create_stream_link(cmd)
                    if stream_url:
                        f.write(f"{stream_url}\n")
                    else:
                        f.write(f"# El stream para '{name}' no pudo ser resuelto\n")
                elif cmd:
                    f.write(f"{cmd}\n")
                else:
                    f.write(f"# Stream no disponible para '{name}'\n")
            
            f.write("\n")
            
            # Escribir series en francés
            f.write("# --- SERIES EN FRANCÉS ---\n")
            for s in fr_series:
                name = s.get("name", s.get("title", "Sin nombre"))
                movie_id = s.get("id", "")
                cat = s.get("_category", "")
                f.write(f'#EXTINF:-1 tvg-id="{movie_id}" tvg-lang="fr" group-title="Series FR - {cat}",{name}\n')
                cmd = s.get("cmd", "")
                if cmd and not cmd.startswith("http"):
                    stream_url = self.create_stream_link(cmd)
                    if stream_url:
                        f.write(f"{stream_url}\n")
                    else:
                        f.write(f"# El stream para '{name}' no pudo ser resuelto\n")
                elif cmd:
                    f.write(f"{cmd}\n")
                else:
                    f.write(f"# Stream no disponible para '{name}'\n")
        
        logger.info(f"\n✅ Lista M3U generada: {output_file}")
        logger.info(f"  Series ES: {len(es_series)}")
        logger.info(f"  Series FR: {len(fr_series)}")
        logger.info(f"  Total entradas: {len(es_series) + len(fr_series)}")

def main():
    portal_url = "http://mag.greatott.me:80"
    mac = "00:1A:79:74:B1:B9"
    
    converter = StalkerToM3U(portal_url, mac, timezone="Europe/Paris")
    converter.generate_m3u("series_es_fr.m3u")

if __name__ == "__main__":
    main()