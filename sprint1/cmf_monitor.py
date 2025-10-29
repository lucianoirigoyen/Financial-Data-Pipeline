"""
Sistema de Monitoreo de Cambios en Estructura CMF Chile
Detecta proactivamente cambios en la estructura HTML y endpoints de CMF
para prevenir fallos en el sistema de scraping.
"""

import os
import json
import logging
import time
import re
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from bs4 import BeautifulSoup
import requests
from fake_useragent import UserAgent

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class CMFMonitor:
    """Monitor de salud del sistema de scraping de CMF Chile"""

    def __init__(self):
        """Inicializar monitor de CMF"""
        self.base_url = "https://www.cmfchile.cl"
        self.test_rut = "8052"  # RUT de prueba conocido
        self.ua = UserAgent()
        self.session = requests.Session()

        # Configuración de directorios
        self.cache_dir = 'cache'
        self.temp_dir = 'temp'
        self.baseline_path = os.path.join(self.cache_dir, 'cmf_baseline.json')
        self.health_report_path = os.path.join(self.cache_dir, 'cmf_health_report.json')
        self.alerts_log_path = os.path.join(self.cache_dir, 'cmf_alerts.log')

        # Headers realistas
        self.session.headers.update({
            'User-Agent': self.ua.random,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        })

        # Inicializar directorios
        self._init_directories()

    def _init_directories(self):
        """Crear directorios necesarios si no existen"""
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)

    def _log_alert(self, level: str, message: str):
        """
        Registrar alerta en archivo de log

        Args:
            level: Nivel de alerta (INFO, WARNING, CRITICAL)
            message: Mensaje descriptivo
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        alert_line = f"{timestamp} | {level} | {message}\n"

        try:
            with open(self.alerts_log_path, 'a', encoding='utf-8') as f:
                f.write(alert_line)
            logger.info(f"[ALERT] {alert_line.strip()}")
        except Exception as e:
            logger.error(f"[ALERT] Error escribiendo alerta: {e}")

    def monitor_cmf_structure(self) -> Dict:
        """
        Monitorear estructura HTML de CMF para detectar cambios clave.
        Verifica presencia de elementos críticos para el scraping.

        Returns:
            Diccionario con estado de cada elemento verificado
        """
        logger.info("[STRUCTURE] Iniciando monitoreo de estructura CMF...")

        result = {
            'timestamp': datetime.now().isoformat(),
            'status': 'ok',
            'checks': {},
            'html_snapshot': None,
            'errors': []
        }

        try:
            # Request a página de fondos mutuos de prueba (URL real usada por el scraper)
            url = f"https://www.cmfchile.cl/institucional/mercados/entidad.php?mercado=V&rut={self.test_rut}&tipoentidad=RGFMU"

            logger.info(f"[STRUCTURE] Accediendo a: {url}")
            response = self.session.get(url, timeout=15)
            response.raise_for_status()

            html_content = response.text
            soup = BeautifulSoup(html_content, 'html.parser')

            # Guardar snapshot del HTML
            result['html_snapshot'] = hashlib.md5(html_content.encode()).hexdigest()

            # CHECK 1: Función JavaScript verFolleto()
            has_ver_folleto = 'verFolleto' in html_content
            result['checks']['javascript_function'] = {
                'status': 'ok' if has_ver_folleto else 'critical',
                'found': has_ver_folleto,
                'details': 'Función verFolleto() encontrada' if has_ver_folleto else 'Función verFolleto() NO encontrada'
            }

            if not has_ver_folleto:
                result['status'] = 'critical'
                result['errors'].append('Función JavaScript verFolleto() no encontrada')
                self._log_alert('CRITICAL', 'Función JavaScript verFolleto() no encontrada en HTML')

            # CHECK 2: Atributos onclick con patrón correcto
            onclick_pattern = re.compile(r'onclick\s*=\s*["\']verFolleto\([^)]+\)["\']')
            onclick_elements = soup.find_all(attrs={'onclick': onclick_pattern})

            result['checks']['onclick_attributes'] = {
                'status': 'ok' if onclick_elements else 'critical',
                'count': len(onclick_elements),
                'details': f'{len(onclick_elements)} elementos con onclick="verFolleto(...)" encontrados'
            }

            if not onclick_elements:
                result['status'] = 'critical'
                result['errors'].append('Atributos onclick con verFolleto() no encontrados')
                self._log_alert('CRITICAL', 'Atributos onclick con verFolleto() no encontrados')

            # CHECK 3: Endpoint ver_folleto_fm.php
            has_endpoint = 'ver_folleto_fm.php' in html_content
            result['checks']['endpoint_reference'] = {
                'status': 'ok' if has_endpoint else 'critical',
                'found': has_endpoint,
                'details': 'Referencia a ver_folleto_fm.php encontrada' if has_endpoint else 'Referencia a ver_folleto_fm.php NO encontrada'
            }

            if not has_endpoint:
                result['status'] = 'critical'
                result['errors'].append('Endpoint ver_folleto_fm.php no referenciado')
                self._log_alert('CRITICAL', 'Endpoint ver_folleto_fm.php no encontrado en HTML')

            # CHECK 4: Parámetros esperados (runFondo, serie, rutAdmin)
            has_run_fondo = 'runFondo' in html_content or 'run_fondo' in html_content.lower()
            has_serie = 'serie' in html_content
            has_rut_admin = 'rutAdmin' in html_content or 'rut_admin' in html_content.lower()

            params_found = sum([has_run_fondo, has_serie, has_rut_admin])
            params_status = 'ok' if params_found >= 2 else 'warning' if params_found >= 1 else 'critical'

            result['checks']['expected_parameters'] = {
                'status': params_status,
                'runFondo': has_run_fondo,
                'serie': has_serie,
                'rutAdmin': has_rut_admin,
                'details': f'{params_found}/3 parámetros esperados encontrados'
            }

            if params_found < 2:
                result['status'] = 'warning' if result['status'] == 'ok' else result['status']
                result['errors'].append(f'Solo {params_found}/3 parámetros esperados encontrados')
                self._log_alert('WARNING', f'Parámetros incompletos: {params_found}/3 encontrados')

            # CHECK 5: Estructura de tabla de series
            series_table = soup.find('table', {'class': 'tabla'}) or soup.find('table')
            result['checks']['series_table'] = {
                'status': 'ok' if series_table else 'warning',
                'found': series_table is not None,
                'details': 'Tabla de series encontrada' if series_table else 'Tabla de series NO encontrada'
            }

            logger.info(f"[STRUCTURE] Monitoreo completado: {result['status']}")

        except requests.RequestException as e:
            result['status'] = 'critical'
            result['errors'].append(f'Error de conexión: {str(e)}')
            logger.error(f"[STRUCTURE] Error de conexión: {e}")
            self._log_alert('CRITICAL', f'Error de conexión al monitorear estructura: {e}')
        except Exception as e:
            result['status'] = 'critical'
            result['errors'].append(f'Error inesperado: {str(e)}')
            logger.error(f"[STRUCTURE] Error inesperado: {e}")
            self._log_alert('CRITICAL', f'Error inesperado al monitorear estructura: {e}')

        return result

    def check_endpoint_availability(self) -> Dict:
        """
        Verificar disponibilidad y funcionamiento del endpoint ver_folleto_fm.php.
        Prueba POST con datos conocidos y valida la respuesta.

        Returns:
            Diccionario con estado del endpoint y métricas
        """
        logger.info("[ENDPOINT] Verificando disponibilidad de endpoint...")

        result = {
            'timestamp': datetime.now().isoformat(),
            'status': 'ok',
            'endpoint_url': None,
            'response_time_ms': None,
            'response_format': None,
            'errors': []
        }

        try:
            endpoint_url = f"{self.base_url}/603/pages/ver_folleto_fm.php"
            result['endpoint_url'] = endpoint_url

            # Datos de prueba conocidos
            test_data = {
                'pestania': '68',
                'run_fondo': '76.113.534-5',
                'serie': 'A',
                'rut_admin': '8052'
            }

            logger.info(f"[ENDPOINT] POST a {endpoint_url} con datos: {test_data}")

            # Medir tiempo de respuesta
            start_time = time.time()
            response = self.session.post(
                endpoint_url,
                data=test_data,
                timeout=15,
                allow_redirects=False
            )
            response_time = (time.time() - start_time) * 1000  # Convertir a ms

            result['response_time_ms'] = round(response_time, 2)
            result['status_code'] = response.status_code

            # Validar respuesta
            response_text = response.text.strip()
            logger.info(f"[ENDPOINT] Respuesta (primeros 200 chars): {response_text[:200]}")

            # Verificar que NO retorna "ERROR"
            if "ERROR" in response_text.upper():
                result['status'] = 'critical'
                result['errors'].append('Endpoint retorna ERROR')
                result['response_format'] = 'error'
                self._log_alert('CRITICAL', f'Endpoint retorna ERROR: {response_text}')

            # Verificar que retorna un path válido (PDF path típico)
            elif '.pdf' in response_text.lower() or '/' in response_text:
                result['status'] = 'ok'
                result['response_format'] = 'pdf_path'
                logger.info(f"[ENDPOINT] Endpoint funcionando correctamente")
            else:
                result['status'] = 'warning'
                result['errors'].append('Formato de respuesta inesperado')
                result['response_format'] = 'unknown'
                self._log_alert('WARNING', f'Formato de respuesta inesperado: {response_text}')

            # Alertar si tiempo de respuesta es muy alto
            if response_time > 5000:  # > 5 segundos
                result['status'] = 'warning' if result['status'] == 'ok' else result['status']
                result['errors'].append(f'Tiempo de respuesta alto: {response_time}ms')
                self._log_alert('WARNING', f'Tiempo de respuesta alto: {response_time}ms')

            logger.info(f"[ENDPOINT] Verificación completada: {result['status']} ({response_time:.2f}ms)")

        except requests.RequestException as e:
            result['status'] = 'critical'
            result['errors'].append(f'Error de conexión: {str(e)}')
            logger.error(f"[ENDPOINT] Error de conexión: {e}")
            self._log_alert('CRITICAL', f'Error de conexión al verificar endpoint: {e}')
        except Exception as e:
            result['status'] = 'critical'
            result['errors'].append(f'Error inesperado: {str(e)}')
            logger.error(f"[ENDPOINT] Error inesperado: {e}")
            self._log_alert('CRITICAL', f'Error inesperado al verificar endpoint: {e}')

        return result

    def validate_pdf_download(self) -> Dict:
        """
        Validar que se puede descargar un PDF de prueba correctamente.
        Verifica headers, tamaño y validez del PDF.

        Returns:
            Diccionario con estado de descarga y validación
        """
        logger.info("[PDF] Validando descarga de PDF de prueba...")

        result = {
            'timestamp': datetime.now().isoformat(),
            'status': 'ok',
            'pdf_path': None,
            'file_size_bytes': None,
            'is_valid_pdf': False,
            'errors': []
        }

        try:
            # Primero obtener path del PDF
            endpoint_url = f"{self.base_url}/603/ver_folleto_fm.php"
            test_data = {
                'pestania': '68',
                'run_fondo': '76.113.534-5',
                'serie': 'A',
                'rut_admin': '8052'
            }

            logger.info(f"[PDF] Obteniendo path del PDF...")
            response = self.session.post(endpoint_url, data=test_data, timeout=15)
            pdf_relative_path = response.text.strip()

            if "ERROR" in pdf_relative_path.upper() or not pdf_relative_path:
                result['status'] = 'critical'
                result['errors'].append('No se pudo obtener path del PDF')
                self._log_alert('CRITICAL', 'No se pudo obtener path del PDF')
                return result

            # Construir URL completa del PDF
            pdf_url = f"{self.base_url}{pdf_relative_path}"
            logger.info(f"[PDF] Descargando PDF desde: {pdf_url}")

            # Descargar PDF
            pdf_response = self.session.get(pdf_url, timeout=30)
            pdf_response.raise_for_status()

            pdf_content = pdf_response.content
            file_size = len(pdf_content)
            result['file_size_bytes'] = file_size

            # Verificar que es un PDF válido (headers b'%PDF')
            is_valid = pdf_content.startswith(b'%PDF')
            result['is_valid_pdf'] = is_valid

            if not is_valid:
                result['status'] = 'critical'
                result['errors'].append('Archivo descargado no es un PDF válido')
                self._log_alert('CRITICAL', 'Archivo descargado no es un PDF válido')

            # Verificar tamaño razonable (>100KB)
            if file_size < 100 * 1024:  # < 100KB
                result['status'] = 'warning' if result['status'] == 'ok' else result['status']
                result['errors'].append(f'Tamaño de PDF sospechosamente pequeño: {file_size} bytes')
                self._log_alert('WARNING', f'PDF pequeño: {file_size} bytes')

            # Guardar PDF de prueba
            test_pdf_path = os.path.join(self.temp_dir, 'monitor_test.pdf')
            with open(test_pdf_path, 'wb') as f:
                f.write(pdf_content)

            result['pdf_path'] = test_pdf_path
            logger.info(f"[PDF] PDF guardado en: {test_pdf_path} ({file_size} bytes)")
            logger.info(f"[PDF] Validación completada: {result['status']}")

        except requests.RequestException as e:
            result['status'] = 'critical'
            result['errors'].append(f'Error descargando PDF: {str(e)}')
            logger.error(f"[PDF] Error descargando PDF: {e}")
            self._log_alert('CRITICAL', f'Error descargando PDF: {e}')
        except Exception as e:
            result['status'] = 'critical'
            result['errors'].append(f'Error inesperado: {str(e)}')
            logger.error(f"[PDF] Error inesperado: {e}")
            self._log_alert('CRITICAL', f'Error inesperado al validar PDF: {e}')

        return result

    def compare_with_baseline(self, current_structure: Dict) -> Dict:
        """
        Comparar estructura actual con baseline guardado.
        Detecta cambios significativos en la estructura HTML.

        Args:
            current_structure: Resultado del monitoreo actual

        Returns:
            Diccionario con diferencias detectadas
        """
        logger.info("[BASELINE] Comparando con baseline...")

        result = {
            'timestamp': datetime.now().isoformat(),
            'status': 'ok',
            'baseline_exists': False,
            'changes_detected': [],
            'new_baseline_created': False
        }

        try:
            # Verificar si existe baseline
            if not os.path.exists(self.baseline_path):
                logger.info("[BASELINE] No existe baseline, creando nuevo...")
                with open(self.baseline_path, 'w', encoding='utf-8') as f:
                    json.dump(current_structure, f, indent=2, ensure_ascii=False)

                result['new_baseline_created'] = True
                result['baseline_exists'] = False
                logger.info(f"[BASELINE] Baseline creado en: {self.baseline_path}")
                return result

            # Cargar baseline existente
            with open(self.baseline_path, 'r', encoding='utf-8') as f:
                baseline = json.load(f)

            result['baseline_exists'] = True

            # Comparar checksums HTML
            baseline_hash = baseline.get('html_snapshot')
            current_hash = current_structure.get('html_snapshot')

            if baseline_hash != current_hash:
                result['changes_detected'].append({
                    'type': 'html_structure_change',
                    'severity': 'warning',
                    'details': 'HTML structure hash changed'
                })

            # Comparar checks individuales
            baseline_checks = baseline.get('checks', {})
            current_checks = current_structure.get('checks', {})

            for check_name, current_data in current_checks.items():
                baseline_data = baseline_checks.get(check_name, {})

                # Comparar status
                if baseline_data.get('status') != current_data.get('status'):
                    result['changes_detected'].append({
                        'type': 'check_status_change',
                        'check': check_name,
                        'severity': 'critical' if current_data.get('status') == 'critical' else 'warning',
                        'old_status': baseline_data.get('status'),
                        'new_status': current_data.get('status')
                    })

                # Comparar valores específicos
                if check_name == 'onclick_attributes':
                    old_count = baseline_data.get('count', 0)
                    new_count = current_data.get('count', 0)
                    if old_count != new_count:
                        result['changes_detected'].append({
                            'type': 'onclick_count_change',
                            'severity': 'warning',
                            'old_count': old_count,
                            'new_count': new_count
                        })

            # Determinar status general
            if result['changes_detected']:
                severities = [change['severity'] for change in result['changes_detected']]
                if 'critical' in severities:
                    result['status'] = 'critical'
                    self._log_alert('CRITICAL', f'{len(result["changes_detected"])} cambios críticos detectados')
                else:
                    result['status'] = 'warning'
                    self._log_alert('WARNING', f'{len(result["changes_detected"])} cambios detectados')

            logger.info(f"[BASELINE] Comparación completada: {len(result['changes_detected'])} cambios detectados")

        except Exception as e:
            result['status'] = 'error'
            result['errors'] = [f'Error comparando con baseline: {str(e)}']
            logger.error(f"[BASELINE] Error: {e}")
            self._log_alert('CRITICAL', f'Error comparando con baseline: {e}')

        return result

    def generate_health_report(self) -> Dict:
        """
        Generar reporte consolidado de salud del sistema CMF.
        Ejecuta todos los checks y consolida resultados.

        Returns:
            Reporte completo de salud
        """
        logger.info("[HEALTH] Generando reporte de salud completo...")

        # Ejecutar todos los checks
        structure_result = self.monitor_cmf_structure()
        endpoint_result = self.check_endpoint_availability()
        pdf_result = self.validate_pdf_download()
        baseline_result = self.compare_with_baseline(structure_result)

        # Consolidar resultados
        all_statuses = [
            structure_result.get('status', 'unknown'),
            endpoint_result.get('status', 'unknown'),
            pdf_result.get('status', 'unknown'),
            baseline_result.get('status', 'unknown')
        ]

        # Determinar status general (el peor de todos)
        if 'critical' in all_statuses:
            overall_status = 'critical'
        elif 'warning' in all_statuses:
            overall_status = 'warning'
        elif 'error' in all_statuses:
            overall_status = 'error'
        else:
            overall_status = 'healthy'

        # Generar recomendaciones
        recommendations = []

        if overall_status == 'critical':
            recommendations.append('ACCIÓN INMEDIATA REQUERIDA: Sistema de scraping puede no funcionar')
            recommendations.append('Verificar manualmente la página de CMF')
            recommendations.append('Contactar al equipo de desarrollo')
        elif overall_status == 'warning':
            recommendations.append('Monitorear de cerca: Se detectaron cambios menores')
            recommendations.append('Revisar logs de alertas para más detalles')
        else:
            recommendations.append('Sistema funcionando correctamente')
            recommendations.append('Continuar con monitoreo regular')

        # Construir reporte
        report = {
            'timestamp': datetime.now().isoformat(),
            'status': overall_status,
            'checks': {
                'javascript_function': structure_result.get('checks', {}).get('javascript_function', {}),
                'endpoint_available': {
                    'status': endpoint_result.get('status', 'unknown'),
                    'response_time_ms': endpoint_result.get('response_time_ms'),
                    'details': f"Endpoint disponible, tiempo: {endpoint_result.get('response_time_ms', 0)}ms"
                },
                'pdf_download': {
                    'status': pdf_result.get('status', 'unknown'),
                    'file_size': pdf_result.get('file_size_bytes'),
                    'is_valid': pdf_result.get('is_valid_pdf', False),
                    'details': f"PDF válido, tamaño: {pdf_result.get('file_size_bytes', 0)} bytes"
                },
                'structure_changes': {
                    'status': baseline_result.get('status', 'unknown'),
                    'changes': baseline_result.get('changes_detected', []),
                    'details': f"{len(baseline_result.get('changes_detected', []))} cambios detectados"
                }
            },
            'recommendations': recommendations,
            'detailed_results': {
                'structure': structure_result,
                'endpoint': endpoint_result,
                'pdf': pdf_result,
                'baseline': baseline_result
            }
        }

        # Guardar reporte
        try:
            with open(self.health_report_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            logger.info(f"[HEALTH] Reporte guardado en: {self.health_report_path}")
        except Exception as e:
            logger.error(f"[HEALTH] Error guardando reporte: {e}")

        logger.info(f"[HEALTH] Reporte generado: Status={overall_status}")

        return report


def run_full_monitor() -> Dict:
    """
    Ejecutar monitor completo de CMF.

    Returns:
        Reporte de salud completo
    """
    monitor = CMFMonitor()
    report = monitor.generate_health_report()
    return report


if __name__ == "__main__":
    """Ejecutar monitor si se corre como script principal"""
    print("=" * 70)
    print("CMF CHILE - SISTEMA DE MONITOREO")
    print("=" * 70)
    print()

    report = run_full_monitor()

    # Mostrar resumen
    print(f"\nSTATUS GENERAL: {report['status'].upper()}")
    print(f"Timestamp: {report['timestamp']}")
    print("\nRECOMENDACIONES:")
    for rec in report['recommendations']:
        print(f"  - {rec}")

    print(f"\nReporte completo guardado en: cache/cmf_health_report.json")
    print("=" * 70)
