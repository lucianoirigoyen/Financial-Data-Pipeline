"""Debug del scraper de fondos"""

import logging
import re
from fondos_mutuos import FondosMutuosProcessor

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

processor = FondosMutuosProcessor()

url = "https://www.cmfchile.cl/institucional/estadisticas/fm.bpr_menu.php"

print("\n" + "="*80)
print("TEST DE SCRAPING DETALLADO")
print("="*80 + "\n")

# Hacer request
print(f"Descargando: {url}")
response = processor.session.get(url, timeout=30)

print(f"Status: {response.status_code}")
print(f"Content length: {len(response.content)} bytes\n")

# Parsear
from bs4 import BeautifulSoup
soup = BeautifulSoup(response.content, 'html.parser')

# Buscar scripts
scripts = soup.find_all('script')
print(f"Total scripts: {len(scripts)}")

scripts_with_type = soup.find_all('script', type='text/javascript')
print(f"Scripts con type='text/javascript': {len(scripts_with_type)}\n")

# Buscar en TODOS los scripts
for i, script in enumerate(scripts):
    if script.string and 'fondos_' in script.string:
        print(f"✓ Script {i+1} contiene 'fondos_'")
        print(f"  Tiene atributo type: {script.get('type')}")
        print(f"  Length: {len(script.string)} chars")

        # Intentar regex
        matches = re.findall(r'fondos_(\d+)\s*=\s*new Array\((.*?)\);', script.string, re.DOTALL)
        print(f"  Regex matches: {len(matches)}")

        if matches:
            rut_admin, fund_data = matches[0]
            print(f"  Primer match - RUT Admin: {rut_admin}")
            items = re.findall(r'"([^"]*)"', fund_data)
            print(f"  Items encontrados: {len(items)}")
            print(f"  Primeros 3 items: {items[:3]}")
        print()
