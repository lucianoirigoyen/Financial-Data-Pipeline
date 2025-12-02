"""
Script to inspect CMF page structure and find correct PDF download mechanism
"""

import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Test URL for BCI CARTERA DINÁMICA CONSERVADORA (RUT: 8638)
test_url = "https://www.cmfchile.cl/institucional/mercados/entidad.php?mercado=V&rut=8638&tipoentidad=RGFMU&vig=VI&row=AAAw+cAAhAABPt6AAA&control=svs&pestania=68"

print(f"\n{'='*80}")
print("INSPECCIÓN DE ESTRUCTURA DE PÁGINA CMF")
print(f"{'='*80}\n")
print(f"URL: {test_url}\n")

# Configure Chrome
chrome_options = Options()
chrome_options.add_argument('--headless=new')
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-dev-shm-usage')

# Use cached driver
cached_driver = os.path.expanduser("~/.wdm/drivers/chromedriver/mac64/141.0.7390.78/chromedriver-mac-x64/chromedriver")
service = Service(cached_driver)
driver = webdriver.Chrome(service=service, options=chrome_options)

try:
    print("🌐 Navegando a página...")
    driver.get(test_url)

    # Wait for page load
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )

    print(f"✅ Página cargada - Título: {driver.title}\n")

    # Wait for AJAX content
    import time
    time.sleep(3)

    print("="*80)
    print("ANÁLISIS DE ESTRUCTURA")
    print("="*80 + "\n")

    # 1. Check for iframes (PDFs might be in iframe)
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    print(f"1. iframes encontrados: {len(iframes)}")
    for i, iframe in enumerate(iframes, 1):
        src = iframe.get_attribute('src') or 'sin src'
        print(f"   iframe {i}: {src}")

    # 2. Look for all links
    all_links = driver.find_elements(By.TAG_NAME, "a")
    print(f"\n2. Total enlaces (a): {len(all_links)}")

    # 3. Links with href containing common PDF patterns
    pdf_patterns = ['.pdf', 'folleto', 'documento', 'descargar', 'download']
    print(f"\n3. Enlaces con patrones PDF:")
    for pattern in pdf_patterns:
        matching = [a for a in all_links if pattern.lower() in (a.get_attribute('href') or '').lower()]
        print(f"   '{pattern}': {len(matching)} enlaces")
        for link in matching[:3]:  # Show first 3
            href = link.get_attribute('href')
            text = link.text.strip() or '(sin texto)'
            print(f"      - Texto: '{text}' | href: {href[:100]}")

    # 4. Links with onclick events
    onclick_links = [a for a in all_links if a.get_attribute('onclick')]
    print(f"\n4. Enlaces con onclick: {len(onclick_links)}")
    for link in onclick_links[:10]:
        onclick = link.get_attribute('onclick')
        text = link.text.strip() or '(sin texto)'
        print(f"   - Texto: '{text}'")
        print(f"     onclick: {onclick[:150]}")

    # 5. Look for buttons
    buttons = driver.find_elements(By.TAG_NAME, "button")
    print(f"\n5. Botones (button): {len(buttons)}")
    for btn in buttons[:5]:
        text = btn.text.strip() or '(sin texto)'
        onclick = btn.get_attribute('onclick') or 'sin onclick'
        print(f"   - Texto: '{text}' | onclick: {onclick[:100]}")

    # 6. Look for forms (PDF might be served via POST)
    forms = driver.find_elements(By.TAG_NAME, "form")
    print(f"\n6. Formularios (form): {len(forms)}")
    for form in forms:
        action = form.get_attribute('action') or 'sin action'
        method = form.get_attribute('method') or 'GET'
        print(f"   - Action: {action} | Method: {method}")

    # 7. Check specific CMF patterns
    print(f"\n7. Buscando patrones específicos CMF:")

    # Pattern: pestania tabs
    tabs = driver.find_elements(By.XPATH, "//*[contains(@class, 'tab') or contains(@id, 'tab')]")
    print(f"   - Elementos con 'tab': {len(tabs)}")

    # Pattern: folleto/ficha
    folleto_elements = driver.find_elements(By.XPATH, "//*[contains(text(), 'Folleto') or contains(text(), 'folleto')]")
    print(f"   - Elementos con texto 'Folleto': {len(folleto_elements)}")
    for el in folleto_elements[:5]:
        tag = el.tag_name
        text = el.text.strip()[:50]
        print(f"      <{tag}>: '{text}'")

    # 8. Save page source for manual inspection
    html_path = "temp/cmf_page_source.html"
    os.makedirs("temp", exist_ok=True)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(driver.page_source)
    print(f"\n8. HTML completo guardado en: {html_path}")

    # 9. Save screenshot
    screenshot_path = "temp/cmf_page_screenshot.png"
    driver.save_screenshot(screenshot_path)
    print(f"9. Screenshot guardado en: {screenshot_path}")

    # 10. Check for JavaScript variables (sometimes PDFs are in JS vars)
    print(f"\n10. Buscando variables JavaScript con 'pdf' o 'folleto':")
    script_content = driver.execute_script("""
        var scripts = document.getElementsByTagName('script');
        var results = [];
        for (var i = 0; i < scripts.length; i++) {
            var content = scripts[i].innerHTML;
            if (content.toLowerCase().includes('pdf') || content.toLowerCase().includes('folleto')) {
                results.push(content.substring(0, 200));
            }
        }
        return results;
    """)
    print(f"   - Scripts con 'pdf/folleto': {len(script_content)}")
    for i, script in enumerate(script_content[:3], 1):
        print(f"      Script {i}: {script.strip()[:150]}...")

    print(f"\n{'='*80}")
    print("✅ INSPECCIÓN COMPLETADA")
    print(f"{'='*80}\n")
    print("PRÓXIMO PASO: Revisar temp/cmf_page_source.html para encontrar estructura exacta")

finally:
    driver.quit()
    print("🔒 Navegador cerrado")
