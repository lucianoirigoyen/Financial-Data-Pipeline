"""
Test script to validate the pipeline fixes
Tests the 4 critical fixes:
1. Data mapping (rentabilidad_12m -> rentabilidad_anual, composicion_detallada -> composicion_portafolio)
2. Success classification logic (clear error if CMF data exists)
3. NoneType concatenation bugs (null-safe string handling)
4. CMF fund status scraper (extract fecha_valor_cuota from CMF)
"""

import os
import json
import sys
import time
import logging
from typing import Dict, List
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('test_fixes.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def test_pipeline_fixes():
    """Test the pipeline with a small sample of funds"""
    from fondos_mutuos import FondosMutuosProcessor
    from main import InBeePipeline

    logger.info("="*80)
    logger.info("INICIANDO TEST DE CORRECCIONES DE PIPELINE")
    logger.info("="*80)

    # Crear directorio de outputs si no existe
    os.makedirs('outputs/test_fixes', exist_ok=True)

    # Inicializar processor
    processor = FondosMutuosProcessor()

    # Lista de fondos para probar (muestra pequeña)
    # Incluimos fondos que sabemos tienen diferentes fuentes de datos
    fondos_test = [
        'BOOSTER CHINA STOCKS',
        'BONOS UF PLUS II',
        'DEUDA PESOS 1-5 AÑOS',
        'FONDO MUTUO CONSERVADOR',
        'FONDO MUTUO AGRESIVO'
    ]

    resultados = {
        'exitosos': [],
        'fallidos': [],
        'resumen': {
            'total': len(fondos_test),
            'exitosos': 0,
            'fallidos': 0,
            'con_rentabilidad': 0,
            'con_composicion': 0,
            'con_fecha_valor': 0,
            'sin_error_fintual': 0
        }
    }

    for i, fondo_id in enumerate(fondos_test):
        logger.info(f"\n{'='*80}")
        logger.info(f"[{i+1}/{len(fondos_test)}] PROCESANDO: {fondo_id}")
        logger.info(f"{'='*80}")

        try:
            start_time = time.time()
            resultado = processor.procesar_fondos_mutuos(fondo_id)
            elapsed = time.time() - start_time

            # Analizar resultado
            tiene_error = resultado.get('error') is not None
            tiene_rentabilidad = resultado.get('rentabilidad_anual') is not None
            tiene_composicion = len(resultado.get('composicion_portafolio', [])) > 0
            tiene_fecha_valor = resultado.get('fecha_valor_cuota') is not None
            tiene_fuente_cmf = resultado.get('fuente_cmf', False)

            logger.info(f"\n[ANALISIS RESULTADO {i+1}]")
            logger.info(f"  Nombre: {resultado.get('nombre', 'N/A')}")
            logger.info(f"  Error: {'SI' if tiene_error else 'NO'} - {resultado.get('error', 'None')}")
            logger.info(f"  Fuente CMF: {'SI' if tiene_fuente_cmf else 'NO'}")
            logger.info(f"  Rentabilidad anual: {'SI' if tiene_rentabilidad else 'NO'} - {resultado.get('rentabilidad_anual')}")
            logger.info(f"  Composición portafolio: {'SI' if tiene_composicion else 'NO'} - {len(resultado.get('composicion_portafolio', []))} activos")
            logger.info(f"  Fecha valor cuota: {'SI' if tiene_fecha_valor else 'NO'} - {resultado.get('fecha_valor_cuota')}")
            logger.info(f"  Estado fondo: {resultado.get('estado_fondo', 'N/A')}")
            logger.info(f"  Tiempo procesamiento: {elapsed:.2f}s")

            # Clasificar resultado
            if tiene_error:
                resultados['fallidos'].append(resultado)
                resultados['resumen']['fallidos'] += 1
                logger.warning(f"[{i+1}] ⚠️  FALLIDO: {resultado.get('error')}")
            else:
                resultados['exitosos'].append(resultado)
                resultados['resumen']['exitosos'] += 1
                logger.info(f"[{i+1}] ✅ EXITOSO")

            # Contadores de métricas
            if tiene_rentabilidad:
                resultados['resumen']['con_rentabilidad'] += 1
            if tiene_composicion:
                resultados['resumen']['con_composicion'] += 1
            if tiene_fecha_valor:
                resultados['resumen']['con_fecha_valor'] += 1
            if tiene_fuente_cmf and not tiene_error:
                resultados['resumen']['sin_error_fintual'] += 1

            # Guardar resultado individual
            output_file = f'outputs/test_fixes/fondo_{i+1}_{fondo_id[:20].replace(" ", "_")}.json'
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(resultado, f, indent=2, ensure_ascii=False, default=str)

        except Exception as e:
            logger.error(f"[{i+1}] ❌ EXCEPTION: {type(e).__name__}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            resultados['fallidos'].append({
                'fondo_id': fondo_id,
                'error': str(e),
                'exception_type': type(e).__name__
            })
            resultados['resumen']['fallidos'] += 1

        # Pequeño delay entre requests
        if i < len(fondos_test) - 1:
            time.sleep(1)

    # Guardar resumen final
    with open('outputs/test_fixes/test_resumen.json', 'w', encoding='utf-8') as f:
        json.dump(resultados, f, indent=2, ensure_ascii=False, default=str)

    # Mostrar resumen en consola
    logger.info("\n" + "="*80)
    logger.info("RESUMEN DE TEST DE CORRECCIONES")
    logger.info("="*80)
    logger.info(f"Total fondos procesados: {resultados['resumen']['total']}")
    logger.info(f"Exitosos: {resultados['resumen']['exitosos']} ({resultados['resumen']['exitosos']/resultados['resumen']['total']*100:.1f}%)")
    logger.info(f"Fallidos: {resultados['resumen']['fallidos']} ({resultados['resumen']['fallidos']/resultados['resumen']['total']*100:.1f}%)")
    logger.info(f"\nMÉTRICAS DE CALIDAD:")
    logger.info(f"  Con rentabilidad_anual: {resultados['resumen']['con_rentabilidad']} ({resultados['resumen']['con_rentabilidad']/resultados['resumen']['total']*100:.1f}%)")
    logger.info(f"  Con composición_portafolio: {resultados['resumen']['con_composicion']} ({resultados['resumen']['con_composicion']/resultados['resumen']['total']*100:.1f}%)")
    logger.info(f"  Con fecha_valor_cuota: {resultados['resumen']['con_fecha_valor']} ({resultados['resumen']['con_fecha_valor']/resultados['resumen']['total']*100:.1f}%)")
    logger.info(f"  Con CMF sin error Fintual: {resultados['resumen']['sin_error_fintual']} ({resultados['resumen']['sin_error_fintual']/resultados['resumen']['total']*100:.1f}%)")

    logger.info("\n" + "="*80)
    logger.info("COMPARACIÓN CON AUDIT FINDINGS:")
    logger.info("="*80)
    logger.info(f"ANTES: Tasa de éxito: 3.2% (8/250 fondos)")
    logger.info(f"AHORA: Tasa de éxito: {resultados['resumen']['exitosos']/resultados['resumen']['total']*100:.1f}% ({resultados['resumen']['exitosos']}/{resultados['resumen']['total']} fondos)")
    logger.info(f"\nANTES: Rentabilidad anual: 0% (0/8 fondos exitosos)")
    logger.info(f"AHORA: Rentabilidad anual: {resultados['resumen']['con_rentabilidad']/max(resultados['resumen']['exitosos'],1)*100:.1f}% ({resultados['resumen']['con_rentabilidad']}/{resultados['resumen']['exitosos']} fondos exitosos)")
    logger.info(f"\nANTES: Fecha valor cuota: 8% (solo 8 fondos con Fintual)")
    logger.info(f"AHORA: Fecha valor cuota: {resultados['resumen']['con_fecha_valor']/resultados['resumen']['total']*100:.1f}% ({resultados['resumen']['con_fecha_valor']}/{resultados['resumen']['total']} fondos)")

    logger.info("\n" + "="*80)
    logger.info("TEST COMPLETADO - Ver outputs/test_fixes/ para resultados detallados")
    logger.info("="*80)

    return resultados


if __name__ == "__main__":
    test_pipeline_fixes()
