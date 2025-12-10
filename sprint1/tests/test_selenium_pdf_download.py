"""Test completo de descarga de PDF con Selenium y nuevo formato de URL"""

import logging
import os
from fondos_mutuos import FondosMutuosProcessor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

processor = FondosMutuosProcessor()

# Test con "BCI CARTERA DINÁMICA CONSERVADORA"
# RUT: 8638-K (según analisis_estructura_cmf.md)
test_funds = [
    {
        'nombre': 'BCI CARTERA DINÁMICA CONSERVADORA',
        'rut_fondo': '8638-K',
        'rut_base': '8638'
    },
    {
        'nombre': 'FM BCI ACC. NACIONAL',
        'rut_fondo': '8974-5',
        'rut_base': '8974'
    }
]

print("\n" + "="*80)
print("TEST DE DESCARGA DE PDFs CON SELENIUM - NUEVO FORMATO DE URL")
print("="*80 + "\n")

for i, fund in enumerate(test_funds, 1):
    print(f"\n{'='*80}")
    print(f"TEST {i}/{len(test_funds)}: {fund['nombre']}")
    print(f"{'='*80}")
    print(f"RUT Fondo: {fund['rut_fondo']}")
    print(f"RUT Base: {fund['rut_base']}")
    print()

    try:
        # Descargar PDF usando el método integrado (maneja URL internamente)
        print("📥 Descargando PDF con Selenium...")
        print("   (El método _download_pdf_from_cmf_improved maneja la obtención de URL internamente)")
        pdf_path = processor._download_pdf_from_cmf_improved(
            rut=fund['rut_base'],
            run_completo=fund['rut_fondo']
        )

        if pdf_path:
            print(f"✅ PDF DESCARGADO:")
            print(f"   Path: {pdf_path}")

            if os.path.exists(pdf_path):
                size_kb = os.path.getsize(pdf_path) / 1024
                print(f"   Tamaño: {size_kb:.2f} KB")

                if size_kb > 10:  # PDFs válidos suelen ser > 10KB
                    print(f"   ✅ ARCHIVO VÁLIDO (tamaño razonable)")
                else:
                    print(f"   ⚠️ Archivo muy pequeño, puede estar corrupto")
            else:
                print(f"   ❌ Path retornado pero archivo no existe")
        else:
            print("❌ NO SE PUDO DESCARGAR PDF")

    except Exception as e:
        print(f"\n❌ ERROR EN TEST:")
        print(f"   {type(e).__name__}: {str(e)}")
        logger.exception("Detalle del error:")

print("\n" + "="*80)
print("RESUMEN DE TESTS")
print("="*80)

# Verificar caché
cache_dir = "cache/pdf"
if os.path.exists(cache_dir):
    pdf_files = [f for f in os.listdir(cache_dir) if f.endswith('.pdf')]
    print(f"\n📁 PDFs en caché: {len(pdf_files)}")
    for pdf in pdf_files:
        pdf_path = os.path.join(cache_dir, pdf)
        size_kb = os.path.getsize(pdf_path) / 1024
        print(f"   - {pdf}: {size_kb:.2f} KB")
else:
    print("\n❌ Directorio de caché no existe")

print("\n" + "="*80 + "\n")
