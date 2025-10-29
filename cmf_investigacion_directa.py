"""
Investigación directa del sistema CMF combinando datos de Fintual
Estrategia: Usar Fintual API para obtener RUTs reales, luego probar CMF
"""

import requests
import json
from typing import Dict, List

class InvestigadorCMFFintual:
    """
    Combina datos de Fintual con pruebas en CMF para encontrar parámetros válidos
    """

    FINTUAL_API = "https://fintual.cl/api"
    CMF_BASE = "https://www.cmfchile.cl"
    CMF_AJAX_ENDPOINT = f"{CMF_BASE}/institucional/inc/ver_folleto_fm.php"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': '*/*',
            'Accept-Language': 'es-ES,es;q=0.9',
        })

    def obtener_fondos_fintual(self) -> List[Dict]:
        """
        Obtiene lista de fondos desde Fintual API
        """
        print("\n" + "="*80)
        print("📡 OBTENIENDO FONDOS DESDE FINTUAL API")
        print("="*80)

        try:
            # Endpoints conocidos de Fintual
            endpoints = [
                f"{self.FINTUAL_API}/goals",
                f"{self.FINTUAL_API}/real_assets",
                f"{self.FINTUAL_API}/funds",
                "https://fintual.cl/api/real_assets"
            ]

            for endpoint in endpoints:
                print(f"\n📍 Probando: {endpoint}")
                try:
                    response = requests.get(endpoint, timeout=10)
                    if response.status_code == 200:
                        print(f"   ✅ Status: 200")
                        data = response.json()
                        print(f"   📦 Datos recibidos: {len(data.get('data', []))} items")

                        # Mostrar estructura
                        if data.get('data'):
                            print(f"   📋 Primeros 3 fondos:")
                            for fondo in data['data'][:3]:
                                print(f"\n      Nombre: {fondo.get('attributes', {}).get('name', 'N/A')}")
                                print(f"      ID: {fondo.get('id', 'N/A')}")
                                print(f"      Tipo: {fondo.get('type', 'N/A')}")

                        return data.get('data', [])

                except Exception as e:
                    print(f"   ❌ Error: {str(e)}")

        except Exception as e:
            print(f"❌ Error general: {str(e)}")

        return []

    def probar_cmf_variaciones_rut(self) -> List[Dict]:
        """
        Prueba diferentes variaciones de RUT con el endpoint CMF
        Basado en RUTs conocidos de administradoras chilenas
        """
        print("\n" + "="*80)
        print("🧪 PROBANDO VARIACIONES DE RUT EN CMF")
        print("="*80)

        # RUTs de administradoras conocidas en Chile
        administradoras = [
            {'nombre': 'BanChile AGF', 'rut': '96588120'},
            {'nombre': 'Santander AGF', 'rut': '96667870'},
            {'nombre': 'BCI AGF', 'rut': '96526210'},
            {'nombre': 'Consorcio AGF', 'rut': '76132017'},
            {'nombre': 'Security AGF', 'rut': '96526280'},
            {'nombre': 'LarrainVial AGF', 'rut': '79568930'},
            {'nombre': 'Principal AGF', 'rut': '96518980'},
        ]

        series_comunes = ['A', 'B', 'C', 'UNICA', 'APV', 'PREMIUM']

        resultados = []

        for admin in administradoras:
            print(f"\n{'='*60}")
            print(f"🏦 {admin['nombre']} (RUT: {admin['rut']})")
            print(f"{'='*60}")

            for serie in series_comunes:
                try:
                    # Probar con RUT completo
                    params = {
                        'runFondo': admin['rut'],
                        'serie': serie,
                        'rutAdmin': admin['rut']
                    }

                    print(f"\n   📋 Serie {serie}: ", end='')

                    response = self.session.post(
                        self.CMF_AJAX_ENDPOINT,
                        data=params,
                        headers={
                            'X-Requested-With': 'XMLHttpRequest',
                            'Content-Type': 'application/x-www-form-urlencoded'
                        },
                        timeout=10
                    )

                    respuesta = response.text.strip()

                    resultado = {
                        'administradora': admin['nombre'],
                        'rut': admin['rut'],
                        'serie': serie,
                        'status': response.status_code,
                        'respuesta': respuesta,
                        'success': respuesta != 'ERROR' and len(respuesta) > 10
                    }

                    if resultado['success']:
                        print(f"✅ ¡ÉXITO! - {respuesta[:80]}")
                        resultados.append(resultado)
                    else:
                        print(f"❌ ERROR o vacío")

                except Exception as e:
                    print(f"❌ Excepción: {str(e)}")

        return resultados

    def probar_cmf_formatos_alternativos(self) -> List[Dict]:
        """
        Prueba formatos alternativos de parámetros
        """
        print("\n" + "="*80)
        print("🔬 PROBANDO FORMATOS ALTERNATIVOS DE PARÁMETROS")
        print("="*80)

        # Casos de prueba basados en diferentes formatos posibles
        casos_prueba = [
            # Formato 1: RUT con guión
            {
                'nombre': 'BanChile con guión',
                'runFondo': '96588120-7',
                'serie': 'A',
                'rutAdmin': '96588120-7'
            },
            # Formato 2: RUT sin guión pero con dígito verificador
            {
                'nombre': 'BanChile DV separado',
                'runFondo': '965881207',
                'serie': 'A',
                'rutAdmin': '965881207'
            },
            # Formato 3: Solo primeros dígitos
            {
                'nombre': 'BanChile acortado',
                'runFondo': '96588',
                'serie': 'A',
                'rutAdmin': '96588'
            },
            # Formato 4: RUT en miles
            {
                'nombre': 'Formato miles',
                'runFondo': '96.588.120',
                'serie': 'A',
                'rutAdmin': '96.588.120'
            },
        ]

        resultados = []

        for caso in casos_prueba:
            print(f"\n🧪 {caso['nombre']}")
            print(f"   Parámetros: runFondo={caso['runFondo']}, serie={caso['serie']}")

            try:
                params = {
                    'runFondo': caso['runFondo'],
                    'serie': caso['serie'],
                    'rutAdmin': caso['rutAdmin']
                }

                response = self.session.post(
                    self.CMF_AJAX_ENDPOINT,
                    data=params,
                    headers={'X-Requested-With': 'XMLHttpRequest'},
                    timeout=10
                )

                respuesta = response.text.strip()

                resultado = {
                    'caso': caso['nombre'],
                    'params': params,
                    'status': response.status_code,
                    'respuesta': respuesta,
                    'success': respuesta != 'ERROR' and len(respuesta) > 10
                }

                if resultado['success']:
                    print(f"   ✅ ¡ÉXITO! - {respuesta[:100]}")
                else:
                    print(f"   ❌ Falló - {respuesta}")

                resultados.append(resultado)

            except Exception as e:
                print(f"   ❌ Error: {str(e)}")

        return resultados

    def analizar_endpoint_directo(self):
        """
        Analiza qué espera exactamente el endpoint haciendo requests de prueba
        """
        print("\n" + "="*80)
        print("🔍 ANÁLISIS DIRECTO DEL ENDPOINT")
        print("="*80)

        print("\n1️⃣  Probando GET vs POST:")

        # Probar GET
        try:
            response = self.session.get(self.CMF_AJAX_ENDPOINT, timeout=10)
            print(f"   GET: Status {response.status_code}, Response: {response.text[:100]}")
        except Exception as e:
            print(f"   GET: Error - {str(e)}")

        # Probar POST vacío
        try:
            response = self.session.post(self.CMF_AJAX_ENDPOINT, timeout=10)
            print(f"   POST vacío: Status {response.status_code}, Response: {response.text[:100]}")
        except Exception as e:
            print(f"   POST vacío: Error - {str(e)}")

        # Probar POST con parámetros vacíos
        try:
            response = self.session.post(
                self.CMF_AJAX_ENDPOINT,
                data={'runFondo': '', 'serie': '', 'rutAdmin': ''},
                timeout=10
            )
            print(f"   POST vacío params: Status {response.status_code}, Response: {response.text[:100]}")
        except Exception as e:
            print(f"   POST vacío params: Error - {str(e)}")

        print("\n2️⃣  Probando diferentes Content-Types:")

        content_types = [
            'application/x-www-form-urlencoded',
            'application/json',
            'multipart/form-data',
        ]

        for ct in content_types:
            try:
                if ct == 'application/json':
                    response = self.session.post(
                        self.CMF_AJAX_ENDPOINT,
                        json={'runFondo': '96588120', 'serie': 'A', 'rutAdmin': '96588120'},
                        headers={'Content-Type': ct},
                        timeout=10
                    )
                else:
                    response = self.session.post(
                        self.CMF_AJAX_ENDPOINT,
                        data={'runFondo': '96588120', 'serie': 'A', 'rutAdmin': '96588120'},
                        headers={'Content-Type': ct},
                        timeout=10
                    )

                print(f"   {ct}: {response.text[:50]}")

            except Exception as e:
                print(f"   {ct}: Error - {str(e)}")


def main():
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║  🔬 INVESTIGACIÓN DIRECTA CMF + FINTUAL                                      ║
║  Estrategia: Combinar datos reales con pruebas exhaustivas                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """)

    investigador = InvestigadorCMFFintual()

    # Paso 1: Obtener fondos de Fintual
    fondos_fintual = investigador.obtener_fondos_fintual()

    # Paso 2: Analizar endpoint directamente
    investigador.analizar_endpoint_directo()

    # Paso 3: Probar variaciones de RUT
    resultados_rut = investigador.probar_cmf_variaciones_rut()

    # Paso 4: Probar formatos alternativos
    resultados_formatos = investigador.probar_cmf_formatos_alternativos()

    # Resumen
    print("\n" + "="*80)
    print("📊 RESUMEN FINAL")
    print("="*80)

    total_exitosos = len([r for r in resultados_rut + resultados_formatos if r.get('success')])

    print(f"\n✅ Peticiones exitosas: {total_exitosos}")
    print(f"❌ Peticiones fallidas: {len(resultados_rut + resultados_formatos) - total_exitosos}")

    if total_exitosos > 0:
        print("\n🎉 ¡URLs DE PDFs ENCONTRADAS!")
        for resultado in resultados_rut + resultados_formatos:
            if resultado.get('success'):
                print(f"\n   📄 {resultado.get('administradora', resultado.get('caso'))}")
                print(f"      Serie: {resultado['serie']}")
                print(f"      URL: {resultado['respuesta']}")

    # Guardar resultados
    with open('resultados_investigacion_cmf.json', 'w', encoding='utf-8') as f:
        json.dump({
            'fondos_fintual': fondos_fintual[:5],  # Primeros 5 para no saturar
            'resultados_rut': resultados_rut,
            'resultados_formatos': resultados_formatos,
            'total_exitosos': total_exitosos
        }, f, indent=2, ensure_ascii=False)

    print("\n💾 Resultados completos guardados en: resultados_investigacion_cmf.json")


if __name__ == "__main__":
    main()
