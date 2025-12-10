"""Debug script para ver qué encuentra Selenium en la página de folletos"""

import logging
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# URL del test (BCI CARTERA DINÁMICA CONSERVADORA con pestania=68)
test_url = "https://www.cmfchile.cl/institucional/mercados/entidad.php?mercado=V&rut=8638&tipoentidad=RGFMU&vig=VI&row=AAAw+cAAhAABPt6AAA&control=svs&pestania=68"

print(f"\n{'='*80}")
print("DEBUG SELENIUM - Análisis de página de folletos CMF")
print(f"{'='*80}\n")
print(f"URL: {test_url}\n")

# Configurar Chrome
chrome_options = Options()
# NO usar headless para poder ver qué pasa
# chrome_options.add_argument('--headless=new')
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-dev-shm-usage')
chrome_options.add_argument('--start-maximized')

# Usar chromedriver cacheado
cached_driver = os.path.expanduser("~/.wdm/drivers/chromedriver/mac64/141.0.7390.78/chromedriver-mac-x64/chromedriver")
service = Service(cached_driver)
driver = webdriver.Chrome(service=service, options=chrome_options)

try:
    print("🌐 Navegando a la página...")
    driver.get(test_url)

    # Esperar carga
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )

    print("✅ Página cargada\n")

    # Esperar AJAX
    time.sleep(3)

    # Obtener título
    print(f"📄 Título: {driver.title}\n")

    # Buscar todos los enlaces
    all_links = driver.find_elements(By.TAG_NAME, "a")
    print(f"🔗 Total de enlaces encontrados: {len(all_links)}\n")

    # Buscar enlaces con PDF
    pdf_links = [link for link in all_links if '.pdf' in link.get_attribute('href') or '' if link.get_attribute('href') else '']
    print(f"📑 Enlaces con '.pdf' en href: {len(pdf_links)}")
    for i, link in enumerate(pdf_links[:5], 1):
        href = link.get_attribute('href')
        text = link.text.strip()
        print(f"   {i}. Texto: '{text}' | href: {href[:80]}")

    # Buscar enlaces con texto relevante
    print(f"\n📋 Enlaces con texto relevante (Folleto, PDF):")
    text_links = driver.find_elements(By.XPATH, "//a[contains(text(), 'PDF') or contains(text(), 'Folleto') or contains(text(), 'folleto') or contains(text(), 'pdf')]")
    print(f"   Encontrados: {len(text_links)}")
    for i, link in enumerate(text_links[:5], 1):
        href = link.get_attribute('href') or 'sin href'
        text = link.text.strip()
        onclick = link.get_attribute('onclick') or 'sin onclick'
        print(f"   {i}. Texto: '{text}'")
        print(f"      href: {href[:80]}")
        print(f"      onclick: {onclick[:80]}")

    # Buscar elementos con onclick
    print(f"\n🖱️  Enlaces con onclick:")
    onclick_links = driver.find_elements(By.XPATH, "//a[@onclick]")
    print(f"   Total con onclick: {len(onclick_links)}")
    for i, link in enumerate(onclick_links[:10], 1):
        onclick = link.get_attribute('onclick')
        text = link.text.strip()
        if 'folleto' in onclick.lower() or 'pdf' in onclick.lower():
            print(f"   {i}. Texto: '{text}' | onclick: {onclick}")

    # Buscar en la pestaña activa
    print(f"\n📑 Analizando contenido de pestaña activa...")
    tab_content = driver.find_elements(By.CSS_SELECTOR, "div[id*='tab'], div[class*='tab']")
    print(f"   Contenedores de pestañas encontrados: {len(tab_content)}")

    # Guardar HTML para análisis
    html_path = "temp/debug_page_source.html"
    os.makedirs("temp", exist_ok=True)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(driver.page_source)
    print(f"\n💾 HTML guardado en: {html_path}")

    # Screenshot
    screenshot_path = "temp/debug_screenshot.png"
    driver.save_screenshot(screenshot_path)
    print(f"📸 Screenshot guardado en: {screenshot_path}")

    print(f"\n{'='*80}")
    print("✅ DEBUG COMPLETADO")
    print(f"{'='*80}\n")

    input("Presiona Enter para cerrar el navegador...")

finally:
    driver.quit()
    print("🔒 Navegador cerrado")
