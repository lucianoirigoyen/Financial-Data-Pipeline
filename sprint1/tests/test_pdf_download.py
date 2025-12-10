"""Test de descarga de PDF con datos reales"""

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
print("TEST DE DESCARGA DE PDF")
print("="*80)
print(f"Fondo: {nombre}")
print(f"RUT Fondo: {rut_fondo}")
print(f"RUT Admin: {rut_admin}")
print("="*80 + "\n")

# Intentar descargar PDF
pdf_path = processor._download_pdf_from_cmf_improved(
    rut=rut_fondo.split('-')[0],  # "8974" (sin guión para algunos métodos)
    run_completo=rut_fondo  # "8974-5" (con guión para el POST)
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
