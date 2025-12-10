"""Test extracción raw de JavaScript"""

import requests
import re
from bs4 import BeautifulSoup

url = "https://www.cmfchile.cl/institucional/estadisticas/fm.bpr_menu.php"

print("Descargando página...")
response = requests.get(url, timeout=30)

print(f"Status: {response.status_code}\n")

# Test 1: Buscar con regex en HTML crudo
print("="*80)
print("TEST 1: REGEX EN HTML CRUDO")
print("="*80)

fund_arrays = re.findall(r'fondos_(\d+)\s*=\s*new Array\((.*?)\);', response.text, re.DOTALL)

print(f"Arrays encontrados: {len(fund_arrays)}\n")

if fund_arrays:
    rut_admin, fund_data = fund_arrays[0]
    print(f"RUT Admin: {rut_admin}")
    print(f"Data length: {len(fund_data)} chars")
    print(f"First 200 chars: {fund_data[:200]}\n")

    # Extraer items
    items = re.findall(r'"([^"]*)"', fund_data)
    print(f"Total items: {len(items)}")
    print(f"Primeros 5 items:")
    for i, item in enumerate(items[:5]):
        print(f"  {i+1}. {item}")

    # Parsear uno
    print(f"\nParseando items:")
    for item in items[1:6]:  # Skip "Seleccione..."
        if 'seleccione' in item.lower():
            continue
        parts = re.split(r'\s{2,}', item.strip(), maxsplit=1)
        if len(parts) == 2:
            print(f"  RUT: {parts[0]}, Nombre: {parts[1]}")

# Test 2: Con BeautifulSoup
print("\n" + "="*80)
print("TEST 2: CON BEAUTIFULSOUP")
print("="*80)

soup = BeautifulSoup(response.content, 'html.parser')
scripts = soup.find_all('script', type='text/javascript')

print(f"Scripts encontrados: {len(scripts)}\n")

for i, script in enumerate(scripts):
    if script.string and 'fondos_' in script.string:
        print(f"Script {i+1} contiene 'fondos_'")
        print(f"  Length: {len(script.string)} chars")

        # Intentar regex
        matches = re.findall(r'fondos_(\d+)\s*=\s*new Array\((.*?)\);', script.string, re.DOTALL)
        print(f"  Matches: {len(matches)}")
        if matches:
            print(f"  Primer match RUT Admin: {matches[0][0]}")
