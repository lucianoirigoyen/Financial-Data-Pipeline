"""
Script de prueba directo del sistema de caché de PDFs
Prueba específicamente la descarga y caché de PDFs de CMF
"""

import sys
import os
import time
import logging
import json

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from fondos_mutuos import FondosMutuosProcessor

def test_pdf_cache_direct():
    """
    Test directo del sistema de caché de PDFs:
    1. Descarga un PDF específico por primera vez
    2. Intenta descargarlo nuevamente (debe usar caché)
    3. Verifica estadísticas
    """
    print("\n" + "="*80)
    print("TEST DIRECTO DE SISTEMA DE CACHÉ DE PDFs")
    print("="*80)

    # Crear processor
    processor = FondosMutuosProcessor()

    # Usar un fondo conocido con RUT específico
    # RUT de ejemplo: 8052 (Santander serie APVDIGITAL)
    rut_test = "8052"
    serie_test = "APVDIGITAL"

    print(f"\n[TEST] Probando descarga de PDF:")
    print(f"[TEST] RUT: {rut_test}")
    print(f"[TEST] Serie: {serie_test}")
    print("\n" + "-"*80)
    print("[TEST] PRIMERA DESCARGA - Debe descargar desde CMF")
    print("-"*80 + "\n")

    # Primera descarga
    start_time = time.time()
    pdf_path1 = processor._download_pdf_from_cmf_improved(rut_test)
    time1 = time.time() - start_time

    if pdf_path1:
        print(f"\n✅ PDF descargado exitosamente: {pdf_path1}")
        print(f"⏱️  Tiempo: {time1:.2f} segundos")

        # Verificar que el archivo existe
        if os.path.exists(pdf_path1):
            file_size = os.path.getsize(pdf_path1)
            print(f"📄 Tamaño del archivo: {file_size / 1024:.2f} KB")
        else:
            print("❌ Error: El archivo no existe")
    else:
        print("❌ Error: No se pudo descargar el PDF")

    print("\n" + "-"*80)
    print("[TEST] Esperando 2 segundos...")
    print("-"*80 + "\n")
    time.sleep(2)

    print("-"*80)
    print("[TEST] SEGUNDA DESCARGA - Debe usar caché")
    print("-"*80 + "\n")

    # Segunda descarga (debe usar caché)
    start_time = time.time()
    pdf_path2 = processor._download_pdf_from_cmf_improved(rut_test)
    time2 = time.time() - start_time

    if pdf_path2:
        print(f"\n✅ PDF obtenido exitosamente: {pdf_path2}")
        print(f"⏱️  Tiempo: {time2:.2f} segundos")

        if os.path.exists(pdf_path2):
            file_size = os.path.getsize(pdf_path2)
            print(f"📄 Tamaño del archivo: {file_size / 1024:.2f} KB")
    else:
        print("❌ Error: No se pudo obtener el PDF")

    # Comparación de tiempos
    print("\n" + "="*80)
    print("COMPARACIÓN DE TIEMPOS")
    print("="*80)
    print(f"Primera descarga:  {time1:.3f} segundos")
    print(f"Segunda descarga:  {time2:.3f} segundos")

    if time2 < time1 * 0.5:  # Debe ser al menos 50% más rápido
        speedup = time1 / time2
        time_saved = time1 - time2
        print(f"Velocidad ganada:  {speedup:.2f}x más rápido")
        print(f"Tiempo ahorrado:   {time_saved:.3f} segundos")
        print("\n✅ CACHÉ FUNCIONANDO CORRECTAMENTE - Mejora significativa")
    elif time2 < time1:
        print("\n⚠️  CACHÉ PARCIAL - Mejora pero no significativa")
    else:
        print("\n❌ CACHÉ NO FUNCIONÓ - Segunda descarga no fue más rápida")

    print("="*80)

    # Mostrar estadísticas de caché
    print("\n[TEST] Estadísticas de caché:")
    processor._log_cache_statistics()

    # Verificar contenido del caché
    print("\n[TEST] Verificando archivos del sistema de caché...")
    print("-"*80)

    if os.path.exists('cache/pdf_cache_index.json'):
        print("✅ Archivo de índice encontrado: cache/pdf_cache_index.json\n")

        with open('cache/pdf_cache_index.json', 'r', encoding='utf-8') as f:
            cache_index = json.load(f)

        if cache_index:
            print(f"📦 Total de PDFs en caché: {len(cache_index)}\n")

            for key, entry in cache_index.items():
                print(f"  • Clave: {key}")
                print(f"    - RUT: {entry.get('rut')}")
                print(f"    - Serie: {entry.get('serie')}")
                print(f"    - Tamaño: {entry.get('file_size', 0) / 1024:.2f} KB")
                print(f"    - Descargado: {entry.get('downloaded_at')}")
                print(f"    - Expira: {entry.get('expires_at')}")

                pdf_path = entry.get('pdf_path')
                if os.path.exists(pdf_path):
                    print(f"    - ✅ Archivo existe: {pdf_path}")
                else:
                    print(f"    - ❌ Archivo NO existe: {pdf_path}")
                print()
        else:
            print("⚠️  El índice de caché está vacío")
    else:
        print("❌ Archivo de índice NO encontrado")

    # Verificar directorio de caché
    if os.path.exists('cache/pdfs'):
        pdfs_in_cache = [f for f in os.listdir('cache/pdfs') if f.endswith('.pdf')]
        print(f"\n📁 Archivos PDF en cache/pdfs/: {len(pdfs_in_cache)}")
        for pdf_file in pdfs_in_cache:
            pdf_full_path = os.path.join('cache/pdfs', pdf_file)
            size = os.path.getsize(pdf_full_path)
            print(f"  • {pdf_file} ({size / 1024:.2f} KB)")
    else:
        print("\n❌ Directorio cache/pdfs/ NO existe")

    print("\n" + "="*80)
    print("TEST COMPLETADO")
    print("="*80 + "\n")

if __name__ == "__main__":
    try:
        test_pdf_cache_direct()
    except Exception as e:
        logger.error(f"Error en test: {e}")
        import traceback
        traceback.print_exc()
