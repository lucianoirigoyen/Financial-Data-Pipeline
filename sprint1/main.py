"""
Pipeline principal para procesamiento de datos financieros inBee
Ejecuta procesamiento de Alpha Vantage y Fondos Mutuos
Sprint 1 - Automatización de datos financieros
"""

import os
import json
import sys
import time
import logging
from typing import Dict, List
from dotenv import load_dotenv

from alpha_vantage import procesar_alpha_vantage
from fondos_mutuos import procesar_fondos_mutuos

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('pipeline.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class InBeePipeline:
    """Clase principal del pipeline de procesamiento de datos financieros inBee"""

    def __init__(self):
        # Cargar variables de entorno
        load_dotenv()

        # Validar configuración
        self._validate_environment()

        # Crear directorios necesarios
        self._setup_directories()

        # Las funciones están disponibles como imports directos
        pass

    def _validate_environment(self) -> None:
        """Validar que las variables de entorno necesarias estén configuradas"""
        required_keys = ['ALPHAVANTAGE_API_KEY']
        optional_keys = ['DEEPL_API_KEY', 'OPENAI_API_KEY']

        missing_required = []
        missing_optional = []

        for key in required_keys:
            if not os.getenv(key):
                missing_required.append(key)

        for key in optional_keys:
            if not os.getenv(key):
                missing_optional.append(key)

        if missing_required:
            logger.error(f"Variables de entorno requeridas faltantes: {missing_required}")
            raise ValueError(f"Faltan variables de entorno críticas: {missing_required}")

        if missing_optional:
            logger.warning(f"Variables de entorno opcionales faltantes: {missing_optional}")
            logger.warning("Algunas funcionalidades pueden estar limitadas")

    def _setup_directories(self) -> None:
        """Crear directorios necesarios si no existen"""
        directories = ['outputs', 'logs', 'temp']

        for directory in directories:
            os.makedirs(directory, exist_ok=True)
            logger.debug(f"Directorio verificado/creado: {directory}")

    def _display_config_info(self) -> None:
        """Mostrar información de configuración del pipeline"""
        print("\n CONFIGURACIÓN DEL PIPELINE:")
        print("-" * 40)

        api_status = {
            'Alpha Vantage': '' if os.getenv('ALPHAVANTAGE_API_KEY') else '',
            'DeepL': '' if os.getenv('DEEPL_API_KEY') else ' (opcional)',
            'OpenAI': '' if os.getenv('OPENAI_API_KEY') else ' (opcional)'
        }

        for api, status in api_status.items():
            print(f"{api}: {status}")

        print(f" Directorio de trabajo: {os.getcwd()}")
        print(f" Archivo de log: pipeline.log")

    def procesar_accion(self, symbol: str) -> Dict:
        """
        Procesar una acción específica usando Alpha Vantage

        Args:
            symbol (str): Símbolo de la acción (ej: 'DIS', 'AAPL')

        Returns:
            Dict: Resultado del procesamiento
        """
        logger.info(f" Iniciando procesamiento de acción: {symbol}")

        try:
            resultado = procesar_alpha_vantage(symbol)

            if 'error' in resultado:
                logger.error(f" Error procesando {symbol}: {resultado['error']}")
                return resultado

            output_file = f'outputs/{symbol.lower()}_data.json'
            self._save_json(resultado, output_file)

            logger.info(f" Acción {symbol} procesada exitosamente con mejoras dinámicas")
            logger.info(f" Campos extraídos: {len(resultado)}")
            logger.info(f" Campos normalizados: {len([k for k in resultado.keys() if '_normalized' in k])}")
            logger.info(f" Campos traducidos: {len([k for k in resultado.keys() if '_es' in k])}")
            return resultado

        except Exception as e:
            error_msg = f"Error inesperado procesando acción {symbol}: {str(e)}"
            logger.error(error_msg)
            return {'error': error_msg, 'symbol': symbol}

    def procesar_fondo(self, fondo_id: str) -> Dict:
        """
        Procesar un fondo mutuo específico

        Args:
            fondo_id (str): Identificador del fondo

        Returns:
            Dict: Resultado del procesamiento
        """
        logger.info(f" Iniciando procesamiento de fondo: {fondo_id}")

        try:
            resultado = procesar_fondos_mutuos(fondo_id)

            if resultado.get('error'):
                logger.error(f" Error procesando fondo {fondo_id}: {resultado['error']}")
                return resultado

            output_file = f'outputs/fondo_{fondo_id.replace(" ", "_")}_data.json'
            self._save_json(resultado, output_file)

            logger.info(f" Fondo {fondo_id} procesado exitosamente con mejoras dinámicas")
            composicion = resultado.get('composicion_portafolio', [])
            logger.info(f" Composición cartera: {len(composicion)} activos procesados dinámicamente")
            return resultado

        except Exception as e:
            error_msg = f"Error inesperado procesando fondo {fondo_id}: {str(e)}"
            logger.error(error_msg)
            return {'error': error_msg, 'fondo_id': fondo_id}

    def procesar_batch_acciones(self, symbols: List[str], delay: float = 12.0) -> Dict:
        """
        Procesar múltiples acciones con delay para respetar rate limits

        Args:
            symbols (List[str]): Lista de símbolos a procesar
            delay (float): Segundos de espera entre requests (Alpha Vantage: 5 calls/min)

        Returns:
            Dict: Resultados de todos los procesamientos
        """
        logger.info(f" Iniciando procesamiento batch de {len(symbols)} acciones")

        resultados = {
            'exitosos': [],
            'fallidos': [],
            'resumen': {
                'total': len(symbols),
                'exitosos': 0,
                'fallidos': 0
            }
        }

        for i, symbol in enumerate(symbols):
            logger.info(f" Procesando acción {i+1}/{len(symbols)}: {symbol}")

            resultado = self.procesar_accion(symbol)

            if 'error' in resultado:
                resultados['fallidos'].append(resultado)
                resultados['resumen']['fallidos'] += 1
            else:
                resultados['exitosos'].append(resultado)
                resultados['resumen']['exitosos'] += 1

            if i < len(symbols) - 1:
                logger.info(f" Esperando {delay} segundos antes del siguiente request...")
                time.sleep(delay)

        self._save_json(resultados, 'outputs/batch_acciones_resumen.json')

        logger.info(f" Batch completado: {resultados['resumen']['exitosos']} exitosos, {resultados['resumen']['fallidos']} fallidos")
        return resultados

    def procesar_batch_fondos(self, fondos_ids: List[str], delay: float = 2.0) -> Dict:
        """
        Procesar múltiples fondos mutuos

        Args:
            fondos_ids (List[str]): Lista de IDs de fondos a procesar
            delay (float): Segundos de espera entre procesamientos

        Returns:
            Dict: Resultados de todos los procesamientos
        """
        logger.info(f" Iniciando procesamiento batch de {len(fondos_ids)} fondos")

        resultados = {
            'exitosos': [],
            'fallidos': [],
            'resumen': {
                'total': len(fondos_ids),
                'exitosos': 0,
                'fallidos': 0
            }
        }

        for i, fondo_id in enumerate(fondos_ids):
            logger.info(f" Procesando fondo {i+1}/{len(fondos_ids)}: {fondo_id}")

            resultado = self.procesar_fondo(fondo_id)

            if resultado.get('error'):
                resultados['fallidos'].append(resultado)
                resultados['resumen']['fallidos'] += 1
            else:
                resultados['exitosos'].append(resultado)
                resultados['resumen']['exitosos'] += 1

            if i < len(fondos_ids) - 1:
                logger.info(f" Esperando {delay} segundos...")
                time.sleep(delay)

        self._save_json(resultados, 'outputs/batch_fondos_resumen.json')

        logger.info(f" Batch completado: {resultados['resumen']['exitosos']} exitosos, {resultados['resumen']['fallidos']} fallidos")
        return resultados

    def _save_json(self, data: Dict, filename: str) -> None:
        """Guardar datos en archivo JSON con formato bonito"""
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            logger.debug(f"Archivo JSON guardado: {filename}")
        except Exception as e:
            logger.error(f"Error guardando JSON {filename}: {e}")

    def generar_reporte_resumen(self) -> Dict:
        """Generar reporte resumen de todos los archivos de output"""
        logger.info(" Generando reporte resumen...")

        output_dir = 'outputs'
        reporte = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'archivos_json': [],
            'archivos_excel': [],
            'estadisticas': {
                'total_archivos': 0,
                'acciones_procesadas': 0,
                'fondos_procesados': 0
            }
        }

        try:
            if os.path.exists(output_dir):
                for filename in os.listdir(output_dir):
                    filepath = os.path.join(output_dir, filename)

                    if filename.endswith('.json'):
                        reporte['archivos_json'].append({
                            'nombre': filename,
                            'tamaño_kb': round(os.path.getsize(filepath) / 1024, 2)
                        })

                        if 'overview' in filename or any(symbol in filename for symbol in ['dis', 'aapl', 'msft', 'googl']):
                            reporte['estadisticas']['acciones_procesadas'] += 1
                        elif 'fondo' in filename:
                            reporte['estadisticas']['fondos_procesados'] += 1

                    elif filename.endswith('.xlsx'):
                        reporte['archivos_excel'].append({
                            'nombre': filename,
                            'tamaño_kb': round(os.path.getsize(filepath) / 1024, 2)
                        })

            reporte['estadisticas']['total_archivos'] = len(reporte['archivos_json']) + len(reporte['archivos_excel'])

            self._save_json(reporte, 'outputs/reporte_resumen.json')

            logger.info(f" Reporte generado: {reporte['estadisticas']['total_archivos']} archivos procesados")
            return reporte

        except Exception as e:
            logger.error(f"Error generando reporte: {e}")
            return {'error': str(e)}


def main():
    """Función principal del pipeline"""
    logger.info(" INICIANDO PIPELINE INBEE - SPRINT 1")
    logger.info("=" * 50)

    try:
        # Inicializar pipeline
        pipeline = InBeePipeline()

        # Mostrar información de configuración
        pipeline._display_config_info()

        # Configuración de procesamiento expandida
        ejemplos_acciones = ['DIS', 'AAPL', 'MSFT', 'GOOGL', 'TSLA']  # Diversas empresas tecnológicas y entretenimiento
        ejemplos_fondos = ['santander_conservador', 'bci_balanceado', 'security_crecimiento', 'chile_ahorro_plus']

        # Usar procesamiento batch para mejor eficiencia
        print(f"\n PROCESANDO {len(ejemplos_acciones)} ACCIONES EN BATCH:")
        print("-" * 50)

        resultados_acciones = pipeline.procesar_batch_acciones(ejemplos_acciones, delay=12.0)

        print(f"\n PROCESANDO {len(ejemplos_fondos)} FONDOS EN BATCH:")
        print("-" * 50)

        resultados_fondos = pipeline.procesar_batch_fondos(ejemplos_fondos, delay=2.0)

        # Mostrar resumen de resultados
        print("\n RESUMEN DE RESULTADOS:")
        print("-" * 40)
        print(f" Acciones - Exitosas: {resultados_acciones['resumen']['exitosos']}, Fallidas: {resultados_acciones['resumen']['fallidos']}")
        print(f" Fondos - Exitosos: {resultados_fondos['resumen']['exitosos']}, Fallidos: {resultados_fondos['resumen']['fallidos']}")

        # Generar reporte final consolidado
        print("\n GENERANDO REPORTE FINAL CONSOLIDADO:")
        print("-" * 50)
        reporte = pipeline.generar_reporte_resumen()

        if 'error' not in reporte:
            print(f" Total archivos generados: {reporte['estadisticas']['total_archivos']}")
            print(f" Acciones procesadas: {reporte['estadisticas']['acciones_procesadas']}")
            print(f" Fondos procesados: {reporte['estadisticas']['fondos_procesados']}")
            print(f" Archivos JSON: {len(reporte['archivos_json'])}")
            print(f" Archivos Excel: {len(reporte['archivos_excel'])}")

            # Mostrar archivos principales generados
            print(f"\n Archivos Excel principales generados:")
            for archivo in reporte['archivos_excel']:
                if archivo['tamaño_kb'] > 5:  # Solo mostrar archivos significativos
                    print(f"  • {archivo['nombre']} ({archivo['tamaño_kb']} KB)")

        print("\n" + "=" * 60)
        print(" PIPELINE INBEE SPRINT 1 COMPLETADO EXITOSAMENTE")
        print(" Revisa la carpeta 'outputs/' para los resultados detallados")
        print(" Log completo disponible en 'pipeline.log'")
        print(" Archivos Excel listos para análisis financiero")

    except Exception as e:
        logger.error(f" Error crítico en pipeline principal: {e}")
        print(f"\n ERROR CRÍTICO: {e}")
        print(" Revisa 'pipeline.log' para más detalles")
        sys.exit(1)


if __name__ == "__main__":
    main()