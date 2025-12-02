"""Ver qué fondos están en la lista de CMF"""

import logging
from fondos_mutuos import FondosMutuosProcessor

logging.basicConfig(level=logging.WARNING)

processor = FondosMutuosProcessor()

print("\n" + "="*80)
print("LISTA DE FONDOS ENCONTRADOS EN CMF:")
print("="*80)

funds_list = processor._scrape_cmf_funds_list()

if funds_list:
    print(f"\nTotal fondos: {len(funds_list)}\n")
    for i, fund in enumerate(funds_list, 1):
        # Usar nuevo formato
        nombre = fund.get('nombre') or fund.get('fund_name', 'N/A')
        rut_fondo = fund.get('rut_fondo', 'N/A')
        rut_admin = fund.get('rut_admin') or fund.get('administrator_id', 'N/A')

        print(f"{i}. {nombre}")
        print(f"   RUT Fondo: {rut_fondo}")
        print(f"   RUT Admin: {rut_admin}")
        print()
else:
    print("\n❌ NO SE ENCONTRARON FONDOS")
