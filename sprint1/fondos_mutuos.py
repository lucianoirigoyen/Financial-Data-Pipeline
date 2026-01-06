"""
Módulo para procesamiento de fondos mutuos CON SCRAPING WEB REAL
Incluye integración con Fintual API, scraping web de CMF Chile y generación de descripciones con IA
"""

import os
import requests
import pandas as pd
import pdfplumber
import logging
import re
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from openai import OpenAI
import openai
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

# Cargar variables de entorno
load_dotenv()

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# FIX 4.4: Regex compilados module-level para performance
REGEX_COMISION = re.compile(r'(\d*[\.,]?\d+)\s*%?')
REGEX_RENT_1ANO = re.compile(r'1\s+año\s+([-]?\d*[\.,]?\d+)\s*%', re.IGNORECASE)
REGEX_RENT_2ANOS = re.compile(r'2\s+años?\s+([-]?\d*[\.,]?\d+)\s*%', re.IGNORECASE)
REGEX_RENT_3ANOS = re.compile(r'[35]\s+años?\s+([-]?\d*[\.,]?\d+)\s*%', re.IGNORECASE)
REGEX_FECHA_CMF = re.compile(r'(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})')
REGEX_VALOR_CUOTA = re.compile(r'valor\s+cuota[:\s]+\$?\s*([\d.,]+)', re.IGNORECASE)
REGEX_PERFIL_RIESGO = re.compile(r'\bR([1-7])\b')


# FIX 1.3: Función utilitaire pour éviter NoneType+str concatenation
def safe_str_concat(*args, separator: str = '') -> str:
    """
    Concatenar strings de forma segura, filtrando valores None.

    Args:
        *args: Valores a concatenar (strings, int, o None)
        separator: Separador entre valores (default: '')

    Returns:
        String concatenado, convirtiendo None a string vacío

    Ejemplos:
        >>> safe_str_concat('https://example.com?rut=', None)
        'https://example.com?rut='
        >>> safe_str_concat('base_', 10446, '_suffix')
        'base_10446_suffix'
    """
    safe_values = [str(arg) if arg is not None else '' for arg in args]
    return separator.join(safe_values)


# FIX 2.1: Función HTTP GET con retry y backoff exponencial
def request_with_retry(session: requests.Session, url: str, max_retries: int = 3, backoff: float = 2, **kwargs) -> Optional[requests.Response]:
    """
    Realizar HTTP GET con retry automático y backoff exponencial.

    Args:
        session: Sesión requests.Session a utilizar
        url: URL a consultar
        max_retries: Número máximo de intentos (default: 3)
        backoff: Factor de backoff exponencial en segundos (default: 2)
        **kwargs: Argumentos adicionales para session.get() (timeout, headers, etc.)

    Returns:
        requests.Response si exitoso, None si falla tras todos los retries

    Ejemplos:
        >>> response = request_with_retry(session, 'https://cmf.cl/api/...', timeout=30)
        >>> if response and response.status_code == 200: ...
    """
    for attempt in range(max_retries):
        try:
            response = session.get(url, **kwargs)

            # FIX 2.3: Logger redirects para detectar cambios de URL
            if response.history:
                logger.info(f"[HTTP RETRY] Redirects detectados: {len(response.history)} → {response.url}")
                for i, resp in enumerate(response.history):
                    logger.debug(f"[HTTP RETRY]   Redirect {i+1}: {resp.status_code} {resp.url}")

            # Éxito: status 200
            if response.status_code == 200:
                if attempt > 0:
                    logger.info(f"[HTTP RETRY] ✓ Éxito en intento {attempt + 1}/{max_retries}")
                return response

            # 404 o 503: intentar retry
            elif response.status_code in [404, 503] and attempt < max_retries - 1:
                wait_time = backoff ** attempt
                logger.warning(f"[HTTP RETRY] HTTP {response.status_code} en {url[:80]}, retry {attempt + 1}/{max_retries} en {wait_time}s")
                time.sleep(wait_time)

            # Otros errores: no retry
            else:
                logger.warning(f"[HTTP RETRY] HTTP {response.status_code} para {url[:80]} - no retry")
                return response

        except requests.exceptions.Timeout as e:
            if attempt < max_retries - 1:
                wait_time = backoff ** attempt
                logger.warning(f"[HTTP RETRY] Timeout en {url[:80]}, retry {attempt + 1}/{max_retries} en {wait_time}s")
                time.sleep(wait_time)
            else:
                logger.error(f"[HTTP RETRY] Timeout tras {max_retries} intentos: {url[:80]}")
                return None

        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                wait_time = backoff ** attempt
                logger.warning(f"[HTTP RETRY] Exception {type(e).__name__} en {url[:80]}, retry {attempt + 1}/{max_retries} en {wait_time}s")
                time.sleep(wait_time)
            else:
                logger.error(f"[HTTP RETRY] Falló tras {max_retries} intentos: {type(e).__name__}: {e}")
                return None

    logger.error(f"[HTTP RETRY] Agotados {max_retries} intentos para {url[:80]}")
    return None


def _wait_for_download_complete(download_dir: str, timeout: int = 60, min_size_kb: int = 10, existing_files: set = None) -> Optional[str]:
    """Poll download directory until PDF download completes (no .crdownload)

    Args:
        download_dir: Directory to monitor for downloads
        timeout: Maximum seconds to wait
        min_size_kb: Minimum file size in KB to consider valid
        existing_files: Set of files that existed before download started (to ignore old files)
    """
    logger.info(f"[DOWNLOAD POLL] Waiting for download to complete (max {timeout}s)...")
    start_time = time.time()

    # FIX CRITICO: Si no se pasa existing_files, capturar el estado ACTUAL del directorio
    # Esto evita detectar PDFs viejos como "nuevos"
    if existing_files is None:
        existing_files = set(os.listdir(download_dir))
        logger.warning(f"[DOWNLOAD POLL] No se pasó existing_files - usando estado actual ({len(existing_files)} archivos)")

    last_files = existing_files.copy()

    while time.time() - start_time < timeout:
        try:
            all_files = set(os.listdir(download_dir))
            pdf_files = [f for f in all_files if f.endswith('.pdf')]
            new_pdfs = [f for f in pdf_files if f not in last_files]

            if new_pdfs:
                pdf_path = os.path.join(download_dir, new_pdfs[0])
                initial_size = os.path.getsize(pdf_path)
                time.sleep(1)
                current_size = os.path.getsize(pdf_path)

                if current_size == initial_size and current_size > (min_size_kb * 1024):
                    size_kb = current_size / 1024
                    logger.info(f"[DOWNLOAD POLL] ✅ PDF downloaded: {new_pdfs[0]} ({size_kb:.2f} KB)")
                    return pdf_path

            last_files = all_files
            time.sleep(0.5)

        except Exception as e:
            logger.debug(f"[DOWNLOAD POLL] Error checking: {e}")
            time.sleep(0.5)

    logger.error(f"[DOWNLOAD POLL] Timeout after {timeout}s")
    return None


# Importar monitor de CMF (opcional)
try:
    from cmf_monitor import CMFMonitor
    CMF_MONITOR_AVAILABLE = True
except ImportError:
    CMF_MONITOR_AVAILABLE = False
    logger.debug("cmf_monitor no disponible, salteando validación de salud")

class FondosMutuosProcessor:
    """Clase para procesar datos de fondos mutuos desde múltiples fuentes CON SCRAPING REAL"""

    def __init__(self):
        self.openai_key = os.getenv('OPENAI_API_KEY')
        self.ua = UserAgent()
        self.session = requests.Session()

        # Headers realistas para evitar bloqueos (mejorados para evitar 403)
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0'
        })

        if not self.openai_key:
            logger.warning("OPENAI_API_KEY no encontrada, la generación de descripciones no funcionará")

        # SISTEMA DE CACHÉ DE PDFs
        self.cache_dir = 'cache/pdfs'
        self.cache_index_path = 'cache/pdf_cache_index.json'
        self.cache_expiration_days = int(os.getenv('PDF_CACHE_EXPIRATION_DAYS', '30'))

        # Estadísticas de caché
        self.cache_stats = {
            'hits': 0,
            'misses': 0,
            'downloads': 0
        }

        # Inicializar sistema de caché
        self._init_cache_system()

        # Limpiar PDFs expirados al inicio
        self._clean_expired_cache()

        # Validar salud de CMF al inicio (opcional)
        self._validate_cmf_health()

    def _init_cache_system(self):
        """
        Inicializar el sistema de caché de PDFs.
        Crea los directorios necesarios y el archivo de índice si no existen.
        """
        try:
            # Crear directorio de caché si no existe
            os.makedirs(self.cache_dir, exist_ok=True)
            logger.info(f"[CACHE] Directorio de caché inicializado: {self.cache_dir}")

            # Crear archivo de índice si no existe
            if not os.path.exists(self.cache_index_path):
                os.makedirs(os.path.dirname(self.cache_index_path), exist_ok=True)
                with open(self.cache_index_path, 'w', encoding='utf-8') as f:
                    json.dump({}, f, indent=2)
                logger.info(f"[CACHE] Archivo de índice creado: {self.cache_index_path}")
            else:
                logger.info(f"[CACHE] Sistema de caché ya inicializado")

        except Exception as e:
            logger.error(f"[CACHE] Error inicializando sistema de caché: {e}")

    def _get_cached_pdf(self, rut: str, serie: str) -> Optional[str]:
        """
        Verificar si existe un PDF en caché válido (no expirado).

        Args:
            rut (str): RUT del fondo
            serie (str): Serie del fondo

        Returns:
            Path al PDF cacheado si existe y es válido, None en caso contrario
        """
        try:
            # Generar clave de caché
            cache_key = f"{rut}_{serie}"

            # Cargar índice de caché
            if not os.path.exists(self.cache_index_path):
                return None

            with open(self.cache_index_path, 'r', encoding='utf-8') as f:
                cache_index = json.load(f)

            # Verificar si existe entrada en el índice
            if cache_key not in cache_index:
                logger.debug(f"[CACHE] MISS - No se encontró entrada para {cache_key}")
                self.cache_stats['misses'] += 1
                return None

            entry = cache_index[cache_key]
            pdf_path = entry.get('pdf_path')
            expires_at = entry.get('expires_at')

            # Verificar si el archivo existe
            if not os.path.exists(pdf_path):
                logger.warning(f"[CACHE] MISS - Archivo no existe: {pdf_path}")
                # Limpiar entrada inválida
                del cache_index[cache_key]
                with open(self.cache_index_path, 'w', encoding='utf-8') as f:
                    json.dump(cache_index, f, indent=2, ensure_ascii=False)
                self.cache_stats['misses'] += 1
                return None

            # Verificar si expiró
            expires_datetime = datetime.fromisoformat(expires_at)
            if datetime.now() > expires_datetime:
                logger.info(f"[CACHE] MISS - PDF expirado: {cache_key}")
                # Eliminar archivo y entrada
                try:
                    os.remove(pdf_path)
                except:
                    pass
                del cache_index[cache_key]
                with open(self.cache_index_path, 'w', encoding='utf-8') as f:
                    json.dump(cache_index, f, indent=2, ensure_ascii=False)
                self.cache_stats['misses'] += 1
                return None

            # PDF válido encontrado
            logger.info(f"[CACHE] HIT - PDF encontrado en caché: {cache_key}")
            self.cache_stats['hits'] += 1
            return pdf_path

        except Exception as e:
            logger.error(f"[CACHE] Error verificando caché: {e}")
            self.cache_stats['misses'] += 1
            return None

    def _save_to_cache(self, rut: str, serie: str, pdf_path: str) -> bool:
        """
        Guardar un PDF en el sistema de caché con metadata.

        Args:
            rut (str): RUT del fondo
            serie (str): Serie del fondo
            pdf_path (str): Path al PDF descargado (en temp/)

        Returns:
            bool: True si se guardó correctamente, False en caso contrario
        """
        try:
            # Generar clave y path de caché
            cache_key = f"{rut}_{serie}"
            cached_pdf_path = os.path.join(self.cache_dir, f"{cache_key}.pdf")

            # Copiar archivo a directorio de caché
            import shutil
            if not os.path.exists(pdf_path):
                logger.error(f"[CACHE] No se puede cachear - archivo no existe: {pdf_path}")
                return False

            shutil.copy2(pdf_path, cached_pdf_path)

            # Calcular fecha de expiración
            downloaded_at = datetime.now()
            expires_at = downloaded_at + timedelta(days=self.cache_expiration_days)

            # Obtener tamaño del archivo
            file_size = os.path.getsize(cached_pdf_path)

            # Crear entrada de metadata
            metadata = {
                "rut": rut,
                "serie": serie,
                "pdf_path": cached_pdf_path,
                "downloaded_at": downloaded_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "file_size": file_size
            }

            # Cargar índice existente
            cache_index = {}
            if os.path.exists(self.cache_index_path):
                with open(self.cache_index_path, 'r', encoding='utf-8') as f:
                    cache_index = json.load(f)

            # Agregar o actualizar entrada
            cache_index[cache_key] = metadata

            # Guardar índice actualizado
            with open(self.cache_index_path, 'w', encoding='utf-8') as f:
                json.dump(cache_index, f, indent=2, ensure_ascii=False)

            logger.info(f"[CACHE] PDF guardado en caché: {cache_key} (expira: {expires_at.strftime('%Y-%m-%d')})")
            return True

        except Exception as e:
            logger.error(f"[CACHE] Error guardando en caché: {e}")
            return False

    def _clean_expired_cache(self):
        """
        Limpiar PDFs expirados del sistema de caché.
        Se ejecuta automáticamente al inicializar el processor.
        """
        try:
            if not os.path.exists(self.cache_index_path):
                logger.debug("[CACHE] No hay índice de caché para limpiar")
                return

            with open(self.cache_index_path, 'r', encoding='utf-8') as f:
                cache_index = json.load(f)

            if not cache_index:
                logger.debug("[CACHE] Índice de caché vacío")
                return

            now = datetime.now()
            expired_keys = []

            # Identificar entradas expiradas
            for cache_key, entry in cache_index.items():
                expires_at = datetime.fromisoformat(entry.get('expires_at'))
                if now > expires_at:
                    expired_keys.append(cache_key)
                    pdf_path = entry.get('pdf_path')
                    # Eliminar archivo si existe
                    if os.path.exists(pdf_path):
                        try:
                            os.remove(pdf_path)
                            logger.info(f"[CACHE] PDF expirado eliminado: {cache_key}")
                        except Exception as e:
                            logger.warning(f"[CACHE] Error eliminando PDF expirado: {e}")

            # Eliminar entradas del índice
            for key in expired_keys:
                del cache_index[key]

            # Guardar índice actualizado
            if expired_keys:
                with open(self.cache_index_path, 'w', encoding='utf-8') as f:
                    json.dump(cache_index, f, indent=2, ensure_ascii=False)
                logger.info(f"[CACHE] Limpieza completada: {len(expired_keys)} PDFs expirados eliminados")
            else:
                logger.debug("[CACHE] No hay PDFs expirados para eliminar")

        except Exception as e:
            logger.error(f"[CACHE] Error limpiando caché expirado: {e}")

    def _validate_cmf_health(self):
        """
        Validar salud del sistema de scraping de CMF.
        Ejecuta un check rápido para detectar problemas proactivamente.
        """
        if not CMF_MONITOR_AVAILABLE:
            logger.debug("[CMF HEALTH] Monitor no disponible, salteando validación")
            return

        try:
            # Ejecutar solo check de estructura (rápido)
            monitor = CMFMonitor()
            structure_result = monitor.monitor_cmf_structure()

            status = structure_result.get('status', 'unknown')

            if status == 'ok':
                logger.info("[CMF HEALTH] Status: healthy ✓")
            elif status == 'warning':
                logger.warning("[CMF HEALTH] Status: warning ⚠ - Se detectaron cambios menores")
                logger.warning("[CMF HEALTH] Recomendación: Ejecutar 'python run_cmf_monitor.py' para más detalles")
            elif status == 'critical':
                logger.error("[CMF HEALTH] Status: critical ✗ - Sistema puede no funcionar")
                logger.error("[CMF HEALTH] ACCIÓN REQUERIDA: Ejecutar 'python run_cmf_monitor.py' para diagnóstico completo")
                logger.error("[CMF HEALTH] Errores detectados:")
                for error in structure_result.get('errors', []):
                    logger.error(f"[CMF HEALTH]   - {error}")
            else:
                logger.warning(f"[CMF HEALTH] Status: {status}")

        except Exception as e:
            logger.debug(f"[CMF HEALTH] Error ejecutando validación: {e}")
            # No interrumpir el flujo si falla la validación

    def _log_cache_statistics(self):
        """
        Mostrar estadísticas de uso del caché.
        Incluye hits, misses, descargas y tasa de aciertos.
        """
        try:
            total_requests = self.cache_stats['hits'] + self.cache_stats['misses']
            if total_requests == 0:
                logger.debug("[CACHE] No se realizaron consultas al caché en esta sesión")
                return

            hit_rate = (self.cache_stats['hits'] / total_requests) * 100 if total_requests > 0 else 0

            logger.info("=" * 60)
            logger.info("[CACHE] ESTADÍSTICAS DE CACHÉ DE PDFs")
            logger.info("=" * 60)
            logger.info(f"[CACHE] Cache Hits:        {self.cache_stats['hits']}")
            logger.info(f"[CACHE] Cache Misses:      {self.cache_stats['misses']}")
            logger.info(f"[CACHE] Nuevas Descargas:  {self.cache_stats['downloads']}")
            logger.info(f"[CACHE] Total Consultas:   {total_requests}")
            logger.info(f"[CACHE] Tasa de Aciertos:  {hit_rate:.1f}%")
            logger.info("=" * 60)

            # Mostrar información del caché actual
            if os.path.exists(self.cache_index_path):
                with open(self.cache_index_path, 'r', encoding='utf-8') as f:
                    cache_index = json.load(f)
                    num_pdfs_cached = len(cache_index)
                    logger.info(f"[CACHE] PDFs en caché:     {num_pdfs_cached}")

                    # Calcular tamaño total del caché
                    total_size = 0
                    for entry in cache_index.values():
                        pdf_path = entry.get('pdf_path')
                        if os.path.exists(pdf_path):
                            total_size += os.path.getsize(pdf_path)

                    total_size_mb = total_size / (1024 * 1024)
                    logger.info(f"[CACHE] Tamaño total:      {total_size_mb:.2f} MB")
                    logger.info("=" * 60)

        except Exception as e:
            logger.error(f"[CACHE] Error mostrando estadísticas: {e}")

    def _get_cmf_page_with_params(self, rut: str, pestania: str = "1") -> Optional[str]:
        """
        Buscar la URL completa de la página de entidad CMF con todos los parámetros incluido el ROW ID.

        Args:
            rut (str): RUT del fondo SIN guión (ej: "8638")
            pestania (str): Número de pestaña (default "1", usar "68" para folletos)

        Returns:
            URL completa con parámetros incluido row, o None
        """
        try:
            # FIX: Validate RUT parameter to prevent NoneType errors
            if not rut or not isinstance(rut, str):
                logger.warning(f"[CMF] RUT inválido recibido: {rut}")
                return None

            logger.info(f"[CMF] Buscando página de entidad para RUT: {rut}, pestaña: {pestania}")

            # Buscar en el listado de fondos
            listado_url = "https://www.cmfchile.cl/institucional/mercados/consulta.php?mercado=V&Estado=VI&entidad=RGFMU"

            # FIX 2.2: Usar request_with_retry en lugar de session.get directo
            response = request_with_retry(self.session, listado_url, timeout=30)
            if not response or response.status_code != 200:
                logger.warning(f"[CMF] No se pudo acceder al listado: {response.status_code if response else 'None'}")
                return None

            soup = BeautifulSoup(response.content, 'html.parser')

            # ESTRATEGIA 1: Buscar enlaces en el HTML que contengan el RUT
            enlaces = soup.find_all('a', href=True)

            for enlace in enlaces:
                href = enlace['href']
                if f'rut={rut}' in href and 'entidad.php' in href and 'row=' in href:
                    # Construir URL completa
                    if href.startswith('http'):
                        url_base = href
                    elif href.startswith('/'):
                        url_base = f"https://www.cmfchile.cl{href}"
                    else:
                        url_base = f"https://www.cmfchile.cl/institucional/mercados/{href}"

                    # Parsear para reemplazar la pestaña
                    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
                    parsed = urlparse(url_base)
                    params = parse_qs(parsed.query)

                    # Actualizar pestaña
                    params['pestania'] = [pestania]

                    # Reconstruir query string (convertir listas a valores únicos)
                    new_params = {k: v[0] if isinstance(v, list) else v for k, v in params.items()}
                    new_query = urlencode(new_params)

                    # Reconstruir URL
                    url_completa = urlunparse((
                        parsed.scheme,
                        parsed.netloc,
                        parsed.path,
                        parsed.params,
                        new_query,
                        parsed.fragment
                    ))

                    logger.info(f"[CMF] ✓ URL encontrada con row ID: {url_completa[:100]}...")
                    return url_completa

            # ESTRATEGIA 2: Acceso directo sin row parameter (funciona para fondos en JavaScript arrays)
            logger.info(f"[CMF] RUT no encontrado en HTML, intentando acceso directo...")
            url_directa = f"https://www.cmfchile.cl/institucional/mercados/entidad.php?mercado=V&rut={rut}&tipoentidad=RGFMU&vig=VI&control=svs&pestania={pestania}"

            # Verificar si la URL directa funciona
            try:
                response_direct = self.session.get(url_directa, timeout=10)
                if response_direct.status_code == 200 and 'PAGE_NOT_FOUND' not in response_direct.url:
                    logger.info(f"[CMF] ✓ Acceso directo exitoso (sin row parameter)")
                    return url_directa
            except:
                pass

            logger.warning(f"[CMF] No se pudo obtener URL para RUT {rut}")
            return None

        except Exception as e:
            logger.error(f"[CMF] Error buscando página: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None

    def _extract_pdf_links_from_cmf_page(self, page_url: str) -> Tuple[List[Dict], Optional[str]]:
        """
        Extraer información de folletos y rutAdmin desde una página de entidad CMF.

        Args:
            page_url (str): URL completa de la página de entidad

        Returns:
            Tuple con:
            - Lista de diccionarios con información de folletos
            - rutAdmin (str): RUT de la administradora extraído de los onclick
        """
        try:
            logger.info(f"[CMF] Extrayendo folletos desde: {page_url}")

            # Agregar o reemplazar pestania=68 para ver folletos informativos
            import re as regex_module
            if 'pestania=' in page_url:
                # Reemplazar la pestania existente con 68
                page_url = regex_module.sub(r'pestania=\d+', 'pestania=68', page_url)
            else:
                # Agregar pestania=68
                page_url = f"{page_url}&pestania=68" if '?' in page_url else f"{page_url}?pestania=68"

            # Headers de navegador para evitar bloqueos
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'es-CL,es;q=0.9',
            }

            # FIX 2.2: Usar request_with_retry para folletos
            response = request_with_retry(self.session, page_url, headers=headers, timeout=30)
            if not response or response.status_code != 200:
                logger.warning(f"[CMF] Error accediendo a página: {response.status_code if response else 'None'}")
                return [], None

            soup = BeautifulSoup(response.content, 'html.parser')

            folletos = []
            rut_admin = None

            # MÉTODO 1: Extraer de onclick="verFolleto(...)"
            # Buscar todos los elementos con onclick que llaman a verFolleto
            onclick_elements = soup.find_all(attrs={'onclick': re.compile(r'verFolleto')})

            logger.info(f"[CMF] Encontrados {len(onclick_elements)} elementos con verFolleto")

            for elem in onclick_elements:
                onclick = elem.get('onclick', '')
                # Extraer parámetros: verFolleto('runFondo','serie','rutAdmin')
                match = re.search(r"verFolleto\('([^']*)',\s*'([^']*)',\s*'([^']*)'\)", onclick)
                if match:
                    run_fondo, serie, rut_admin_found = match.groups()

                    # Guardar el primer rutAdmin encontrado
                    if rut_admin_found and not rut_admin:
                        rut_admin = rut_admin_found
                        logger.info(f"[CMF] ✅ rutAdmin extraído: {rut_admin}")

                    # Agregar serie única
                    if serie and serie not in [f['serie'] for f in folletos]:
                        folletos.append({
                            'serie': serie,
                            'runFondo': run_fondo,
                            'rutAdmin': rut_admin_found,
                            'encontrado': True
                        })
                        logger.debug(f"[CMF] Folleto encontrado: Serie={serie}, runFondo={run_fondo}, rutAdmin={rut_admin_found}")

            # MÉTODO 2 (fallback): Buscar en tabla si no encontramos con onclick
            if not folletos:
                texto_folletos = soup.find(string=re.compile('Folletos Informativos.*VIGENTES', re.IGNORECASE))

                if texto_folletos:
                    tabla = texto_folletos.find_parent('table')
                    if not tabla:
                        elemento_actual = texto_folletos.parent
                        for _ in range(10):
                            if elemento_actual:
                                tabla = elemento_actual.find_next('table')
                                if tabla:
                                    break
                                elemento_actual = elemento_actual.parent

                    if tabla:
                        filas = tabla.find_all('tr')

                        for fila in filas:
                            celdas = fila.find_all('td')

                            if len(celdas) >= 4:
                                icono_doc = fila.find('img', src=re.compile('doc\\.gif', re.IGNORECASE))

                                if icono_doc:
                                    serie = None
                                    fecha_envio = None

                                    for i, celda in enumerate(celdas):
                                        texto = celda.get_text().strip()

                                        if re.match(r'\d{2}/\d{2}/\d{4}', texto):
                                            if not fecha_envio:
                                                fecha_envio = texto

                                        if texto and len(texto) < 20 and texto.isupper():
                                            serie = texto

                                    if serie or fecha_envio:
                                        folletos.append({
                                            'serie': serie or 'UNICA',
                                            'fecha_envio': fecha_envio,
                                            'encontrado': True
                                        })
                                        logger.debug(f"[CMF] Folleto encontrado (método tabla): Serie={serie}, Fecha={fecha_envio}")
###toda esta parte se puede optimizar mas no me gustan tantos ifs y demas
            if not folletos:
                logger.warning("[CMF] No se encontraron folletos, intentando serie UNICA")
                folletos = [{'serie': 'UNICA', 'fecha_envio': None, 'encontrado': False}]

            logger.info(f"[CMF] Total folletos encontrados: {len(folletos)}, rutAdmin: {rut_admin}")
            return folletos, rut_admin

        except Exception as e:
            logger.error(f"[CMF] Error extrayendo folletos: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return [], None

    def _extract_rut_base(self, run: str) -> str:
        """
        Extraer RUT base del RUN (sin guión ni dígito verificador)
        Ejemplo: "10446-9" -> "10446"
        """
        if not run:
            return ""
        # Remover guión y dígito verificador
        rut_base = run.split('-')[0] if '-' in run else run
        return rut_base.strip()

    def _download_pdf_from_cmf_improved(self, rut: str, run_completo: str = None) -> Optional[str]:
        """
        Método mejorado: Usar Selenium para acceder a la página de folletos y descargar PDF.

        Args:
            rut (str): RUT del fondo sin guión ni dígito verificador (ej: "8638")
            run_completo (str): RUN completo con guión (ej: "8638-K")

        Returns:
            Path al PDF descargado o None
        """
        try:
            # FIX: Validate RUT parameter to prevent NoneType errors
            if not rut or not isinstance(rut, str):
                logger.warning(f"[CMF PDF] RUT inválido recibido: {rut}")
                return None

            logger.info(f"[CMF PDF SELENIUM] Iniciando descarga para RUT: {rut}")

            # VERIFICAR CACHÉ PRIMERO
            cached_pdf = self._get_cached_pdf(rut, "UNICA")
            if cached_pdf:
                logger.info(f"[CACHE] ✓ PDF encontrado en caché")
                return cached_pdf

            self.cache_stats['downloads'] += 1

            # PASO 1: Obtener URL con pestaña de folletos (pestania=68)
            page_url = self._get_cmf_page_with_params(rut, pestania="68")

            if not page_url:
                logger.warning(f"[CMF PDF] ❌ No se encontró URL para RUT {rut}")
                return None

            logger.info(f"[CMF PDF] ✓ URL folletos: {page_url[:80]}...")

            # PASO 2: Usar Selenium para cargar la página y extraer PDF
            # TODO: Por ahora intentamos con requests/BeautifulSoup
            # Si no funciona, implementar Selenium
            pdf_path = self._download_pdf_with_selenium(page_url, rut, run_completo)

            if pdf_path:
                logger.info(f"[CMF PDF] ✅ PDF descargado exitosamente")
                # Guardar en caché
                self._save_to_cache(rut, "UNICA", pdf_path)
                return pdf_path
            else:
                logger.warning(f"[CMF PDF] ❌ No se pudo descargar PDF")
                return None

        except Exception as e:
            logger.error(f"[CMF PDF MEJORADO] Error: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None

    def _download_pdf_with_selenium(self, page_url: str, rut: str, run_completo: str = None) -> Optional[str]:
        """
        Usar Selenium para acceder a la página de folletos y descargar el PDF.

        Args:
            page_url (str): URL de la página con pestania=68 (folletos)
            rut (str): RUT del fondo
            run_completo (str): RUN completo con guión

        Returns:
            Path al PDF descargado o None
        """
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from webdriver_manager.chrome import ChromeDriverManager
            import time

            logger.info(f"[SELENIUM] Iniciando navegador Chrome headless...")

            # Configurar Chrome en modo headless
            chrome_options = Options()
            chrome_options.add_argument('--headless=new')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36')

            # Set Chrome binary location (cross-platform)
            # Check environment variable first, then fallback to platform defaults
            chrome_binary = os.getenv('CHROME_BINARY_PATH')

            if not chrome_binary:
                # Auto-detect based on platform
                import platform
                system = platform.system()

                if system == 'Darwin':  # macOS
                    chrome_binary = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
                elif system == 'Linux':
                    # Try common Linux locations
                    for path in ['/usr/bin/google-chrome', '/usr/bin/chromium-browser', '/usr/bin/chromium']:
                        if os.path.exists(path):
                            chrome_binary = path
                            break
                elif system == 'Windows':
                    # Try common Windows locations
                    for path in [
                        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
                        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'
                    ]:
                        if os.path.exists(path):
                            chrome_binary = path
                            break

            if chrome_binary and os.path.exists(chrome_binary):
                chrome_options.binary_location = chrome_binary
                logger.info(f"[SELENIUM] Using Chrome binary: {chrome_binary}")
            else:
                logger.warning(f"[SELENIUM] Chrome binary not found, using system default")

            # Directorio de descargas
            download_dir = os.path.abspath('temp')
            os.makedirs(download_dir, exist_ok=True)

            # FIX CRITICO: Limpiar archivos .crdownload antiguos que pueden interferir
            try:
                crdownload_files = [f for f in os.listdir(download_dir) if f.endswith('.crdownload')]
                if crdownload_files:
                    logger.warning(f"[SELENIUM] Limpiando {len(crdownload_files)} archivos .crdownload antiguos...")
                    for f in crdownload_files:
                        try:
                            os.remove(os.path.join(download_dir, f))
                        except:
                            pass
            except Exception as e:
                logger.debug(f"[SELENIUM] Error limpiando .crdownload: {e}")

            prefs = {
                'download.default_directory': download_dir,
                'download.prompt_for_download': False,
                'plugins.always_open_pdf_externally': True  # Descargar PDF en lugar de abrirlo
            }
            chrome_options.add_experimental_option('prefs', prefs)

            # Inicializar driver (cross-platform)
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            logger.info(f"[SELENIUM] ✓ Chrome started")

            try:
                logger.info(f"[SELENIUM] Navegando a: {page_url[:80]}...")
                driver.get(page_url)

                # Esperar que cargue la página
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )

                page_title = driver.title
                logger.info(f"[SELENIUM] ✓ Page loaded: {page_title}")

                # IMPROVED: Wait for JavaScript and AJAX to fully load
                logger.info(f"[SELENIUM] Waiting for JavaScript and AJAX to load...")

                # Wait for tabs element
                try:
                    WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located((By.ID, "tabs"))
                    )
                    logger.info(f"[SELENIUM] ✓ Tabs element loaded")
                except:
                    logger.warning(f"[SELENIUM] ⚠️ Timeout waiting for tabs element")

                # Wait for jQuery/AJAX to complete (if page uses jQuery)
                try:
                    WebDriverWait(driver, 15).until(
                        lambda d: d.execute_script('return typeof jQuery != "undefined" ? jQuery.active == 0 : true')
                    )
                    logger.info(f"[SELENIUM] ✓ AJAX requests completed")
                except:
                    logger.debug(f"[SELENIUM] jQuery not detected or AJAX check failed")

                # Wait for document ready state
                try:
                    WebDriverWait(driver, 10).until(
                        lambda d: d.execute_script('return document.readyState') == 'complete'
                    )
                    logger.info(f"[SELENIUM] ✓ Document ready state: complete")
                except:
                    logger.warning(f"[SELENIUM] ⚠️ Document ready state check failed")

                # Scroll to load lazy content and activate tab navigation
                logger.info(f"[SELENIUM] Scrolling and activating content...")
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)
                driver.execute_script("window.scrollTo(0, 0);")  # Scroll back to top
                time.sleep(2)  # Wait for any lazy-loaded content

                # Try to activate the "Folletos" tab if it exists
                try:
                    # Common tab activation patterns
                    tab_activation_scripts = [
                        "document.querySelector('a[href*=\"pestania=68\"]').click();",
                        "document.querySelector('a[onclick*=\"pestania=68\"]').click();",
                        "$('a[href*=\"pestania=68\"]').click();",  # jQuery version
                    ]

                    for script in tab_activation_scripts:
                        try:
                            driver.execute_script(script)
                            logger.info(f"[SELENIUM] ✓ Tab 'Folletos' activado con script")
                            time.sleep(2)  # Wait for tab content to load
                            break
                        except:
                            continue
                except Exception as e:
                    logger.debug(f"[SELENIUM] No se pudo activar tab Folletos automáticamente: {e}")

                # FIX 3.1: Élargir selectors con fallbacks múltiples
                logger.info(f"[SELENIUM] Looking for PDF links (múltiples selectors)...")

                # Lista de selectores en orden de prioridad
                selectors = [
                    "//a[contains(@onclick, 'verFolleto') or contains(@onclick, 'abrirFolleto')]",
                    "//button[contains(@onclick, 'verFolleto') or contains(@onclick, 'abrirFolleto')]",
                    "//a[contains(@href, '.pdf')]",
                    "//*[contains(text(), 'Folleto') or contains(text(), 'FOLLETO')]/ancestor::a",
                    "//a[contains(@class, 'folleto')]"
                ]

                pdf_links = []
                selector_usado = None

                for selector in selectors:
                    try:
                        pdf_links = driver.find_elements(By.XPATH, selector)
                        if pdf_links:
                            selector_usado = selector
                            logger.info(f"[SELENIUM] ✓ Encontrados {len(pdf_links)} enlaces con selector: {selector[:60]}...")
                            break
                    except Exception as e:
                        logger.debug(f"[SELENIUM] Selector falló: {selector[:60]}... - {e}")
                        continue

                if pdf_links:
                    logger.info(f"[SELENIUM] ✓ Encontrados {len(pdf_links)} enlaces potenciales")

                    # CRITICAL FIX: Filter links to find the CORRECT one for this RUT/serie
                    # When there are multiple links (e.g., 226), we need to find the right one
                    correct_link = None

                    if len(pdf_links) > 1:
                        logger.info(f"[SELENIUM] Múltiples enlaces encontrados, filtrando por RUT {rut}...")

                        # Strategy 1: Find link whose onclick contains our RUT
                        for link in pdf_links:
                            onclick = link.get_attribute('onclick') or ''
                            href = link.get_attribute('href') or ''

                            # Check if onclick contains our RUT
                            if rut in onclick or rut in href:
                                correct_link = link
                                logger.info(f"[SELENIUM] ✓ Enlace correcto encontrado (contiene RUT {rut})")
                                break

                        # Strategy 2: If no match, try to find by proximity (link text or parent text)
                        if not correct_link:
                            for link in pdf_links:
                                # Get surrounding text
                                try:
                                    parent_text = link.find_element(By.XPATH, '..').text
                                    if rut in parent_text:
                                        correct_link = link
                                        logger.info(f"[SELENIUM] ✓ Enlace encontrado por texto cercano (RUT {rut})")
                                        break
                                except:
                                    pass

                    # Fallback: use first link if no specific match found
                    if not correct_link:
                        if len(pdf_links) > 1:
                            logger.warning(f"[SELENIUM] ⚠️ No se encontró enlace específico para RUT {rut}, usando primero de {len(pdf_links)}")
                        correct_link = pdf_links[0]

                    first_link = correct_link
                    pdf_url = first_link.get_attribute('href') or 'javascript:void(0)'
                    onclick_attr = first_link.get_attribute('onclick') or 'N/A'

                    logger.info(f"[SELENIUM] Usando enlace - href: {pdf_url[:60]}...")
                    logger.info(f"[SELENIUM] Usando enlace - onclick: {onclick_attr[:60]}...")

                    # FIX CRITICO: Eliminar PDF anterior del mismo RUT si existe
                    # Esto evita conflictos y asegura que siempre tenemos la versión más reciente
                    expected_final_name = f"folleto_{rut}.pdf"
                    expected_final_path = os.path.join(download_dir, expected_final_name)
                    if os.path.exists(expected_final_path):
                        logger.warning(f"[SELENIUM] Eliminando PDF anterior: {expected_final_name}")
                        try:
                            os.remove(expected_final_path)
                        except Exception as e:
                            logger.error(f"[SELENIUM] No se pudo eliminar PDF anterior: {e}")

                    # FIX CRITICO: Capturar estado del directorio ANTES del click
                    # Esto permite detectar solo archivos NUEVOS descargados
                    files_before_download = set(os.listdir(download_dir))
                    logger.info(f"[SELENIUM] Archivos existentes antes del click: {len(files_before_download)}")

                    # Click triggers AJAX POST and window.open(pdf_url)
                    logger.info(f"[SELENIUM] Executing click...")
                    driver.execute_script("arguments[0].click();", first_link)

                    # Wait for download with polling - PASAR existing_files para evitar detectar PDFs viejos
                    pdf_path = _wait_for_download_complete(download_dir, timeout=60, existing_files=files_before_download)

                    if pdf_path:
                        latest_file = pdf_path

                        # Renombrar con formato estándar
                        final_name = f"folleto_{rut}.pdf"
                        final_path = os.path.join(download_dir, final_name)

                        # FIX: Solo renombrar si el archivo descargado NO es el archivo final
                        # Esto evita errores cuando latest_file == final_path
                        if latest_file != final_path:
                            # Si el destino ya existe, sobrescribir
                            if os.path.exists(final_path):
                                logger.warning(f"[SELENIUM] Sobrescribiendo PDF existente: {final_name}")
                                os.remove(final_path)

                            os.rename(latest_file, final_path)
                            logger.info(f"[SELENIUM] PDF renombrado: {os.path.basename(latest_file)} -> {final_name}")
                        else:
                            logger.info(f"[SELENIUM] PDF ya tiene el nombre correcto: {final_name}")

                        logger.info(f"[SELENIUM] ✅ PDF downloaded: {final_path}")
                        return final_path
                    else:
                        logger.warning(f"[SELENIUM] ❌ Download failed or timeout")
                        return None
                else:
                    # FIX 3.4: Fallback BeautifulSoup si XPath falla
                    logger.warning(f"[SELENIUM] ❌ XPath no encontró enlaces, intentando fallback BeautifulSoup...")

                    try:
                        page_source = driver.page_source
                        soup = BeautifulSoup(page_source, 'html.parser')

                        # Buscar enlaces con onclick que contenga 'folleto' o 'verFolleto'
                        links_onclick = soup.find_all(['a', 'button'], onclick=re.compile(r'(ver|abrir)?[Ff]olleto', re.IGNORECASE))

                        if links_onclick:
                            logger.info(f"[SELENIUM BEAUTIFULSOUP] ✓ Encontrados {len(links_onclick)} enlaces con BeautifulSoup")

                            # Intentar extraer parámetros del onclick
                            for link in links_onclick:
                                onclick = link.get('onclick', '')
                                logger.debug(f"[SELENIUM BEAUTIFULSOUP] onclick encontrado: {onclick[:100]}...")

                                # Patrón para extraer parámetros verFolleto('run', 'serie', 'rutAdmin')
                                match = re.search(r"verFolleto\('([^']*)',\s*'([^']*)',\s*'([^']*)'\)", onclick)
                                if match:
                                    logger.info(f"[SELENIUM BEAUTIFULSOUP] Parámetros extraídos, pero descarga directa no implementada")
                                    # TODO: Implementar descarga directa con parámetros extraídos
                                    break

                        # También buscar enlaces directos a PDF
                        links_pdf = soup.find_all('a', href=re.compile(r'\.pdf$', re.IGNORECASE))
                        if links_pdf:
                            logger.info(f"[SELENIUM BEAUTIFULSOUP] ✓ Encontrados {len(links_pdf)} enlaces directos PDF")
                            # TODO: Implementar descarga de enlaces directos

                    except Exception as e:
                        logger.error(f"[SELENIUM BEAUTIFULSOUP] Error en fallback: {e}")

                    # IMPROVED: Guardar FULL PAGE screenshot para debugging
                    screenshot_path = f"temp/debug_screenshot_{rut}.png"

                    try:
                        # Method 1: Try full page screenshot (requires specific driver support)
                        original_size = driver.get_window_size()
                        required_width = driver.execute_script('return document.body.parentNode.scrollWidth')
                        required_height = driver.execute_script('return document.body.parentNode.scrollHeight')

                        # Set window to full page size
                        driver.set_window_size(required_width, required_height)

                        # Wait for resize
                        time.sleep(0.5)

                        # Take screenshot
                        driver.save_screenshot(screenshot_path)

                        # Restore original size
                        driver.set_window_size(original_size['width'], original_size['height'])

                        logger.info(f"[SELENIUM] Full page screenshot guardado ({required_width}x{required_height}px): {screenshot_path}")

                    except Exception as e:
                        # Fallback: regular screenshot if full page fails
                        logger.warning(f"[SELENIUM] No se pudo tomar screenshot de página completa: {e}")
                        driver.save_screenshot(screenshot_path)
                        logger.info(f"[SELENIUM] Screenshot regular guardado: {screenshot_path}")

                    # Also save page HTML for deeper debugging
                    try:
                        html_path = f"temp/debug_page_{rut}.html"
                        with open(html_path, 'w', encoding='utf-8') as f:
                            f.write(driver.page_source)
                        logger.info(f"[SELENIUM] HTML guardado para debugging: {html_path}")
                    except Exception as e:
                        logger.debug(f"[SELENIUM] No se pudo guardar HTML: {e}")

                    return None

            finally:
                driver.quit()
                logger.info(f"[SELENIUM] Navegador cerrado")

        except ImportError as e:
            logger.error(f"[SELENIUM] ❌ Error de importación: {e}")
            logger.error(f"[SELENIUM] Instalar dependencias: pip install selenium webdriver-manager")
            return None
        except Exception as e:
            logger.error(f"[SELENIUM] Error: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None

    def _download_pdf_from_cmf(self, rut: str, run_completo: str = None, serie: str = "UNICA", rut_admin: str = None) -> Optional[str]:
        """
        Descargar PDF de Folleto Informativo desde CMF Chile

        El proceso es en 2 pasos:
        1. POST a ver_folleto_fm.php que retorna la URL del PDF viewer
        2. GET a esa URL del PDF viewer para descargar el PDF real

        Args:
            rut (str): RUT del fondo sin guión (ej: "10441")
            run_completo (str): RUN completo con guión si está disponible (ej: "10441-8")
            serie (str): Serie del fondo (por defecto "UNICA")
            rut_admin (str): RUT de la administradora (requerido para descarga exitosa)

        Returns:
            str: Path al archivo PDF descargado, o None si falla
        """
        try:
            logger.info(f"[CMF PDF] Descargando folleto informativo para RUT: {rut}, Serie: {serie}, RutAdmin: {rut_admin}")

            # VERIFICAR CACHÉ PRIMERO
            cached_pdf = self._get_cached_pdf(rut, serie)
            if cached_pdf:
                logger.info(f"[CACHE] PDF encontrado en caché, evitando descarga")
                return cached_pdf

            # Si no está en caché, proceder con descarga
            logger.info(f"[CACHE] PDF no encontrado en caché, descargando desde CMF...")
            self.cache_stats['downloads'] += 1

            # Crear carpeta temp si no existe
            os.makedirs('temp', exist_ok=True)

            # PASO 1: POST request para obtener la URL del PDF viewer
            # CORRECCION: URL correcta del endpoint (antes: /institucional/inc/)
            # Probando SIN /pages/ (cmf_monitor.py línea 308 usa sin /pages/)
            pdf_request_url = "https://www.cmfchile.cl/603/ver_folleto_fm.php"

            # Headers críticos para que funcione la descarga
            # CORRECCION: Simplificados, removiendo Content-Type y X-Requested-With que pueden causar rechazo
            # FIX 1.1: Proteger concatenation RUT en Referer header (evitar NoneType crash)
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'es-CL,es;q=0.9',
                'Origin': 'https://www.cmfchile.cl',
                'Referer': f'https://www.cmfchile.cl/institucional/mercados/entidad.php?mercado=V&rut={rut or ""}'
            }

            # CORRECCION: Usar run_completo si está disponible, sino usar rut
            # CMF necesita el RUN con guión (ej: "10446-9" o "76.113.534-5")
            run_fondo_value = run_completo if run_completo else rut

            # Parámetros según el código JavaScript de CMF
            # CORRECCION: Cambiar a snake_case y agregar pestania=68
            payload = {
                'pestania': '68',  # Indica sección de folletos informativos (CRÍTICO)
                'run_fondo': run_fondo_value,  # Usar RUN completo con guión
                'serie': serie,
                'rut_admin': rut_admin or ''  # RUT de la administradora (CRÍTICO)
            }

            logger.info(f"[CMF PDF] PASO 1 - POST a {pdf_request_url}")
            logger.info(f"[CMF PDF] Payload: {payload}")

            response = self.session.post(pdf_request_url, data=payload, headers=headers, timeout=60)

            logger.info(f"[CMF PDF] Response status: {response.status_code}")
            logger.info(f"[CMF PDF] Response URL: {response.url}")

            if response.status_code != 200:
                logger.warning(f"[CMF PDF] Error HTTP {response.status_code} en PASO 1")
                logger.warning(f"[CMF PDF] Response text (primeros 500 chars): {response.text[:500]}")
                return None

            # La respuesta debe ser un path relativo al PDF viewer o "ERROR"
            pdf_viewer_path = response.text.strip()

            logger.debug(f"[CMF PDF] Respuesta PASO 1: {pdf_viewer_path[:200]}")

            # CORRECCION: Validar que no sea HTML de error antes de intentar usarla como path
            if pdf_viewer_path.startswith('<!DOCTYPE') or pdf_viewer_path.startswith('<html'):
                logger.error(f"[CMF PDF] Respuesta HTML recibida en lugar de path. Primeros 500 chars: {pdf_viewer_path[:500]}")
                return None

            if pdf_viewer_path == 'ERROR' or not pdf_viewer_path:
                logger.warning(f"[CMF PDF] No se encontró folleto para RUT {rut}, Serie {serie}")
                return None

            # PASO 2: Descargar el PDF desde la URL del viewer
            logger.debug(f"[CMF PDF] PASO 2 - Descargando PDF desde viewer: {pdf_viewer_path}")

            # FIX 1.2: Validar pdf_viewer_path antes de construir URL (evitar NoneType crash)
            if not pdf_viewer_path or pdf_viewer_path == 'ERROR':
                logger.warning(f"[CMF PDF] Path de viewer inválido: {pdf_viewer_path}")
                return None

            # Construir URL completa (siempre es un path relativo que comienza con /)
            if pdf_viewer_path.startswith('/'):
                pdf_url = f"https://www.cmfchile.cl{pdf_viewer_path}"
            else:
                pdf_url = f"https://www.cmfchile.cl/{pdf_viewer_path}"

            logger.info(f"[CMF PDF] URL completa del PDF viewer: {pdf_url}")

            # Descargar el PDF con headers de navegador
            pdf_response = self.session.get(pdf_url, headers=headers, timeout=60, allow_redirects=True)

            if pdf_response.status_code == 200:
                # Verificar que es un PDF
                content_type = pdf_response.headers.get('Content-Type', '')

                if 'pdf' in content_type.lower() or pdf_response.content[:4] == b'%PDF':
                    # Guardar PDF en temp
                    pdf_path = f'temp/fondo_{rut}_{serie}.pdf'
                    with open(pdf_path, 'wb') as f:
                        f.write(pdf_response.content)

                    file_size = len(pdf_response.content)
                    logger.info(f"[CMF PDF] ✅ PDF descargado exitosamente: {pdf_path} ({file_size} bytes)")

                    # GUARDAR EN CACHÉ
                    if self._save_to_cache(rut, serie, pdf_path):
                        logger.info(f"[CACHE] PDF guardado en caché para futuras consultas")

                    return pdf_path
                else:
                    logger.warning(f"[CMF PDF] La respuesta no es un PDF válido. Content-Type: {content_type}")
                    logger.debug(f"[CMF PDF] Primeros 500 bytes: {pdf_response.content[:500]}")
                    return None
            else:
                logger.warning(f"[CMF PDF] Error HTTP {pdf_response.status_code} al descargar PDF")
                return None

        except Exception as e:
            logger.error(f"[CMF PDF] Error descargando PDF: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None

    def _extract_extended_data_from_pdf(self, pdf_path: str) -> Dict:
        """
        Extraer datos EXTENDIDOS de un PDF de Folleto Informativo

        VERSIÓN MEJORADA con más patrones de extracción:
        - Tipo de fondo (conservador/balanceado/agresivo/moderado/liquidez)
        - Perfil de riesgo mejorado (bajo/medio/alto + escalas R1-R7)
        - Horizonte de inversión (corto/mediano/largo plazo)
        - Comisiones (administración y rescate)
        - Rentabilidad histórica (12m, 24m, 36m)
        - Patrimonio del fondo
        - Composición detallada de portafolio
        - Nivel de confianza en la extracción

        Args:
            pdf_path (str): Ruta al archivo PDF

        Returns:
            Dict con datos extendidos extraídos
        """
        try:
            logger.info(f"[PDF EXTENDED] Extrayendo datos extendidos de: {pdf_path}")

            # CRITICAL FIX: Extract RUT/RUN from PDF filename, not from content
            # The filename IS the authoritative RUT/RUN (e.g., "fondo_10446_UNICA.pdf" or "9108_UNICA.pdf")
            import os
            filename = os.path.basename(pdf_path)
            rut_from_filename = None
            serie_from_filename = None

            # Pattern 1: fondo_{RUT}_{SERIE}.pdf (e.g., "fondo_10446_UNICA.pdf")
            # Pattern 2: {RUT}_{SERIE}.pdf (e.g., "9108_UNICA.pdf")
            filename_patterns = [
                r'fondo_(\d+)(?:_([A-Z]+))?\.pdf',  # fondo_10446_UNICA.pdf
                r'(\d+)_([A-Z]+)\.pdf',              # 9108_UNICA.pdf
                r'(\d+)\.pdf',                       # 9108.pdf
            ]

            for pattern in filename_patterns:
                filename_match = re.search(pattern, filename, re.IGNORECASE)
                if filename_match:
                    rut_from_filename = filename_match.group(1)
                    serie_from_filename = filename_match.group(2) if len(filename_match.groups()) >= 2 and filename_match.group(2) else 'UNICA'
                    logger.info(f"[PDF RUT] Extraído del filename: RUT={rut_from_filename}, Serie={serie_from_filename}")
                    break

            if not rut_from_filename:
                logger.warning(f"[PDF RUT] No se pudo extraer RUT del filename: {filename}")

            resultado = {
                # CRITICAL: RUT/RUN from filename (authoritative source)
                'rut': rut_from_filename,
                'run': rut_from_filename,  # Same as RUT in most cases
                'serie_fondo': serie_from_filename,

                # Required fields from instructions
                'administradora': None,
                'descripcion_fondo': None,
                'tiempo_rescate': None,
                'moneda': None,
                'patrimonio_fondo': None,
                'patrimonio_sede': None,
                'TAC': None,
                'TAC_industria': None,
                'inversion_minima': None,
                'rentabilidades_nominales': {},
                'mejores_rentabilidades': {},
                'peores_rentabilidades': {},
                'rentabilidades_anualizadas': {},

                # Existing fields
                'tipo_fondo': None,
                'perfil_riesgo': None,
                'perfil_riesgo_escala': None,  # R1-R7
                'tolerancia_riesgo': None,  # NUEVO: Baja/Media/Alta
                'perfil_inversionista_ideal': None,  # NUEVO: Conservador/Moderado/Agresivo
                'horizonte_inversion': None,
                'horizonte_inversion_meses': None,
                'comision_administracion': None,
                'comision_rescate': None,
                'fondo_rescatable': None,  # NUEVO: True/False
                'plazos_rescates': None,  # NUEVO: "X días"
                'duracion': None,  # NUEVO: "X años" o "Indefinido"
                'monto_minimo': None,  # NUEVO: "$ XXX CLP" o "XX UF"
                'monto_minimo_moneda': None,  # NUEVO: CLP, UF, USD
                'monto_minimo_valor': None,  # NUEVO: valor numérico
                'rentabilidad_12m': None,
                'rentabilidad_24m': None,
                'rentabilidad_36m': None,
                'patrimonio': None,
                'patrimonio_moneda': None,
                'composicion_portafolio': [],
                'composicion_detallada': [],
                'extraction_confidence': 'low',
                'texto_completo': '',
                'pdf_procesado': True
            }

            # Abrir PDF con pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                texto_completo = ""
                for page in pdf.pages:
                    texto_completo += page.extract_text() or ""

                logger.debug(f"[PDF EXTENDED] Extraídas {len(pdf.pages)} páginas, {len(texto_completo)} caracteres")

                # FIX 5.2 & 5.4: OCR fallback si extracción text es muy pobre
                if len(texto_completo.strip()) < 100:
                    logger.warning(f"[PDF OCR] Text extraction pobre ({len(texto_completo)} chars), intentando OCR fallback...")

                    # FIX 5.1: Verificar si pytesseract está instalado
                    try:
                        from pdf2image import convert_from_path
                        import pytesseract

                        # FIX 5.3: Convertir solo primeras 3 páginas con dpi=300
                        logger.info(f"[PDF OCR] Convirtiendo primeras 3 páginas (dpi=300)...")
                        images = convert_from_path(
                            pdf_path,
                            dpi=300,
                            first_page=1,
                            last_page=min(3, len(pdf.pages))
                        )

                        texto_ocr = ""
                        for i, img in enumerate(images):
                            logger.debug(f"[PDF OCR] Procesando página {i+1}/{len(images)}...")
                            page_text = pytesseract.image_to_string(img, lang='spa')
                            texto_ocr += f"\n--- OCR PÁGINA {i+1} ---\n{page_text}"

                        if len(texto_ocr.strip()) > len(texto_completo.strip()):
                            texto_completo = texto_ocr
                            logger.info(f"[PDF OCR] ✅ OCR exitoso: {len(texto_completo)} chars extraídos")
                            resultado['extraction_method'] = 'OCR'
                        else:
                            logger.warning(f"[PDF OCR] OCR no mejoró extracción ({len(texto_ocr)} vs {len(texto_completo)})")
                            resultado['extraction_method'] = 'pdfplumber (poor)'

                    except ImportError:
                        logger.warning(f"[PDF OCR] pytesseract/pdf2image no instalados - install: pip install pytesseract pdf2image")
                        logger.warning(f"[PDF OCR] También instalar Tesseract: brew install tesseract poppler (macOS)")
                        resultado['extraction_method'] = 'pdfplumber (poor, OCR unavailable)'

                    except Exception as e:
                        logger.error(f"[PDF OCR] Error en OCR fallback: {type(e).__name__}: {e}")
                        resultado['extraction_method'] = 'pdfplumber (poor, OCR failed)'
                else:
                    # FIX 5.4: Logger método de extracción
                    logger.info(f"[PDF EXTRACTION] ✅ pdfplumber exitoso: {len(texto_completo)} chars")
                    resultado['extraction_method'] = 'pdfplumber'

                resultado['texto_completo'] = texto_completo
                texto_lower = texto_completo.lower()
                lineas = texto_completo.split('\n')

                # Contador de campos extraídos para calcular confianza
                campos_extraidos = 0
                campos_totales = 20  # Aumentado para incluir nuevos campos críticos

                # ============================================================
                # EXTRACTION 0: SERIE_FONDO from PDF content (if not from filename)
                # ============================================================
                # FIX: If serie not found in filename or is generic, try PDF content
                # More flexible patterns to catch lowercase, mixed case, alphanumeric
                if not serie_from_filename or serie_from_filename == 'UNICA':
                    serie_patterns = [
                        (r'Serie[:\s]+([A-Za-z0-9]+)', 'direct'),
                        (r'Clase[:\s]+([A-Za-z0-9]+)', 'clase'),
                        (r'Tipo\s+de\s+Cuota[:\s]+([A-Za-z0-9]+)', 'tipo_cuota'),
                        (r'Cuota\s+Serie[:\s]+([A-Za-z0-9]+)', 'cuota_serie'),
                        # Additional patterns for table formats
                        (r'(?:Serie|Clase)\s*[\|\s]+([A-Za-z0-9]+)', 'table_format'),
                    ]

                    for pattern, pattern_name in serie_patterns:
                        match = re.search(pattern, texto_completo, re.IGNORECASE)
                        if match:
                            serie_from_content = match.group(1).upper().strip()
                            # Only override if found specific series (not generic keywords)
                            if serie_from_content not in ['UNICA', 'GENERAL', 'SERIE', 'CLASE', 'TIPO']:
                                resultado['serie_fondo'] = serie_from_content
                                campos_extraidos += 1
                                logger.info(f"[PDF] Serie extraída del contenido ({pattern_name}): {serie_from_content}")
                                break

                # ============================================================
                # EXTRACTION 1: ADMINISTRADORA (NEW - CRITICAL)
                # ============================================================
                # Extract fund administrator name from various sections
                # FIX: PDFs have admin name on NEXT LINE after "Administradora:", not same line
                administradora_patterns = [
                    # Pattern 1: Multi-line capture after "Administradora:" label
                    (r'Administradora[:\s]*\n\s*([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\s\.]+(?:S\.A\.|SA|AGF)[^\n]*(?:\n[A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\s\.]+)*)', 'multiline_after_label'),
                    # Pattern 2: Direct capture of company name with AGF suffix
                    (r'([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\s\.]+ADMINISTRADORA\s+GENERAL\s+DE\s+FONDOS)', 'agf_full'),
                    (r'([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\s\.]+(?:S\.A\.|SA)\s+ADMINISTRADORA\s+GENERAL\s+DE\s+FONDOS)', 'sa_agf'),
                    # Pattern 3: Search for company names ending in "S.A. AGF"
                    (r'([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\s\.]+S\.A\.\s+AGF)', 'sa_agf_compact'),
                    # Pattern 4: Old patterns as fallback
                    (r'Razón\s+Social[:\s]+([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\s\.]+(?:S\.A\.|SA|AGF)?)', 'razon_social'),
                    (r'Nombre\s+de\s+la\s+Administradora[:\s]+([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ\s\.]+)', 'nombre'),
                ]

                for pattern, pattern_name in administradora_patterns:
                    match = re.search(pattern, texto_completo, re.IGNORECASE | re.MULTILINE | re.DOTALL)
                    if match:
                        admin_name = match.group(1).strip()
                        # Clean up: remove trailing punctuation, newlines, multiple spaces
                        admin_name = re.sub(r'\n', ' ', admin_name)
                        admin_name = re.sub(r'\s+', ' ', admin_name)
                        admin_name = re.sub(r'[:\.,;]+$', '', admin_name).strip()

                        # Remove garbage prefixes that appear before actual admin name
                        # E.g., "Rentabilidad en UF CREDICORP CAPITAL..." -> "CREDICORP CAPITAL..."
                        garbage_prefixes = [
                            r'^Rentabilidad\s+en\s+\w+\s+',
                            r'^Información\s+General\s+',
                            r'^Folleto\s+Informativo\s+',
                        ]
                        for prefix_pattern in garbage_prefixes:
                            admin_name = re.sub(prefix_pattern, '', admin_name, flags=re.IGNORECASE)

                        # Validation: must contain "AGF" or "ADMINISTRADORA" or end with S.A.
                        if (len(admin_name) > 10 and
                            ('AGF' in admin_name.upper() or
                             'ADMINISTRADORA' in admin_name.upper() or
                             admin_name.endswith('S.A.') or
                             admin_name.endswith('SA'))):
                            resultado['administradora'] = admin_name
                            campos_extraidos += 1
                            logger.info(f"[PDF] Administradora encontrada ({pattern_name}): {admin_name}")
                            break

                # ============================================================
                # EXTRACTION 2: DESCRIPCION_FONDO (NEW - CRITICAL)
                # ============================================================
                # Extract fund description from objective/policy sections
                # FIX: PDFs have "Objetivo" header, then text on next lines (possibly multi-line)
                descripcion_patterns = [
                    # Pattern 1: Capture multiple lines after "Objetivo"
                    (r'Objetivo[:\s]*\n\s*([^\n]+(?:\n[^\n]+){0,5})', 'objetivo_multiline'),
                    # Pattern 2: Direct "Objetivo del Fondo" with text after
                    (r'Objetivo\s+del\s+Fondo[:\s]*\n\s*([^\n]+(?:\n[^\n]+){0,5})', 'objetivo_fondo'),
                    # Pattern 3: Description label
                    (r'Descripci[oó]n[:\s]*\n\s*([^\n]+(?:\n[^\n]+){0,3})', 'descripcion'),
                    # Pattern 4: Policy label
                    (r'Pol[ií]tica\s+de\s+Inversi[oó]n[:\s]*\n\s*([^\n]+(?:\n[^\n]+){0,3})', 'politica'),
                    # Pattern 5: Freeform capture of objective sentences
                    (r'(?:El\s+objetivo\s+principal\s+del\s+Fondo|El\s+fondo\s+tiene\s+como\s+objetivo|Este\s+fondo)\s+[^\n.]{30,400}', 'freeform'),
                ]

                for pattern, pattern_name in descripcion_patterns:
                    match = re.search(pattern, texto_completo, re.IGNORECASE | re.DOTALL)
                    if match:
                        descripcion = match.group(1) if pattern_name != 'freeform' else match.group(0)
                        descripcion = descripcion.strip()
                        # Clean: normalize whitespace, remove newlines
                        descripcion = re.sub(r'\s+', ' ', descripcion)
                        # Stop at first period or limit to reasonable length
                        sentences = descripcion.split('.')
                        if len(sentences) > 0:
                            # Take first 1-2 sentences
                            descripcion = '. '.join(sentences[0:2]).strip()
                            if not descripcion.endswith('.'):
                                descripcion += '.'

                        if len(descripcion) > 30:
                            resultado['descripcion_fondo'] = descripcion
                            campos_extraidos += 1
                            logger.info(f"[PDF] Descripción encontrada ({pattern_name}): {descripcion[:100]}...")
                            break

                # ============================================================
                # EXTRACTION 3: MONEDA (NEW - CRITICAL)
                # ============================================================
                # Extract currency denomination from various sections
                moneda_patterns = [
                    (r'Moneda[:\s]+(CLP|USD|UF|EUR|Pesos|D[oó]lares?|Unidades? de Fomento)', 'direct'),
                    (r'Denominaci[oó]n[:\s]+(CLP|USD|UF|EUR|Pesos|D[oó]lares?|Unidades? de Fomento)', 'denominacion'),
                    (r'Expresado en[:\s]+(CLP|USD|UF|EUR|Pesos|D[oó]lares?)', 'expresado'),
                ]

                for pattern, pattern_name in moneda_patterns:
                    match = re.search(pattern, texto_completo, re.IGNORECASE)
                    if match:
                        moneda_raw = match.group(1).upper()
                        # Normalize to standard codes
                        if 'PESO' in moneda_raw or 'CLP' in moneda_raw:
                            resultado['moneda'] = 'CLP'
                        elif 'DOLAR' in moneda_raw or 'DÓLAR' in moneda_raw or 'USD' in moneda_raw:
                            resultado['moneda'] = 'USD'
                        elif 'UF' in moneda_raw or 'UNIDAD' in moneda_raw:
                            resultado['moneda'] = 'UF'
                        elif 'EUR' in moneda_raw:
                            resultado['moneda'] = 'EUR'

                        if resultado.get('moneda'):
                            campos_extraidos += 1
                            logger.info(f"[PDF] Moneda encontrada ({pattern_name}): {resultado['moneda']}")
                            break

                # ============================================================
                # EXTRACTION 4: TIEMPO_RESCATE (NEW - IMPROVED)
                # ============================================================
                # Extract redemption time with flexible patterns
                # FIX: PDFs have "Plazo rescates: A más tardar X días corridos" - need flexibility
                tiempo_rescate_patterns = [
                    # Pattern 1: Flexible match with optional text before number
                    (r'Plazo\s+(?:de\s+)?rescates?[:\s]+.*?(\d+)\s*d[ií]as?', 'plazo_flexible'),
                    # Pattern 2: Standard patterns
                    (r'Plazo\s+(?:de\s+)?Rescate[:\s]+(\d+)\s*d[ií]as?', 'plazo_dias'),
                    (r'Rescate\s+en[:\s]+(\d+)\s*d[ií]as?', 'rescate_en'),
                    # Pattern 3: T+N notation
                    (r'T\+(\d+)', 't_plus'),
                    # Pattern 4: Disponible en
                    (r'Disponible\s+en[:\s]+(\d+)\s*d[ií]as?', 'disponible'),
                    # Pattern 5: Immediate redemption (special case)
                    (r'Rescate\s+inmediato', '0'),
                    (r'Mismo\s+d[ií]a', '0'),
                ]

                for pattern, dias_value in tiempo_rescate_patterns:
                    if isinstance(dias_value, str) and dias_value == '0':
                        # Immediate redemption patterns
                        if re.search(pattern, texto_completo, re.IGNORECASE):
                            resultado['tiempo_rescate'] = '0 días'
                            campos_extraidos += 1
                            logger.info(f"[PDF] Tiempo rescate: inmediato (0 días)")
                            break
                    else:
                        match = re.search(pattern, texto_completo, re.IGNORECASE)
                        if match:
                            dias = match.group(1)
                            resultado['tiempo_rescate'] = f"{dias} días"
                            campos_extraidos += 1
                            logger.info(f"[PDF] Tiempo rescate: {dias} días")
                            break

                # ============================================================
                # EXTRACTION 5: TAC and TAC_INDUSTRIA (NEW - CRITICAL)
                # ============================================================
                # Extract Total Annual Cost (Tasa Anual de Costos)
                tac_patterns = [
                    (r'TAC\s+Serie[:\s]+([\d,\.]+)\s*%', 'tac_serie'),
                    (r'Tasa\s+Anual\s+de\s+Costos[:\s]+([\d,\.]+)\s*%', 'tac_full'),
                    (r'Total\s+Annual\s+Cost[:\s]+([\d,\.]+)\s*%', 'tac_english'),
                ]

                for pattern, pattern_name in tac_patterns:
                    match = re.search(pattern, texto_completo, re.IGNORECASE)
                    if match:
                        try:
                            tac_str = match.group(1).replace(',', '.')
                            tac_value = float(tac_str) / 100  # Convert to decimal
                            resultado['TAC'] = tac_value
                            campos_extraidos += 1
                            logger.info(f"[PDF] TAC encontrado ({pattern_name}): {tac_value:.4f} ({tac_str}%)")
                            break
                        except (ValueError, AttributeError) as e:
                            logger.debug(f"[PDF] Error parseando TAC: {e}")

                # TAC Industria (industry average)
                tac_industria_patterns = [
                    (r'TAC\s+(?:Promedio\s+)?Industria[:\s]+([\d,\.]+)\s*%', 'tac_industria'),
                    (r'Promedio\s+de\s+la\s+Industria[:\s]+([\d,\.]+)\s*%', 'promedio_industria'),
                ]

                for pattern, pattern_name in tac_industria_patterns:
                    match = re.search(pattern, texto_completo, re.IGNORECASE)
                    if match:
                        try:
                            tac_ind_str = match.group(1).replace(',', '.')
                            tac_ind_value = float(tac_ind_str) / 100
                            resultado['TAC_industria'] = tac_ind_value
                            campos_extraidos += 1
                            logger.info(f"[PDF] TAC Industria ({pattern_name}): {tac_ind_value:.4f}")
                            break
                        except (ValueError, AttributeError) as e:
                            logger.debug(f"[PDF] Error parseando TAC industria: {e}")

                # ============================================================
                # EXTRACTION 6: INVERSION_MINIMA (NEW - COMPREHENSIVE)
                # ============================================================
                # Map monto_minimo to inversion_minima for consistency
                # This will be populated by existing monto_minimo extraction logic below
                # We'll map it at the end of extraction

                # ============================================================
                # PATRÓN 1: TIPO DE FONDO (Mejorado)
                # ============================================================
                patrones_tipo = {
                    'Conservador': ['conservador', 'capital garantizado', 'preservation', 'preservación'],
                    'Agresivo': ['agresivo', 'aggressive', 'growth', 'crecimiento', 'accionario'],
                    'Balanceado': ['balanceado', 'balanced', 'mixto', 'mixed', 'moderado'],
                    'Dinámico': ['dinámico', 'dynamic', 'flexible'],
                    'Liquidez': ['liquidez', 'liquidity', 'money market', 'monetario', 'disponible']
                }

                for tipo, keywords in patrones_tipo.items():
                    if any(keyword in texto_lower for keyword in keywords):
                        resultado['tipo_fondo'] = tipo
                        campos_extraidos += 1
                        logger.info(f"[PDF EXTENDED] Tipo de fondo: {tipo}")
                        break

                # ============================================================
                # PATRÓN 2: PERFIL DE RIESGO MEJORADO
                # ============================================================
                # A. Buscar escala R1-R7 (común en fondos chilenos)
                match_r_scale = re.search(r'\bR([1-7])\b', texto_completo)
                if match_r_scale:
                    r_numero = int(match_r_scale.group(1))
                    resultado['perfil_riesgo_escala'] = f'R{r_numero}'

                    # Convertir R1-R7 a categorías bajo/medio/alto
                    if r_numero <= 2:
                        resultado['perfil_riesgo'] = 'Bajo'
                    elif r_numero <= 4:
                        resultado['perfil_riesgo'] = 'Medio'
                    else:
                        resultado['perfil_riesgo'] = 'Alto'

                    campos_extraidos += 1
                    logger.info(f"[PDF EXTENDED] Perfil riesgo: {resultado['perfil_riesgo']} ({resultado['perfil_riesgo_escala']})")

                # B. Buscar palabras clave de riesgo
                if not resultado['perfil_riesgo']:
                    patrones_riesgo = {
                        'Bajo': ['riesgo bajo', 'bajo riesgo', 'conservador', 'risk: low'],
                        'Alto': ['riesgo alto', 'alto riesgo', 'agresivo', 'risk: high'],
                        'Medio': ['riesgo medio', 'riesgo moderado', 'moderado', 'risk: medium']
                    }

                    for nivel, keywords in patrones_riesgo.items():
                        if any(keyword in texto_lower for keyword in keywords):
                            resultado['perfil_riesgo'] = nivel
                            campos_extraidos += 1
                            logger.info(f"[PDF EXTENDED] Perfil riesgo (keywords): {nivel}")
                            break

                # ============================================================
                # PATRÓN 2B: TOLERANCIA AL RIESGO (NUEVO - MEJORADO)
                # ============================================================
                # Buscar tolerancia al riesgo con múltiples variaciones usando regex
                # FIX: Pattern must match "Tolerancia al riesgo: Moderada" with optional colon
                tolerancia_patterns = [
                    (r'Tolerancia\s+al\s+riesgo\s*[:\s]*\s*(Baja|Media|Alta|Moderada|Conservadora|Agresiva)', 'tolerancia_direct'),
                    (r'\btoleranc[ia]+\s+(?:al\s+)?riesgo\s*[:\s]*\s*(baja|media|alta|conservador[a]?|moderad[oa]|agresiv[oa])',
                     'tolerancia_keyword'),
                    (r'\b(conservador[a]?|moderad[oa]|agresiv[oa])\s+(?:perfil|inversionista)',
                     'perfil_keyword'),
                    (r'\bperfil\s+de\s+riesgo\s+(?:es\s+)?(bajo|medio|alto|conservador|moderado|agresivo)',
                     'perfil_riesgo_keyword'),
                    (r'\binversionista[s]?\s+(conservador[es]?|moderado[s]?|agresivo[s]?)',
                     'inversionista_keyword'),
                ]

                for pattern, pattern_name in tolerancia_patterns:
                    match = re.search(pattern, texto_completo, re.IGNORECASE)
                    if match:
                        keyword = match.group(1).lower()

                        # Mapear a categorías estándar
                        if 'conserv' in keyword or 'baj' in keyword:
                            resultado['tolerancia_riesgo'] = 'Baja'
                            resultado['perfil_inversionista_ideal'] = 'Conservador'
                        elif 'moder' in keyword or 'medi' in keyword:
                            resultado['tolerancia_riesgo'] = 'Media'
                            resultado['perfil_inversionista_ideal'] = 'Moderado'
                        elif 'agres' in keyword or 'alt' in keyword:
                            resultado['tolerancia_riesgo'] = 'Alta'
                            resultado['perfil_inversionista_ideal'] = 'Agresivo'

                        if resultado.get('tolerancia_riesgo'):
                            campos_extraidos += 1
                            logger.info(f"[PDF] Tolerancia al riesgo encontrada ({pattern_name}): {resultado['tolerancia_riesgo']}")
                            break

                # Additional TABLE-AWARE patterns for risk tolerance
                if not resultado.get('tolerancia_riesgo'):
                    table_risk_patterns = [
                        (r'Tolerancia\s+(?:al\s+)?Riesgo\s*[\|\s:]+(Baja|Media|Alta|Moderada)', 'table_direct'),
                        (r'Perfil\s+de\s+Riesgo\s*[\|\s:]+(Bajo|Medio|Alto|Conservador|Moderado|Agresivo)', 'table_perfil'),
                        (r'Nivel\s+de\s+Riesgo\s*[\|\s:]+(Bajo|Medio|Alto|[1-7])', 'table_nivel'),
                    ]

                    for pattern, pattern_name in table_risk_patterns:
                        match = re.search(pattern, texto_completo, re.IGNORECASE)
                        if match:
                            risk_value = match.group(1).strip().capitalize()
                            # Normalize to standard categories
                            if risk_value in ['Baja', 'Bajo', 'Conservador', '1', '2']:
                                resultado['tolerancia_riesgo'] = 'Baja'
                            elif risk_value in ['Media', 'Medio', 'Moderada', 'Moderado', '3', '4', '5']:
                                resultado['tolerancia_riesgo'] = 'Media'
                            elif risk_value in ['Alta', 'Alto', 'Agresivo', '6', '7']:
                                resultado['tolerancia_riesgo'] = 'Alta'

                            if resultado.get('tolerancia_riesgo'):
                                campos_extraidos += 1
                                logger.info(f"[PDF] Tolerancia riesgo ({pattern_name}): {resultado['tolerancia_riesgo']}")
                                break

                # ============================================================
                # PATRÓN 3: HORIZONTE DE INVERSIÓN (MEJORADO)
                # ============================================================
                # Buscar horizonte de inversión con múltiples variaciones
                horizonte_patterns = [
                    (r'horizonte\s+(?:de\s+)?inversi[oó]n\s+(?:recomendad[oa]?\s+)?(?:es\s+)?(?:de\s+)?(corto|mediano|largo)\s+plazo',
                     'horizonte_keyword'),
                    (r'plazo\s+(?:de\s+inversi[oó]n\s+)?(?:recomendad[oa]?\s+)?(?:es\s+)?(?:de\s+)?(corto|mediano|largo)',
                     'plazo_keyword'),
                    (r'(corto|mediano|largo)\s+plazo\s+(?:de\s+)?inversi[oó]n',
                     'plazo_inversion'),
                    (r'inversi[oó]n\s+a\s+(corto|mediano|largo)\s+plazo',
                     'inversion_plazo'),
                ]

                for pattern, pattern_name in horizonte_patterns:
                    match = re.search(pattern, texto_completo, re.IGNORECASE)
                    if match:
                        plazo = match.group(1).lower()

                        if 'corto' in plazo:
                            resultado['horizonte_inversion'] = 'Corto Plazo'
                            resultado['horizonte_inversion_meses'] = 12  # Default: 1 año
                        elif 'mediano' in plazo:
                            resultado['horizonte_inversion'] = 'Mediano Plazo'
                            resultado['horizonte_inversion_meses'] = 36  # Default: 3 años
                        elif 'largo' in plazo:
                            resultado['horizonte_inversion'] = 'Largo Plazo'
                            resultado['horizonte_inversion_meses'] = 60  # Default: 5 años

                        if resultado.get('horizonte_inversion'):
                            campos_extraidos += 1
                            logger.debug(f"[PDF] Horizonte encontrado ({pattern_name}): {resultado['horizonte_inversion']}")
                            break

                # Buscar también meses/años específicos: "24 meses", "5 años"
                if not resultado.get('horizonte_inversion'):
                    match_meses = re.search(r'(\d+)\s*meses', texto_completo, re.IGNORECASE)
                    match_anos = re.search(r'(\d+)\s*años?', texto_completo, re.IGNORECASE)

                    if match_meses:
                        meses = int(match_meses.group(1))
                        resultado['horizonte_inversion_meses'] = meses
                        if meses < 12:
                            resultado['horizonte_inversion'] = 'Corto Plazo'
                        elif meses <= 36:
                            resultado['horizonte_inversion'] = 'Mediano Plazo'
                        else:
                            resultado['horizonte_inversion'] = 'Largo Plazo'
                        campos_extraidos += 1
                        logger.info(f"[PDF EXTENDED] Horizonte: {resultado['horizonte_inversion']} ({meses} meses)")
                    elif match_anos:
                        anos = int(match_anos.group(1))
                        resultado['horizonte_inversion_meses'] = anos * 12
                        if anos <= 1:
                            resultado['horizonte_inversion'] = 'Corto Plazo'
                        elif anos <= 3:
                            resultado['horizonte_inversion'] = 'Mediano Plazo'
                        else:
                            resultado['horizonte_inversion'] = 'Largo Plazo'
                        campos_extraidos += 1
                        logger.info(f"[PDF EXTENDED] Horizonte: {resultado['horizonte_inversion']} ({anos} años)")

                # ============================================================
                # PATRÓN 4: COMISIÓN DE ADMINISTRACIÓN
                # ============================================================
                for linea in lineas:
                    if 'remun' in linea.lower() or 'tac serie' in linea.lower():
                        # FIX 4.1 & 4.4: Usar regex compilado module-level
                        match_comision = REGEX_COMISION.search(linea)
                        if match_comision:
                            try:
                                comision_str = match_comision.group(1).replace(',', '.')

                                # FIX 4.2: Validar que no sea string vacío o solo punto
                                if not comision_str or comision_str == '.' or comision_str == '':
                                    continue

                                comision_num = float(comision_str)

                                # Si es mayor a 10, probablemente está en porcentaje
                                if comision_num > 10:
                                    resultado['comision_administracion'] = comision_num / 100
                                else:
                                    resultado['comision_administracion'] = comision_num / 100

                                campos_extraidos += 1
                                logger.info(f"[PDF EXTENDED] Comisión admin: {resultado['comision_administracion']:.4f} ({comision_num}%)")
                                break
                            except ValueError as e:
                                logger.debug(f"[PDF EXTENDED] Error parseando comisión: {e}")
                                continue

                # ============================================================
                # PATRÓN 5: COMISIÓN DE RESCATE
                # ============================================================
                for linea in lineas:
                    if 'comisión máxima' in linea.lower() or 'comision rescate' in linea.lower():
                        matches = re.findall(r'(\d+[\.,]\d+)', linea)
                        if matches:
                            try:
                                # Tomar el primer valor encontrado
                                comision_str = matches[0].replace(',', '.')
                                comision_num = float(comision_str)

                                if comision_num > 0:
                                    resultado['comision_rescate'] = comision_num / 100
                                    campos_extraidos += 1
                                    logger.info(f"[PDF EXTENDED] Comisión rescate: {resultado['comision_rescate']:.4f} ({comision_num}%)")
                                    break
                            except ValueError as e:
                                logger.debug(f"[PDF] Error al parsear comisión rescate: {e}")
                                continue

                # ============================================================
                # PATRÓN 5B: INFORMACIÓN DE RESCATE (NUEVO)
                # ============================================================
                # Detectar si el fondo es rescatable con múltiples patrones
                texto_completo_lower = texto_completo.lower()
                rescatable_patterns = [
                    (r'\brescatable\b', True),
                    (r'\bsin\s+rescate\b', False),
                    (r'\bno\s+rescatable\b', False),
                    (r'\bliquidez\s+(?:diaria|inmediata|disponible)', True),
                    (r'\breembolso\s+disponible\b', True),
                    (r'\bplazo\s+(?:de\s+)?rescate[:\s]+(\d+)', True),  # Si menciona plazo, es rescatable
                    (r'\bcerrado\s+(?:por|hasta|durante)', False),  # Fondo cerrado
                ]

                for pattern, is_rescatable in rescatable_patterns:
                    if re.search(pattern, texto_completo_lower, re.IGNORECASE):
                        resultado['fondo_rescatable'] = is_rescatable
                        campos_extraidos += 1
                        logger.info(f"[PDF EXTENDED] Fondo {'rescatable' if is_rescatable else 'NO rescatable'} (patrón: {pattern})")
                        break

                # Si no se encontró información, dejar como None (desconocido)
                if resultado.get('fondo_rescatable') is None:
                    logger.debug("[PDF EXTENDED] No se pudo determinar si el fondo es rescatable")

                # Buscar plazo de rescate con múltiples formatos
                plazo_patterns = [
                    (r'plazo\s+(?:de\s+)?rescate[:\s]+(\d+)\s*días?', 'días'),
                    (r'rescate\s+en\s+(\d+)\s*días?', 'días'),
                    (r'disponible\s+en\s+(\d+)\s*días?', 'días'),
                    (r'rescate\s+inmediato', '0'),  # Rescate inmediato = 0 días
                    (r'rescate\s+(?:el\s+)?mismo\s+día', '0'),
                    (r'T\+(\d+)', 'días'),  # Formato T+2, T+1, etc.
                ]

                for pattern, unidad in plazo_patterns:
                    match = re.search(pattern, texto_completo, re.IGNORECASE)
                    if match:
                        if unidad == '0':
                            resultado['plazos_rescates'] = 'Inmediato (0 días)'
                            campos_extraidos += 1
                            logger.info(f"[PDF EXTENDED] Plazo de rescate: Inmediato")
                        else:
                            try:
                                dias = int(match.group(1))
                                resultado['plazos_rescates'] = f"{dias} días"
                                campos_extraidos += 1
                                logger.info(f"[PDF EXTENDED] Plazo de rescate encontrado: {dias} días")
                            except (ValueError, IndexError) as e:
                                logger.debug(f"[PDF] Error al parsear plazo de rescate: {e}")
                                pass
                        break

                # Buscar duración del fondo con múltiples formatos
                duracion_patterns = [
                    (r'duraci[oó]n\s+(?:del\s+fondo\s+)?(?:es\s+)?(\d+)\s*años?', 'años'),
                    (r'plazo\s+(?:del\s+fondo\s+)?(?:es\s+)?(\d+)\s*años?', 'años'),
                    (r'vigencia\s+(?:de\s+)?(\d+)\s*años?', 'años'),
                    (r'duraci[oó]n\s+(?:del\s+fondo\s+)?(?:es\s+)?(\d+)\s*meses', 'meses'),
                    (r'duraci[oó]n\s+(?:es\s+)?indefinida', 'indefinido'),
                    (r'(?:fondo\s+)?sin\s+(?:fecha\s+de\s+)?vencimiento', 'indefinido'),
                    (r'(?:fondo\s+)?perpetuo', 'indefinido'),
                    (r'(?:fondo\s+)?de\s+inversi[oó]n\s+abierto', 'indefinido'),  # Fondos abiertos suelen ser indefinidos
                ]

                for pattern, tipo in duracion_patterns:
                    match = re.search(pattern, texto_completo, re.IGNORECASE)
                    if match:
                        if tipo == 'indefinido':
                            resultado['duracion'] = 'Indefinido'
                            campos_extraidos += 1
                            logger.info(f"[PDF EXTENDED] Duración del fondo encontrada: Indefinido")
                        elif tipo == 'años':
                            try:
                                anos = int(match.group(1))
                                resultado['duracion'] = f"{anos} años"
                                campos_extraidos += 1
                                logger.info(f"[PDF EXTENDED] Duración: {anos} años")
                            except (ValueError, IndexError):
                                pass
                        elif tipo == 'meses':
                            try:
                                meses = int(match.group(1))
                                resultado['duracion'] = f"{meses} meses"
                                campos_extraidos += 1
                                logger.info(f"[PDF EXTENDED] Duración: {meses} meses")
                            except (ValueError, IndexError):
                                pass

                        if resultado.get('duracion'):
                            break

                # ============================================================
                # PATRÓN 5C: MONTO MÍNIMO DE INVERSIÓN (NUEVO)
                # ============================================================
                patrones_monto_minimo = [
                    'monto mínimo', 'inversión mínima', 'aporte mínimo',
                    'capital mínimo', 'monto inicial', 'inversión inicial',
                    'cuota mínima', 'aporte inicial mínimo'
                ]

                for i, linea in enumerate(lineas):
                    linea_lower = linea.lower()
                    if any(patron in linea_lower for patron in patrones_monto_minimo):
                        # Buscar en línea actual y próximas 3 líneas
                        texto_busqueda = ' '.join(lineas[i:min(i+4, len(lineas))]).lower()

                        # Patrón 1: UF (común en fondos chilenos)
                        # Ejemplos: "UF 100", "100 UF", "UF 1.000", "UF100"
                        match_uf = re.search(r'(?:UF|uf)\s*[:\.]?\s*(\d+(?:[\.,]\d+)*)', texto_busqueda, re.IGNORECASE)
                        if match_uf:
                            uf = match_uf.group(1).replace('.', '').replace(',', '.')
                            try:
                                uf_num = float(uf)
                                resultado['monto_minimo'] = f"{uf_num:.2f} UF"
                                resultado['monto_minimo_moneda'] = 'UF'
                                resultado['monto_minimo_valor'] = uf_num
                                campos_extraidos += 1
                                logger.info(f"[PDF EXTENDED] Monto mínimo: {uf_num:.2f} UF")
                                break
                            except ValueError as e:
                                logger.debug(f"[PDF] Error al parsear monto mínimo: {e}")
                                pass

                        # Patrón 2: Pesos chilenos con símbolo $
                        # Ejemplos: "$100.000", "$ 1.000.000", "$100,000"
                        match_pesos_simbolo = re.search(r'\$\s*(\d{1,3}(?:[\.,]\d{3})*(?:[\.,]\d{1,2})?)', texto_busqueda)
                        if match_pesos_simbolo:
                            monto = match_pesos_simbolo.group(1).replace('.', '').replace(',', '')
                            try:
                                monto_num = float(monto)
                                if monto_num > 1000:  # Filtrar valores muy bajos que podrían ser errores
                                    resultado['monto_minimo'] = f"${monto_num:,.0f} CLP"
                                    resultado['monto_minimo_moneda'] = 'CLP'
                                    resultado['monto_minimo_valor'] = monto_num
                                    campos_extraidos += 1
                                    logger.info(f"[PDF EXTENDED] Monto mínimo: ${monto_num:,.0f} CLP")
                                    break
                            except ValueError as e:
                                logger.debug(f"[PDF] Error al parsear monto mínimo: {e}")
                                pass

                        # Patrón 3: Números seguidos de "pesos", "CLP", "pesos chilenos"
                        # Ejemplos: "100.000 pesos", "1000000 CLP", "500 mil pesos"
                        match_pesos_texto = re.search(r'(\d{1,3}(?:[\.,]\d{3})*)\s*(?:pesos|clp|peso)', texto_busqueda)
                        if match_pesos_texto:
                            monto = match_pesos_texto.group(1).replace('.', '').replace(',', '')
                            try:
                                monto_num = float(monto)
                                if monto_num > 1000:
                                    resultado['monto_minimo'] = f"${monto_num:,.0f} CLP"
                                    resultado['monto_minimo_moneda'] = 'CLP'
                                    resultado['monto_minimo_valor'] = monto_num
                                    campos_extraidos += 1
                                    logger.info(f"[PDF EXTENDED] Monto mínimo: ${monto_num:,.0f} CLP")
                                    break
                            except ValueError as e:
                                logger.debug(f"[PDF] Error al parsear monto mínimo: {e}")
                                pass

                        # Patrón 4: "X mil", "X millones"
                        # Ejemplos: "100 mil pesos", "1 millón"
                        match_miles = re.search(r'(\d+(?:[\.,]\d+)?)\s*mil(?:\s+(?:pesos|clp))?', texto_busqueda)
                        match_millones = re.search(r'(\d+(?:[\.,]\d+)?)\s*mill[oó]n(?:es)?(?:\s+(?:pesos|clp))?', texto_busqueda)

                        if match_millones:
                            num = match_millones.group(1).replace(',', '.')
                            try:
                                num_float = float(num)
                                monto_num = num_float * 1_000_000
                                resultado['monto_minimo'] = f"${monto_num:,.0f} CLP"
                                resultado['monto_minimo_moneda'] = 'CLP'
                                resultado['monto_minimo_valor'] = monto_num
                                campos_extraidos += 1
                                logger.info(f"[PDF EXTENDED] Monto mínimo: ${monto_num:,.0f} CLP ({num_float} millones)")
                                break
                            except ValueError as e:
                                logger.debug(f"[PDF] Error al parsear monto mínimo: {e}")
                                pass
                        elif match_miles:
                            num = match_miles.group(1).replace(',', '.')
                            try:
                                num_float = float(num)
                                monto_num = num_float * 1_000
                                resultado['monto_minimo'] = f"${monto_num:,.0f} CLP"
                                resultado['monto_minimo_moneda'] = 'CLP'
                                resultado['monto_minimo_valor'] = monto_num
                                campos_extraidos += 1
                                logger.info(f"[PDF EXTENDED] Monto mínimo: ${monto_num:,.0f} CLP ({num_float} mil)")
                                break
                            except ValueError as e:
                                logger.debug(f"[PDF] Error al parsear monto mínimo: {e}")
                                pass

                        # Patrón 5: USD (algunos fondos internacionales)
                        match_usd = re.search(r'(?:USD|US\$|U\.S\.\$)\s*(\d+(?:[\.,]\d+)*)', texto_busqueda, re.IGNORECASE)
                        if match_usd:
                            usd = match_usd.group(1).replace(',', '')
                            try:
                                usd_num = float(usd)
                                resultado['monto_minimo'] = f"${usd_num:,.2f} USD"
                                resultado['monto_minimo_moneda'] = 'USD'
                                resultado['monto_minimo_valor'] = usd_num
                                campos_extraidos += 1
                                logger.info(f"[PDF EXTENDED] Monto mínimo: ${usd_num:,.2f} USD")
                                break
                            except ValueError as e:
                                logger.debug(f"[PDF] Error al parsear monto mínimo: {e}")
                                pass

                        # Patrón 6: "mínimo de $X" o "mínimo: $X"
                        match_minimo_de = re.search(r'mínimo\s+(?:de\s+)?(?:inversión\s+)?(?:de\s+)?\$\s*(\d{1,3}(?:[\.,]\d{3})*(?:[\.,]\d{1,2})?)', texto_busqueda, re.IGNORECASE)
                        if match_minimo_de:
                            try:
                                monto_str = match_minimo_de.group(1).replace('.', '').replace(',', '.')
                                monto_float = float(monto_str)
                                if monto_float > 1000:  # Validar que sea razonable
                                    resultado['monto_minimo'] = f"${monto_float:,.0f} CLP"
                                    resultado['monto_minimo_moneda'] = 'CLP'
                                    resultado['monto_minimo_valor'] = monto_float
                                    campos_extraidos += 1
                                    logger.info(f"[PDF EXTENDED] Monto mínimo (patrón 6): ${monto_float:,.0f} CLP")
                                    break
                            except ValueError as e:
                                logger.debug(f"[PDF] Error al parsear monto mínimo: {e}")
                                pass

                        # Patrón 7: "aporte inicial" como sinónimo de monto mínimo
                        match_aporte = re.search(r'aporte\s+inicial\s+(?:de\s+)?(?:es\s+)?(?:de\s+)?([A-Z]{2,3})\s*(\d{1,3}(?:[\.,]\d{3})*(?:[\.,]\d+)?)', texto_busqueda, re.IGNORECASE)
                        if match_aporte:
                            try:
                                moneda = match_aporte.group(1).upper()
                                monto_str = match_aporte.group(2).replace('.', '').replace(',', '.')
                                monto_float = float(monto_str)

                                if moneda in ['UF', 'CLP', 'USD'] and monto_float > 0:
                                    resultado['monto_minimo'] = f"{monto_float:,.0f} {moneda}"
                                    resultado['monto_minimo_moneda'] = moneda
                                    resultado['monto_minimo_valor'] = monto_float
                                    campos_extraidos += 1
                                    logger.info(f"[PDF EXTENDED] Monto mínimo (patrón 7 - aporte): {resultado['monto_minimo']}")
                                    break
                            except ValueError as e:
                                logger.debug(f"[PDF] Error al parsear monto mínimo: {e}")
                                pass

                # ============================================================
                # PATRÓN 6: RENTABILIDAD HISTÓRICA (ULTRA-FLEXIBLE)
                # ============================================================
                # Extract rentabilidades with MAXIMUM flexibility:
                # - Any period (meses/años)
                # - Any separator (space, |, :, tab, multiple spaces)
                # - Table or free-text format
                # - Handles negative returns

                # Pattern: "NUMBER meses/años [ANYTHING] NUMBER%"
                # Examples: "12 meses 5,2%", "1 año    | 3,5%", "24 meses: -2,1%"
                rentabilidad_flexible_pattern = r'(\d+)\s*(?:mes|m)[a-zñáéíóú]*\s*[:\|\s]+([-]?[\d,\.]+)\s*%'
                for match in re.finditer(rentabilidad_flexible_pattern, texto_completo, re.IGNORECASE):
                    try:
                        meses = int(match.group(1))
                        rent_str = match.group(2).replace(',', '.')
                        if rent_str and rent_str not in ['.', '-', '-.', ',']:
                            rent_value = float(rent_str) / 100

                            # Map to standard fields
                            if meses == 12 and not resultado.get('rentabilidad_12m'):
                                resultado['rentabilidad_12m'] = rent_value
                                campos_extraidos += 1
                                logger.info(f"[PDF] Rentabilidad 12m: {rent_value:.2%}")
                            elif meses == 24 and not resultado.get('rentabilidad_24m'):
                                resultado['rentabilidad_24m'] = rent_value
                                campos_extraidos += 1
                                logger.info(f"[PDF] Rentabilidad 24m: {rent_value:.2%}")
                            elif meses == 36 and not resultado.get('rentabilidad_36m'):
                                resultado['rentabilidad_36m'] = rent_value
                                campos_extraidos += 1
                                logger.info(f"[PDF] Rentabilidad 36m: {rent_value:.2%}")

                            # Store ALL in rentabilidades_nominales
                            resultado['rentabilidades_nominales'][f"{meses}_meses"] = rent_value
                            logger.debug(f"[PDF] Rentabilidad {meses}m: {rent_value:.2%}")
                    except (ValueError, IndexError) as e:
                        logger.debug(f"[PDF] Error parseando rentabilidad: {e}")

                # Pattern for AÑOS format
                rentabilidad_anos_pattern = r'(\d+)\s*(?:año|a)[ñnos]*\s*[:\|\s]+([-]?[\d,\.]+)\s*%'
                for match in re.finditer(rentabilidad_anos_pattern, texto_completo, re.IGNORECASE):
                    try:
                        anos = int(match.group(1))
                        rent_str = match.group(2).replace(',', '.')
                        if rent_str and rent_str not in ['.', '-', '-.', ',']:
                            rent_value = float(rent_str) / 100
                            meses_equiv = anos * 12

                            # Map to standard fields
                            if meses_equiv == 12 and not resultado.get('rentabilidad_12m'):
                                resultado['rentabilidad_12m'] = rent_value
                                campos_extraidos += 1
                                logger.info(f"[PDF] Rentabilidad 12m (1 año): {rent_value:.2%}")
                            elif meses_equiv == 24 and not resultado.get('rentabilidad_24m'):
                                resultado['rentabilidad_24m'] = rent_value
                                campos_extraidos += 1
                                logger.info(f"[PDF] Rentabilidad 24m (2 años): {rent_value:.2%}")
                            elif meses_equiv == 36 and not resultado.get('rentabilidad_36m'):
                                resultado['rentabilidad_36m'] = rent_value
                                campos_extraidos += 1
                                logger.info(f"[PDF] Rentabilidad 36m (3 años): {rent_value:.2%}")

                            # Store in rentabilidades_nominales
                            resultado['rentabilidades_nominales'][f"{anos}_anos"] = rent_value
                            logger.debug(f"[PDF] Rentabilidad {anos} años: {rent_value:.2%}")
                    except (ValueError, IndexError) as e:
                        logger.debug(f"[PDF] Error parseando rentabilidad años: {e}")

                # ============================================================
                # PATRÓN 7: PATRIMONIO DEL FONDO (IMPROVED - SEPARATE FONDO vs SEDE)
                # ============================================================
                # Distinguish between patrimonio_fondo (total fund) and patrimonio_sede (series/class)
                for linea in lineas:
                    linea_lower = linea.lower()

                    # Pattern A: Patrimonio Serie (specific to this serie/class)
                    if 'patrimonio serie' in linea_lower or 'patrimonio de la serie' in linea_lower:
                        match_sede = re.search(r'([A-Z]{3})?\s*\$?\s*([\d.,]+)', linea)
                        if match_sede:
                            try:
                                moneda = match_sede.group(1) or resultado.get('moneda') or 'CLP'
                                monto_str = match_sede.group(2).replace('.', '').replace(',', '')
                                monto = float(monto_str)

                                resultado['patrimonio_sede'] = monto
                                resultado['patrimonio_moneda'] = moneda
                                campos_extraidos += 1
                                logger.info(f"[PDF] Patrimonio SEDE: {moneda} {monto:,.0f}")
                            except ValueError as e:
                                logger.debug(f"[PDF] Error parseando patrimonio sede: {e}")
                                continue

                    # Pattern B: Patrimonio Total / Patrimonio Fondo (entire fund)
                    elif 'patrimonio total' in linea_lower or 'patrimonio del fondo' in linea_lower or 'patrimonio fondo' in linea_lower:
                        match_fondo = re.search(r'([A-Z]{3})?\s*\$?\s*([\d.,]+)', linea)
                        if match_fondo:
                            try:
                                moneda = match_fondo.group(1) or resultado.get('moneda') or 'CLP'
                                monto_str = match_fondo.group(2).replace('.', '').replace(',', '')
                                monto = float(monto_str)

                                resultado['patrimonio_fondo'] = monto
                                resultado['patrimonio_moneda'] = moneda
                                campos_extraidos += 1
                                logger.info(f"[PDF] Patrimonio FONDO: {moneda} {monto:,.0f}")
                            except ValueError as e:
                                logger.debug(f"[PDF] Error parseando patrimonio fondo: {e}")
                                continue

                # Legacy mapping: keep 'patrimonio' for backwards compatibility
                if resultado.get('patrimonio_fondo'):
                    resultado['patrimonio'] = resultado['patrimonio_fondo']
                elif resultado.get('patrimonio_sede'):
                    resultado['patrimonio'] = resultado['patrimonio_sede']

                # ============================================================
                # PATRÓN 8: COMPOSICIÓN DE PORTAFOLIO (Mejorada con patrones alternativos)
                # ============================================================
                composicion = []
                composicion_detallada = []

                # Patrón 1: "Activo XX,XX%" o "Activo XX.XX %"
                for i, linea in enumerate(lineas):
                    match = re.search(r'([A-Za-záéíóúñÁÉÍÓÚÑ\s\.]+)\s+(\d+[\.,]?\d*)\s*%', linea)
                    if match:
                        activo_nombre = match.group(1).strip()
                        porcentaje_str = match.group(2).replace(',', '.')

                        try:
                            porcentaje_num = float(porcentaje_str)
                            porcentaje_decimal = porcentaje_num / 100

                            # Filtrar nombres muy cortos o genéricos
                            if len(activo_nombre) > 3 and porcentaje_decimal > 0:
                                item = {
                                    'activo': activo_nombre,
                                    'porcentaje': porcentaje_decimal
                                }
                                composicion.append(item)

                                # Clasificar activo para composición detallada
                                categoria = self._clasificar_activo(activo_nombre)
                                item_detallado = item.copy()
                                item_detallado['categoria'] = categoria
                                composicion_detallada.append(item_detallado)

                                logger.debug(f"[PDF EXTENDED] Encontrado (P1): {activo_nombre} = {porcentaje_decimal:.2%} (cat: {categoria})")
                        except ValueError as e:
                            logger.debug(f"[PDF] Error al parsear item de composición: {e}")
                            continue

                # Logging cuando Patrón 1 falla
                if not composicion_detallada:
                    logger.debug("[PDF] Patrón 1 de composición no encontró matches, probando patrón 2...")

                # Patrón 2: Tabla con columnas "Instrumento | Porcentaje" o similar
                # Buscar sección "Composición de Cartera" o "Inversiones"
                if not composicion:
                    logger.info("[PDF EXTENDED] Patrón 1 no encontró composición, intentando Patrón 2 (tabla)...")
                    en_seccion_composicion = False
                    for i, linea in enumerate(lineas):
                        linea_lower = linea.lower()

                        # Detectar inicio de sección de composición
                        if any(keyword in linea_lower for keyword in ['composición', 'cartera', 'inversiones', 'activos']):
                            if any(keyword2 in linea_lower for keyword2 in ['portafolio', 'serie', 'fondo']):
                                en_seccion_composicion = True
                                logger.debug(f"[PDF EXTENDED] Iniciando sección composición en línea {i}")
                                continue

                        # Si estamos en la sección, buscar patrones más flexibles
                        if en_seccion_composicion:
                            # Buscar líneas con múltiples números: "Bonos BCP  15.234  12,5%"
                            match_tabla = re.search(r'([A-Za-záéíóúñÁÉÍÓÚÑ\s]+?)\s+[\d.,]+\s+(\d+[\.,]\d+)\s*%', linea)
                            if match_tabla:
                                activo_nombre = match_tabla.group(1).strip()
                                porcentaje_str = match_tabla.group(2).replace(',', '.')
                                try:
                                    porcentaje_decimal = float(porcentaje_str) / 100
                                    if len(activo_nombre) > 3 and porcentaje_decimal > 0:
                                        item = {'activo': activo_nombre, 'porcentaje': porcentaje_decimal}
                                        composicion.append(item)
                                        categoria = self._clasificar_activo(activo_nombre)
                                        item_detallado = item.copy()
                                        item_detallado['categoria'] = categoria
                                        composicion_detallada.append(item_detallado)
                                        logger.debug(f"[PDF EXTENDED] Encontrado (P2): {activo_nombre} = {porcentaje_decimal:.2%}")
                                except ValueError as e:
                                    logger.debug(f"[PDF] Error al parsear item de composición: {e}")
                                    continue

                            # Salir si encontramos otra sección
                            if any(keyword in linea_lower for keyword in ['rentabilidad', 'comisiones', 'factores de riesgo']):
                                en_seccion_composicion = False
                                logger.debug(f"[PDF EXTENDED] Finalizando sección composición en línea {i}")

                # Patrón 3: Buscar tabla explícita con headers
                if not composicion:
                    logger.info("[PDF EXTENDED] Patrón 2 no encontró composición, intentando Patrón 3 (headers)...")
                    for i, linea in enumerate(lineas):
                        if 'instrumento' in linea.lower() and '%' in linea.lower():
                            # Buscar en las siguientes 30 líneas
                            for j in range(i+1, min(i+31, len(lineas))):
                                linea_data = lineas[j]
                                # Formato: cualquier texto seguido de número con %
                                match_simple = re.search(r'^([^0-9]+?)\s+(\d+[\.,]\d+)\s*%?', linea_data)
                                if match_simple:
                                    activo_nombre = match_simple.group(1).strip()
                                    porcentaje_str = match_simple.group(2).replace(',', '.')
                                    try:
                                        porcentaje_decimal = float(porcentaje_str) / 100
                                        if len(activo_nombre) > 3 and porcentaje_decimal > 0 and porcentaje_decimal <= 1:
                                            item = {'activo': activo_nombre, 'porcentaje': porcentaje_decimal}
                                            composicion.append(item)
                                            categoria = self._clasificar_activo(activo_nombre)
                                            item_detallado = item.copy()
                                            item_detallado['categoria'] = categoria
                                            composicion_detallada.append(item_detallado)
                                            logger.debug(f"[PDF EXTENDED] Encontrado (P3): {activo_nombre} = {porcentaje_decimal:.2%}")
                                    except ValueError as e:
                                        logger.debug(f"[PDF] Error al parsear item de composición: {e}")
                                        continue
                            break

                # Ordenar por porcentaje descendente
                composicion.sort(key=lambda x: x['porcentaje'], reverse=True)
                composicion_detallada.sort(key=lambda x: x['porcentaje'], reverse=True)

                resultado['composicion_portafolio'] = composicion[:15]
                resultado['composicion_detallada'] = composicion_detallada[:20]

                if composicion:
                    campos_extraidos += 1
                    suma_porcentajes = sum(item['porcentaje'] for item in composicion)
                    logger.info(f"[PDF] Composición extraída exitosamente: {len(composicion)} activos (suma: {suma_porcentajes:.2%})")
                else:
                    # ETL FIX: Logging explícito cuando composición está vacía
                    logger.warning(f"[PDF] No se pudo extraer composición de portafolio con ningún patrón. Texto disponible: {len(texto_completo)} caracteres")
                    logger.warning(f"[PDF EXTENDED] COMPOSICIÓN VACÍA - Ningún patrón encontró activos del portafolio")
                    logger.warning(f"[PDF EXTENDED] Esto indica un formato de PDF no soportado o datos ausentes")

                # ============================================================
                # EXTRACTION 7: RENTABILIDADES EXTENDED (NEW - COMPREHENSIVE)
                # ============================================================
                # Extract rentabilidades nominales, mejores, peores, and anualizadas
                # These are in ADDITION to the existing rentabilidad_12m, 24m, 36m

                # RENTABILIDADES NOMINALES (period returns)
                rentabilidades_nominales = {}
                nominal_patterns = [
                    (r'(?:Rentabilidad|Retorno)\s+Nominal\s+(\d+)\s*(?:mes|m)[a-z]*[:\s]+([-]?[\d,\.]+)\s*%', 'meses'),
                    (r'(?:Rentabilidad|Retorno)\s+(\d+)\s*(?:mes|m)[a-z]*[:\s]+([-]?[\d,\.]+)\s*%', 'meses_short'),
                    (r'(?:Rentabilidad|Retorno)\s+(\d+)\s*(?:año|a)[ños]*[:\s]+([-]?[\d,\.]+)\s*%', 'anos'),
                ]

                for pattern, pattern_type in nominal_patterns:
                    matches = re.finditer(pattern, texto_completo, re.IGNORECASE)
                    for match in matches:
                        periodo = match.group(1)
                        valor_str = match.group(2).replace(',', '.')
                        try:
                            valor = float(valor_str) / 100  # Convert to decimal
                            if 'ano' in pattern_type or 'año' in pattern_type:
                                key = f"{periodo}_anos"
                            else:
                                key = f"{periodo}_meses"
                            rentabilidades_nominales[key] = valor
                            logger.debug(f"[PDF] Rentabilidad nominal {key}: {valor:.4f}")
                        except ValueError as e:
                            logger.debug(f"[PDF] Error parseando rentabilidad nominal: {e}")

                if rentabilidades_nominales:
                    resultado['rentabilidades_nominales'] = rentabilidades_nominales
                    campos_extraidos += 1
                    logger.info(f"[PDF] Rentabilidades nominales: {len(rentabilidades_nominales)} periodos")

                # MEJORES RENTABILIDADES (best returns)
                mejores_rentabilidades = {}
                mejor_patterns = [
                    (r'Mejor\s+(?:Rentabilidad|Retorno)\s+(?:Mensual|Mes)[:\s]+([-]?[\d,\.]+)\s*%', 'mensual'),
                    (r'Mejor\s+(?:Rentabilidad|Retorno)\s+(?:Anual|Año)[:\s]+([-]?[\d,\.]+)\s*%', 'anual'),
                    (r'M[aá]xim[oa]\s+(?:Rentabilidad|Retorno)[:\s]+([-]?[\d,\.]+)\s*%', 'maximo'),
                ]

                for pattern, tipo in mejor_patterns:
                    match = re.search(pattern, texto_completo, re.IGNORECASE)
                    if match:
                        try:
                            valor_str = match.group(1).replace(',', '.')
                            valor = float(valor_str) / 100
                            mejores_rentabilidades[tipo] = valor
                            logger.debug(f"[PDF] Mejor rentabilidad {tipo}: {valor:.4f}")
                        except ValueError as e:
                            logger.debug(f"[PDF] Error parseando mejor rentabilidad: {e}")

                if mejores_rentabilidades:
                    resultado['mejores_rentabilidades'] = mejores_rentabilidades
                    campos_extraidos += 1
                    logger.info(f"[PDF] Mejores rentabilidades: {len(mejores_rentabilidades)} periodos")

                # PEORES RENTABILIDADES (worst returns)
                peores_rentabilidades = {}
                peor_patterns = [
                    (r'Peor\s+(?:Rentabilidad|Retorno)\s+(?:Mensual|Mes)[:\s]+([-]?[\d,\.]+)\s*%', 'mensual'),
                    (r'Peor\s+(?:Rentabilidad|Retorno)\s+(?:Anual|Año)[:\s]+([-]?[\d,\.]+)\s*%', 'anual'),
                    (r'M[ií]nim[oa]\s+(?:Rentabilidad|Retorno)[:\s]+([-]?[\d,\.]+)\s*%', 'minimo'),
                ]

                for pattern, tipo in peor_patterns:
                    match = re.search(pattern, texto_completo, re.IGNORECASE)
                    if match:
                        try:
                            valor_str = match.group(1).replace(',', '.')
                            valor = float(valor_str) / 100
                            peores_rentabilidades[tipo] = valor
                            logger.debug(f"[PDF] Peor rentabilidad {tipo}: {valor:.4f}")
                        except ValueError as e:
                            logger.debug(f"[PDF] Error parseando peor rentabilidad: {e}")

                if peores_rentabilidades:
                    resultado['peores_rentabilidades'] = peores_rentabilidades
                    campos_extraidos += 1
                    logger.info(f"[PDF] Peores rentabilidades: {len(peores_rentabilidades)} periodos")

                # RENTABILIDADES ANUALIZADAS (annualized returns)
                rentabilidades_anualizadas = {}
                anualizada_patterns = [
                    (r'(?:Rentabilidad|Retorno)\s+Anualizada?\s+(\d+)\s*(?:año|a)[ños]*[:\s]+([-]?[\d,\.]+)\s*%', 'anos'),
                    (r'(?:Rentabilidad|Retorno)\s+Promedio\s+Anual\s+(\d+)\s*(?:año|a)[ños]*[:\s]+([-]?[\d,\.]+)\s*%', 'promedio'),
                ]

                for pattern, pattern_type in anualizada_patterns:
                    matches = re.finditer(pattern, texto_completo, re.IGNORECASE)
                    for match in matches:
                        periodo = match.group(1)
                        valor_str = match.group(2).replace(',', '.')
                        try:
                            valor = float(valor_str) / 100
                            key = f"{periodo}_anos"
                            rentabilidades_anualizadas[key] = valor
                            logger.debug(f"[PDF] Rentabilidad anualizada {key}: {valor:.4f}")
                        except ValueError as e:
                            logger.debug(f"[PDF] Error parseando rentabilidad anualizada: {e}")

                if rentabilidades_anualizadas:
                    resultado['rentabilidades_anualizadas'] = rentabilidades_anualizadas
                    campos_extraidos += 1
                    logger.info(f"[PDF] Rentabilidades anualizadas: {len(rentabilidades_anualizadas)} periodos")

                # ============================================================
                # EXTRACTION 8: MAP INVERSION_MINIMA (CONSISTENCY FIX)
                # ============================================================
                # Map monto_minimo to inversion_minima for output consistency
                if resultado.get('monto_minimo'):
                    resultado['inversion_minima'] = resultado['monto_minimo']
                    logger.debug(f"[PDF] Inversión mínima mapeada: {resultado['inversion_minima']}")

                # ============================================================
                # CALCULAR NIVEL DE CONFIANZA
                # ============================================================
                porcentaje_extraido = (campos_extraidos / campos_totales) * 100

                if porcentaje_extraido >= 70:
                    resultado['extraction_confidence'] = 'high'
                elif porcentaje_extraido >= 40:
                    resultado['extraction_confidence'] = 'medium'
                else:
                    resultado['extraction_confidence'] = 'low'

                logger.info(f"[PDF EXTENDED] Campos extraídos: {campos_extraidos}/{campos_totales} ({porcentaje_extraido:.0f}%) - Confianza: {resultado['extraction_confidence']}")

                return resultado

        except FileNotFoundError:
            logger.error(f"[PDF EXTENDED] Archivo no encontrado: {pdf_path}")
            return {'pdf_procesado': False, 'error': 'Archivo no encontrado'}
        except Exception as e:
            logger.error(f"[PDF EXTENDED] Error procesando PDF: {e}")
            return {'pdf_procesado': False, 'error': str(e)}

    def _clasificar_activo(self, nombre_activo: str) -> str:
        """
        Clasificar un activo en categorías generales

        Args:
            nombre_activo (str): Nombre del activo

        Returns:
            str: Categoría del activo
        """
        nombre_lower = nombre_activo.lower()

        # Mapeo de palabras clave a categorías
        categorias = {
            'Renta Fija Gobierno': ['tesorería', 'gobierno', 'bcp', 'btu', 'banco central'],
            'Renta Fija Corporativa': ['corporativo', 'bonos', 'pagarés', 'depósitos'],
            'Acciones Locales': ['acciones', 'equity', 'chilenas'],
            'Acciones Internacionales': ['internacional', 'extranjero', 'eeuu', 'usa'],
            'Fondos Mutuos': ['fondo mutuo', 'mutual fund'],
            'Derivados': ['derivados', 'forwards', 'opciones'],
            'Efectivo': ['efectivo', 'cash', 'liquidez']
        }

        for categoria, keywords in categorias.items():
            if any(keyword in nombre_lower for keyword in keywords):
                return categoria

        return 'Otros'

    def _scrape_fund_status_from_cmf(self, rut: str) -> Dict:
        """
        Scrape fund status from CMF detail page to extract fecha_valor_cuota and fund status.

        This addresses the critical issue where 96.8% of funds lack current status information
        because they're not in Fintual API.

        Args:
            rut (str): RUT del fondo sin guión (ej: "8638")

        Returns:
            Dict with fecha_valor_cuota, valor_cuota, estado_fondo
        """
        resultado = {
            'fecha_valor_cuota': None,
            'valor_cuota': None,
            'estado_fondo': 'Desconocido'
        }

        try:
            # FIX: Validate RUT parameter
            if not rut or not isinstance(rut, str):
                logger.warning(f"[CMF STATUS] RUT inválido: {rut}")
                return resultado

            # Build CMF fund detail URL (pestania=7 typically shows fund values)
            url = f"https://www.cmfchile.cl/institucional/mercados/entidad.php?mercado=V&rut={rut}&tipoentidad=RGFMU&pestania=7"
            logger.info(f"[CMF STATUS] Scraping status from: {url}")

            # FIX 2.2: Usar request_with_retry para scraping status
            response = request_with_retry(self.session, url, timeout=15)
            if not response or response.status_code != 200:
                logger.warning(f"[CMF STATUS] HTTP {response.status_code if response else 'None'} para RUT {rut}")
                return resultado

            soup = BeautifulSoup(response.content, 'html.parser')
            texto_completo = soup.get_text()

            # FIX 6.1: Pattern 1: Extract most recent date (formato DD-MM-YYYY, DD/MM/YYYY, DD-MM-YY, DD/MM/YY)
            fecha_regex = r'(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})'
            fechas_encontradas = re.findall(fecha_regex, response.text)

            if fechas_encontradas:
                # Convert to ISO format and get most recent
                from datetime import datetime
                fechas_parsed = []
                for fecha_str in fechas_encontradas:
                    try:
                        # FIX 6.1: Intentar formato largo (YYYY) primero, luego corto (YY)
                        fecha_normalizada = fecha_str.replace('/', '-')
                        try:
                            fecha = datetime.strptime(fecha_normalizada, '%d-%m-%Y')
                        except ValueError:
                            # Intentar formato corto DD-MM-YY
                            fecha = datetime.strptime(fecha_normalizada, '%d-%m-%y')
                        fechas_parsed.append(fecha)
                    except ValueError:
                        continue

                if fechas_parsed:
                    fecha_mas_reciente = max(fechas_parsed)
                    resultado['fecha_valor_cuota'] = fecha_mas_reciente.strftime('%Y-%m-%d')
                    logger.info(f"[CMF STATUS] Fecha valor cuota: {resultado['fecha_valor_cuota']}")

            # Pattern 2: Extract fund status (Vigente, Liquidado, Fusionado)
            texto_lower = texto_completo.lower()
            if 'vigente' in texto_lower:
                resultado['estado_fondo'] = 'Vigente'
            elif 'liquidado' in texto_lower or 'liquidación' in texto_lower:
                resultado['estado_fondo'] = 'Liquidado'
            elif 'fusionado' in texto_lower:
                resultado['estado_fondo'] = 'Fusionado'

            logger.info(f"[CMF STATUS] Estado fondo: {resultado['estado_fondo']}")

            # Pattern 3: Try to extract valor_cuota (current share value)
            # Look for patterns like "Valor cuota: $1.234,56" or similar
            valor_pattern = r'valor\s+cuota[:\s]+\$?\s*([\d.,]+)'
            valor_match = re.search(valor_pattern, texto_lower)
            if valor_match:
                try:
                    valor_str = valor_match.group(1).replace('.', '').replace(',', '.')
                    resultado['valor_cuota'] = float(valor_str)
                    logger.info(f"[CMF STATUS] Valor cuota: {resultado['valor_cuota']}")
                except ValueError:
                    pass

            # FIX 6.2: Fallback pestania=1 si no se encontró fecha en pestania=7
            if not resultado['fecha_valor_cuota']:
                logger.info(f"[CMF STATUS] No se encontró fecha en pestania=7, intentando fallback pestania=1...")
                url_fallback = f"https://www.cmfchile.cl/institucional/mercados/entidad.php?mercado=V&rut={rut}&tipoentidad=RGFMU&pestania=1"

                response_fallback = request_with_retry(self.session, url_fallback, timeout=15)
                if response_fallback and response_fallback.status_code == 200:
                    fechas_encontradas_fb = re.findall(fecha_regex, response_fallback.text)

                    if fechas_encontradas_fb:
                        from datetime import datetime
                        fechas_parsed_fb = []
                        for fecha_str in fechas_encontradas_fb:
                            try:
                                fecha_normalizada = fecha_str.replace('/', '-')
                                try:
                                    fecha = datetime.strptime(fecha_normalizada, '%d-%m-%Y')
                                except ValueError:
                                    fecha = datetime.strptime(fecha_normalizada, '%d-%m-%y')
                                fechas_parsed_fb.append(fecha)
                            except ValueError:
                                continue

                        if fechas_parsed_fb:
                            fecha_mas_reciente_fb = max(fechas_parsed_fb)
                            resultado['fecha_valor_cuota'] = fecha_mas_reciente_fb.strftime('%Y-%m-%d')
                            logger.info(f"[CMF STATUS] Fecha valor cuota (fallback pestania=1): {resultado['fecha_valor_cuota']}")

            # FIX 6.3: Fallback extracción desde tables HTML si regex falló en ambas pestañas
            if not resultado['fecha_valor_cuota']:
                logger.info(f"[CMF STATUS] Regex falló, intentando extraer fecha desde tables HTML...")
                try:
                    # Intentar con pestania=7 primero
                    url_table = f"https://www.cmfchile.cl/institucional/mercados/entidad.php?mercado=V&rut={rut}&tipoentidad=RGFMU&pestania=7"
                    response_table = request_with_retry(self.session, url_table, timeout=15)

                    if response_table and response_table.status_code == 200:
                        soup_table = BeautifulSoup(response_table.content, 'html.parser')

                        # Buscar tables con class="tabla" o cualquier table
                        tables = soup_table.find_all('table')

                        for table in tables:
                            # Buscar celdas que contengan "fecha" y extraer valor adyacente
                            rows = table.find_all('tr')
                            for row in rows:
                                cells = row.find_all(['td', 'th'])
                                for i, cell in enumerate(cells):
                                    cell_text = cell.get_text(strip=True).lower()
                                    if 'fecha' in cell_text and i + 1 < len(cells):
                                        # La siguiente celda podría contener la fecha
                                        next_cell = cells[i + 1].get_text(strip=True)
                                        fecha_match = re.search(fecha_regex, next_cell)
                                        if fecha_match:
                                            from datetime import datetime
                                            try:
                                                fecha_str = fecha_match.group(1)
                                                fecha_normalizada = fecha_str.replace('/', '-')
                                                try:
                                                    fecha = datetime.strptime(fecha_normalizada, '%d-%m-%Y')
                                                except ValueError:
                                                    fecha = datetime.strptime(fecha_normalizada, '%d-%m-%y')
                                                resultado['fecha_valor_cuota'] = fecha.strftime('%Y-%m-%d')
                                                logger.info(f"[CMF STATUS] Fecha valor cuota (table HTML): {resultado['fecha_valor_cuota']}")
                                                break
                                            except Exception:
                                                continue
                                if resultado['fecha_valor_cuota']:
                                    break
                            if resultado['fecha_valor_cuota']:
                                break

                except Exception as e:
                    logger.warning(f"[CMF STATUS] Error extrayendo fecha desde tables HTML: {e}")

            return resultado

        except Exception as e:
            logger.error(f"[CMF STATUS] Error scraping status for RUT {rut}: {e}")
            return resultado

    def _extract_data_from_pdf(self, pdf_path: str) -> Dict:
        """
        Extraer datos estructurados de un PDF de Folleto Informativo

        FUNCIÓN ORIGINAL (mantenida para compatibilidad)
        Usa la nueva función extendida pero retorna formato compatible.

        Busca patrones para:
        - Tipo de fondo (conservador/balanceado/agresivo/moderado)
        - Perfil de riesgo (bajo/medio/alto)
        - Composición de portafolio (tabla con activos y porcentajes)

        Args:
            pdf_path (str): Ruta al archivo PDF

        Returns:
            Dict con datos extraídos
        """
        # Llamar a la función extendida
        resultado_extendido = self._extract_extended_data_from_pdf(pdf_path)

        # FIX: Return ALL extracted fields including rentabilidad_12m, composicion_detallada, etc.
        # The old version was losing critical data by only returning a subset of fields
        return resultado_extendido

    def _get_fintual_data(self, fondo_id: str) -> Optional[Dict]:
        """
        Obtener datos completos desde Fintual API (3 CAPAS)

        CAPA 1: Listado de fondos con RUN
        CAPA 2: Detalle del fondo específico
        CAPA 3: Series del fondo (real_assets) con valor cuota, comisiones, etc.
        """
        try:
            # CAPA 1: Buscar fondo en el listado completo
            logger.info(f"[FINTUAL CAPA 1] Buscando fondo: {fondo_id}")
            url_listado = "https://fintual.cl/api/asset_providers/3/conceptual_assets"

            response = requests.get(url_listado, timeout=30)

            if response.status_code != 200:
                logger.warning(f"No se pudo acceder al listado de Fintual: {response.status_code}")
                return None

            data = response.json()
            fondos = data.get('data', [])

            # Buscar fondo por nombre o symbol
            fondo_encontrado = None
            fondo_id_lower = fondo_id.lower()

            for fondo in fondos:
                attrs = fondo.get('attributes', {})
                nombre = attrs.get('name', '').lower()
                symbol = attrs.get('symbol', '').lower()

                if (fondo_id_lower in nombre or
                    fondo_id_lower in symbol or
                    nombre in fondo_id_lower):
                    fondo_encontrado = fondo
                    break

            if not fondo_encontrado:
                logger.warning(f"Fondo '{fondo_id}' no encontrado en Fintual")
                return None

            # Extraer datos de CAPA 1
            attrs = fondo_encontrado.get('attributes', {})
            conceptual_asset_id = fondo_encontrado.get('id')

            resultado = {
                'nombre': attrs.get('name', ''),
                'symbol': attrs.get('symbol', ''),
                'category': attrs.get('category', ''),
                'currency': attrs.get('currency', ''),
                'run': attrs.get('run', ''),  # RUN completo con guión (ej: "10446-9")
                'rut_base': self._extract_rut_base(attrs.get('run', '')),  # RUT sin guión (ej: "10446")
                'conceptual_asset_id': conceptual_asset_id,
                'data_source': attrs.get('data_source', '')
            }

            logger.info(f"[FINTUAL CAPA 1] Fondo encontrado: {resultado['nombre']}, RUN: {resultado['run']}, RUT: {resultado['rut_base']}")

            # CAPA 3: Obtener series del fondo (real_assets)
            if conceptual_asset_id:
                logger.info(f"[FINTUAL CAPA 3] Obteniendo series del fondo ID: {conceptual_asset_id}")
                url_series = f"https://fintual.cl/api/conceptual_assets/{conceptual_asset_id}/real_assets"

                response_series = requests.get(url_series, timeout=30)

                if response_series.status_code == 200:
                    series_data = response_series.json()
                    series = series_data.get('data', [])

                    # Extraer información de series
                    series_info = []
                    for serie in series:
                        serie_attrs = serie.get('attributes', {})
                        last_day = serie_attrs.get('last_day', {})

                        series_info.append({
                            'serie': serie_attrs.get('serie', ''),
                            'name': serie_attrs.get('name', ''),
                            'symbol': serie_attrs.get('symbol', ''),
                            'valor_cuota': last_day.get('price') if last_day else None,
                            'fecha_valor_cuota': last_day.get('date') if last_day else None,
                            'patrimonio_total': serie_attrs.get('total_assets'),
                            'patrimonio_neto': serie_attrs.get('total_net_assets'),
                            'comision_administracion': serie_attrs.get('fixed_management_fee'),
                            'comision_rescate': serie_attrs.get('redemption_fee'),
                            'participes': serie_attrs.get('shareholders')
                        })

                    resultado['series'] = series_info
                    logger.info(f"[FINTUAL CAPA 3] Encontradas {len(series_info)} series del fondo")
                else:
                    logger.warning(f"No se pudieron obtener series: {response_series.status_code}")
                    resultado['series'] = []

            return resultado

        except requests.exceptions.RequestException as e:
            logger.error(f"Error obteniendo datos de Fintual: {e}")
            return None
        except Exception as e:
            logger.error(f"Error procesando datos de Fintual: {e}")
            return None

    def _scrape_cmf_funds_list(self) -> List[Dict]:
        """Hacer scraping MEJORADO de la lista completa de fondos disponibles en CMF"""
        try:
            logger.info("Obteniendo lista completa de fondos desde CMF...")

            # URLs a intentar
            urls = [
                "https://www.cmfchile.cl/institucional/estadisticas/fm.bpr_menu.php",
                "https://www.cmfchile.cl/institucional/estadisticas/fm_patrimonio_menu.php",
                "https://www.cmfchile.cl/institucional/estadisticas/fondos_mutuos.php"
            ]

            funds_list = []

            for url in urls:
                try:
                    response = self.session.get(url, timeout=30)

                    if response.status_code != 200:
                        continue

                    soup = BeautifulSoup(response.content, 'html.parser')

                    # Método 1: Buscar en scripts JavaScript
                    # Formato esperado: var fondos_96767630=new Array("Seleccione...","9049-2   DEPÓSITO PLUS G",...)
                    # IMPORTANTE: Buscar en TODOS los scripts (CMF usa type="text/JavaScript" con J mayúscula)
                    scripts = soup.find_all('script')
                    for script in scripts:
                        if script.string and 'fondos_' in script.string:
                            script_content = script.string
                            # Buscar: var fondos_XXXXXXXXX=new Array(...)
                            fund_arrays = re.findall(r'fondos_(\d+)\s*=\s*new Array\((.*?)\);', script_content, re.DOTALL)

                            for rut_admin, fund_data in fund_arrays:
                                # Extraer todos los strings entre comillas
                                items = re.findall(r'"([^"]*)"', fund_data)

                                # Cada item tiene formato: "RUT   NOMBRE" o "Seleccione..."
                                for item in items:
                                    # Ignorar "Seleccione..." y strings vacíos
                                    if not item or 'seleccione' in item.lower():
                                        continue

                                    # Parsear formato "9049-2   DEPÓSITO PLUS G"
                                    # Separar por espacios múltiples
                                    parts = re.split(r'\s{2,}', item.strip(), maxsplit=1)

                                    if len(parts) == 2:
                                        rut_fondo = parts[0].strip()  # "9049-2"
                                        nombre_fondo = parts[1].strip()  # "DEPÓSITO PLUS G"

                                        # Validar que el RUT tenga formato correcto
                                        if re.match(r'^\d+-[\dkK]$', rut_fondo):
                                            funds_list.append({
                                                'rut_fondo': rut_fondo,  # RUT del fondo (ej: "9049-2")
                                                'rut_admin': rut_admin,  # RUT de la administradora (ej: "96767630")
                                                'nombre': nombre_fondo,
                                                'full_id': f"{rut_admin}_{rut_fondo}",
                                                'source': 'javascript'
                                            })
                                            logger.debug(f"Fondo encontrado: {rut_fondo} - {nombre_fondo} (Admin: {rut_admin})")

                    if funds_list:  # Si encontramos fondos, no necesitamos probar más URLs
                        break

                except Exception as e:
                    logger.warning(f"Error procesando URL {url}: {e}")
                    continue

            # Eliminar duplicados basado en RUT del fondo
            seen_ruts = set()
            unique_funds = []
            for fund in funds_list:
                # Usar 'nombre' si existe (nuevo formato), sino 'fund_name' (legacy)
                nombre = fund.get('nombre') or fund.get('fund_name', '')
                rut = fund.get('rut_fondo') or fund.get('full_id', '')

                # Validar que tiene datos mínimos
                if len(nombre) > 5 and rut and rut not in seen_ruts:
                    seen_ruts.add(rut)
                    unique_funds.append(fund)

            # NO GENERAR FONDOS FAKE - Retornar lista vacía si no hay datos reales
            if not unique_funds:
                logger.error("ERROR CRÍTICO: No se encontraron fondos reales en CMF")
                return []

            logger.info(f"Encontrados {len(unique_funds)} fondos únicos en CMF")
            return unique_funds

        except Exception as e:
            logger.error(f"ERROR CRÍTICO: Error scrapeando lista CMF: {e}")
            return []  # NO INVENTAR DATOS

   
    def _search_fund_in_cmf_by_rut(self, rut: str) -> Optional[Dict]:
        """
        Buscar fondo en CMF usando RUT (identificador único)

        Args:
            rut (str): RUT del fondo sin guión ni dígito verificador (ej: "10446")

        Returns:
            Dict con información del fondo desde CMF o None si no se encuentra
        """
        try:
            if not rut:
                logger.warning("RUT vacío proporcionado para búsqueda en CMF")
                return None

            logger.info(f"[CMF] Buscando fondo con RUT: {rut}")

            # URL de la página de entidad en CMF usando el RUT
            url = f"https://www.cmfchile.cl/institucional/mercados/entidad.php?mercado=V&rut={rut}&tipoentidad=RGFMU"

            response = self.session.get(url, timeout=30)

            if response.status_code != 200:
                logger.warning(f"[CMF] No se pudo acceder a la página del fondo RUT {rut}: {response.status_code}")
                return None

            soup = BeautifulSoup(response.content, 'html.parser')

            # Extraer información de la página
            fund_info = {
                'rut': rut,
                'rut_completo': None,  # Con dígito verificador
                'nombre': None,
                'url_cmf': url,
                'fuente': 'cmf_directo'
            }

            # Buscar el nombre del fondo en el título o headers
            title = soup.find('h1') or soup.find('h2') or soup.find('title')
            if title:
                nombre_texto = title.get_text().strip()
                # Limpiar el texto (remover "CMF Chile -" etc)
                nombre_limpio = nombre_texto.replace('CMF Chile -', '').replace('CMF Chile', '').strip()
                fund_info['nombre'] = nombre_limpio
                logger.info(f"[CMF] Nombre encontrado: {nombre_limpio}")

            # Buscar el RUN completo (con dígito verificador)
            # Patrón: "RUN: 10446-9" o similar
            texto_pagina = soup.get_text()
            run_match = re.search(r'RUN[:\s]+(\d+-[\dkK])', texto_pagina, re.IGNORECASE)
            if run_match:
                fund_info['rut_completo'] = run_match.group(1)
                logger.info(f"[CMF] RUN completo encontrado: {fund_info['rut_completo']}")

            # Verificar que encontramos datos válidos
            if fund_info['nombre']:
                logger.info(f"[CMF] Fondo encontrado exitosamente: {fund_info['nombre']}")
                return fund_info
            else:
                logger.warning(f"[CMF] No se pudo extraer información del fondo con RUT {rut}")
                return None

        except Exception as e:
            logger.error(f"[CMF] Error buscando fondo por RUT {rut}: {e}")
            return None

    def _search_fund_in_cmf(self, target_name: str) -> Optional[Dict]:
        """Buscar un fondo específico en la lista de CMF por nombre (método legacy)"""
        try:
            funds_list = self._scrape_cmf_funds_list()

            if not funds_list:
                return None

            target_lower = target_name.lower().replace('_', ' ')

            # Buscar coincidencia exacta o parcial
            best_match = None
            best_score = 0

            for fund in funds_list:
                # Usar 'nombre' (nuevo formato) o 'fund_name' (legacy)
                fund_name = fund.get('nombre') or fund.get('fund_name', '')
                fund_name_lower = fund_name.lower()

                # Calcular score de similitud
                score = 0

                # Coincidencia exacta
                if target_lower == fund_name_lower:
                    score = 100

                # Palabras clave contenidas
                elif target_lower in fund_name_lower:
                    score = 80

                # Palabras individuales
                else:
                    target_words = target_lower.split()
                    fund_words = fund_name_lower.split()

                    matches = sum(1 for word in target_words if any(word in fund_word for fund_word in fund_words))
                    if matches > 0:
                        score = (matches / len(target_words)) * 60

                if score > best_score:
                    best_score = score
                    best_match = fund

            if best_match and best_score > 30:  # Umbral mínimo de similitud
                fund_name_match = best_match.get('nombre') or best_match.get('fund_name', 'Unknown')
                logger.info(f"Fondo encontrado en CMF: {fund_name_match} (score: {best_score})")
                logger.info(f"  RUT Fondo: {best_match.get('rut_fondo')}, RUT Admin: {best_match.get('rut_admin')}")
                return best_match
            else:
                logger.warning(f"No se encontró fondo similar a '{target_name}' en CMF")
                return None

        except Exception as e:
            logger.error(f"Error buscando fondo en CMF: {e}")
            return None

    def _get_fund_financial_data(self, fund_info: Dict) -> Dict:
        """Obtener TODOS los datos financieros disponibles dinámicamente desde CMF"""
        try:
            logger.info(f"Obteniendo datos financieros completos para: {fund_info['fund_name']}")

            # URL para datos de patrimonio y rentabilidad
            url = "https://www.cmfchile.cl/institucional/estadisticas/fm.patrimonio_resultado.php"

            # Parámetros para la consulta específica
            params = {
                'consulta': 'fecha',  # Consulta por fecha
                'rut_admin': fund_info['administrator_id'],
                'cod_fondo': fund_info['fund_code'],
                'fecha_desde': (datetime.now() - timedelta(days=90)).strftime('%d/%m/%Y'),  # 3 meses atrás
                'fecha_hasta': datetime.now().strftime('%d/%m/%Y')
            }

            response = self.session.get(url, params=params, timeout=30)

            if response.status_code == 200:
                # Parsear la respuesta HTML para extraer TODOS los datos disponibles
                soup = BeautifulSoup(response.content, 'html.parser')

                # Buscar tablas con datos financieros
                tables = soup.find_all('table')

                # Estructura dinámica para almacenar TODOS los datos encontrados
                financial_data = {}
                data_patterns = {
                    'patrimonio': ['patrimonio', 'assets', 'activos'],
                    'valor_cuota': ['valor cuota', 'precio', 'price', 'cuota'],
                    'rentabilidad': ['rentabilidad', 'return', 'rendimiento'],
                    'numero_participes': ['participes', 'investors', 'inversionistas'],
                    'gastos': ['gastos', 'expenses', 'costos'],
                    'comisiones': ['comision', 'fee', 'tarifa'],
                    'duracion': ['duracion', 'duration', 'plazo'],
                    'volatilidad': ['volatilidad', 'volatility', 'riesgo']
                }
#sera en esta parte que faltara el perfil de riesgo / tolerancia al riesgo 
                # Extraer TODOS los datos numéricos encontrados
                for table in tables:
                    rows = table.find_all('tr')
                    for row in rows:
                        cells = row.find_all(['td', 'th'])
                        if len(cells) >= 2:
                            text = ' '.join([cell.get_text().strip() for cell in cells])
                            text_lower = text.lower()

                            # Buscar patrones dinámicamente
                            for key, patterns in data_patterns.items():
                                for pattern in patterns:
                                    if pattern in text_lower:
                                        # Extraer valor numérico o porcentual
                                        if 'rentabilidad' in pattern or 'return' in pattern:
                                            value = self._extract_percentage_value(text)
                                            if value is not None:
                                                if 'mes' in text_lower or 'month' in text_lower:
                                                    financial_data[f'{key}_mes'] = value
                                                elif 'año' in text_lower or 'anual' in text_lower or 'year' in text_lower:
                                                    financial_data[f'{key}_anual'] = value
                                                else:
                                                    financial_data[key] = value
                                        else:
                                            value = self._extract_numeric_value(text)
                                            if value:
                                                financial_data[key] = value

                            # También extraer cualquier dato numérico que no coincida con patrones
                            numeric_value = self._extract_numeric_value(text)
                            percentage_value = self._extract_percentage_value(text)

                            if numeric_value and not any(key for key in financial_data.values() if key == numeric_value):
                                # Crear clave descriptiva basada en el texto
                                clean_text = re.sub(r'[^\w\s]', '', text_lower)
                                words = clean_text.split()[:3]  # Primeras 3 palabras
                                key_name = '_'.join(words) if words else f'valor_{len(financial_data)}'
                                financial_data[f'data_{key_name}'] = numeric_value

                            if percentage_value is not None and not any(key for key in financial_data.values() if key == percentage_value):
                                clean_text = re.sub(r'[^\w\s]', '', text_lower)
                                words = clean_text.split()[:3]
                                key_name = '_'.join(words) if words else f'porcentaje_{len(financial_data)}'
                                financial_data[f'pct_{key_name}'] = percentage_value

                logger.info(f"Datos financieros extraídos dinámicamente: {len(financial_data)} campos")
                logger.debug(f"Campos encontrados: {list(financial_data.keys())}")
                return financial_data

            else:
                logger.warning(f"Error obteniendo datos financieros: {response.status_code}")
                return {}

        except Exception as e:
            logger.error(f"Error obteniendo datos financieros: {e}")
            return {}

    def _get_fund_portfolio_data(self, fund_info: Dict) -> Dict:
        """Obtener TODOS los datos de cartera/composición disponibles dinámicamente desde CMF"""
        try:
            logger.info(f"Obteniendo composición completa de cartera para: {fund_info['fund_name']}")

            # Intentar múltiples endpoints para obtener datos de cartera
            portfolio_urls = [
                "https://www.cmfchile.cl/institucional/estadisticas/ffm_cartera.php",
                "https://www.cmfchile.cl/institucional/estadisticas/fm_cartera_detalle.php",
                "https://www.cmfchile.cl/institucional/estadisticas/fm_composicion.php"
            ]

            portfolio_data = {}

            for url in portfolio_urls:
                try:
                    # Obtener datos del mes anterior
                    prev_month = datetime.now().replace(day=1) - timedelta(days=1)

                    # Hacer POST para generar archivo de cartera
                    data = {
                        'mes': f"{prev_month.month:02d}",
                        'ano': str(prev_month.year),
                        'tipo': 'nacional',  # Empezar con cartera nacional
                        'rut_admin': fund_info.get('administrator_id', ''),
                        'cod_fondo': fund_info.get('fund_code', '')
                    }

                    response = self.session.post(url, data=data, timeout=60)

                    if response.status_code == 200 and response.text.strip():
                        # El archivo puede venir en varios formatos
                        content = response.text.strip()

                        # Detectar formato automáticamente
                        detected_data = self._parse_portfolio_content_dynamic(content, fund_info)

                        if detected_data:
                            portfolio_data.update(detected_data)
                            logger.info(f"Datos de cartera extraídos de {url}: {len(detected_data)} elementos")

                except Exception as e:
                    logger.debug(f"Error probando URL {url}: {e}")
                    continue

            if portfolio_data:
                # Procesar y normalizar cartera con todos los datos encontrados
                return self._process_portfolio_data_dynamic(portfolio_data, fund_info)
            else:
                logger.error(f"No se encontró información de cartera para el fondo")
                return {
                    'composicion_portafolio': [],
                    'error': 'No se pudo obtener composición real del portafolio',
                    'data_source': 'ERROR'
                }

        except Exception as e:
            logger.error(f"Error obteniendo cartera: {e}")
            return {
                'composicion_portafolio': [],
                'error': f'Error obteniendo cartera: {str(e)}',
                'data_source': 'ERROR'
            }

    def _parse_portfolio_content_dynamic(self, content: str, fund_info: Dict) -> Dict:
        """Parsear dinámicamente el contenido de cartera en cualquier formato"""
        portfolio_items = {}

        try:
            # Detectar separadores comunes
            separators = ['\t', ';', ',', '|']
            detected_separator = '\t'  # Default

            for sep in separators:
                if content.count(sep) > content.count(detected_separator):
                    detected_separator = sep

            lines = content.split('\n')

            if len(lines) > 1:
                # Analizar header para entender estructura
                header_line = lines[0].lower()
                headers = header_line.split(detected_separator)

                logger.debug(f"Headers detectados: {headers}")

                # Buscar índices de columnas importantes dinámicamente
                col_indices = {}
                for i, header in enumerate(headers):
                    header_clean = header.strip().lower()
                    if any(word in header_clean for word in ['instrumento', 'instrument', 'activo', 'asset']):
                        col_indices['instrument'] = i
                    elif any(word in header_clean for word in ['emisor', 'issuer', 'empresa', 'company']):
                        col_indices['issuer'] = i
                    elif any(word in header_clean for word in ['monto', 'amount', 'valor', 'value']):
                        col_indices['amount'] = i
                    elif any(word in header_clean for word in ['porcentaje', 'percentage', '%', 'pct']):
                        col_indices['percentage'] = i
                    elif any(word in header_clean for word in ['admin', 'administradora']):
                        col_indices['admin'] = i
                    elif any(word in header_clean for word in ['fondo', 'fund']):
                        col_indices['fund'] = i

                # Procesar datos línea por línea
                for line_num, line in enumerate(lines[1:], 1):
                    if not line.strip():
                        continue

                    fields = line.split(detected_separator)

                    # Verificar si esta línea corresponde a nuestro fondo
                    line_lower = line.lower()
                    fund_match = False

                    if (fund_info.get('fund_code', '').lower() in line_lower or
                        fund_info.get('administrator_id', '') in line or
                        any(word.lower() in line_lower for word in fund_info.get('fund_name', '').split()[:3] if len(word) > 3)):
                        fund_match = True

                    # También procesar líneas que contengan datos financieros relevantes
                    if fund_match or len(fields) >= 3:
                        item_data = {
                            'line_number': line_num,
                            'raw_line': line,
                            'fields': fields
                        }

                        # Extraer datos usando índices detectados
                        for key, index in col_indices.items():
                            if index < len(fields):
                                item_data[key] = fields[index].strip()

                        # Extraer valores numéricos de todos los campos
                        for i, field in enumerate(fields):
                            numeric_val = self._extract_numeric_value(field)
                            percentage_val = self._extract_percentage_value(field)

                            if numeric_val:
                                item_data[f'numeric_{i}'] = numeric_val
                            if percentage_val is not None:
                                item_data[f'percentage_{i}'] = percentage_val

                        portfolio_items[f'item_{line_num}'] = item_data

            logger.debug(f"Items de cartera parseados: {len(portfolio_items)}")
            return portfolio_items

        except Exception as e:
            logger.error(f"Error parseando contenido de cartera: {e}")
            return {}

    def _process_portfolio_data_dynamic(self, raw_portfolio: Dict, fund_info: Dict) -> Dict:
        """Procesar dinámicamente TODOS los datos crudos de cartera"""
        try:
            processed_portfolio = {
                'composicion_portafolio': [],
                'total_items_raw': len(raw_portfolio),
                'data_quality_score': 0,
                'extraction_metadata': {
                    'fund_matches_found': 0,
                    'numeric_fields_found': 0,
                    'instruments_identified': 0,
                    'processing_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
            }

            # Agrupar por tipo de instrumento dinámicamente
            instrument_groups = {}
            total_amount = 0
            numeric_fields_count = 0

            for item_key, item_data in raw_portfolio.items():
                try:
                    # Identificar instrumento
                    instrument_name = None
                    amount = 0
                    percentage = None

                    # Buscar nombre de instrumento en los campos
                    if 'instrument' in item_data:
                        instrument_name = item_data['instrument']
                    elif 'issuer' in item_data:
                        instrument_name = item_data['issuer']
                    else:
                        # Buscar en campos de texto más largos
                        for field in item_data.get('fields', []):
                            if len(field.strip()) > 10 and not field.replace('.', '').replace(',', '').isdigit():
                                instrument_name = field.strip()
                                break

                    # Buscar monto o porcentaje
                    if 'amount' in item_data:
                        amount = self._extract_numeric_value(item_data['amount']) or 0
                    if 'percentage' in item_data:
                        percentage = self._extract_percentage_value(item_data['percentage'])

                    # Buscar en campos numéricos
                    for key, value in item_data.items():
                        if key.startswith('numeric_'):
                            if amount == 0:  # Solo usar si no tenemos amount ya
                                amount = value
                            numeric_fields_count += 1
                        elif key.startswith('percentage_') and percentage is None:
                            percentage = value

                    if instrument_name:
                        # Clasificar instrumento dinámicamente
                        instrument_type = self._classify_instrument_dynamic(instrument_name)

                        if instrument_type not in instrument_groups:
                            instrument_groups[instrument_type] = {
                                'total_amount': 0,
                                'items': [],
                                'count': 0
                            }

                        instrument_groups[instrument_type]['total_amount'] += amount
                        instrument_groups[instrument_type]['count'] += 1
                        instrument_groups[instrument_type]['items'].append({
                            'name': instrument_name,
                            'amount': amount,
                            'percentage': percentage,
                            'raw_data': item_data
                        })

                        total_amount += amount
                        processed_portfolio['extraction_metadata']['instruments_identified'] += 1

                except Exception as e:
                    logger.debug(f"Error procesando item {item_key}: {e}")

            # Convertir a formato normalizado
            composition = []
            if total_amount > 0:
                for instrument_type, group_data in instrument_groups.items():
                    group_percentage = group_data['total_amount'] / total_amount
                    composition.append({
                        'activo': instrument_type,
                        'porcentaje': group_percentage,
                        'monto_total': group_data['total_amount'],
                        'cantidad_instrumentos': group_data['count'],
                        'instrumentos_detalle': group_data['items'][:5]  # Top 5 por tipo
                    })

            # Ordenar por porcentaje descendente
            composition.sort(key=lambda x: x['porcentaje'], reverse=True)

            processed_portfolio['composicion_portafolio'] = composition[:15]  # Top 15
            processed_portfolio['extraction_metadata']['numeric_fields_found'] = numeric_fields_count

            # Calcular score de calidad
            quality_score = min(10, len(composition) * 2)  # Máximo 10
            if processed_portfolio['extraction_metadata']['instruments_identified'] > 10:
                quality_score += 2
            if numeric_fields_count > 5:
                quality_score += 1

            processed_portfolio['data_quality_score'] = quality_score

            logger.info(f"Cartera procesada dinámicamente: {len(composition)} tipos de activos, score: {quality_score}/10")
            return processed_portfolio

        except Exception as e:
            logger.error(f"Error procesando cartera dinámicamente: {e}")
            return {'composicion_portafolio': [], 'error': str(e)}

    def _classify_instrument_dynamic(self, instrument_name: str) -> str:
        """Clasificar dinámicamente un instrumento financiero con patrones expandidos"""
        name_lower = instrument_name.lower()

        # Patrones expandidos para clasificación
        classifications = {
            'Bonos Gobierno': ['bono gobierno', 'treasury', 'btc', 'bono central', 'bcp', 'tesoreria'],
            'Bonos Corporativos': ['bono empresa', 'corporate bond', 'bono corporativo', 'empresa', 'corp'],
            'Acciones Chilenas': ['accion chile', 'equity chile', 'bolsa santiago', 'ipsa', 'chile'],
            'Acciones Extranjeras': ['accion extranjera', 'foreign equity', 'international', 'usa', 'europe', 'global'],
            'Depósitos a Plazo': ['deposito plazo', 'deposit', 'plazo fijo', 'tiempo deposito'],
            'Cuotas de Fondos': ['cuota fondo', 'fund share', 'mutual fund', 'fondo mutuo', 'etf'],
            'Instrumentos Moneda': ['moneda', 'currency', 'forex', 'divisa', 'cambio'],
            'Derivados Financieros': ['derivado', 'forward', 'future', 'swap', 'option'],
            'Bienes Raíces': ['real estate', 'inmobiliario', 'property', 'reit'],
            'Materias Primas': ['commodity', 'oro', 'gold', 'petroleo', 'oil', 'copper', 'cobre']
        }

        # Buscar coincidencias
        for category, patterns in classifications.items():
            if any(pattern in name_lower for pattern in patterns):
                return category

        # Clasificación por longitud y características del texto
        if len(name_lower) < 10:
            return 'Instrumentos de Corto Plazo'
        elif any(char.isdigit() for char in name_lower):
            return 'Instrumentos con Vencimiento'
        else:
            return 'Otros Instrumentos'

    def _process_portfolio_data(self, raw_portfolio: List[Dict]) -> Dict:
        """Procesar datos crudos de cartera para generar composición normalizada"""
        try:
            # Agrupar por tipo de instrumento
            grouped = {}
            total_amount = 0

            for item in raw_portfolio:
                instrument_type = self._classify_instrument(item['instrumento'])
                amount = item['monto'] or 0

                if instrument_type not in grouped:
                    grouped[instrument_type] = 0
                grouped[instrument_type] += amount
                total_amount += amount

            # Convertir a porcentajes
            composition = []
            if total_amount > 0:
                for instrument, amount in grouped.items():
                    percentage = amount / total_amount
                    composition.append({
                        'activo': instrument,
                        'porcentaje': percentage
                    })

            # Ordenar por porcentaje descendente
            composition.sort(key=lambda x: x['porcentaje'], reverse=True)

            return {
                'composicion_portafolio': composition[:10],  # Top 10
                'total_instruments': len(raw_portfolio),
                'portfolio_date': (datetime.now() - timedelta(days=30)).strftime('%Y-%m')
            }

        except Exception as e:
            logger.error(f"Error procesando cartera: {e}")
            return {'composicion_portafolio': []}

    def _classify_instrument(self, instrument_name: str) -> str:
        """Clasificar un instrumento financiero en categorías generales"""
        name_lower = instrument_name.lower()

        if any(word in name_lower for word in ['bono', 'bond', 'btc', 'treasury']):
            return 'Bonos'
        elif any(word in name_lower for word in ['accion', 'equity', 'stock', 'share']):
            return 'Acciones'
        elif any(word in name_lower for word in ['deposito', 'plazo', 'deposit']):
            return 'Depósitos a Plazo'
        elif any(word in name_lower for word in ['cuota', 'fondo', 'fund']):
            return 'Cuotas de Fondos'
        elif any(word in name_lower for word in ['moneda', 'currency', 'forex']):
            return 'Instrumentos de Moneda'
        else:
            return 'Otros Instrumentos'

    def _generate_sample_portfolio(self, fund_info: Dict) -> Dict:
        """
        ELIMINADO: Generar cartera de muestra basada en el nombre del fondo

        Esta función generaba datos FALSOS. Ahora retorna error explícito.
        NO SE DEBEN INVENTAR DATOS DE COMPOSICIÓN DE PORTAFOLIO.
        """
        logger.error("[DATOS FALSOS BLOQUEADOS] No se puede generar cartera simulada")
        return {
            'composicion_portafolio': [],
            'error': 'No hay datos reales de composición disponibles',
            'is_sample': False,
            'data_source': 'ERROR: No se pudo obtener datos reales'
        }

    def _extract_numeric_value(self, text: str) -> Optional[float]:
        """Extraer valor numérico de un texto"""
        try:
            # Buscar números con separadores de miles y decimales
            pattern = r'[\d,]+\.?\d*'
            matches = re.findall(pattern, text.replace('.', '').replace(',', '.'))

            if matches:
                return float(matches[-1])  # Tomar el último número encontrado
            return None
        except Exception as e:
            logger.debug(f"[UTIL] Error en _extract_numeric_value: {e}, input: {text[:100] if text else 'None'}")
            return None

    def _extract_percentage_value(self, text: str) -> Optional[float]:
        """Extraer valor porcentual de un texto y convertirlo a decimal"""
        try:
            # Buscar patrón de porcentaje
            pattern = r'(-?\d+\.?\d*)\s*%'
            match = re.search(pattern, text)

            if match:
                return float(match.group(1)) / 100  # Convertir a decimal
            return None
        except:
            return None

    def _generate_ai_description(self, fondo_data: Dict) -> str:
        """Generar descripción amigable usando OpenAI"""
        if not self.openai_key:
            return "Descripción no disponible - API key de OpenAI no configurada"

        try:
            # Cargar prompt desde archivo
            prompt_path = 'prompts/fondos_prompt.txt'
            if os.path.exists(prompt_path):
                with open(prompt_path, 'r', encoding='utf-8') as f:
                    prompt_template = f.read()
            else:
                prompt_template = self._get_default_prompt()

            # Preparar datos para el prompt
            composicion_str = ', '.join([
                f"{item['activo']}: {item['porcentaje']:.1%}"
                for item in fondo_data.get('composicion_portafolio', [])[:5]
            ])

            # Formatear prompt con datos del fondo
            prompt = prompt_template.format(
                nombre_fondo=fondo_data.get('nombre', 'N/A'),
                tipo_fondo=fondo_data.get('tipo_fondo', 'N/A'),
                perfil_riesgo=fondo_data.get('perfil_riesgo', 'N/A'),
                composicion_top5=composicion_str or 'No disponible',
                rentabilidad_12m=fondo_data.get('rentabilidad_anual', 'N/A')
            )

            # Llamada a OpenAI (nueva sintaxis para v1.0+)
            client = openai.OpenAI(api_key=self.openai_key)
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Eres un experto en finanzas que escribe descripciones claras para jóvenes inversores chilenos."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=600,
                temperature=0.7
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"Error generando descripción con IA: {e}")
            return f"Error generando descripción automática: {str(e)}"

    def _get_default_prompt(self) -> str:
        """Prompt por defecto si no se encuentra el archivo"""
        return """
        Genera una descripción clara y amigable del siguiente fondo mutuo:

        Nombre: {nombre_fondo}
        Tipo: {tipo_fondo}
        Perfil de riesgo: {perfil_riesgo}
        Principales inversiones: {composicion_top5}
        Rentabilidad 12 meses: {rentabilidad_12m}

        Explica en máximo 400 palabras qué es este fondo, para quién es adecuado,
        y cuál es su estrategia de inversión. Usa un tono profesional pero accesible.
        """

    def _calculate_fund_metrics(self, data: Dict) -> Dict:
        """Calcular métricas avanzadas del fondo mutuo"""
        metrics = {
            'clasificacion_riesgo_detallada': '', # Antes salia "medio" ( lo cual estaba generado por ia) ver en los logs si cambio algo dejarlo vacio
            'perfil_inversionista_ideal': '',
            'horizonte_inversion_recomendado': '',
            'ventajas_principales': [],
            'desventajas_principales': [],
            'comparacion_benchmarks': {},
            'analisis_diversificacion': {},
            'proyeccion_rentabilidad': {},
            'costos_estimados': {}
        }

        try:
            tipo_fondo = data.get('tipo_fondo', '').lower()
            composicion = data.get('composicion_portafolio', [])

            # Clasificación de riesgo detallada - SOLO basada en datos reales
            perfil_riesgo = data.get('perfil_riesgo', None)

            # ETL FIX: NO inferir desde nombre del fondo
            # Usar clasificación oficial del CMF/PDF o dejar como None
            if perfil_riesgo and perfil_riesgo != 'N/A':
                metrics['clasificacion_riesgo_detallada'] = perfil_riesgo
            else:
                metrics['clasificacion_riesgo_detallada'] = None

            # NO GENERAR PERFILES/HORIZONTES/VENTAJAS GENÉRICAS
            # Estos deben venir del documento oficial del fondo o IA con contexto real
            # FIX: Usar datos extraídos del PDF, no hardcodear
            metrics['perfil_inversionista_ideal'] = data.get('perfil_inversionista_ideal', None)
            metrics['horizonte_inversion_recomendado'] = data.get('horizonte_inversion', None)
            metrics['horizonte_inversion_meses'] = data.get('horizonte_inversion_meses', None)
            metrics['ventajas_principales'] = []
            metrics['desventajas_principales'] = []

            # Análisis de diversificación
            if composicion:
                total_activos = len(composicion)
                concentracion_max = max([item.get('porcentaje', 0) for item in composicion]) if composicion else 0

                metrics['analisis_diversificacion'] = {
                    'total_activos': total_activos,
                    'concentracion_maxima': concentracion_max,
                    'nivel_diversificacion': 'Alta' if total_activos > 15 and concentracion_max < 0.2 else
                                           'Media' if total_activos > 8 and concentracion_max < 0.3 else 'Baja',
                    'distribucion_por_tipo': self._analyze_asset_distribution(composicion)
                }

            # NO GENERAR PROYECCIONES - Solo usar datos reales
            # Las proyecciones requieren datos históricos reales, no estimaciones
            rentabilidad_real = data.get('rentabilidad_anual')

            if rentabilidad_real is not None:
                metrics['proyeccion_rentabilidad'] = {
                    'rentabilidad_real_anual': rentabilidad_real,
                    'nota': 'Rentabilidad histórica real - No es garantía de rendimiento futuro'
                }
            else:
                metrics['proyeccion_rentabilidad'] = {
                    'error': 'No hay datos de rentabilidad disponibles'
                }

            # NO INVENTAR COSTOS - Solo usar datos scrapeados del PDF/CMF
            # Las comisiones deben extraerse de los documentos oficiales del fondo
            # Return actual comisiones if extracted
            comisiones = {}
            if data.get('comision_administracion') is not None:
                comisiones['comision_administracion'] = data['comision_administracion']
            if data.get('comision_rescate') is not None:
                comisiones['comision_rescate'] = data['comision_rescate']

            if not comisiones:
                metrics['costos_estimados'] = {'error': 'Costos no disponibles'}
            else:
                metrics['costos_estimados'] = comisiones

            # NO INCLUIR benchmarks sin datos reales
            # Los benchmarks requieren cotizaciones en tiempo real
            metrics['comparacion_benchmarks'] = {
                'nota': 'Comparación con benchmarks requiere datos de mercado actualizados'
            }

        except Exception as e:
            logger.warning(f"Error calculando métricas del fondo: {e}")

        return metrics

    def _analyze_asset_distribution(self, composicion: List[Dict]) -> Dict:
        """Analizar distribución de activos por tipo"""
        distribution = {'renta_fija': 0, 'renta_variable': 0, 'otros': 0}

        for item in composicion:
            activo = item.get('activo', '').lower()
            porcentaje = item.get('porcentaje', 0)

            if any(word in activo for word in ['bono', 'depósito', 'plazo', 'treasury']):
                distribution['renta_fija'] += porcentaje
            elif any(word in activo for word in ['accion', 'equity', 'stock']):
                distribution['renta_variable'] += porcentaje
            else:
                distribution['otros'] += porcentaje

        return distribution

    def _estimate_volatility(self, tipo_fondo: str) -> Optional[float]:
        """
        ELIMINADO: Estimar volatilidad anual basada en tipo de fondo
        La volatilidad NO se puede inventar, debe calcularse de datos históricos reales
        """
        logger.warning("[DATOS INVENTADOS BLOQUEADOS] No se puede estimar volatilidad sin datos históricos")
        return None

    def _calculate_data_quality_score(self, data: Dict) -> Dict:
        """
        Calculate a data quality score (0-100) based on field completeness.
        Returns dict with score, level, and breakdown by category.
        """
        # Define critical, important, and optional fields
        critical_fields = ['nombre', 'run', 'rut_base', 'tipo_fondo', 'perfil_riesgo']
        important_fields = ['horizonte_inversion', 'tolerancia_riesgo', 'composicion_portafolio',
                            'rentabilidad_12m', 'comision_administracion']
        optional_fields = ['patrimonio', 'fondo_rescatable', 'plazos_rescates',
                           'duracion', 'monto_minimo']

        # Calculate scores
        critical_score = sum([1 for f in critical_fields if data.get(f)]) / len(critical_fields) * 60
        important_score = sum([1 for f in important_fields if data.get(f)]) / len(important_fields) * 30
        optional_score = sum([1 for f in optional_fields if data.get(f)]) / len(optional_fields) * 10

        total_score = critical_score + important_score + optional_score

        # Determine quality level
        if total_score >= 80:
            quality_level = 'Excelente'
        elif total_score >= 60:
            quality_level = 'Buena'
        elif total_score >= 40:
            quality_level = 'Regular'
        else:
            quality_level = 'Baja'

        return {
            'score': round(total_score, 1),
            'level': quality_level,
            'critical_pct': round(critical_score / 60 * 100, 1),
            'important_pct': round(important_score / 30 * 100, 1),
            'optional_pct': round(optional_score / 10 * 100, 1)
        }

    def _generate_confidence_warnings(self, data: Dict) -> str:
        """
        Generate comprehensive confidence warnings based on data quality.
        Returns a string with warnings separated by ' | '
        """
        confidence_warnings = []

        # Calculate confidence score
        confidence = data.get('extraction_confidence', 'unknown')

        if confidence == 'low' or confidence == 'unknown':
            confidence_warnings.append('⚠ Baja confianza en extracción de datos')

        # Check specific critical fields
        critical_fields = ['run', 'tipo_fondo', 'perfil_riesgo', 'composicion_portafolio']
        missing_critical = [f for f in critical_fields if not data.get(f)]

        if missing_critical:
            confidence_warnings.append(f'⚠ Campos críticos faltantes: {", ".join(missing_critical)}')

        # Check if composicion is empty
        if not data.get('composicion_portafolio') or len(data.get('composicion_portafolio', [])) == 0:
            confidence_warnings.append('⚠ Composición de portafolio no extraída')

        # Check if RUN is missing
        if not data.get('run'):
            confidence_warnings.append('⚠ RUN no disponible - Verificar en CMF manualmente')

        # Check if error exists
        if data.get('error'):
            confidence_warnings.append(f'⚠ Error durante extracción: {data["error"]}')

        # Return combined warnings or "Ninguna"
        return ' | '.join(confidence_warnings) if confidence_warnings else 'Ninguna'

    def _generate_excel(self, data: Dict) -> None:
        """Generar archivo Excel AVANZADO con análisis completo del fondo"""
        try:
            # Calcular métricas avanzadas
            metrics = self._calculate_fund_metrics(data)

            # Hoja 1: Resumen Ejecutivo
            resumen_data = {
                'Aspecto': [
                    'Nombre del Fondo',
                    'Nombre en CMF',
                    'RUN del Fondo',
                    'RUT Base',
                    'Estado del Fondo',
                    'Fecha Valor Cuota',
                    'Tipo de Fondo',
                    'Perfil de Riesgo',
                    'Escala de Riesgo (R1-R7)',
                    'Tolerancia al Riesgo',
                    'Patrimonio',
                    'Comisión Administración (%)',
                    'Comisión Rescate (%)',
                    'Clasificación Detallada',
                    'Rentabilidad 12 Meses (%)',
                    'Rentabilidad 24 Meses (%)',
                    'Rentabilidad 36 Meses (%)',
                    'Fondo Rescatable',
                    'Plazo de Rescate',
                    'Duración del Fondo',
                    'Monto Mínimo',
                    'Fuente de Datos',
                    'Fecha de Análisis',
                    'Perfil Inversionista Ideal',
                    'Horizonte Recomendado',
                    'Horizonte en Meses'
                ],
                'Detalle': [
                    data.get('nombre', 'Sin nombre'),
                    data.get('nombre_cmf', 'No registrado en CMF'),
                    data.get('run', 'No disponible en fuentes'),
                    data.get('rut_base', 'No disponible en fuentes'),
                    data.get('estado_fondo', 'Estado desconocido'),
                    data.get('fecha_valor_cuota', 'Fecha no disponible'),
                    data.get('tipo_fondo', 'Tipo no extraído'),
                    data.get('perfil_riesgo', 'Perfil no extraído'),
                    data.get('perfil_riesgo_escala', 'No disponible'),
                    data.get('tolerancia_riesgo', 'No especificado en PDF'),
                    data.get('patrimonio', 'No disponible'),
                    f"{data.get('comision_administracion', 0):.4f}" if data.get('comision_administracion') else 'No extraída',
                    f"{data.get('comision_rescate', 0):.4f}" if data.get('comision_rescate') else 'No extraída',
                    metrics.get('clasificacion_riesgo_detallada', 'No clasificado'),
                    f"{data.get('rentabilidad_12m', 0):.2%}" if data.get('rentabilidad_12m') else 'No disponible',
                    f"{data.get('rentabilidad_24m', 0):.2%}" if data.get('rentabilidad_24m') else 'No disponible',
                    f"{data.get('rentabilidad_36m', 0):.2%}" if data.get('rentabilidad_36m') else 'No disponible',
                    'Sí' if data.get('fondo_rescatable') is True else 'No' if data.get('fondo_rescatable') is False else 'No especificado',
                    data.get('plazos_rescates', 'No especificado'),
                    data.get('duracion', 'No especificada'),
                    data.get('monto_minimo', 'No especificado'),
                    'CMF Chile + Scraping Web' if data.get('fuente_cmf') else 'ERROR: Datos CMF no disponibles',
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    metrics.get('perfil_inversionista_ideal') if metrics.get('perfil_inversionista_ideal') else 'No determinado',
                    metrics.get('horizonte_inversion_recomendado') if metrics.get('horizonte_inversion_recomendado') else 'No especificado en PDF',
                    metrics.get('horizonte_inversion_meses') if metrics.get('horizonte_inversion_meses') else 'No determinado'
                ]
            }

            # Hoja 2: Composición del Portafolio
            composicion = data.get('composicion_portafolio', [])
            if composicion and len(composicion) > 0:
                composicion_data = {
                    'Activo/Instrumento': [item.get('activo', 'Sin nombre') for item in composicion],
                    'Tipo': [item.get('tipo_activo', 'No clasificado') for item in composicion],
                    'Porcentaje': [item.get('porcentaje', 0) for item in composicion]
                }

                # Add summary row
                total_porcentaje = sum([item.get('porcentaje', 0) for item in composicion])
                composicion_data['Activo/Instrumento'].append('TOTAL')
                composicion_data['Tipo'].append('-')
                composicion_data['Porcentaje'].append(total_porcentaje)

                # Add validation warning if total != 100%
                if abs(total_porcentaje - 100.0) > 5.0:
                    composicion_data['Activo/Instrumento'].append('⚠ NOTA')
                    composicion_data['Tipo'].append('Advertencia')
                    composicion_data['Porcentaje'].append('')
                    logger.warning(f"[EXCEL] Composición no suma 100%: {total_porcentaje:.2f}%")
            else:
                composicion_data = {
                    'Activo/Instrumento': ['No se pudo extraer composición del PDF'],
                    'Tipo': ['Verifique el folleto informativo manualmente'],
                    'Porcentaje': ['']
                }

            # Hoja 3: Análisis de Riesgo y Rentabilidad - SOLO DATOS REALES
            proyeccion = metrics.get('proyeccion_rentabilidad', {})
            diversificacion = metrics.get('analisis_diversificacion', {})

            # Solo incluir métricas CALCULADAS (no inventadas)
            metricas_lista = []
            valores_lista = []
            interpretaciones_lista = []

            # Rentabilidad real (si existe)
            if 'rentabilidad_real_anual' in proyeccion:
                metricas_lista.append('Rentabilidad Anual Real')
                valores_lista.append(f"{proyeccion['rentabilidad_real_anual']:.2%}")
                interpretaciones_lista.append('Rentabilidad histórica - No garantiza rendimiento futuro')

            # Análisis de diversificación (CALCULADO de composición real)
            if diversificacion:
                if 'nivel_diversificacion' in diversificacion:
                    metricas_lista.append('Nivel de Diversificación')
                    valores_lista.append(diversificacion.get('nivel_diversificacion', 'N/A'))
                    interpretaciones_lista.append('Nivel de distribución del riesgo (calculado)')

                if 'total_activos' in diversificacion:
                    metricas_lista.append('Total de Activos')
                    valores_lista.append(str(diversificacion.get('total_activos', 'N/A')))
                    interpretaciones_lista.append('Cantidad de instrumentos diferentes')

                if 'concentracion_maxima' in diversificacion:
                    metricas_lista.append('Concentración Máxima')
                    valores_lista.append(f"{diversificacion.get('concentracion_maxima', 0):.2%}")
                    interpretaciones_lista.append('Máxima exposición a un solo activo')

            # Si no hay datos, mostrar mensaje
            if not metricas_lista:
                metricas_lista = ['Sin Datos Disponibles']
                valores_lista = ['N/A']
                interpretaciones_lista = ['Requiere datos de scraping de CMF/PDFs']

            riesgo_rentabilidad_data = {
                'Métrica': metricas_lista,
                'Valor': valores_lista,
                'Interpretación': interpretaciones_lista
            }

            # Hoja 4: Ventajas y Desventajas - SOLO SI HAY DATOS REALES
            ventajas = metrics.get('ventajas_principales', [])
            desventajas = metrics.get('desventajas_principales', [])

            # Solo crear hoja si hay datos reales (no listas vacías)
            if ventajas or desventajas:
                max_items = max(len(ventajas), len(desventajas), 1)
                ventajas.extend([''] * (max_items - len(ventajas)))
                desventajas.extend([''] * (max_items - len(desventajas)))

                ventajas_desventajas_data = {
                    'Ventajas': ventajas,
                    'Desventajas': desventajas
                }
            else:
                # No hay ventajas/desventajas reales
                ventajas_desventajas_data = {
                    'Nota': ['Ventajas y desventajas requieren análisis del documento oficial del fondo']
                }

            # Hoja 5: Descripción Generada por IA
            descripcion_data = {
                'Sección': ['Descripción Completa del Fondo'],
                'Contenido': [data.get('descripcion_amigable', 'Descripción no disponible')]
            }

            # Hoja 6: Metadatos de Extracción (NUEVO)
            # Esta hoja documenta la procedencia de los datos y confiabilidad de la extracción

            # Build CMF URL if RUT available
            cmf_url = 'No disponible'
            if data.get('rut_base'):
                rut_base = data['rut_base']
                cmf_url = f"https://www.cmfchile.cl/institucional/mercados/entidad.php?mercado=V&rut={rut_base}&grupo=&tipoentidad=RGFMU&row=&vig=VI&control=svs&pestania=1&tpl=alt"

            # Calculate data quality score
            quality = self._calculate_data_quality_score(data)

            metadata_data = {
                'Campo': [
                    'Timestamp Extracción',
                    'Método Extracción PDF',
                    'Confianza Extracción',
                    'Calidad de Datos (0-100)',
                    'Nivel de Calidad',
                    'Campos Críticos (%)',
                    'Campos Importantes (%)',
                    'PDF Procesado',
                    'Fuente CMF',
                    'Fuente Fintual',
                    'URL CMF Fondo',
                    'Campos Extraídos PDF',
                    'Total Páginas PDF',
                    'Caracteres Extraídos',
                    'Composición Detectada',
                    'RUN Validado',
                    'Estado Fondo',
                    'Fuentes de Datos',
                    'Advertencias'
                ],
                'Valor': [
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    data.get('extraction_method', 'pdfplumber'),
                    data.get('extraction_confidence', 'unknown'),
                    quality['score'],
                    quality['level'],
                    quality['critical_pct'],
                    quality['important_pct'],
                    'Sí' if data.get('pdf_procesado') else 'No',
                    'Sí' if data.get('fuente_cmf') else 'No',
                    'Sí' if data.get('fintual_match') else 'No',
                    cmf_url,
                    f"{len([k for k, v in data.items() if v and k not in ['texto_completo', 'composicion_portafolio', 'composicion_detallada']])}",
                    data.get('total_paginas_pdf', 'N/A'),
                    len(data.get('texto_completo', '')) if data.get('texto_completo') else 0,
                    f"{len(data.get('composicion_portafolio', []))} activos",
                    'Sí' if data.get('run') and data.get('rut_base') else 'No',
                    data.get('estado_fondo', 'Desconocido'),
                    ', '.join([f"{k}: {v}" for k, v in data.get('data_sources', {}).items()]) if data.get('data_sources') else 'No rastreado',
                    self._generate_confidence_warnings(data)
                ],
                'Descripción': [
                    'Fecha y hora de la extracción de datos',
                    'Método usado para extraer texto del PDF (pdfplumber u OCR)',
                    'Nivel de confianza en los datos extraídos (high/medium/low)',
                    'Score cuantitativo de calidad (0-100) basado en completitud',
                    'Nivel cualitativo: Excelente/Buena/Regular/Baja',
                    'Porcentaje de campos críticos extraídos (nombre, RUN, tipo, riesgo)',
                    'Porcentaje de campos importantes extraídos (horizonte, tolerancia, etc)',
                    'Si se procesó correctamente el PDF del folleto informativo',
                    'Si se obtuvieron datos del sitio CMF Chile',
                    'Si el fondo existe en la API de Fintual',
                    'URL directa a la ficha del fondo en CMF (clickeable)',
                    'Cantidad de campos con datos válidos extraídos del PDF',
                    'Número total de páginas del PDF procesado',
                    'Cantidad de caracteres extraídos del PDF (indicador de calidad)',
                    'Número de activos detectados en la composición del portafolio',
                    'Si se validó el RUN del fondo contra múltiples fuentes',
                    'Estado operacional del fondo (Vigente/Liquidado/Fusionado)',
                    'Origen de cada campo extraído (trazabilidad completa)',
                    'Indicaciones sobre la calidad de los datos'
                ]
            }

            # Crear archivo Excel con todas las hojas
            fondo_nombre = data.get('nombre', 'fondo_desconocido').replace(' ', '_').replace('/', '_')
            output_path = f'outputs/analisis_completo_fondo_{fondo_nombre}.xlsx'
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                # Escribir todas las hojas
                pd.DataFrame(resumen_data).to_excel(writer, sheet_name='Resumen Ejecutivo', index=False)
                pd.DataFrame(composicion_data).to_excel(writer, sheet_name='Composición Portafolio', index=False)
                pd.DataFrame(riesgo_rentabilidad_data).to_excel(writer, sheet_name='Riesgo y Rentabilidad', index=False)
                pd.DataFrame(ventajas_desventajas_data).to_excel(writer, sheet_name='Ventajas y Desventajas', index=False)
                pd.DataFrame(descripcion_data).to_excel(writer, sheet_name='Descripción IA', index=False)
                pd.DataFrame(metadata_data).to_excel(writer, sheet_name='Metadatos Extracción', index=False)

                # Add error sheet if extraction had errors
                if data.get('error'):
                    error_data = {
                        'Tipo de Error': [],
                        'Descripción': [],
                        'Recomendación': []
                    }

                    error_str = data['error']

                    # Parse error string and provide recommendations
                    if 'Fintual' in error_str:
                        error_data['Tipo de Error'].append('API Fintual')
                        error_data['Descripción'].append('Fondo no encontrado en Fintual')
                        error_data['Recomendación'].append('Datos RUN/RUT pueden estar incompletos. Verificar en CMF.')

                    if 'CMF' in error_str:
                        error_data['Tipo de Error'].append('CMF Scraping')
                        error_data['Descripción'].append('Fondo no encontrado en sitio CMF')
                        error_data['Recomendación'].append('Verificar que el nombre del fondo sea correcto.')

                    if 'PDF' in error_str or data.get('extraction_confidence') == 'low':
                        error_data['Tipo de Error'].append('Extracción PDF')
                        error_data['Descripción'].append('Datos extraídos con baja confianza')
                        error_data['Recomendación'].append('Revisar folleto informativo manualmente.')

                    if error_data['Tipo de Error']:
                        df_errores = pd.DataFrame(error_data)
                        df_errores.to_excel(writer, sheet_name='Errores y Advertencias', index=False)

                        # Format error sheet
                        worksheet_err = writer.sheets['Errores y Advertencias']
                        worksheet_err.column_dimensions['A'].width = 20
                        worksheet_err.column_dimensions['B'].width = 50
                        worksheet_err.column_dimensions['C'].width = 50

                # Ajustar formato
                for sheet_name in writer.sheets:
                    worksheet = writer.sheets[sheet_name]
                    for column in worksheet.columns:
                        max_length = 0
                        column_letter = column[0].column_letter
                        for cell in column:
                            try:
                                cell_length = len(str(cell.value))
                                if cell_length > max_length:
                                    max_length = cell_length
                            except Exception as e:
                                logger.debug(f"[EXCEL] Error calculando largo de celda: {e}")
                                pass
                        # Set reasonable defaults if calculation fails
                        if max_length == 0:
                            if sheet_name == 'Resumen Ejecutivo':
                                worksheet.column_dimensions[column_letter].width = 30  # Field names
                            else:
                                worksheet.column_dimensions[column_letter].width = 20  # Default
                        else:
                            adjusted_width = min(max_length + 2, 100)
                            worksheet.column_dimensions[column_letter].width = adjusted_width

            logger.info(f"✓ Archivo Excel generado: {output_path}")

            # ETL FIX: Validar que el archivo Excel fue creado correctamente
            if not os.path.exists(output_path):
                raise RuntimeError(f"Archivo Excel no fue creado: {output_path}")

            file_size = os.path.getsize(output_path)
            if file_size == 0:
                raise RuntimeError(f"Archivo Excel está vacío (0 bytes): {output_path}")

            logger.info(f"✓ Validación exitosa: Archivo Excel existe y tiene {file_size} bytes")

        except Exception as e:
            logger.error(f"❌ ERROR CRÍTICO generando Excel: {e}")
            # NO USAR FALLBACK - Propagar error para que sea visible
            raise RuntimeError(f"Fallo en generación de Excel: {e}") from e

    def _classify_investment_type(self, activo: str) -> str:
        """Clasificar tipo de inversión basado en el nombre del activo"""
        activo_lower = activo.lower()
        if any(word in activo_lower for word in ['bono', 'bond', 'treasury', 'btc']):
            return 'Renta Fija'
        elif any(word in activo_lower for word in ['accion', 'equity', 'stock']):
            return 'Renta Variable'
        elif any(word in activo_lower for word in ['deposito', 'plazo', 'deposit']):
            return 'Depósito'
        elif any(word in activo_lower for word in ['cuota', 'fondo', 'fund']):
            return 'Fondo de Inversión'
        else:
            return 'Otros Instrumentos'

    def _generate_simple_excel(self, data: Dict) -> None:
        """Método de respaldo para generar Excel simple"""
        try:
            simple_data = {
                'Nombre': [data.get('nombre', '')],
                'Tipo': [data.get('tipo_fondo', '')],
                'Riesgo': [data.get('perfil_riesgo', '')],
                'Rentabilidad': [data.get('rentabilidad_anual', 'N/A')]
            }

            fondo_nombre = data.get('nombre', 'fondo_desconocido').replace(' ', '_')
            output_path = f'outputs/fondo_simple_{fondo_nombre}.xlsx'
            pd.DataFrame(simple_data).to_excel(output_path, index=False)
            logger.info(f"Archivo Excel simple generado: {output_path}")

        except Exception as e:
            logger.error(f"Error generando Excel simple: {e}")

    def procesar_fondos_mutuos(self, fondo_id: str) -> Dict:
        """
        Función principal para procesar fondos mutuos CON SCRAPING REAL

        Args:
            fondo_id (str): Identificador del fondo o nombre parcial

        Returns:
            Dict: Datos procesados del fondo
        """
        logger.info(f" INICIANDO PROCESAMIENTO CON SCRAPING REAL para: {fondo_id}")

        # FIX: Initialize with None (null in JSON) for missing data, not empty strings
        # ETL Compliance: Return null for absent fields, not ""
        resultado = {
            'fondo_id': fondo_id,
            'nombre': None,  # Changed from '' to None
            'nombre_cmf': None,  # Changed from '' to None
            'run': None,
            'rut_base': None,
            'tipo_fondo': None,  # Changed from '' to None
            'perfil_riesgo': None,  # Changed from '' to None
            'descripcion_amigable': None,  # Changed from '' to None
            'composicion_portafolio': [],  # Empty array is correct for lists
            'rentabilidad_anual': None,
            'fuente_cmf': False,
            'scraping_success': False,
            'error': None,
            'data_sources': {}  # Track where each field came from
        }

        try:
            # Fase 1: Obtener datos de Fintual (3 CAPAS)
            logger.info("═" * 60)
            logger.info(" Fase 1: Obteniendo datos de Fintual (3 CAPAS)...")
            logger.info("═" * 60)

            fintual_data = self._get_fintual_data(fondo_id)

            if fintual_data:
                resultado.update(fintual_data)

                # Track sources from Fintual
                for key in fintual_data.keys():
                    if key not in ['series', 'data_sources']:  # Skip metadata fields
                        resultado['data_sources'][key] = 'Fintual API'

                # FIX: Extract fecha_valor_cuota from first series if available
                series = fintual_data.get('series', [])
                if series and len(series) > 0:
                    primera_serie = series[0]
                    if primera_serie.get('fecha_valor_cuota'):
                        resultado['fecha_valor_cuota'] = primera_serie['fecha_valor_cuota']
                        resultado['data_sources']['fecha_valor_cuota'] = 'Fintual API'
                        logger.info(f" Fecha valor cuota desde Fintual: {resultado['fecha_valor_cuota']}")

                logger.info(f" Datos de Fintual obtenidos para: {fintual_data.get('nombre', fondo_id)}")
                logger.info(f" RUN: {fintual_data.get('run')}, RUT base: {fintual_data.get('rut_base')}")
                logger.info(f" Series encontradas: {len(fintual_data.get('series', []))}")
            else:
                # Si no hay datos de Fintual, marcar error pero intentar extraer RUN de CMF
                resultado['nombre'] = fondo_id.replace('_', ' ').title()
                resultado['rentabilidad_anual'] = None  # NO SIMULAR DATOS
                resultado['error'] = 'No se obtuvieron datos de Fintual'
                logger.error(" No se obtuvieron datos de Fintual - No hay datos reales disponibles")

                # Intentar extraer RUN del nombre del fondo si tiene formato estándar
                # Ejemplo: "Fondo Mutuo Banchile 10446-9" -> extraer "10446-9"
                import re
                run_match = re.search(r'\b(\d{4,6}-[\dkK])\b', fondo_id)
                if run_match:
                    resultado['run'] = run_match.group(1)
                    resultado['rut_base'] = resultado['run'].split('-')[0]
                    resultado['data_sources']['run'] = 'Nombre del fondo'
                    resultado['data_sources']['rut_base'] = 'Nombre del fondo'
                    logger.info(f"[RUN] Extraído del nombre: {resultado['run']}")

            # Fase 2: SCRAPING REAL de CMF USANDO EL RUT
            logger.info("═" * 60)
            logger.info(" Fase 2: Buscando fondo en CMF usando RUT...")
            logger.info("═" * 60)

            cmf_fund = None

            # ESTRATEGIA 1: Buscar por RUT si lo tenemos de Fintual
            if resultado.get('rut_base'):
                logger.info(f" [ESTRATEGIA 1] Buscando por RUT: {resultado['rut_base']}")
                cmf_fund = self._search_fund_in_cmf_by_rut(resultado['rut_base'])

            # ESTRATEGIA 2 (fallback): Buscar por nombre si no tenemos RUT o no se encontró
            if not cmf_fund:
                logger.info(f" [ESTRATEGIA 2 - Fallback] Buscando por nombre: {resultado['nombre'] or fondo_id}")
                cmf_fund = self._search_fund_in_cmf(resultado['nombre'] or fondo_id)

            if cmf_fund:
                # Determinar el nombre del fondo dependiendo de la fuente
                nombre_cmf = cmf_fund.get('nombre') or cmf_fund.get('fund_name', '')
                logger.info(f" Fondo encontrado en CMF: {nombre_cmf}")
                logger.info(f" RUT CMF: {cmf_fund.get('rut')}, RUT completo: {cmf_fund.get('rut_completo')}")

                resultado.update({
                    'nombre_cmf': nombre_cmf,
                    'rut_cmf': cmf_fund.get('rut'),
                    'rut_completo_cmf': cmf_fund.get('rut_completo'),
                    'url_cmf': cmf_fund.get('url_cmf'),
                    'fuente_cmf': True,
                    'scraping_success': True,
                    'cmf_fund_info': cmf_fund
                })

                # Track CMF data sources
                resultado['data_sources']['nombre_cmf'] = 'CMF Scraping'
                resultado['data_sources']['rut_cmf'] = 'CMF Scraping'
                resultado['data_sources']['url_cmf'] = 'CMF Scraping'

                # CRITICAL FIX: Extract RUN from CMF data with improved fallback chain
                # Priority 1: rut_fondo (most common in cmf_fund_info)
                # Priority 2: rut field (legacy)
                # Priority 3: onclick attribute (fallback)
                run_extracted = None
                rut_base_extracted = None

                # Priority 1: rut_fondo (most common in cmf_fund_info)
                if cmf_fund.get('rut_fondo'):
                    run_extracted = cmf_fund['rut_fondo']
                    logger.info(f"[RUN CMF] Extraído de rut_fondo: {run_extracted}")
                # Priority 2: rut field (legacy)
                elif cmf_fund.get('rut'):
                    run_extracted = cmf_fund['rut']
                    logger.info(f"[RUN CMF] Extraído de rut: {run_extracted}")
                # Priority 3: onclick attribute (fallback)
                elif cmf_fund.get('onclick'):
                    onclick_str = cmf_fund['onclick']
                    run_match = re.search(r'\b(\d{4,6}-[\dkK])\b', onclick_str)
                    if run_match:
                        run_extracted = run_match.group(1)
                        logger.info(f"[RUN CMF] Extraído de onclick: {run_extracted}")

                # If RUN was extracted, populate run and rut_base
                if run_extracted:
                    resultado['run'] = run_extracted
                    # Extract RUT base (without verificator digit)
                    if '-' in run_extracted:
                        rut_base_extracted = run_extracted.split('-')[0]
                    else:
                        rut_base_extracted = run_extracted

                    resultado['rut_base'] = rut_base_extracted
                    resultado['data_sources']['run'] = 'CMF Scraping'
                    resultado['data_sources']['rut_base'] = 'CMF Scraping'
                    logger.info(f"[RUN CMF] Final: RUN={run_extracted}, RUT_BASE={rut_base_extracted}")
                else:
                    logger.warning("[RUN CMF] No se pudo extraer RUN/RUT de los datos de CMF")

                # FIX: Clear Fintual error if CMF data is successfully obtained
                # A fund is successful if we have CMF data, even without Fintual
                if resultado.get('error') == 'No se obtuvieron datos de Fintual':
                    resultado['error'] = None
                    logger.info(" Error de Fintual eliminado - Datos CMF válidos obtenidos")

                # FIX: Scrape fund status from CMF to get fecha_valor_cuota
                # This addresses the critical missing data for 96.8% of funds
                logger.info(" Extrayendo estado y fecha_valor_cuota desde CMF...")
                rut_para_status = cmf_fund.get('rut') or resultado.get('rut_base')
                if rut_para_status:
                    status_data = self._scrape_fund_status_from_cmf(rut_para_status)

                    # FIX CRÍTICO: Guardar estado_fondo SIEMPRE, no solo si hay fecha_valor_cuota
                    # Esto permite detectar fondos cerrados (Liquidado/Fusionado) y skip PDFs
                    resultado['estado_fondo'] = status_data.get('estado_fondo', 'Desconocido')

                    if status_data.get('fecha_valor_cuota'):
                        # Only update if not already set by Fintual
                        if not resultado.get('fecha_valor_cuota'):
                            resultado['fecha_valor_cuota'] = status_data['fecha_valor_cuota']
                        if status_data.get('valor_cuota'):
                            resultado['valor_cuota_cmf'] = status_data['valor_cuota']
                        logger.info(f" Datos de estado obtenidos: fecha={status_data['fecha_valor_cuota']}, estado={status_data['estado_fondo']}")
                    else:
                        logger.info(f" Estado fondo obtenido: {resultado['estado_fondo']} (sin fecha_valor_cuota)")

                # Verificar que el RUT de Fintual coincide con el RUT de CMF
                if resultado.get('rut_base') and cmf_fund.get('rut'):
                    if resultado['rut_base'] == cmf_fund['rut']:
                        logger.info(" MATCH EXITOSO: RUT de Fintual coincide con RUT de CMF")
                    else:
                        logger.warning(f" ADVERTENCIA: RUT no coincide - Fintual: {resultado['rut_base']}, CMF: {cmf_fund['rut']}")

                # Obtener datos financieros reales (si la estructura lo soporta)
                if 'fund_code' in cmf_fund and 'administrator_id' in cmf_fund:
                    financial_data = self._get_fund_financial_data(cmf_fund)
                    if financial_data:
                        resultado.update({
                            'patrimonio': financial_data.get('patrimonio'),
                            'valor_cuota': financial_data.get('valor_cuota'),
                            'rentabilidad_mes': financial_data.get('rentabilidad_mes'),
                            'rentabilidad_anual': financial_data.get('rentabilidad_ano') or resultado.get('rentabilidad_anual')
                        })

                    # Obtener composición de cartera real
                    portfolio_data = self._get_fund_portfolio_data(cmf_fund)
                    if portfolio_data:
                        resultado.update(portfolio_data)

                # FIX: Skip PDF download if fund is closed (Liquidado/Fusionado)
                # This saves time and resources for inactive funds
                estado_fondo = resultado.get('estado_fondo', 'Desconocido')
                skip_pdf = estado_fondo in ['Liquidado', 'Fusionado']

                if skip_pdf:
                    logger.info(f" ⏭️  SKIPPING PDF download - Fondo {estado_fondo} (inactivo)")
                    pdf_path = None
                else:
                    # SIEMPRE intentar descargar PDF (independiente de si tiene fund_code o no)
                    logger.info(" Intentando descargar PDF del folleto informativo...")
                    # Extraer RUT base del campo que tenga (rut, rut_fondo, o rut_base)
                    # FIX: Null-safe extraction of RUT for PDF download
                    rut_fondo_split = cmf_fund.get('rut_fondo', '').split('-')[0] if cmf_fund.get('rut_fondo') else ''
                    rut_para_pdf = cmf_fund.get('rut') or rut_fondo_split or resultado.get('rut_base')

                    # Only attempt PDF download if we have a valid RUT
                    pdf_path = None
                    if rut_para_pdf:
                        pdf_path = self._download_pdf_from_cmf_improved(rut_para_pdf, resultado.get('run'))
                    else:
                        logger.warning(" No se encontró RUT válido para descargar PDF")

                if pdf_path:
                    # Extraer datos del PDF
                    logger.info("═" * 60)
                    logger.info(" Fase 2.5: Extrayendo datos del PDF...")
                    logger.info("═" * 60)

                    pdf_data = self._extract_data_from_pdf(pdf_path)
#### CRITICAL FIX: Transfer ALL extracted PDF fields, not just hardcoded subset
                    if pdf_data.get('pdf_procesado'):
                        # COMPREHENSIVE FIELD TRANSFER - All extracted fields from PDF
                        # This fixes the issue where extracted data was being discarded

                        # Define fields to transfer (excluding metadata and internal fields)
                        fields_to_transfer = [
                            # Required fields from extraction
                            'administradora', 'descripcion_fondo', 'tiempo_rescate', 'moneda',
                            'patrimonio_fondo', 'patrimonio_sede', 'TAC', 'TAC_industria',
                            'inversion_minima', 'rentabilidades_nominales', 'mejores_rentabilidades',
                            'peores_rentabilidades', 'rentabilidades_anualizadas',
                            # Standard fields
                            'tipo_fondo', 'perfil_riesgo', 'perfil_riesgo_escala', 'tolerancia_riesgo',
                            'perfil_inversionista_ideal', 'horizonte_inversion', 'horizonte_inversion_meses',
                            'comision_administracion', 'comision_rescate', 'fondo_rescatable',
                            'plazos_rescates', 'duracion', 'monto_minimo', 'monto_minimo_moneda',
                            'monto_minimo_valor', 'rentabilidad_12m', 'rentabilidad_24m',
                            'rentabilidad_36m', 'patrimonio', 'patrimonio_moneda',
                            'composicion_portafolio', 'composicion_detallada', 'extraction_confidence',
                            'rut', 'run', 'serie_fondo'
                        ]

                        # Transfer all available fields
                        for field in fields_to_transfer:
                            if pdf_data.get(field) is not None:
                                # Don't overwrite if already set from higher-priority source (except for PDF-authoritative fields)
                                pdf_authoritative = field in ['rut', 'run', 'serie_fondo', 'administradora',
                                                               'descripcion_fondo', 'TAC', 'TAC_industria']
                                if pdf_authoritative or not resultado.get(field):
                                    resultado[field] = pdf_data[field]
                                    resultado['data_sources'][field] = 'PDF'
                                    logger.debug(f"[PDF TRANSFER] {field}: {pdf_data[field]}")

                        # Special mapping: rentabilidad_12m to rentabilidad_anual if not set
                        if pdf_data.get('rentabilidad_12m') and not resultado.get('rentabilidad_anual'):
                            resultado['rentabilidad_anual'] = pdf_data['rentabilidad_12m']
                            resultado['data_sources']['rentabilidad_anual'] = 'PDF'
                            logger.info(f" Rentabilidad anual mapeada desde PDF: {resultado['rentabilidad_anual']:.2%}")

                        # Special mapping: composicion_detallada to composicion_portafolio if empty
                        if pdf_data.get('composicion_detallada') and not resultado.get('composicion_portafolio'):
                            resultado['composicion_portafolio'] = pdf_data['composicion_detallada']
                            resultado['data_sources']['composicion_portafolio'] = 'PDF'
                            logger.info(f" Composición mapeada desde composicion_detallada: {len(resultado['composicion_portafolio'])} activos")

                        # Special mapping: monto_minimo to inversion_minima
                        if pdf_data.get('monto_minimo') and not resultado.get('inversion_minima'):
                            resultado['inversion_minima'] = pdf_data['monto_minimo']
                            resultado['data_sources']['inversion_minima'] = 'PDF'

                        # FIX: Clear error if we have extracted meaningful data from PDF
                        if (pdf_data.get('tipo_fondo') or pdf_data.get('rentabilidad_12m') or
                            len(pdf_data.get('composicion_portafolio', [])) > 0):
                            if resultado.get('error') == 'No se obtuvieron datos de Fintual':
                                resultado['error'] = None
                                logger.info(" Error de Fintual eliminado - Datos PDF válidos obtenidos")

                        logger.info(f" Datos extraídos del PDF: Tipo={pdf_data.get('tipo_fondo')}, Riesgo={pdf_data.get('perfil_riesgo')}, Activos={len(pdf_data.get('composicion_portafolio', []))}")
                    else:
                        logger.warning(f" Error procesando PDF: {pdf_data.get('error')}")
                else:
                    logger.warning(" No se pudo descargar el PDF del folleto informativo")

                # ETL FIX: NO inferir tipo_fondo ni perfil_riesgo desde nombre
                # Mantener valores extraídos o None si no se pudo extraer
                # La inferencia desde nombre es una VIOLACIÓN ETL
                logger.info(f"[ETL] PDF no disponible. tipo_fondo y perfil_riesgo quedan como extraídos: {resultado.get('tipo_fondo', None)}, {resultado.get('perfil_riesgo', None)}")
 # NO generar portafolio simulado
            else:
                logger.error(" Fondo no encontrado en CMF - No hay datos reales disponibles")
                # Safe error concatenation - handle None case
                existing_error = resultado.get('error') or ''
                new_error = 'Fondo no encontrado en CMF'
                combined_error = f"{existing_error} | {new_error}".strip(' |') if existing_error else new_error
                resultado.update({
                    'fuente_cmf': False,
                    'tipo_fondo': None,
                    'perfil_riesgo': None,
                    'composicion_portafolio': [],
                    'error': combined_error
                })
               

            # Fase 3: Generar descripción con IA
            logger.info(" Fase 3: Generando descripción con IA...")
            descripcion = self._generate_ai_description(resultado)
            resultado['descripcion_amigable'] = descripcion

            # # Fase 4: Enriquecer con análisis adicional
            # logger.info(" Fase 4: Generando análisis de inversión...")
            # try:
            #     additional_analysis = self._generate_fund_investment_analysis(resultado)
            #     resultado.update(additional_analysis)
            # except Exception as e:
            #     logger.warning(f"Error en análisis adicional: {e}")

            # Fase 5: Generar Excel avanzado
            logger.info(" Fase 5: Generando archivo Excel avanzado...")
            self._generate_excel(resultado)

        except Exception as e:
            logger.error(f" Error procesando fondo {fondo_id}: {e}")
            resultado['error'] = str(e)

        # Mostrar estadísticas de caché al finalizar
        self._log_cache_statistics()

        return resultado

    def _generate_fund_investment_analysis(self, data: Dict) -> Dict:
        """Generar análisis de inversión completo para el fondo"""
        analysis = {
            'fecha_analisis': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'resumen_ejecutivo_fondo': '',
            'puntos_clave_fondo': [],
            'riesgos_identificados_fondo': [],
            'oportunidades_fondo': [],
            'recomendacion_final': '',
            'comparacion_alternativas': {}
        }

        try:
            fund_name = data.get('nombre', 'El fondo')
            fund_type = data.get('tipo_fondo', 'mixto')
            rentabilidad = data.get('rentabilidad_anual', 0)

            # Resumen ejecutivo - SOLO datos reales
            perfil_riesgo = data.get('perfil_riesgo', 'No especificado')
            if rentabilidad and rentabilidad > 0:
                analysis['resumen_ejecutivo_fondo'] = f"""{fund_name} es un fondo mutuo de tipo {fund_type.lower()}
con una rentabilidad anual real del {rentabilidad:.2%}.
Perfil de riesgo: {perfil_riesgo.lower()}."""
            else:
                analysis['resumen_ejecutivo_fondo'] = f"""{fund_name} es un fondo mutuo de tipo {fund_type.lower()}.
Perfil de riesgo: {perfil_riesgo.lower()}.
Rentabilidad: No disponible."""

            # Puntos clave - SOLO basados en datos REALES (sin umbrales arbitrarios)
            if rentabilidad and rentabilidad > 0:
                analysis['puntos_clave_fondo'].append(f'Rentabilidad anual real: {rentabilidad:.2%}')
            if fund_type.lower() == 'conservador':
                analysis['puntos_clave_fondo'].append('Fondo clasificado como conservador')
            if data.get('fuente_cmf'):
                analysis['puntos_clave_fondo'].append('Datos verificados con CMF Chile')

            # Identificar riesgos específicos del fondo - CALCULADOS de datos reales
            composicion = data.get('composicion_portafolio', [])
            if composicion:
                max_concentration = max([item.get('porcentaje', 0) for item in composicion])
                # Solo reportar concentración alta si > 40% (estándar de diversificación)
                if max_concentration > 0.4:
                    analysis['riesgos_identificados_fondo'].append(f'Alta concentración en un activo ({max_concentration:.1%})')

            if fund_type.lower() == 'agresivo':
                analysis['riesgos_identificados_fondo'].append('Fondo clasificado como agresivo - mayor volatilidad esperada')
            elif fund_type.lower() == 'conservador':
                analysis['riesgos_identificados_fondo'].append('Fondo conservador - menor volatilidad pero potencial de retorno limitado')

            # Oportunidades - basadas en DATOS REALES sin comparaciones arbitrarias
            if fund_type.lower() in ['balanceado', 'mixto']:
                analysis['oportunidades_fondo'].append('Fondo balanceado - diversificación entre renta fija y variable')

            if len(composicion) > 10:
                analysis['oportunidades_fondo'].append('Portafolio bien diversificado')

            # NO GENERAR recomendaciones con umbrales arbitrarios
            # Las recomendaciones de inversión requieren análisis profesional personalizado
            analysis['recomendacion_final'] = 'Recomendación requiere asesoría financiera profesional - Datos presentados solo con fines informativos'

            # NO INCLUIR comparaciones con datos hardcodeados/inventados
            # Las comparaciones requieren datos de mercado actualizados en tiempo real
            analysis['comparacion_alternativas'] = {
                'nota': 'Comparaciones requieren datos de mercado en tiempo real - consultar fuentes oficiales'
            }

        except Exception as e:
            logger.warning(f"Error generando análisis de inversión del fondo: {e}")
            analysis['resumen_ejecutivo_fondo'] = 'Análisis no disponible debido a datos insuficientes'

        return analysis

    # def _get_investment_horizon(self, fund_type: str) -> str:
    #     """Obtener horizonte de inversión recomendado"""
    #     if 'conservador' in fund_type.lower():
    #         return '6 meses a 2 años'
    #     elif 'agresivo' in fund_type.lower():
    #         return '5 años o más'
    #     else:
    #         return '2 a 5 años'

    # def _calculate_risk_score(self, data: Dict) -> int:
    #     """Calcular puntaje de riesgo (1-5)"""
    #     score = 3  # Base

    #     fund_type = data.get('tipo_fondo', '').lower()
    #     if 'conservador' in fund_type:
    #         score = 2
    #     elif 'agresivo' in fund_type:
    #         score = 5

    #     # Ajustar por concentración
    #     composicion = data.get('composicion_portafolio', [])
    #     if composicion:
    #         max_concentration = max([item.get('porcentaje', 0) for item in composicion])
    #         if max_concentration > 0.5:
    #             score += 1

    #     return min(score, 5)

    # def _calculate_return_score(self, data: Dict) -> int:
    #     """
    #     ELIMINADO: Calcular puntaje de retorno esperado con umbrales hardcodeados
    #     Los umbrales arbitrarios (12%, 8%, 5%, 3%) no son datos reales
    #     """
    #     rentabilidad = data.get('rentabilidad_anual', 0)
    #
    #     if rentabilidad > 0.12:
    #         return 5
    #     elif rentabilidad > 0.08:
    #         return 4
    #     elif rentabilidad > 0.05:
    #         return 3
    #     elif rentabilidad > 0.03:
    #         return 2
    #     else:
    #         return 1

            # # Agregar métricas finales de calidad
            # resultado['calidad_datos'] = self._assess_data_quality(resultado)

            # logger.info(f" PROCESAMIENTO COMPLETADO para: {resultado.get('nombre_cmf') or resultado.get('nombre')}")
            # logger.info(f" Calidad de datos: {resultado['calidad_datos']['score']}/10 - {resultado['calidad_datos']['descripcion']}")

    def _assess_data_quality(self, data: Dict) -> Dict:
        """Evaluar la calidad y completitud de los datos obtenidos"""
        quality_score = 0
        max_score = 10
        issues = []
        strengths = []

        # Evaluar nombre del fondo
        if data.get('nombre') and len(data.get('nombre', '')) > 5:
            quality_score += 1
            strengths.append('Nombre del fondo identificado')
        else:
            issues.append('Nombre del fondo incompleto')

        # Evaluar fuente de datos
        if data.get('fuente_cmf'):
            quality_score += 2
            strengths.append('Datos verificados con CMF')
        else:
            quality_score += 0.5
            issues.append('Datos basados en simulación')

        # Evaluar composición del portafolio
        composicion = data.get('composicion_portafolio', [])
        if len(composicion) >= 5:
            quality_score += 2
            strengths.append('Composición detallada del portafolio')
        elif len(composicion) > 0:
            quality_score += 1
            issues.append('Composición limitada del portafolio')
        else:
            issues.append('Sin datos de composición')

        # Evaluar rentabilidad
        if data.get('rentabilidad_anual') and data.get('rentabilidad_anual') > 0:
            quality_score += 1.5
            strengths.append('Rentabilidad anual disponible')
        else:
            issues.append('Sin datos de rentabilidad')

        # Evaluar descripción generada
        if data.get('descripcion_amigable') and len(data.get('descripcion_amigable', '')) > 200:
            quality_score += 1.5
            strengths.append('Descripción completa generada por IA')
        else:
            issues.append('Descripción incompleta o ausente')

        # Evaluar clasificación
        if data.get('tipo_fondo') and data.get('perfil_riesgo'):
            quality_score += 1
            strengths.append('Clasificación de riesgo definida')
        else:
            issues.append('Clasificación incompleta')

        # Evaluar scraping
        if data.get('scraping_success'):
            quality_score += 1
            strengths.append('Scraping web exitoso')
        else:
            issues.append('Scraping web fallido')

        # Determinar descripción de calidad
        if quality_score >= 8:
            descripcion = 'Excelente - Datos completos y verificados'
        elif quality_score >= 6:
            descripcion = 'Buena - Datos mayormente completos'
        elif quality_score >= 4:
            descripcion = 'Regular - Datos parciales'
        else:
            descripcion = 'Baja - Datos limitados o simulados'

        return {
            'score': round(quality_score, 1),
            'max_score': max_score,
            'descripcion': descripcion,
            'fortalezas': strengths,
            'areas_mejora': issues
        }


def procesar_fondos_mutuos(fondo_id: str) -> Dict:
    """
    Función wrapper para facilitar el uso desde otros módulos

    Args:
        fondo_id (str): ID del fondo a procesar

    Returns:
        Dict: Datos procesados CON SCRAPING REAL
    """
    processor = FondosMutuosProcessor()
    return processor.procesar_fondos_mutuos(fondo_id)


if __name__ == "__main__":
    # Ejemplo de uso para testing CON SCRAPING REAL
    print(" Probando scraping REAL de fondos mutuos...")

    # Probar con diferentes nombres de fondos
    test_funds = ["santander", "bci", "conservador"]

    for fund_name in test_funds:
        print(f"\n Procesando: {fund_name}")
        resultado = procesar_fondos_mutuos(fund_name)

        print(f" Resultado:")
        print(f"  - Nombre: {resultado.get('nombre', 'N/A')}")
        print(f"  - Nombre CMF: {resultado.get('nombre_cmf', 'N/A')}")
        print(f"  - Fuente CMF: {resultado.get('fuente_cmf', False)}")
        print(f"  - Scraping exitoso: {resultado.get('scraping_success', False)}")
        print(f"  - Tipo: {resultado.get('tipo_fondo', 'N/A')}")
        print(f"  - Composición: {len(resultado.get('composicion_portafolio', []))} activos")

        if resultado.get('error'):
            print(f"  - Error: {resultado['error']}")

        print("-" * 50)
        
        
        
        
        
        
