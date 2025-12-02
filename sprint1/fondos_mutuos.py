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


def _wait_for_download_complete(download_dir: str, timeout: int = 60, min_size_kb: int = 10) -> Optional[str]:
    """Poll download directory until PDF download completes (no .crdownload)"""
    logger.info(f"[DOWNLOAD POLL] Waiting for download to complete (max {timeout}s)...")
    start_time = time.time()
    last_files = set()

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

    logger.error(f"[DOWNLOAD POLL] ❌ Timeout after {timeout}s")
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
            logger.info(f"[CMF] Buscando página de entidad para RUT: {rut}, pestaña: {pestania}")

            # Buscar en el listado de fondos
            listado_url = "https://www.cmfchile.cl/institucional/mercados/consulta.php?mercado=V&Estado=VI&entidad=RGFMU"

            response = self.session.get(listado_url, timeout=30)
            if response.status_code != 200:
                logger.warning(f"[CMF] No se pudo acceder al listado: {response.status_code}")
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

            response = self.session.get(page_url, headers=headers, timeout=30)
            if response.status_code != 200:
                logger.warning(f"[CMF] Error accediendo a página: {response.status_code}")
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

            # Set Chrome binary location
            chrome_binary = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
            if os.path.exists(chrome_binary):
                chrome_options.binary_location = chrome_binary

            # Directorio de descargas
            download_dir = os.path.abspath('temp')
            os.makedirs(download_dir, exist_ok=True)

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

                # Wait for JavaScript tabs to load
                logger.info(f"[SELENIUM] Waiting for JavaScript load...")
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "tabs"))
                )

                # CMF uses onclick="verFolleto(...)" for PDFs
                logger.info(f"[SELENIUM] Looking for verFolleto links...")
                pdf_links = driver.find_elements(By.XPATH, "//a[contains(@onclick, 'verFolleto')]")

                if pdf_links:
                    logger.info(f"[SELENIUM] ✓ Encontrados {len(pdf_links)} enlaces potenciales")

                    # Tomar el primer enlace
                    first_link = pdf_links[0]
                    pdf_url = first_link.get_attribute('href')

                    logger.info(f"[SELENIUM] onclick: {pdf_url[:80]}...")

                    # Click triggers AJAX POST and window.open(pdf_url)
                    logger.info(f"[SELENIUM] Executing click...")
                    driver.execute_script("arguments[0].click();", first_link)

                    # Wait for download with polling
                    pdf_path = _wait_for_download_complete(download_dir, timeout=60)

                    if pdf_path:
                        latest_file = pdf_path

                        # Renombrar con formato estándar
                        final_name = f"folleto_{rut}.pdf"
                        final_path = os.path.join(download_dir, final_name)

                        # Si ya existe, sobrescribir
                        if os.path.exists(final_path):
                            os.remove(final_path)

                        os.rename(latest_file, final_path)

                        logger.info(f"[SELENIUM] ✅ PDF downloaded: {final_path}")
                        return final_path
                    else:
                        logger.warning(f"[SELENIUM] ❌ Download failed or timeout")
                        return None
                else:
                    logger.warning(f"[SELENIUM] ❌ No se encontraron enlaces a PDFs")
                    # Guardar screenshot para debugging
                    screenshot_path = f"temp/debug_screenshot_{rut}.png"
                    driver.save_screenshot(screenshot_path)
                    logger.info(f"[SELENIUM] Screenshot guardado: {screenshot_path}")
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
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'es-CL,es;q=0.9',
                'Origin': 'https://www.cmfchile.cl',
                'Referer': f'https://www.cmfchile.cl/institucional/mercados/entidad.php?mercado=V&rut={rut}'
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

            resultado = {
                'tipo_fondo': None,
                'perfil_riesgo': None,
                'perfil_riesgo_escala': None,  # R1-R7
                'horizonte_inversion': None,
                'horizonte_inversion_meses': None,
                'comision_administracion': None,
                'comision_rescate': None,
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

                resultado['texto_completo'] = texto_completo
                texto_lower = texto_completo.lower()
                lineas = texto_completo.split('\n')

                logger.debug(f"[PDF EXTENDED] Extraídas {len(pdf.pages)} páginas, {len(texto_completo)} caracteres")

                # Contador de campos extraídos para calcular confianza
                campos_extraidos = 0
                campos_totales = 12  # Total de campos clave

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
                # PATRÓN 3: HORIZONTE DE INVERSIÓN
                # ============================================================
                for linea in lineas:
                    if 'horizonte' in linea.lower():
                        linea_lower = linea.lower()

                        # Buscar categorías
                        if 'corto plazo' in linea_lower:
                            resultado['horizonte_inversion'] = 'Corto Plazo'
                            resultado['horizonte_inversion_meses'] = 12
                            campos_extraidos += 1
                        elif 'mediano plazo' in linea_lower or 'medio plazo' in linea_lower:
                            resultado['horizonte_inversion'] = 'Mediano Plazo'
                            resultado['horizonte_inversion_meses'] = 24
                            campos_extraidos += 1
                        elif 'largo plazo' in linea_lower:
                            resultado['horizonte_inversion'] = 'Largo Plazo'
                            resultado['horizonte_inversion_meses'] = 60
                            campos_extraidos += 1

                        # Buscar meses/años específicos: "24 meses", "5 años"
                        match_meses = re.search(r'(\d+)\s*meses', linea_lower)
                        match_anos = re.search(r'(\d+)\s*años?', linea_lower)

                        if match_meses:
                            meses = int(match_meses.group(1))
                            resultado['horizonte_inversion_meses'] = meses
                            if meses < 12:
                                resultado['horizonte_inversion'] = 'Corto Plazo'
                            elif meses <= 36:
                                resultado['horizonte_inversion'] = 'Mediano Plazo'
                            else:
                                resultado['horizonte_inversion'] = 'Largo Plazo'
                        elif match_anos:
                            anos = int(match_anos.group(1))
                            resultado['horizonte_inversion_meses'] = anos * 12
                            if anos <= 1:
                                resultado['horizonte_inversion'] = 'Corto Plazo'
                            elif anos <= 3:
                                resultado['horizonte_inversion'] = 'Mediano Plazo'
                            else:
                                resultado['horizonte_inversion'] = 'Largo Plazo'

                        if resultado['horizonte_inversion']:
                            logger.info(f"[PDF EXTENDED] Horizonte: {resultado['horizonte_inversion']} ({resultado['horizonte_inversion_meses']} meses)")
                            break

                # ============================================================
                # PATRÓN 4: COMISIÓN DE ADMINISTRACIÓN
                # ============================================================
                for linea in lineas:
                    if 'remun' in linea.lower() or 'tac serie' in linea.lower():
                        # Buscar "Remun. Anual Máx. (%) 0,6500" o "TAC Serie 0,50%"
                        match_comision = re.search(r'(\d+[\.,]\d+)\s*%?', linea)
                        if match_comision:
                            try:
                                comision_str = match_comision.group(1).replace(',', '.')
                                comision_num = float(comision_str)

                                # Si es mayor a 10, probablemente está en porcentaje
                                if comision_num > 10:
                                    resultado['comision_administracion'] = comision_num / 100
                                else:
                                    resultado['comision_administracion'] = comision_num / 100

                                campos_extraidos += 1
                                logger.info(f"[PDF EXTENDED] Comisión admin: {resultado['comision_administracion']:.4f} ({comision_num}%)")
                                break
                            except ValueError:
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
                            except ValueError:
                                continue

                # ============================================================
                # PATRÓN 6: RENTABILIDAD HISTÓRICA
                # ============================================================
                for i, linea in enumerate(lineas):
                    if 'rentabilidades anualizadas' in linea.lower() or '1 año' in linea.lower():
                        # Buscar en las siguientes 10 líneas
                        for j in range(i, min(i + 10, len(lineas))):
                            linea_busqueda = lineas[j]

                            # Patrón: "1 Año 0,48%"
                            match_1ano = re.search(r'1\s+año\s+([-]?\d+[\.,]?\d*)\s*%', linea_busqueda, re.IGNORECASE)
                            if match_1ano:
                                try:
                                    rent_str = match_1ano.group(1).replace(',', '.')
                                    resultado['rentabilidad_12m'] = float(rent_str) / 100
                                    campos_extraidos += 1
                                    logger.info(f"[PDF EXTENDED] Rentabilidad 12m: {resultado['rentabilidad_12m']:.2%}")
                                except ValueError:
                                    pass

                            # Patrón: "2 Años 5,5%"
                            match_2anos = re.search(r'2\s+años?\s+([-]?\d+[\.,]?\d*)\s*%', linea_busqueda, re.IGNORECASE)
                            if match_2anos:
                                try:
                                    rent_str = match_2anos.group(1).replace(',', '.')
                                    resultado['rentabilidad_24m'] = float(rent_str) / 100
                                    campos_extraidos += 1
                                    logger.info(f"[PDF EXTENDED] Rentabilidad 24m: {resultado['rentabilidad_24m']:.2%}")
                                except ValueError:
                                    pass

                            # Patrón: "3 Años" o "5 Años"
                            match_3anos = re.search(r'[35]\s+años?\s+([-]?\d+[\.,]?\d*)\s*%', linea_busqueda, re.IGNORECASE)
                            if match_3anos:
                                try:
                                    rent_str = match_3anos.group(1).replace(',', '.')
                                    resultado['rentabilidad_36m'] = float(rent_str) / 100
                                    campos_extraidos += 1
                                    logger.info(f"[PDF EXTENDED] Rentabilidad 36m: {resultado['rentabilidad_36m']:.2%}")
                                except ValueError:
                                    pass

                # ============================================================
                # PATRÓN 7: PATRIMONIO DEL FONDO
                # ============================================================
                for linea in lineas:
                    if 'patrimonio serie' in linea.lower() or 'patrimonio total' in linea.lower():
                        # Buscar montos: "$806.202.087", "USD 1.246.638.652"
                        match_patrimonio = re.search(r'([A-Z]{3})?\s*\$?\s*([\d.,]+)', linea)
                        if match_patrimonio:
                            try:
                                moneda = match_patrimonio.group(1) or 'CLP'
                                monto_str = match_patrimonio.group(2).replace('.', '').replace(',', '')
                                monto = float(monto_str)

                                resultado['patrimonio'] = monto
                                resultado['patrimonio_moneda'] = moneda
                                campos_extraidos += 1
                                logger.info(f"[PDF EXTENDED] Patrimonio: {moneda} {monto:,.0f}")
                                break
                            except ValueError:
                                continue

                # ============================================================
                # PATRÓN 8: COMPOSICIÓN DE PORTAFOLIO (Mejorada)
                # ============================================================
                composicion = []
                composicion_detallada = []

                for i, linea in enumerate(lineas):
                    # Buscar patrón: "Pagarés 77,25%"
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

                                logger.debug(f"[PDF EXTENDED] Encontrado: {activo_nombre} = {porcentaje_decimal:.2%} (cat: {categoria})")
                        except ValueError:
                            continue

                # Ordenar por porcentaje descendente
                composicion.sort(key=lambda x: x['porcentaje'], reverse=True)
                composicion_detallada.sort(key=lambda x: x['porcentaje'], reverse=True)

                resultado['composicion_portafolio'] = composicion[:15]
                resultado['composicion_detallada'] = composicion_detallada[:20]

                if composicion:
                    campos_extraidos += 1
                    suma_porcentajes = sum(item['porcentaje'] for item in composicion)
                    logger.info(f"[PDF EXTENDED] Composición: {len(composicion)} activos (suma: {suma_porcentajes:.2%})")

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

        # Retornar formato compatible con código existente
        return {
            'tipo_fondo': resultado_extendido.get('tipo_fondo'),
            'perfil_riesgo': resultado_extendido.get('perfil_riesgo'),
            'composicion_portafolio': resultado_extendido.get('composicion_portafolio', []),
            'texto_completo': resultado_extendido.get('texto_completo', ''),
            'pdf_procesado': resultado_extendido.get('pdf_procesado', True)
        }

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

                    # Método 2 DESHABILITADO: Select/option extrae administradoras, no fondos
                    # # Método 2: Buscar en elementos select/option
                    # selects = soup.find_all('select')
                    # for select in selects:
                    #     if select.get('name') and ('fondo' in select.get('name', '').lower() or
                    #                              'admin' in select.get('name', '').lower()):
                    #         options = select.find_all('option')
                    #         for option in options:
                    #             if option.get('value') and option.text.strip():
                    #                 funds_list.append({
                    #                     'administrator_id': 'unknown',
                    #                     'fund_code': option.get('value'),
                    #                     'fund_name': option.text.strip(),
                    #                     'full_id': f"select_{option.get('value')}",
                    #                     'source': 'select_option'
                    #                 })

                    # Método 3 DESHABILITADO: Tablas no contienen fondos individuales
                    # # Método 3: Buscar en tablas
                    # tables = soup.find_all('table')
                    # for table in tables:
                    #     rows = table.find_all('tr')
                    #     for row in rows:
                    #         cells = row.find_all(['td', 'th'])
                    #         if len(cells) >= 2:
                    #             text_content = ' '.join([cell.get_text().strip() for cell in cells])
                    #             if 'fondo' in text_content.lower() and len(text_content) > 10:
                    #                 funds_list.append({
                    #                     'administrator_id': 'table_extract',
                    #                     'fund_code': 'table_row',
                    #                     'fund_name': text_content[:100],  # Limitar longitud
                    #                     'full_id': f"table_{len(funds_list)}",
                    #                     'source': 'table_data'
                    #                 })

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

    # def _generate_sample_funds_list(self) -> List[Dict]:
    #     """Generar lista de fondos de ejemplo cuando no se pueden obtener datos reales"""
    #     return [
    #         {'administrator_id': '96598160', 'fund_code': 'CONS001', 'fund_name': 'Santander Fondo Mutuo Conservador Pesos', 'full_id': 'sample_sant_cons', 'source': 'sample'},
    #         {'administrator_id': '96571220', 'fund_code': 'BAL001', 'fund_name': 'BCI Fondo Mutuo Balanceado', 'full_id': 'sample_bci_bal', 'source': 'sample'},
    #         {'administrator_id': '96574580', 'fund_code': 'AGR001', 'fund_name': 'Security Fondo Mutuo Agresivo', 'full_id': 'sample_sec_agr', 'source': 'sample'},
    #         {'administrator_id': '96515190', 'fund_code': 'CORP001', 'fund_name': 'Banchile Fondo Mutuo Corporativo', 'full_id': 'sample_ban_corp', 'source': 'sample'},
    #         {'administrator_id': '81513400', 'fund_code': 'INV001', 'fund_name': 'Principal Fondo de Inversión', 'full_id': 'sample_pri_inv', 'source': 'sample'},
    #         {'administrator_id': '96659680', 'fund_code': 'REN001', 'fund_name': 'Itau Fondo Mutuo Rentabilidad', 'full_id': 'sample_ita_ren', 'source': 'sample'},
    #         {'administrator_id': '99571760', 'fund_code': 'CAP001', 'fund_name': 'Scotiabank Capital Fondo Mutuo', 'full_id': 'sample_sco_cap', 'source': 'sample'},
    #         {'administrator_id': '76645710', 'fund_code': 'DIN001', 'fund_name': 'LarrainVial Fondo Dinámico', 'full_id': 'sample_lv_din', 'source': 'sample'}
    #     ]

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
        except:
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
            'clasificacion_riesgo_detallada': 'Medio',
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
            perfil_riesgo = data.get('perfil_riesgo', 'N/A')

            # Usar clasificación oficial del CMF si existe
            if perfil_riesgo and perfil_riesgo != 'N/A':
                metrics['clasificacion_riesgo_detallada'] = perfil_riesgo
            elif 'conservador' in tipo_fondo or 'capital garantizado' in tipo_fondo:
                metrics['clasificacion_riesgo_detallada'] = 'Bajo (inferido del nombre)'
            elif 'agresivo' in tipo_fondo or 'acciones' in tipo_fondo:
                metrics['clasificacion_riesgo_detallada'] = 'Alto (inferido del nombre)'
            else:
                metrics['clasificacion_riesgo_detallada'] = 'Medio (inferido del nombre)'

            # NO GENERAR PERFILES/HORIZONTES/VENTAJAS GENÉRICAS
            # Estos deben venir del documento oficial del fondo o IA con contexto real
            metrics['perfil_inversionista_ideal'] = 'N/A - Requiere documento oficial del fondo'
            metrics['horizonte_inversion_recomendado'] = 'N/A - Requiere documento oficial del fondo'
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
            metrics['costos_estimados'] = {
                'error': 'Costos no disponibles - requieren extracción de PDF oficial del fondo'
            }

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
                    'Tipo de Fondo',
                    'Perfil de Riesgo',
                    'Clasificación Detallada',
                    'Rentabilidad Anual',
                    'Fuente de Datos',
                    'Fecha de Análisis',
                    'Perfil Inversionista Ideal',
                    'Horizonte Recomendado'
                ],
                'Detalle': [
                    data.get('nombre', 'N/A'),
                    data.get('nombre_cmf', 'N/A'),
                    data.get('tipo_fondo', 'N/A'),
                    data.get('perfil_riesgo', 'N/A'),
                    metrics.get('clasificacion_riesgo_detallada', 'N/A'),
                    f"{data.get('rentabilidad_anual', 0):.2%}" if data.get('rentabilidad_anual') else 'N/A',
                    'CMF Chile + Scraping Web' if data.get('fuente_cmf') else 'ERROR: Datos CMF no disponibles',
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    metrics.get('perfil_inversionista_ideal', 'N/A - Requiere documento oficial'),
                    metrics.get('horizonte_inversion_recomendado', 'N/A - Requiere documento oficial')
                ]
            }

            # Hoja 2: Composición del Portafolio
            composicion = data.get('composicion_portafolio', [])
            if composicion:
                composicion_data = {
                    'Activo/Instrumento': [item.get('activo', '') for item in composicion],
                    'Porcentaje': [f"{item.get('porcentaje', 0):.2%}" for item in composicion],
                    'Porcentaje Decimal': [item.get('porcentaje', 0) for item in composicion],
                    'Tipo de Inversión': [self._classify_investment_type(item.get('activo', '')) for item in composicion]
                }
            else:
                composicion_data = {'Activo/Instrumento': ['Sin datos'], 'Porcentaje': ['N/A'], 'Porcentaje Decimal': [0], 'Tipo de Inversión': ['N/A']}

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
                            except:
                                pass
                        adjusted_width = min(max_length + 2, 100)
                        worksheet.column_dimensions[column_letter].width = adjusted_width

            logger.info(f"✓ Archivo Excel generado: {output_path}")

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

        resultado = {
            'fondo_id': fondo_id,
            'nombre': '',
            'nombre_cmf': '',
            'tipo_fondo': '',
            'perfil_riesgo': '',
            'descripcion_amigable': '',
            'composicion_portafolio': [],
            'rentabilidad_anual': None,
            'fuente_cmf': False,
            'scraping_success': False,
            'error': None
        }

        try:
            # Fase 1: Obtener datos de Fintual (3 CAPAS)
            logger.info("═" * 60)
            logger.info(" Fase 1: Obteniendo datos de Fintual (3 CAPAS)...")
            logger.info("═" * 60)

            fintual_data = self._get_fintual_data(fondo_id)

            if fintual_data:
                resultado.update(fintual_data)
                logger.info(f" Datos de Fintual obtenidos para: {fintual_data.get('nombre', fondo_id)}")
                logger.info(f" RUN: {fintual_data.get('run')}, RUT base: {fintual_data.get('rut_base')}")
                logger.info(f" Series encontradas: {len(fintual_data.get('series', []))}")
            else:
                # Si no hay datos de Fintual, marcar error
                resultado['nombre'] = fondo_id.replace('_', ' ').title()
                resultado['rentabilidad_anual'] = None  # NO SIMULAR DATOS
                resultado['error'] = 'No se obtuvieron datos de Fintual'
                logger.error(" No se obtuvieron datos de Fintual - No hay datos reales disponibles")

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

                # SIEMPRE intentar descargar PDF (independiente de si tiene fund_code o no)
                logger.info(" Intentando descargar PDF del folleto informativo...")
                # Extraer RUT base del campo que tenga (rut, rut_fondo, o rut_base)
                rut_para_pdf = cmf_fund.get('rut') or cmf_fund.get('rut_fondo', '').split('-')[0] or resultado.get('rut_base')
                pdf_path = self._download_pdf_from_cmf_improved(rut_para_pdf, resultado.get('run'))

                if pdf_path:
                    # Extraer datos del PDF
                    logger.info("═" * 60)
                    logger.info(" Fase 2.5: Extrayendo datos del PDF...")
                    logger.info("═" * 60)

                    pdf_data = self._extract_data_from_pdf(pdf_path)

                    if pdf_data.get('pdf_procesado'):
                        # Actualizar resultado con datos del PDF
                        if pdf_data.get('tipo_fondo'):
                            resultado['tipo_fondo'] = pdf_data['tipo_fondo']
                        if pdf_data.get('perfil_riesgo'):
                            resultado['perfil_riesgo'] = pdf_data['perfil_riesgo']
                        if pdf_data.get('composicion_portafolio'):
                            resultado['composicion_portafolio'] = pdf_data['composicion_portafolio']

                        logger.info(f" Datos extraídos del PDF: Tipo={pdf_data.get('tipo_fondo')}, Riesgo={pdf_data.get('perfil_riesgo')}, Activos={len(pdf_data.get('composicion_portafolio', []))}")
                    else:
                        logger.warning(f" Error procesando PDF: {pdf_data.get('error')}")
                else:
                    logger.warning(" No se pudo descargar el PDF del folleto informativo")

                # Inferir tipo de fondo basado en el nombre CMF
                fund_name_lower = nombre_cmf.lower()
                if any(word in fund_name_lower for word in ['conservador', 'garantizado', 'capital']):
                    resultado.update({'tipo_fondo': 'Conservador', 'perfil_riesgo': 'Bajo'})
                elif any(word in fund_name_lower for word in ['agresivo', 'acciones', 'growth']):
                    resultado.update({'tipo_fondo': 'Agresivo', 'perfil_riesgo': 'Alto'})
                elif any(word in fund_name_lower for word in ['balanceado', 'mixto', 'balanced']):
                    resultado.update({'tipo_fondo': 'Balanceado', 'perfil_riesgo': 'Medio'})
                else:
                    resultado.update({'tipo_fondo': 'Mixto', 'perfil_riesgo': 'Medio'})

            else:
                logger.error(" Fondo no encontrado en CMF - No hay datos reales disponibles")
                resultado.update({
                    'fuente_cmf': False,
                    'tipo_fondo': None,
                    'perfil_riesgo': None,
                    'composicion_portafolio': [],
                    'error': resultado.get('error', '') + ' | Fondo no encontrado en CMF'
                })
                # NO generar portafolio simulado

            # Fase 3: Generar descripción con IA
            logger.info(" Fase 3: Generando descripción con IA...")
            descripcion = self._generate_ai_description(resultado)
            resultado['descripcion_amigable'] = descripcion

            # Fase 4: Enriquecer con análisis adicional
            logger.info(" Fase 4: Generando análisis de inversión...")
            try:
                additional_analysis = self._generate_fund_investment_analysis(resultado)
                resultado.update(additional_analysis)
            except Exception as e:
                logger.warning(f"Error en análisis adicional: {e}")

            # Fase 5: Generar Excel avanzado
            logger.info(" Fase 5: Generando archivo Excel avanzado...")
            self._generate_excel(resultado)

        except Exception as e:
            logger.error(f" Error procesando fondo {fondo_id}: {e}")
            resultado['error'] = str(e)

        # Mostrar estadísticas de caché al finalizar
        self._log_cache_statistics()

        return resultado

    def _simulate_realistic_return(self, fondo_id: str) -> Optional[float]:
        """
        ELIMINADO: Simular rentabilidad realista basada en el tipo de fondo

        Esta función generaba rentabilidades FALSAS.
        NO SE DEBEN INVENTAR DATOS FINANCIEROS.
        """
        logger.error(f"[DATOS FALSOS BLOQUEADOS] No se puede simular rentabilidad para {fondo_id}")
        return None  # Retornar None en lugar de dato inventado

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
        
        
        
        
        
        
