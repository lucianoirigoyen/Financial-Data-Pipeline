#!/usr/bin/env python3
"""
Script ejecutable para monitorear salud de CMF Chile
Ejecuta todos los checks y muestra resultados con colores en consola
"""

import sys
import json
from datetime import datetime
from cmf_monitor import CMFMonitor


# Códigos de color ANSI para terminal
class Colors:
    """Códigos de color para salida en consola"""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def print_header(text: str):
    """Imprimir header con formato"""
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'=' * 70}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text.center(70)}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'=' * 70}{Colors.ENDC}\n")


def print_check_result(check_name: str, status: str, details: str = ""):
    """Imprimir resultado de un check con colores"""
    # Determinar color según status
    if status == 'ok' or status == 'healthy':
        color = Colors.OKGREEN
        symbol = "✓"
    elif status == 'warning':
        color = Colors.WARNING
        symbol = "⚠"
    elif status == 'critical' or status == 'error':
        color = Colors.FAIL
        symbol = "✗"
    else:
        color = Colors.OKBLUE
        symbol = "?"

    # Imprimir resultado
    print(f"  {color}{symbol} {check_name.ljust(30)}: {status.upper()}{Colors.ENDC}")
    if details:
        print(f"    {Colors.OKCYAN}{details}{Colors.ENDC}")


def print_recommendations(recommendations: list):
    """Imprimir recomendaciones"""
    print(f"\n{Colors.BOLD}RECOMENDACIONES:{Colors.ENDC}")
    for rec in recommendations:
        if "ACCIÓN INMEDIATA" in rec or "CRÍTICO" in rec:
            color = Colors.FAIL
        elif "Monitorear" in rec or "Revisar" in rec:
            color = Colors.WARNING
        else:
            color = Colors.OKGREEN

        print(f"  {color}• {rec}{Colors.ENDC}")


def print_changes(changes: list):
    """Imprimir cambios detectados"""
    if not changes:
        return

    print(f"\n{Colors.BOLD}CAMBIOS DETECTADOS:{Colors.ENDC}")
    for change in changes:
        severity = change.get('severity', 'info')
        change_type = change.get('type', 'unknown')

        if severity == 'critical':
            color = Colors.FAIL
            symbol = "✗"
        elif severity == 'warning':
            color = Colors.WARNING
            symbol = "⚠"
        else:
            color = Colors.OKBLUE
            symbol = "ℹ"

        print(f"  {color}{symbol} [{severity.upper()}] {change_type}{Colors.ENDC}")

        # Imprimir detalles del cambio
        for key, value in change.items():
            if key not in ['type', 'severity']:
                print(f"      {key}: {value}")


def print_statistics(report: dict):
    """Imprimir estadísticas del monitoreo"""
    print(f"\n{Colors.BOLD}ESTADÍSTICAS:{Colors.ENDC}")

    # Endpoint timing
    endpoint_time = report.get('checks', {}).get('endpoint_available', {}).get('response_time_ms')
    if endpoint_time:
        time_color = Colors.OKGREEN if endpoint_time < 1000 else Colors.WARNING if endpoint_time < 3000 else Colors.FAIL
        print(f"  {time_color}Tiempo de respuesta endpoint: {endpoint_time}ms{Colors.ENDC}")

    # PDF size
    pdf_size = report.get('checks', {}).get('pdf_download', {}).get('file_size')
    if pdf_size:
        size_kb = pdf_size / 1024
        size_color = Colors.OKGREEN if size_kb > 100 else Colors.WARNING
        print(f"  {size_color}Tamaño PDF de prueba: {size_kb:.2f} KB{Colors.ENDC}")

    # Número de cambios
    changes_count = len(report.get('checks', {}).get('structure_changes', {}).get('changes', []))
    changes_color = Colors.OKGREEN if changes_count == 0 else Colors.WARNING
    print(f"  {changes_color}Cambios en estructura: {changes_count}{Colors.ENDC}")


def main():
    """Función principal del script"""
    print_header("CMF CHILE - SISTEMA DE MONITOREO")

    print(f"{Colors.OKCYAN}Iniciando monitoreo completo de CMF Chile...{Colors.ENDC}")
    print(f"{Colors.OKCYAN}Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{Colors.ENDC}\n")

    # Crear instancia del monitor
    monitor = CMFMonitor()

    # Ejecutar checks individuales con feedback visual
    print(f"{Colors.BOLD}EJECUTANDO CHECKS:{Colors.ENDC}\n")

    # CHECK 1: Estructura HTML
    print(f"  {Colors.OKCYAN}▸ Monitoreando estructura HTML...{Colors.ENDC}")
    structure_result = monitor.monitor_cmf_structure()

    # CHECK 2: Endpoint availability
    print(f"  {Colors.OKCYAN}▸ Verificando endpoint availability...{Colors.ENDC}")
    endpoint_result = monitor.check_endpoint_availability()

    # CHECK 3: PDF download
    print(f"  {Colors.OKCYAN}▸ Validando descarga de PDF...{Colors.ENDC}")
    pdf_result = monitor.validate_pdf_download()

    # CHECK 4: Baseline comparison
    print(f"  {Colors.OKCYAN}▸ Comparando con baseline...{Colors.ENDC}")
    baseline_result = monitor.compare_with_baseline(structure_result)

    # Generar reporte consolidado
    print(f"\n{Colors.OKCYAN}▸ Generando reporte consolidado...{Colors.ENDC}\n")
    report = monitor.generate_health_report()

    # Mostrar resultados
    print_header("RESULTADOS DEL MONITOREO")

    # Status general
    overall_status = report['status']
    if overall_status == 'healthy':
        status_color = Colors.OKGREEN
        status_symbol = "✓✓✓"
    elif overall_status == 'warning':
        status_color = Colors.WARNING
        status_symbol = "⚠⚠"
    elif overall_status == 'critical':
        status_color = Colors.FAIL
        status_symbol = "✗✗✗"
    else:
        status_color = Colors.OKBLUE
        status_symbol = "???"

    print(f"{Colors.BOLD}STATUS GENERAL:{Colors.ENDC} {status_color}{status_symbol} {overall_status.upper()} {status_symbol}{Colors.ENDC}\n")

    # Resultados de checks individuales
    print(f"{Colors.BOLD}CHECKS INDIVIDUALES:{Colors.ENDC}\n")

    # JavaScript function
    js_check = report.get('checks', {}).get('javascript_function', {})
    print_check_result(
        "Función JavaScript",
        js_check.get('status', 'unknown'),
        js_check.get('details', '')
    )

    # Endpoint
    endpoint_check = report.get('checks', {}).get('endpoint_available', {})
    print_check_result(
        "Endpoint disponible",
        endpoint_check.get('status', 'unknown'),
        endpoint_check.get('details', '')
    )

    # PDF download
    pdf_check = report.get('checks', {}).get('pdf_download', {})
    print_check_result(
        "Descarga PDF",
        pdf_check.get('status', 'unknown'),
        pdf_check.get('details', '')
    )

    # Baseline comparison
    baseline_check = report.get('checks', {}).get('structure_changes', {})
    print_check_result(
        "Cambios en estructura",
        baseline_check.get('status', 'unknown'),
        baseline_check.get('details', '')
    )

    # Mostrar cambios detectados
    changes = baseline_check.get('changes', [])
    if changes:
        print_changes(changes)

    # Estadísticas
    print_statistics(report)

    # Recomendaciones
    print_recommendations(report.get('recommendations', []))

    # Archivos generados
    print(f"\n{Colors.BOLD}ARCHIVOS GENERADOS:{Colors.ENDC}")
    print(f"  {Colors.OKCYAN}• Reporte de salud: cache/cmf_health_report.json{Colors.ENDC}")
    print(f"  {Colors.OKCYAN}• Log de alertas: cache/cmf_alerts.log{Colors.ENDC}")
    print(f"  {Colors.OKCYAN}• PDF de prueba: temp/monitor_test.pdf{Colors.ENDC}")

    # Footer
    print_header("FIN DEL MONITOREO")

    # Determinar exit code
    if overall_status == 'healthy':
        exit_code = 0
    elif overall_status == 'warning':
        exit_code = 1
    else:  # critical or error
        exit_code = 2

    print(f"{Colors.OKCYAN}Exit code: {exit_code}{Colors.ENDC}")
    print()

    return exit_code


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print(f"\n\n{Colors.WARNING}Monitoreo interrumpido por el usuario{Colors.ENDC}")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n{Colors.FAIL}ERROR FATAL: {e}{Colors.ENDC}")
        sys.exit(2)
