"""Test de descarga DIRECTA de PDF (sin buscar página de entidad)"""

import logging
from fondos_mutuos import FondosMutuosProcessor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

processor = FondosMutuosProcessor()

# Datos del fondo "FM BCI ACC. NACIONAL"
rut_fondo = "8974-5"
rut_admin = "96767630"
nombre = "FM BCI ACC. NACIONAL"

print("\n" + "="*80)
print("TEST DE DESCARGA DIRECTA DE PDF")
print("="*80)
print(f"Fondo: {nombre}")
print(f"RUT Fondo: {rut_fondo}")
print(f"RUT Admin: {rut_admin}")
print("="*80 + "\n")

# Llamar DIRECTAMENTE a _download_pdf_from_cmf (sin el wrapper _improved)
pdf_path = processor._download_pdf_from_cmf(
    rut=rut_fondo.split('-')[0],  # "8974"
    run_completo=rut_fondo,  # "8974-5"
    serie="UNICA",
    rut_admin=rut_admin  # "96767630"
)

if pdf_path:
    print(f"\n✅ PDF DESCARGADO:")
    print(f"   Path: {pdf_path}")

    import os
    if os.path.exists(pdf_path):
        size_kb = os.path.getsize(pdf_path) / 1024
        print(f"   Tamaño: {size_kb:.2f} KB")
        print(f"\n✅ ARCHIVO EXISTE Y ES VÁLIDO")
    else:
        print(f"\n⚠️ Path retornado pero archivo no existe")
else:
    print(f"\n❌ NO SE PUDO DESCARGAR PDF")
