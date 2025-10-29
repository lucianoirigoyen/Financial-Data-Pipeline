#!/usr/bin/env python3
"""
Script para analizar y replicar el sistema AJAX de descarga de PDFs de la CMF
Replica la función JavaScript verFolleto() para obtener URLs de PDFs
"""

import requests
from typing import Dict, Optional
import json
import time

class CMFPDFDownloader:
    """
    Replica el sistema AJAX de CMF para obtener URLs de folletos de fondos mutuos
    """

    BASE_URL = "https://www.cmfchile.cl"
    AJAX_ENDPOINT = f"{BASE_URL}/institucional/inc/ver_folleto_fm.php"

    def __init__(self):
        """Inicializa sesión con headers apropiados"""
        self.session = requests.Session()

        # Headers críticos que replica el navegador
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',  # Identifica petición AJAX
            'Origin': self.BASE_URL,
            'Referer': f'{self.BASE_URL}/institucional/mercados/entidad.php',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin'
        })

    def obtener_folleto(self, run_fondo: str, serie: str, rut_admin: str) -> Dict:
        """
        Replica la función JavaScript verFolleto()

        Args:
            run_fondo: RUN del fondo mutuo
            serie: Serie del fondo (ej: UNICA, A, B, BPLUS)
            rut_admin: RUT de la administradora

        Returns:
            Dict con status, url_pdf, y mensaje
        """

        # Datos del POST - replica exactamente el $.post de jQuery
        post_data = {
            'runFondo': run_fondo,
            'serie': serie,
            'rutAdmin': rut_admin
        }

        print(f"\n{'='*80}")
        print(f"🔍 Probando: RUT Admin={rut_admin}, Run Fondo={run_fondo}, Serie={serie}")
        print(f"{'='*80}")

        try:
            # Hacer POST al endpoint AJAX
            response = self.session.post(
                self.AJAX_ENDPOINT,
                data=post_data,
                timeout=10,
                allow_redirects=True
            )

            print(f"📊 Status Code: {response.status_code}")
            print(f"📝 Content-Type: {response.headers.get('Content-Type', 'N/A')}")
            print(f"📏 Content-Length: {len(response.content)} bytes")

            # Analizar respuesta
            respuesta_texto = response.text.strip()
            print(f"📄 Respuesta: {respuesta_texto[:200]}")

            resultado = {
                'rut_admin': rut_admin,
                'run_fondo': run_fondo,
                'serie': serie,
                'status_code': response.status_code,
                'success': False,
                'url_pdf': None,
                'mensaje': ''
            }

            if response.status_code == 200:
                # Según el JS, si devuelve 'ERROR' no hay folleto
                if respuesta_texto == 'ERROR':
                    resultado['mensaje'] = "❌ No se encuentra el Folleto (respuesta: ERROR)"
                    print(f"❌ {resultado['mensaje']}")

                # Si devuelve una URL (el JS hace window.open(data))
                elif respuesta_texto.startswith('http') or respuesta_texto.startswith('/'):
                    resultado['success'] = True
                    resultado['url_pdf'] = respuesta_texto
                    resultado['mensaje'] = "✅ URL de PDF obtenida"
                    print(f"✅ URL encontrada: {respuesta_texto}")

                    # Intentar validar que el PDF existe
                    if self._validar_pdf(respuesta_texto):
                        print(f"✅ PDF validado - accesible")
                    else:
                        print(f"⚠️  URL devuelta pero PDF no accesible")
                        resultado['mensaje'] = "⚠️ URL devuelta pero PDF no accesible"
                        resultado['success'] = False

                else:
                    resultado['mensaje'] = f"⚠️  Respuesta inesperada: {respuesta_texto[:100]}"
                    print(f"⚠️  {resultado['mensaje']}")
            else:
                resultado['mensaje'] = f"❌ Error HTTP {response.status_code}"
                print(f"❌ {resultado['mensaje']}")

            return resultado

        except requests.exceptions.RequestException as e:
            print(f"❌ Error de red: {str(e)}")
            return {
                'rut_admin': rut_admin,
                'run_fondo': run_fondo,
                'serie': serie,
                'success': False,
                'url_pdf': None,
                'mensaje': f"Error de red: {str(e)}"
            }

    def _validar_pdf(self, url: str) -> bool:
        """
        Valida que la URL devuelta apunta a un PDF accesible

        Args:
            url: URL a validar

        Returns:
            True si el PDF es accesible
        """
        try:
            # Construir URL completa si es relativa
            if url.startswith('/'):
                url_completa = f"{self.BASE_URL}{url}"
            else:
                url_completa = url

            # HEAD request para verificar sin descargar
            response = self.session.head(url_completa, timeout=5, allow_redirects=True)

            if response.status_code == 200:
                content_type = response.headers.get('Content-Type', '')
                return 'pdf' in content_type.lower()

            return False

        except Exception:
            return False

    def descargar_pdf(self, url: str, nombre_archivo: str) -> bool:
        """
        Descarga el PDF desde la URL obtenida

        Args:
            url: URL del PDF
            nombre_archivo: Nombre para guardar el archivo

        Returns:
            True si se descargó exitosamente
        """
        try:
            # Construir URL completa si es relativa
            if url.startswith('/'):
                url_completa = f"{self.BASE_URL}{url}"
            else:
                url_completa = url

            print(f"\n📥 Descargando PDF desde: {url_completa}")

            response = self.session.get(url_completa, timeout=30)

            if response.status_code == 200:
                with open(nombre_archivo, 'wb') as f:
                    f.write(response.content)

                print(f"✅ PDF descargado: {nombre_archivo} ({len(response.content)} bytes)")
                return True
            else:
                print(f"❌ Error al descargar: Status {response.status_code}")
                return False

        except Exception as e:
            print(f"❌ Error al descargar PDF: {str(e)}")
            return False


def main():
    """
    Función principal - prueba diferentes combinaciones de RUT/Serie
    """

    print("="*80)
    print("🔬 ANÁLISIS SISTEMA AJAX DE DESCARGA PDFs - CMF CHILE")
    print("="*80)
    print("\nReplicando función JavaScript verFolleto()")
    print(f"Endpoint: {CMFPDFDownloader.AJAX_ENDPOINT}\n")

    downloader = CMFPDFDownloader()

    # Casos de prueba basados en fondos reales de CMF
    casos_prueba = [
        {
            'nombre': 'Coopeuch - Serie UNICA',
            'rut_admin': '10441',
            'run_fondo': '10441',  # Mismo que admin generalmente
            'serie': 'UNICA'
        },
        {
            'nombre': 'Banchile - Serie BPLUS',
            'rut_admin': '8052',
            'run_fondo': '8052',
            'serie': 'BPLUS'
        },
        {
            'nombre': 'Banchile - Serie B',
            'rut_admin': '8052',
            'run_fondo': '8052',
            'serie': 'B'
        },
        {
            'nombre': 'Banchile - Serie A',
            'rut_admin': '8052',
            'run_fondo': '8052',
            'serie': 'A'
        },
        {
            'nombre': 'Banchile - Serie DIGITAL',
            'rut_admin': '8052',
            'run_fondo': '8052',
            'serie': 'DIGITAL'
        },
        {
            'nombre': 'Fondo 8248 - Serie A',
            'rut_admin': '8248',
            'run_fondo': '8248',
            'serie': 'A'
        },
        {
            'nombre': 'Santander - Serie A',
            'rut_admin': '8083',
            'run_fondo': '8083',
            'serie': 'A'
        },
        {
            'nombre': 'Security - Serie A',
            'rut_admin': '8226',
            'run_fondo': '8226',
            'serie': 'A'
        }
    ]

    resultados = []
    pdfs_encontrados = []

    # Ejecutar pruebas
    for caso in casos_prueba:
        print(f"\n🧪 CASO DE PRUEBA: {caso['nombre']}")

        resultado = downloader.obtener_folleto(
            run_fondo=caso['run_fondo'],
            serie=caso['serie'],
            rut_admin=caso['rut_admin']
        )

        resultado['nombre_caso'] = caso['nombre']
        resultados.append(resultado)

        # Si encontró URL, intentar descargar
        if resultado['success'] and resultado['url_pdf']:
            pdfs_encontrados.append(resultado)

            # Descargar primer PDF como ejemplo
            if len(pdfs_encontrados) == 1:
                nombre_archivo = f"test_pdf_{caso['rut_admin']}_{caso['serie']}.pdf"
                downloader.descargar_pdf(resultado['url_pdf'], nombre_archivo)

        # Pausa entre requests para ser respetuosos
        time.sleep(1)

    # Resumen final
    print("\n" + "="*80)
    print("📊 RESUMEN DE RESULTADOS")
    print("="*80)

    exitosos = sum(1 for r in resultados if r['success'])
    print(f"\n✅ Exitosos: {exitosos}/{len(resultados)}")
    print(f"❌ Fallidos: {len(resultados) - exitosos}/{len(resultados)}")

    if pdfs_encontrados:
        print(f"\n📄 URLs DE PDFs ENCONTRADAS:")
        for pdf in pdfs_encontrados:
            print(f"  • {pdf['nombre_caso']}")
            print(f"    URL: {pdf['url_pdf']}")
            print(f"    RUT: {pdf['rut_admin']} | Serie: {pdf['serie']}")
    else:
        print(f"\n❌ No se encontraron URLs de PDFs válidas")

    # Guardar resultados en JSON
    with open('resultados_cmf_ajax.json', 'w', encoding='utf-8') as f:
        json.dump(resultados, f, indent=2, ensure_ascii=False)

    print(f"\n💾 Resultados guardados en: resultados_cmf_ajax.json")

    # Conclusiones
    print("\n" + "="*80)
    print("💡 CONCLUSIONES")
    print("="*80)

    if exitosos > 0:
        print("\n✅ SOLUCIÓN FUNCIONAL ENCONTRADA:")
        print("   1. Hacer POST a: https://www.cmfchile.cl/institucional/inc/ver_folleto_fm.php")
        print("   2. Parámetros: runFondo, serie, rutAdmin")
        print("   3. Headers críticos: X-Requested-With, Referer, User-Agent")
        print("   4. La respuesta es directamente la URL del PDF")
        print("   5. Descargar PDF usando GET con la URL obtenida")
    else:
        print("\n⚠️  NO SE ENCONTRARON PDFs VÁLIDOS")
        print("   Posibles causas:")
        print("   - RUTs/Series de prueba incorrectos")
        print("   - Necesidad de cookies de sesión adicionales")
        print("   - Sistema requiere interacción previa con la página")
        print("   - Parámetros adicionales no identificados")


if __name__ == "__main__":
    main()
