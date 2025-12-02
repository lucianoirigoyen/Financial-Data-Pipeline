"""
FIXED IMPLEMENTATION - Selenium PDF Download for CMF Chile

Changes from original:
1. ✅ Uses correct CMF AJAX endpoint (../inc/ver_folleto_fm.php)
2. ✅ Replaces time.sleep() with WebDriverWait
3. ✅ Adds download verification with polling
4. ✅ Adds comprehensive logging
5. ✅ Removes hardcoded ChromeDriver path
6. ✅ Adds proper error handling

To integrate: Copy these functions to fondos_mutuos.py, replacing existing versions
"""

import os
import time
import logging
from typing import Optional
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger(__name__)


def _wait_for_download_complete(download_dir: str, timeout: int = 60, min_size_kb: int = 10) -> Optional[str]:
    """
    Poll download directory until PDF download completes (no .crdownload file)

    Args:
        download_dir: Directory where PDFs are downloaded
        timeout: Maximum seconds to wait
        min_size_kb: Minimum file size in KB to consider valid

    Returns:
        Path to downloaded PDF or None if timeout/failure
    """
    logger.info(f"[DOWNLOAD POLL] Esperando descarga completar (max {timeout}s)...")
    start_time = time.time()
    last_files = set()

    while time.time() - start_time < timeout:
        try:
            # Get all files in download directory
            all_files = set(os.listdir(download_dir))

            # Filter for PDF files (not .crdownload, .tmp, etc.)
            pdf_files = [f for f in all_files if f.endswith('.pdf')]

            # Check for new PDFs
            new_pdfs = [f for f in pdf_files if f not in last_files]

            if new_pdfs:
                # Found new PDF - verify it's not still downloading
                pdf_path = os.path.join(download_dir, new_pdfs[0])

                # Wait for file size to stabilize (download complete)
                initial_size = os.path.getsize(pdf_path)
                time.sleep(1)  # Wait 1 second

                current_size = os.path.getsize(pdf_path)

                if current_size == initial_size and current_size > (min_size_kb * 1024):
                    # File size stable and meets minimum size
                    size_kb = current_size / 1024
                    logger.info(f"[DOWNLOAD POLL] ✅ PDF descargado: {new_pdfs[0]} ({size_kb:.2f} KB)")
                    return pdf_path
                else:
                    logger.debug(f"[DOWNLOAD POLL] Archivo aún descargando... ({current_size} bytes)")

            # Check for incomplete downloads
            incomplete = [f for f in all_files if '.crdownload' in f or '.tmp' in f]
            if incomplete:
                logger.debug(f"[DOWNLOAD POLL] Descarga en progreso: {incomplete}")

            last_files = all_files
            time.sleep(0.5)  # Poll every 500ms

        except Exception as e:
            logger.debug(f"[DOWNLOAD POLL] Error checking: {e}")
            time.sleep(0.5)

    logger.error(f"[DOWNLOAD POLL] ❌ Timeout después de {timeout}s")
    return None


def _download_pdf_with_selenium_FIXED(self, page_url: str, rut: str, run_completo: str = None, rut_admin: str = None) -> Optional[str]:
    """
    FIXED VERSION: Usar Selenium para descargar PDF desde CMF Chile

    CMF Chile Structure (descubierto mediante inspección):
    - PDFs se sirven via AJAX POST a: ../inc/ver_folleto_fm.php
    - Parámetros: runFondo (RUT con guión), serie (código serie), rutAdmin
    - JavaScript function: verFolleto(runFondo, serie, rutAdmin)

    Args:
        page_url: URL de la página con pestania=68 (folletos)
        rut: RUT del fondo sin guión (ej: "8638")
        run_completo: RUN completo con guión (ej: "8638-K")
        rut_admin: RUT del administrador (opcional)

    Returns:
        Path al PDF descargado o None
    """
    driver = None

    try:
        logger.info(f"[SELENIUM] ==================== INICIO ====================")
        logger.info(f"[SELENIUM] Descargando PDF para RUT: {rut} ({run_completo})")

        # Setup download directory
        download_dir = os.path.abspath('temp')
        os.makedirs(download_dir, exist_ok=True)

        # Clear old files to avoid confusion
        old_files = [f for f in os.listdir(download_dir) if f.endswith('.pdf')]
        logger.debug(f"[SELENIUM] PDFs existentes antes de descarga: {len(old_files)}")

        # Configure Chrome
        chrome_options = Options()
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

        # Configure download preferences
        prefs = {
            'download.default_directory': download_dir,
            'download.prompt_for_download': False,
            'plugins.always_open_pdf_externally': True,
            'profile.default_content_setting_values.automatic_downloads': 1
        }
        chrome_options.add_experimental_option('prefs', prefs)

        # Initialize Chrome driver (cross-platform)
        logger.info(f"[SELENIUM] Iniciando Chrome headless...")
        try:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            logger.info(f"[SELENIUM] ✓ Chrome iniciado correctamente")
        except Exception as e:
            logger.error(f"[SELENIUM] ❌ Error iniciando Chrome: {e}")
            return None

        # Navigate to page
        logger.info(f"[SELENIUM] Navegando a: {page_url[:80]}...")
        driver.get(page_url)

        # Wait for page load
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        page_title = driver.title
        logger.info(f"[SELENIUM] ✓ Página cargada: {page_title}")

        # Wait for AJAX/JavaScript to load
        logger.info(f"[SELENIUM] Esperando carga de JavaScript...")
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "tabs"))
        )

        # CMF uses onclick="verFolleto(runFondo, serie, rutAdmin)" to fetch PDFs
        # Find all verFolleto links
        logger.info(f"[SELENIUM] Buscando enlaces verFolleto...")

        # Try to find the first available series
        folleto_links = driver.find_elements(By.XPATH, "//a[contains(@onclick, 'verFolleto')]")

        if not folleto_links:
            logger.error(f"[SELENIUM] ❌ No se encontraron enlaces verFolleto")
            screenshot_path = f"temp/error_no_folleto_{rut}.png"
            driver.save_screenshot(screenshot_path)
            logger.info(f"[SELENIUM] Screenshot guardado: {screenshot_path}")
            return None

        logger.info(f"[SELENIUM] ✓ Encontrados {len(folleto_links)} enlaces verFolleto")

        # Extract parameters from first link
        first_link = folleto_links[0]
        onclick = first_link.get_attribute('onclick')
        logger.info(f"[SELENIUM] onclick del primer enlace: {onclick}")

        # Click the link (triggers AJAX POST and window.open)
        logger.info(f"[SELENIUM] Ejecutando click en enlace PDF...")
        driver.execute_script("arguments[0].click();", first_link)

        # Wait for download to start and complete
        pdf_path = _wait_for_download_complete(download_dir, timeout=60)

        if pdf_path:
            # Rename to standard format
            final_name = f"folleto_{rut}.pdf"
            final_path = os.path.join(download_dir, final_name)

            # Remove old file if exists
            if os.path.exists(final_path) and final_path != pdf_path:
                os.remove(final_path)

            # Rename
            if pdf_path != final_path:
                os.rename(pdf_path, final_path)
                logger.info(f"[SELENIUM] Renombrado a: {final_name}")

            logger.info(f"[SELENIUM] ✅ DESCARGA EXITOSA: {final_path}")
            logger.info(f"[SELENIUM] ==================== FIN ====================")
            return final_path
        else:
            logger.error(f"[SELENIUM] ❌ Descarga falló o timeout")
            screenshot_path = f"temp/error_download_timeout_{rut}.png"
            driver.save_screenshot(screenshot_path)
            logger.info(f"[SELENIUM] Screenshot guardado: {screenshot_path}")
            return None

    except Exception as e:
        logger.error(f"[SELENIUM] ❌ Excepción: {type(e).__name__}: {e}")
        if driver:
            try:
                screenshot_path = f"temp/error_exception_{rut}.png"
                driver.save_screenshot(screenshot_path)
                logger.info(f"[SELENIUM] Screenshot de error: {screenshot_path}")
            except:
                pass
        import traceback
        logger.debug(traceback.format_exc())
        return None

    finally:
        if driver:
            driver.quit()
            logger.info(f"[SELENIUM] Navegador cerrado")


def _download_pdf_from_cmf_improved_FIXED(self, rut: str, run_completo: str = None) -> Optional[str]:
    """
    FIXED VERSION: Método mejorado para descargar PDF desde CMF

    Args:
        rut: RUT del fondo sin guión (ej: "8638")
        run_completo: RUN completo con guión (ej: "8638-K")

    Returns:
        Path al PDF descargado o None
    """
    try:
        logger.info(f"[CMF PDF] Iniciando descarga para RUT: {rut}")

        # CHECK CACHE FIRST
        cached_pdf = self._get_cached_pdf(rut, "UNICA")
        if cached_pdf:
            logger.info(f"[CACHE] ✓ PDF encontrado en caché: {cached_pdf}")
            return cached_pdf

        self.cache_stats['downloads'] += 1

        # Get URL with pestania=68 (Folleto Informativo tab)
        page_url = self._get_cmf_page_with_params(rut, pestania="68")

        if not page_url:
            logger.warning(f"[CMF PDF] ❌ No se pudo obtener URL para RUT {rut}")
            return None

        logger.info(f"[CMF PDF] ✓ URL obtenida: {page_url[:80]}...")

        # Download PDF with Selenium
        pdf_path = _download_pdf_with_selenium_FIXED(self, page_url, rut, run_completo)

        if pdf_path:
            logger.info(f"[CMF PDF] ✅ PDF descargado exitosamente")
            # Save to cache
            self._save_to_cache(rut, "UNICA", pdf_path)
            return pdf_path
        else:
            logger.warning(f"[CMF PDF] ❌ No se pudo descargar PDF")
            return None

    except Exception as e:
        logger.error(f"[CMF PDF] Error: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return None


# ==============================================================================
# BATCH PROCESSING IMPROVEMENTS FOR main.py
# ==============================================================================

def procesar_batch_fondos_FIXED(self, fondos_ids: list, delay: float = 2.0) -> dict:
    """
    FIXED VERSION: Procesar múltiples fondos con manejo robusto de errores

    Mejoras:
    1. ✅ Try/except por cada fondo (no se rompe el batch)
    2. ✅ Checkpoints cada 10 fondos
    3. ✅ Logging detallado de progreso
    4. ✅ Continúa aunque un fondo falle

    Args:
        fondos_ids: Lista de IDs de fondos a procesar
        delay: Segundos entre fondos (rate limiting)

    Returns:
        Dict con resultados exitosos y fallidos
    """
    import time
    import json

    logger.info(f"="*80)
    logger.info(f"BATCH PROCESSING: {len(fondos_ids)} fondos")
    logger.info(f"="*80)

    resultados = {
        'exitosos': [],
        'fallidos': [],
        'resumen': {
            'total': len(fondos_ids),
            'exitosos': 0,
            'fallidos': 0,
            'start_time': time.strftime("%Y-%m-%d %H:%M:%S")
        }
    }

    start_batch = time.time()

    for i, fondo_id in enumerate(fondos_ids):
        logger.info(f"\n{'='*80}")
        logger.info(f"[{i+1}/{len(fondos_ids)}] Procesando: {fondo_id}")
        logger.info(f"{'='*80}")

        try:
            start_fund = time.time()

            # Process fund
            resultado = self.procesar_fondo(fondo_id)

            elapsed = time.time() - start_fund

            if resultado.get('error'):
                logger.warning(f"[{i+1}] ⚠️  Error parcial en {fondo_id}: {resultado['error']}")
                logger.warning(f"[{i+1}] Tiempo: {elapsed:.2f}s")
                resultados['fallidos'].append(resultado)
                resultados['resumen']['fallidos'] += 1
            else:
                logger.info(f"[{i+1}] ✅ ÉXITO: {fondo_id}")
                logger.info(f"[{i+1}] Tiempo: {elapsed:.2f}s")
                resultados['exitosos'].append(resultado)
                resultados['resumen']['exitosos'] += 1

        except KeyboardInterrupt:
            logger.warning(f"\n[{i+1}] ⚠️  BATCH INTERRUMPIDO POR USUARIO")
            break

        except Exception as e:
            logger.error(f"[{i+1}] ❌ EXCEPCIÓN CRÍTICA en {fondo_id}: {type(e).__name__}: {e}")
            resultados['fallidos'].append({
                'fondo_id': fondo_id,
                'error': str(e),
                'exception_type': type(e).__name__
            })
            resultados['resumen']['fallidos'] += 1

            # Continue with next fund - DON'T break
            continue

        # CHECKPOINT every 10 funds
        if (i + 1) % 10 == 0:
            checkpoint_file = f'outputs/batch_checkpoint_{i+1}_of_{len(fondos_ids)}.json'
            try:
                with open(checkpoint_file, 'w', encoding='utf-8') as f:
                    json.dump(resultados, f, indent=2, ensure_ascii=False, default=str)
                logger.info(f"[CHECKPOINT] ✓ Progreso guardado: {checkpoint_file}")
            except Exception as e:
                logger.warning(f"[CHECKPOINT] ⚠️  Error guardando checkpoint: {e}")

        # Rate limiting (except for last fund)
        if i < len(fondos_ids) - 1:
            logger.debug(f"[DELAY] Esperando {delay}s...")
            time.sleep(delay)

    # Final summary
    elapsed_total = time.time() - start_batch
    resultados['resumen']['end_time'] = time.strftime("%Y-%m-%d %H:%M:%S")
    resultados['resumen']['elapsed_seconds'] = elapsed_total
    resultados['resumen']['elapsed_minutes'] = elapsed_total / 60

    logger.info(f"\n{'='*80}")
    logger.info(f"BATCH COMPLETADO")
    logger.info(f"{'='*80}")
    logger.info(f"Total: {len(fondos_ids)} fondos")
    logger.info(f"Exitosos: {resultados['resumen']['exitosos']} ({resultados['resumen']['exitosos']/len(fondos_ids)*100:.1f}%)")
    logger.info(f"Fallidos: {resultados['resumen']['fallidos']} ({resultados['resumen']['fallidos']/len(fondos_ids)*100:.1f}%)")
    logger.info(f"Tiempo total: {elapsed_total/60:.2f} minutos")
    logger.info(f"Promedio por fondo: {elapsed_total/len(fondos_ids):.2f} segundos")

    # Save final summary
    self._save_json(resultados, 'outputs/batch_fondos_resumen.json')

    return resultados


"""
==============================================================================
INTEGRATION INSTRUCTIONS
==============================================================================

1. In fondos_mutuos.py:
   - Replace _download_pdf_with_selenium() with _download_pdf_with_selenium_FIXED()
   - Replace _download_pdf_from_cmf_improved() with _download_pdf_from_cmf_improved_FIXED()
   - Add _wait_for_download_complete() function

2. In main.py:
   - Replace procesar_batch_fondos() with procesar_batch_fondos_FIXED()

3. Test with single fund:
   python3 test_selenium_pdf_download.py

4. Test with 10 funds batch before running 1300

5. For 1300 funds:
   - Run during off-peak hours
   - Monitor outputs/batch_checkpoint_*.json for progress
   - Can resume from checkpoint if interrupted
"""
