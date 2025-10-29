"""
Script de prueba para verificar descarga de PDFs desde CMF Chile
"""

import os
import sys
import logging
from dotenv import load_dotenv

# Configurar logging detallado
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Cargar variables de entorno
load_dotenv()

# Importar el procesador
from fondos_mutuos import FondosMutuosProcessor

def test_pdf_download():
    """Probar descarga de PDFs de fondos mutuos desde CMF"""

    print("="*80)
    print("PRUEBA DE DESCARGA DE PDFs DESDE CMF CHILE")
    print("="*80)

    processor = FondosMutuosProcessor()

    # Casos de prueba con RUTs reales de fondos mutuos chilenos
    test_cases = [
        {
            'nombre': 'Santander Private Banking Agresivo',
            'rut': '8908',
            'run_completo': '8908-6',
            'serie': 'UNICA'
        },
        {
            'nombre': 'BCI Asset Management',
            'rut': '10441',
            'run_completo': '10441-8',
            'serie': 'A'
        },
        {
            'nombre': 'LarrainVial Ahorro',
            'rut': '8315',
            'run_completo': '8315-5',
            'serie': 'UNICA'
        }
    ]

    resultados = []

    for i, test in enumerate(test_cases, 1):
        print(f"\n{'='*80}")
        print(f"PRUEBA {i}/{len(test_cases)}: {test['nombre']}")
        print(f"RUT: {test['rut']} | RUN: {test['run_completo']} | Serie: {test['serie']}")
        print("="*80)

        try:
            # Intentar descarga con método mejorado
            pdf_path = processor._download_pdf_from_cmf_improved(
                rut=test['rut'],
                run_completo=test['run_completo']
            )

            if pdf_path and os.path.exists(pdf_path):
                file_size = os.path.getsize(pdf_path)
                print(f"\n✅ ÉXITO: PDF descargado")
                print(f"   - Ubicación: {pdf_path}")
                print(f"   - Tamaño: {file_size:,} bytes ({file_size/1024:.2f} KB)")

                # Intentar extraer datos del PDF
                print(f"\n📊 Extrayendo datos del PDF...")
                datos_pdf = processor._extract_data_from_pdf(pdf_path)

                print(f"   - Tipo de fondo: {datos_pdf.get('tipo_fondo', 'No encontrado')}")
                print(f"   - Perfil de riesgo: {datos_pdf.get('perfil_riesgo', 'No encontrado')}")
                print(f"   - Composición: {len(datos_pdf.get('composicion_portafolio', []))} activos")

                if datos_pdf.get('composicion_portafolio'):
                    print(f"\n   Top 5 activos:")
                    for j, item in enumerate(datos_pdf['composicion_portafolio'][:5], 1):
                        print(f"      {j}. {item['activo']}: {item['porcentaje']:.2%}")

                resultados.append({
                    'nombre': test['nombre'],
                    'exito': True,
                    'pdf_path': pdf_path,
                    'datos_extraidos': datos_pdf
                })
            else:
                print(f"\n❌ FALLO: No se pudo descargar el PDF")
                resultados.append({
                    'nombre': test['nombre'],
                    'exito': False,
                    'error': 'No se pudo descargar'
                })

        except Exception as e:
            print(f"\n❌ ERROR: {str(e)}")
            logger.exception("Error en prueba")
            resultados.append({
                'nombre': test['nombre'],
                'exito': False,
                'error': str(e)
            })

    # Resumen final
    print("\n" + "="*80)
    print("RESUMEN DE PRUEBAS")
    print("="*80)

    exitos = sum(1 for r in resultados if r['exito'])
    fallos = len(resultados) - exitos

    print(f"\nTotal de pruebas: {len(resultados)}")
    print(f"✅ Exitosas: {exitos}")
    print(f"❌ Fallidas: {fallos}")
    print(f"📊 Tasa de éxito: {(exitos/len(resultados)*100):.1f}%")

    print("\nDetalle:")
    for r in resultados:
        status = "✅" if r['exito'] else "❌"
        print(f"  {status} {r['nombre']}")
        if not r['exito']:
            print(f"      Error: {r.get('error', 'Desconocido')}")

    return resultados

if __name__ == "__main__":
    try:
        resultados = test_pdf_download()

        # Verificar si al menos una prueba fue exitosa
        if any(r['exito'] for r in resultados):
            print("\n✅ CONCLUSIÓN: La descarga de PDFs desde CMF funciona correctamente")
            sys.exit(0)
        else:
            print("\n⚠️ CONCLUSIÓN: Ninguna descarga fue exitosa, revisar implementación")
            sys.exit(1)

    except Exception as e:
        print(f"\n❌ ERROR FATAL: {e}")
        logger.exception("Error fatal en script de prueba")
        sys.exit(1)
