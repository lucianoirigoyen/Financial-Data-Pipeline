"""
Script de prueba para verificar el sistema de caché de PDFs
Ejecuta el mismo fondo dos veces para demostrar que la segunda usa caché
"""

import sys
import os
import time
import logging

# Configurar logging para ver los mensajes de caché
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from fondos_mutuos import FondosMutuosProcessor

def test_cache_system():
    """
    Test del sistema de caché:
    1. Primera ejecución: descarga PDF desde CMF
    2. Segunda ejecución: usa PDF del caché
    3. Muestra estadísticas
    """
    print("\n" + "="*80)
    print("TEST DE SISTEMA DE CACHÉ DE PDFs")
    print("="*80)

    # Crear processor
    processor = FondosMutuosProcessor()

    # Fondo de prueba: Santander (RUT conocido)
    fondo_test = "santander"

    print(f"\n[TEST] Procesando fondo: {fondo_test}")
    print("[TEST] PRIMERA EJECUCIÓN - Debe descargar PDF desde CMF\n")

    # Primera ejecución
    start_time = time.time()
    resultado1 = processor.procesar_fondos_mutuos(fondo_test)
    time1 = time.time() - start_time

    print(f"\n[TEST] Primera ejecución completada en {time1:.2f} segundos")
    print(f"[TEST] Fondo encontrado: {resultado1.get('nombre', 'N/A')}")
    print(f"[TEST] Fuente CMF: {resultado1.get('fuente_cmf', False)}")

    # Esperar un momento
    print("\n[TEST] Esperando 3 segundos antes de la segunda ejecución...\n")
    time.sleep(3)

    # Crear nuevo processor para limpiar estadísticas
    processor2 = FondosMutuosProcessor()

    print("[TEST] SEGUNDA EJECUCIÓN - Debe usar caché\n")

    # Segunda ejecución (debe usar caché)
    start_time = time.time()
    resultado2 = processor2.procesar_fondos_mutuos(fondo_test)
    time2 = time.time() - start_time

    print(f"\n[TEST] Segunda ejecución completada en {time2:.2f} segundos")
    print(f"[TEST] Fondo encontrado: {resultado2.get('nombre', 'N/A')}")
    print(f"[TEST] Fuente CMF: {resultado2.get('fuente_cmf', False)}")

    # Comparación de tiempos
    print("\n" + "="*80)
    print("RESULTADOS DEL TEST")
    print("="*80)
    print(f"Tiempo primera ejecución:  {time1:.2f} segundos")
    print(f"Tiempo segunda ejecución:  {time2:.2f} segundos")

    if time2 < time1:
        speedup = time1 / time2
        time_saved = time1 - time2
        print(f"Velocidad ganada:          {speedup:.2f}x más rápido")
        print(f"Tiempo ahorrado:           {time_saved:.2f} segundos")
        print("\n✅ CACHÉ FUNCIONANDO CORRECTAMENTE")
    else:
        print("\n⚠️  ADVERTENCIA: La segunda ejecución no fue más rápida")

    print("="*80)

    # Verificar archivo de índice de caché
    print("\n[TEST] Verificando archivos de caché...")

    if os.path.exists('cache/pdf_cache_index.json'):
        print("✅ Archivo de índice de caché encontrado: cache/pdf_cache_index.json")

        import json
        with open('cache/pdf_cache_index.json', 'r', encoding='utf-8') as f:
            cache_index = json.load(f)

        print(f"✅ PDFs en caché: {len(cache_index)}")

        print("\n[TEST] Contenido del índice de caché:")
        for key, entry in cache_index.items():
            print(f"  - {key}:")
            print(f"    RUT: {entry.get('rut')}")
            print(f"    Serie: {entry.get('serie')}")
            print(f"    Tamaño: {entry.get('file_size', 0) / 1024:.2f} KB")
            print(f"    Descargado: {entry.get('downloaded_at')}")
            print(f"    Expira: {entry.get('expires_at')}")

            # Verificar que el archivo existe
            pdf_path = entry.get('pdf_path')
            if os.path.exists(pdf_path):
                print(f"    ✅ Archivo PDF existe: {pdf_path}")
            else:
                print(f"    ❌ Archivo PDF NO existe: {pdf_path}")
    else:
        print("❌ Archivo de índice de caché NO encontrado")

    print("\n" + "="*80)
    print("TEST COMPLETADO")
    print("="*80 + "\n")

if __name__ == "__main__":
    try:
        test_cache_system()
    except Exception as e:
        logger.error(f"Error en test: {e}")
        import traceback
        traceback.print_exc()
