#!/usr/bin/env python3
"""
Test rápido para verificar descarga de PDF con diferentes formatos de RUN
Prueba 4 variantes de formato para determinar cuál acepta CMF
"""
import sys
sys.path.append('/Users/lucianoleroi/Desktop/Fran/sprint/sprint1')

from fondos_mutuos import FondosMutuosProcessor
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def test_pdf_download():
    processor = FondosMutuosProcessor()

    # Test con diferentes formatos
    test_cases = [
        {'name': 'SIN guión ni puntos', 'rut': '8052', 'run_completo': '761135345', 'serie': 'A', 'rut_admin': '8052'},
        {'name': 'CON guión, SIN puntos', 'rut': '8052', 'run_completo': '76113534-5', 'serie': 'A', 'rut_admin': '8052'},
        {'name': 'CON puntos y guión', 'rut': '8052', 'run_completo': '76.113.534-5', 'serie': 'A', 'rut_admin': '8052'},
        {'name': 'Solo RUT', 'rut': '8052', 'run_completo': None, 'serie': 'A', 'rut_admin': '8052'},
    ]

    results = []
    for i, test in enumerate(test_cases, 1):
        logger.info(f"\n{'='*70}")
        logger.info(f"Test {i}/{len(test_cases)}: {test['name']}")
        logger.info(f"RUT={test['rut']}, RUN={test['run_completo']}, Serie={test['serie']}")
        logger.info(f"{'='*70}")

        pdf_path = processor._download_pdf_from_cmf(
            rut=test['rut'],
            run_completo=test['run_completo'],
            serie=test['serie'],
            rut_admin=test['rut_admin']
        )

        success = pdf_path is not None
        results.append({'name': test['name'], 'success': success, 'pdf': pdf_path})

        if pdf_path:
            logger.info(f"✅ EXITO: PDF descargado en {pdf_path}")
            # Verificar que es PDF válido
            try:
                with open(pdf_path, 'rb') as f:
                    header = f.read(10)
                    if header.startswith(b'%PDF'):
                        logger.info(f"✅ PDF VALIDO: Header correcto")
                    else:
                        logger.error(f"❌ PDF INVALIDO: Header = {header}")
            except Exception as e:
                logger.error(f"❌ ERROR: No se pudo leer PDF: {e}")
        else:
            logger.error(f"❌ FALLO: No se pudo descargar PDF")

    # Resumen
    logger.info(f"\n{'='*70}")
    logger.info("RESUMEN DE RESULTADOS")
    logger.info(f"{'='*70}")
    for result in results:
        status = '✅ FUNCIONA' if result['success'] else '❌ FALLO'
        logger.info(f"{status} - {result['name']}")

    successful = [r for r in results if r['success']]
    if successful:
        logger.info(f"\n🎯 FORMATO(S) QUE FUNCIONAN:")
        for r in successful:
            logger.info(f"   - {r['name']}")
    else:
        logger.info(f"\n❌ NINGÚN FORMATO FUNCIONÓ - revisar endpoint y parámetros")

if __name__ == '__main__':
    test_pdf_download()
