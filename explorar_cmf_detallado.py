"""
Script para explorar en detalle la estructura de CMF y encontrar parámetros reales
Analiza las páginas de listado de fondos para extraer RUTs y series válidos
"""

import requests
from bs4 import BeautifulSoup
import json
import re
from urllib.parse import urljoin, parse_qs, urlparse

class ExploradorCMF:
    """
    Explora el sitio de CMF para identificar parámetros válidos de fondos mutuos
    """

    BASE_URL = "https://www.cmfchile.cl"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'es-ES,es;q=0.9',
        })

    def buscar_pagina_fondos(self):
        """
        Busca la página principal de fondos mutuos en CMF
        """
        print("\n" + "="*80)
        print("🔍 BUSCANDO PÁGINA DE FONDOS MUTUOS EN CMF")
        print("="*80)

        # URLs candidatas para fondos mutuos
        urls_candidatas = [
            "/institucional/estadisticas/entidad.php?mercado=V&tipoentidad=FFMM",
            "/institucional/mercados/entidad.php?mercado=V&tipoentidad=FFMM",
            "/portal/estadisticas/606/w3-propertyvalue-1407.html",
            "/portal/principal/605/w3-channel.html",
        ]

        for url_relativa in urls_candidatas:
            url_completa = urljoin(self.BASE_URL, url_relativa)
            print(f"\n📍 Probando: {url_completa}")

            try:
                response = self.session.get(url_completa, timeout=15)

                if response.status_code == 200:
                    print(f"   ✅ Accesible (Status: {response.status_code})")
                    print(f"   📏 Tamaño: {len(response.content)} bytes")

                    # Buscar indicios de fondos mutuos
                    if 'fondo' in response.text.lower() or 'mutuo' in response.text.lower():
                        print(f"   🎯 Contiene menciones a 'fondo' o 'mutuo'")
                        return url_completa, response
                else:
                    print(f"   ❌ Status: {response.status_code}")

            except Exception as e:
                print(f"   ❌ Error: {str(e)}")

        return None, None

    def extraer_links_folletos(self, html_content):
        """
        Extrae todos los links y scripts relacionados con folletos/PDFs
        """
        print("\n" + "="*80)
        print("📄 ANALIZANDO LINKS DE FOLLETOS")
        print("="*80)

        soup = BeautifulSoup(html_content, 'html.parser')

        # Buscar todos los enlaces que mencionen folleto, PDF, etc
        links_relevantes = []

        # 1. Links directos
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            texto = link.get_text(strip=True).lower()

            if any(palabra in href.lower() or palabra in texto for palabra in
                   ['folleto', 'pdf', 'ver_folleto', 'documento', 'reglamento']):
                links_relevantes.append({
                    'tipo': 'link',
                    'href': href,
                    'texto': texto[:100],
                    'onclick': link.get('onclick', '')
                })

        print(f"\n🔗 Links relevantes encontrados: {len(links_relevantes)}")

        for i, link in enumerate(links_relevantes[:10], 1):  # Mostrar primeros 10
            print(f"\n   {i}. Texto: {link['texto']}")
            print(f"      URL: {link['href']}")
            if link['onclick']:
                print(f"      onClick: {link['onclick'][:150]}")

        # 2. Buscar scripts con funciones de folleto
        print("\n📜 BUSCANDO FUNCIONES JAVASCRIPT RELACIONADAS")
        scripts = soup.find_all('script')

        for script in scripts:
            script_text = script.string
            if script_text:
                # Buscar función verFolleto o similar
                if 'folleto' in script_text.lower() or 'ver_folleto' in script_text.lower():
                    print("\n   🎯 Script con 'folleto' encontrado:")
                    # Extraer líneas relevantes
                    lineas = script_text.split('\n')
                    for linea in lineas:
                        if 'folleto' in linea.lower() or 'post' in linea.lower():
                            print(f"      {linea.strip()[:150]}")

        return links_relevantes

    def extraer_tabla_fondos(self, html_content):
        """
        Extrae tabla de fondos con RUTs y series si existe
        """
        print("\n" + "="*80)
        print("📊 BUSCANDO TABLA DE FONDOS")
        print("="*80)

        soup = BeautifulSoup(html_content, 'html.parser')

        # Buscar tablas
        tablas = soup.find_all('table')
        print(f"\n📋 Tablas encontradas: {len(tablas)}")

        fondos_encontrados = []

        for i, tabla in enumerate(tablas[:5], 1):  # Analizar primeras 5 tablas
            print(f"\n   Tabla {i}:")

            # Extraer headers
            headers = []
            header_row = tabla.find('thead') or tabla.find('tr')
            if header_row:
                headers = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]
                print(f"      Headers: {headers[:8]}")  # Primeros 8

            # Extraer primeras filas de datos
            filas = tabla.find_all('tr')[1:6]  # Primeras 5 filas de datos
            for fila in filas:
                celdas = [td.get_text(strip=True) for td in fila.find_all('td')]
                if celdas:
                    print(f"      Fila: {celdas[:6]}")  # Primeras 6 columnas

                    # Buscar enlaces o botones en la fila
                    links = fila.find_all('a')
                    for link in links:
                        onclick = link.get('onclick', '')
                        href = link.get('href', '')

                        if onclick:
                            # Intentar extraer parámetros del onclick
                            match = re.search(r'verFolleto\((.*?)\)', onclick)
                            if match:
                                params = match.group(1)
                                print(f"         🎯 verFolleto encontrado: {params}")

                                fondos_encontrados.append({
                                    'fila_data': celdas,
                                    'onclick': onclick,
                                    'params_raw': params
                                })

        return fondos_encontrados

    def buscar_datos_en_javascript(self, html_content):
        """
        Busca datos embebidos en JavaScript (arrays, objetos JSON, etc)
        """
        print("\n" + "="*80)
        print("🔍 BUSCANDO DATOS EN JAVASCRIPT")
        print("="*80)

        soup = BeautifulSoup(html_content, 'html.parser')
        scripts = soup.find_all('script')

        for script in scripts:
            script_text = script.string
            if script_text:
                # Buscar arrays o objetos con datos de fondos
                if 'rut' in script_text.lower() and ('serie' in script_text.lower() or 'fondo' in script_text.lower()):
                    print("\n   🎯 Script con 'rut' y 'serie'/'fondo' encontrado:")

                    # Intentar extraer objetos JSON o arrays
                    # Buscar patrones como: var fondos = [{...}]
                    matches = re.finditer(r'var\s+(\w+)\s*=\s*(\[.*?\]|\{.*?\})', script_text, re.DOTALL)

                    for match in matches:
                        var_name = match.group(1)
                        var_value = match.group(2)[:500]  # Primeros 500 chars

                        if 'rut' in var_value.lower() or 'fondo' in var_value.lower():
                            print(f"\n      Variable: {var_name}")
                            print(f"      Valor: {var_value[:300]}...")

    def probar_endpoint_con_params_extraidos(self, fondos_data):
        """
        Prueba el endpoint AJAX con parámetros extraídos de la página
        """
        print("\n" + "="*80)
        print("🧪 PROBANDO ENDPOINT CON PARÁMETROS REALES")
        print("="*80)

        endpoint = f"{self.BASE_URL}/institucional/inc/ver_folleto_fm.php"

        resultados = []

        for i, fondo in enumerate(fondos_data[:5], 1):  # Probar primeros 5
            print(f"\n🔬 Prueba {i}/{min(5, len(fondos_data))}")
            print(f"   Datos de fila: {fondo['fila_data'][:3]}")
            print(f"   Params raw: {fondo['params_raw']}")

            # Intentar parsear los parámetros
            try:
                # Limpiar y separar parámetros
                params_str = fondo['params_raw'].replace("'", "").replace('"', '').strip()
                params_list = [p.strip() for p in params_str.split(',')]

                if len(params_list) >= 3:
                    run_fondo = params_list[0]
                    serie = params_list[1]
                    rut_admin = params_list[2]

                    print(f"   📌 runFondo={run_fondo}, serie={serie}, rutAdmin={rut_admin}")

                    # Hacer POST
                    post_data = {
                        'runFondo': run_fondo,
                        'serie': serie,
                        'rutAdmin': rut_admin
                    }

                    response = self.session.post(
                        endpoint,
                        data=post_data,
                        headers={
                            'X-Requested-With': 'XMLHttpRequest',
                            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
                        },
                        timeout=10
                    )

                    print(f"   📊 Status: {response.status_code}")
                    print(f"   📄 Respuesta: {response.text[:200]}")

                    resultado = {
                        'params': post_data,
                        'status': response.status_code,
                        'response': response.text,
                        'success': response.text != 'ERROR' and response.status_code == 200
                    }

                    resultados.append(resultado)

                    if resultado['success']:
                        print(f"   ✅ ¡ÉXITO! URL encontrada: {response.text}")
                    else:
                        print(f"   ❌ Falló")

            except Exception as e:
                print(f"   ❌ Error parseando: {str(e)}")

        return resultados


def main():
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║  🔬 EXPLORADOR DETALLADO CMF - Análisis de Estructura de Fondos Mutuos      ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """)

    explorador = ExploradorCMF()

    # Paso 1: Encontrar página de fondos
    url_fondos, response = explorador.buscar_pagina_fondos()

    if not url_fondos:
        print("\n❌ No se pudo encontrar la página de fondos mutuos")
        return

    print(f"\n✅ Página de fondos encontrada: {url_fondos}")

    # Paso 2: Analizar contenido
    html_content = response.text

    # Guardar HTML para análisis manual si es necesario
    with open('cmf_fondos_page.html', 'w', encoding='utf-8') as f:
        f.write(html_content)
    print("\n💾 HTML guardado en: cmf_fondos_page.html")

    # Paso 3: Extraer links de folletos
    links = explorador.extraer_links_folletos(html_content)

    # Paso 4: Buscar tabla de fondos
    fondos_data = explorador.extraer_tabla_fondos(html_content)

    # Paso 5: Buscar datos en JavaScript
    explorador.buscar_datos_en_javascript(html_content)

    # Paso 6: Si encontramos fondos, probar el endpoint
    if fondos_data:
        print(f"\n🎯 Fondos con función verFolleto encontrados: {len(fondos_data)}")
        resultados = explorador.probar_endpoint_con_params_extraidos(fondos_data)

        # Guardar resultados
        with open('resultados_exploracion_cmf.json', 'w', encoding='utf-8') as f:
            json.dump({
                'fondos_encontrados': len(fondos_data),
                'links_relevantes': len(links),
                'pruebas_realizadas': len(resultados),
                'resultados': resultados
            }, f, indent=2, ensure_ascii=False)

        print("\n💾 Resultados guardados en: resultados_exploracion_cmf.json")

    else:
        print("\n⚠️  No se encontraron fondos con función verFolleto")
        print("   Esto sugiere que:")
        print("   - La página usa carga dinámica (AJAX)")
        print("   - Los datos están en una URL diferente")
        print("   - Se requiere autenticación o cookies adicionales")

    print("\n" + "="*80)
    print("✅ EXPLORACIÓN COMPLETADA")
    print("="*80)


if __name__ == "__main__":
    main()
