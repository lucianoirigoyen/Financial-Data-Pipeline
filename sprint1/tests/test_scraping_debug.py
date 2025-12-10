"""
Test de debugging del scraping de CMF Chile
Probar paso a paso: búsqueda de fondos, RUTs, descarga de PDFs
"""

import logging
import sys
from fondos_mutuos import FondosMutuosProcessor

# Configurar logging detallado
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('test_scraping_debug.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def test_busqueda_por_nombre():
    """Test 1: Buscar un fondo por nombre"""
    print("\n" + "="*80)
    print("TEST 1: BÚSQUEDA DE FONDO POR NOMBRE")
    print("="*80)

    processor = FondosMutuosProcessor()

    # Probar con un fondo conocido
    fondo_nombre = "bci cartera dinamica conservadora"
    logger.info(f"Buscando fondo: {fondo_nombre}")

    fund_info = processor._search_fund_in_cmf(fondo_nombre)

    if fund_info:
        print(f"\n✅ FONDO ENCONTRADO:")
        print(f"   Nombre: {fund_info.get('fund_name')}")
        print(f"   RUT Admin: {fund_info.get('administrator_id')}")
        print(f"   Código: {fund_info.get('fund_code')}")
        print(f"   ID: {fund_info.get('full_id')}")
        return fund_info
    else:
        print("\n❌ NO SE ENCONTRÓ EL FONDO")
        return None

def test_busqueda_por_rut(rut: str):
    """Test 2: Buscar fondo directamente por RUT"""
    print("\n" + "="*80)
    print(f"TEST 2: BÚSQUEDA DIRECTA POR RUT: {rut}")
    print("="*80)

    processor = FondosMutuosProcessor()

    fund_info = processor._search_fund_in_cmf_by_rut(rut)

    if fund_info:
        print(f"\n✅ FONDO ENCONTRADO POR RUT:")
        print(f"   Nombre: {fund_info.get('nombre')}")
        print(f"   RUT: {fund_info.get('rut')}")
        print(f"   RUN completo: {fund_info.get('rut_completo')}")
        print(f"   URL CMF: {fund_info.get('url_cmf')}")
        return fund_info
    else:
        print(f"\n❌ NO SE ENCONTRÓ FONDO CON RUT {rut}")
        return None

def test_extraccion_pdf_links(rut: str):
    """Test 3: Extraer links de PDFs de la página CMF"""
    print("\n" + "="*80)
    print(f"TEST 3: EXTRACCIÓN DE LINKS DE PDFs PARA RUT: {rut}")
    print("="*80)

    processor = FondosMutuosProcessor()

    # Obtener página CMF
    page_url = processor._get_cmf_page_with_params(rut)

    if not page_url:
        print(f"\n❌ NO SE PUDO OBTENER URL DE PÁGINA CMF")
        return None, None

    print(f"\n✅ URL de página CMF: {page_url}")

    # Extraer links de PDFs
    folletos, rut_admin = processor._extract_pdf_links_from_cmf_page(page_url)

    if folletos:
        print(f"\n✅ FOLLETOS ENCONTRADOS: {len(folletos)}")
        print(f"   RUT Admin: {rut_admin}")
        for i, folleto in enumerate(folletos, 1):
            print(f"   {i}. Serie: {folleto.get('serie')}, RutAdmin: {folleto.get('rutAdmin')}")
        return folletos, rut_admin
    else:
        print(f"\n❌ NO SE ENCONTRARON FOLLETOS")
        return None, None

def test_descarga_pdf(rut: str, run_completo: str = None):
    """Test 4: Descargar PDF"""
    print("\n" + "="*80)
    print(f"TEST 4: DESCARGA DE PDF PARA RUT: {rut}")
    print("="*80)

    processor = FondosMutuosProcessor()

    pdf_path = processor._download_pdf_from_cmf_improved(rut, run_completo)

    if pdf_path:
        print(f"\n✅ PDF DESCARGADO EXITOSAMENTE:")
        print(f"   Path: {pdf_path}")

        # Verificar que el archivo existe
        import os
        if os.path.exists(pdf_path):
            size_kb = os.path.getsize(pdf_path) / 1024
            print(f"   Tamaño: {size_kb:.2f} KB")
            return pdf_path
        else:
            print(f"\n⚠️ ADVERTENCIA: Path retornado pero archivo no existe")
            return None
    else:
        print(f"\n❌ NO SE PUDO DESCARGAR PDF")
        return None

def test_extraccion_contenido_pdf(pdf_path: str):
    """Test 5: Extraer contenido del PDF"""
    print("\n" + "="*80)
    print(f"TEST 5: EXTRACCIÓN DE CONTENIDO DEL PDF")
    print("="*80)

    processor = FondosMutuosProcessor()

    data = processor._extract_data_from_pdf(pdf_path)

    if data:
        print(f"\n✅ DATOS EXTRAÍDOS DEL PDF:")
        print(f"   Campos encontrados: {len(data)}")
        for key, value in list(data.items())[:10]:  # Primeros 10 campos
            print(f"   - {key}: {str(value)[:100]}...")
        return data
    else:
        print(f"\n❌ NO SE PUDO EXTRAER CONTENIDO DEL PDF")
        return None

def main():
    """Ejecutar todos los tests en secuencia"""
    print("\n")
    print("╔" + "="*78 + "╗")
    print("║" + " "*20 + "TEST DE SCRAPING CMF CHILE" + " "*32 + "║")
    print("╚" + "="*78 + "╝")

    # Test 1: Buscar por nombre
    fund_info = test_busqueda_por_nombre()

    if not fund_info:
        print("\n⚠️ PRUEBA ABORTADA: No se pudo encontrar el fondo inicial")
        return

    # Extraer RUT si está disponible
    rut = fund_info.get('administrator_id')

    if rut:
        # Test 2: Buscar por RUT
        fund_by_rut = test_busqueda_por_rut(rut)

        # Test 3: Extraer links de PDFs
        folletos, rut_admin = test_extraccion_pdf_links(rut)

        # Test 4: Descargar PDF
        run_completo = fund_by_rut.get('rut_completo') if fund_by_rut else None
        pdf_path = test_descarga_pdf(rut, run_completo)

        # Test 5: Extraer contenido del PDF
        if pdf_path:
            test_extraccion_contenido_pdf(pdf_path)

    print("\n" + "="*80)
    print("TESTS COMPLETADOS")
    print("="*80)
    print("\nRevisa 'test_scraping_debug.log' para detalles completos\n")

if __name__ == "__main__":
    main()
