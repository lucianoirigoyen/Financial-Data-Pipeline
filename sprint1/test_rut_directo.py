"""
Test de búsqueda directa por RUT
Probar con RUTs conocidos de fondos
"""

import logging
from fondos_mutuos import FondosMutuosProcessor

logging.basicConfig(level=logging.INFO)

processor = FondosMutuosProcessor()

# RUTs conocidos de fondos (ejemplos):
ruts_prueba = [
    ("10446", "Fintual - Risky Norris"),
    ("10441", "Fintual - Moderate Pitt"),
    ("10442", "Fintual - Conservative Clooney"),
    ("8052", "Ejemplo de test"),
]

print("\n" + "="*80)
print("TEST DE BÚSQUEDA DIRECTA POR RUT")
print("="*80 + "\n")

for rut, descripcion in ruts_prueba:
    print(f"Probando RUT: {rut} ({descripcion})")
    print("-" * 60)

    fund_info = processor._search_fund_in_cmf_by_rut(rut)

    if fund_info:
        print(f"✅ ENCONTRADO:")
        print(f"   Nombre: {fund_info.get('nombre')}")
        print(f"   RUT: {fund_info.get('rut')}")
        print(f"   RUN completo: {fund_info.get('rut_completo')}")
        print(f"   URL: {fund_info.get('url_cmf')}")
    else:
        print(f"❌ NO ENCONTRADO")

    print()
