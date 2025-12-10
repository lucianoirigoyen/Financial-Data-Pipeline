#!/usr/bin/env python3
"""
Test script para validar extracción extendida de datos desde PDFs

Prueba la nueva función _extract_extended_data_from_pdf() con todos los PDFs
disponibles y genera un reporte de cobertura de campos.
"""

import os
import sys
import json
from pathlib import Path
from fondos_mutuos import FondosMutuosProcessor

def test_pdf_extraction():
    """
    Ejecutar pruebas de extracción en todos los PDFs disponibles
    """
    print("=" * 80)
    print("TEST DE EXTRACCIÓN EXTENDIDA DE DATOS DESDE PDFs")
    print("=" * 80)
    print()

    # Buscar PDFs en directorio temp/
    pdf_dir = Path("temp")
    pdfs = list(pdf_dir.glob("*.pdf"))

    if not pdfs:
        print("❌ No se encontraron PDFs en directorio temp/")
        return

    print(f"📄 Encontrados {len(pdfs)} PDFs para analizar\n")

    # Inicializar procesador
    processor = FondosMutuosProcessor()

    # Contadores globales
    total_campos = 12  # Total de campos que intentamos extraer
    resultados_globales = []

    # Procesar cada PDF
    for i, pdf_path in enumerate(pdfs, 1):
        print(f"\n{'=' * 80}")
        print(f"PDF {i}/{len(pdfs)}: {pdf_path.name}")
        print(f"{'=' * 80}")

        try:
            # Extraer datos extendidos
            resultado = processor._extract_extended_data_from_pdf(str(pdf_path))

            if not resultado.get('pdf_procesado', False):
                print(f"❌ Error procesando PDF: {resultado.get('error', 'Unknown')}")
                continue

            # Contar campos extraídos
            campos_encontrados = []
            campos_faltantes = []

            # Lista de campos a verificar
            campos_verificar = [
                ('tipo_fondo', 'Tipo de Fondo'),
                ('perfil_riesgo', 'Perfil de Riesgo'),
                ('perfil_riesgo_escala', 'Escala Riesgo (R1-R7)'),
                ('horizonte_inversion', 'Horizonte de Inversión'),
                ('comision_administracion', 'Comisión Administración'),
                ('comision_rescate', 'Comisión Rescate'),
                ('rentabilidad_12m', 'Rentabilidad 12 meses'),
                ('rentabilidad_24m', 'Rentabilidad 24 meses'),
                ('rentabilidad_36m', 'Rentabilidad 36 meses'),
                ('patrimonio', 'Patrimonio'),
                ('composicion_portafolio', 'Composición Portafolio'),
                ('composicion_detallada', 'Composición Detallada'),
            ]

            print("\n📊 CAMPOS EXTRAÍDOS:")
            print("-" * 80)

            for campo_key, campo_nombre in campos_verificar:
                valor = resultado.get(campo_key)

                if valor is not None and valor != [] and valor != '':
                    campos_encontrados.append(campo_key)

                    # Formatear valor según tipo
                    if campo_key == 'composicion_portafolio':
                        valor_mostrar = f"{len(valor)} activos"
                        print(f"✅ {campo_nombre:30s}: {valor_mostrar}")
                        # Mostrar top 3 activos
                        for j, activo in enumerate(valor[:3], 1):
                            print(f"     {j}. {activo['activo']:25s} {activo['porcentaje']:>7.2%}")
                    elif campo_key == 'composicion_detallada':
                        valor_mostrar = f"{len(valor)} activos clasificados"
                        print(f"✅ {campo_nombre:30s}: {valor_mostrar}")
                    elif campo_key in ['comision_administracion', 'comision_rescate']:
                        print(f"✅ {campo_nombre:30s}: {valor:.4f} ({valor*100:.2f}%)")
                    elif campo_key in ['rentabilidad_12m', 'rentabilidad_24m', 'rentabilidad_36m']:
                        print(f"✅ {campo_nombre:30s}: {valor:.2%}")
                    elif campo_key == 'patrimonio':
                        moneda = resultado.get('patrimonio_moneda', 'CLP')
                        print(f"✅ {campo_nombre:30s}: {moneda} {valor:,.0f}")
                    else:
                        print(f"✅ {campo_nombre:30s}: {valor}")
                else:
                    campos_faltantes.append(campo_key)
                    print(f"❌ {campo_nombre:30s}: No encontrado")

            # Calcular estadísticas
            num_encontrados = len(campos_encontrados)
            porcentaje_cobertura = (num_encontrados / len(campos_verificar)) * 100
            confianza = resultado.get('extraction_confidence', 'unknown')

            print("\n" + "=" * 80)
            print(f"📈 ESTADÍSTICAS DE EXTRACCIÓN:")
            print("-" * 80)
            print(f"Campos extraídos:    {num_encontrados}/{len(campos_verificar)} ({porcentaje_cobertura:.1f}%)")
            print(f"Nivel de confianza:  {confianza.upper()}")
            print(f"Caracteres en PDF:   {len(resultado.get('texto_completo', ''))}")
            print("=" * 80)

            # Guardar resultado
            resultados_globales.append({
                'pdf': pdf_path.name,
                'campos_encontrados': num_encontrados,
                'total_campos': len(campos_verificar),
                'porcentaje_cobertura': porcentaje_cobertura,
                'confianza': confianza,
                'datos': {
                    campo: resultado.get(campo)
                    for campo, _ in campos_verificar
                }
            })

        except Exception as e:
            print(f"\n❌ ERROR procesando {pdf_path.name}: {e}")
            import traceback
            traceback.print_exc()

    # RESUMEN GLOBAL
    print("\n\n" + "=" * 80)
    print("📊 RESUMEN GLOBAL DE EXTRACCIÓN")
    print("=" * 80)
    print()

    if resultados_globales:
        # Tabla resumen
        print(f"{'PDF':<40s} {'Campos':>8s} {'Cobertura':>10s} {'Confianza':>12s}")
        print("-" * 80)

        for res in resultados_globales:
            print(f"{res['pdf']:<40s} {res['campos_encontrados']:>3d}/{res['total_campos']:<3d} "
                  f"{res['porcentaje_cobertura']:>8.1f}%  {res['confianza']:>12s}")

        # Promedios
        print("-" * 80)
        promedio_cobertura = sum(r['porcentaje_cobertura'] for r in resultados_globales) / len(resultados_globales)
        print(f"{'PROMEDIO':<40s} {'':>8s} {promedio_cobertura:>8.1f}%")
        print("=" * 80)

        # Análisis de campos más comunes
        print("\n📋 ANÁLISIS DE CAMPOS:")
        print("-" * 80)

        campos_conteo = {}
        for res in resultados_globales:
            for campo, nombre in campos_verificar:
                valor = res['datos'].get(campo)
                if valor is not None and valor != [] and valor != '':
                    campos_conteo[nombre] = campos_conteo.get(nombre, 0) + 1

        for nombre, count in sorted(campos_conteo.items(), key=lambda x: x[1], reverse=True):
            porcentaje = (count / len(resultados_globales)) * 100
            barra = "█" * int(porcentaje / 5)
            print(f"{nombre:30s}: {barra:20s} {count}/{len(resultados_globales)} ({porcentaje:.0f}%)")

        print("=" * 80)

        # Guardar resultados en JSON
        output_file = "outputs/test_extraction_results.json"
        os.makedirs("outputs", exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(resultados_globales, f, indent=2, ensure_ascii=False, default=str)

        print(f"\n💾 Resultados guardados en: {output_file}")

    else:
        print("❌ No se pudieron procesar PDFs")

    print("\n✅ TEST COMPLETADO\n")


if __name__ == "__main__":
    test_pdf_extraction()
