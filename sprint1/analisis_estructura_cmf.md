# Análisis de Estructura del Sitio CMF Chile

## Objetivo
Encontrar la forma correcta de descargar PDFs de folletos informativos de fondos mutuos desde CMF Chile.

## URLs Identificadas

### 1. Página de Estadísticas (✅ FUNCIONA)
```
https://www.cmfchile.cl/institucional/estadisticas/fm.bpr_menu.php
```
- **Status**: 200 OK
- **Contenido**: JavaScript arrays con lista completa de fondos
- **Datos extraídos**:
  - RUT fondo (ej: "8947-8")
  - RUT administradora (ej: "96767630")
  - Nombre fondo
- **Total fondos**: 1,304 fondos

### 2. Listado de Fondos (✅ FUNCIONA)
```
https://www.cmfchile.cl/institucional/mercados/consulta.php?mercado=V&Estado=VI&entidad=RGFMU
```
- **Status**: 200 OK
- **Contenido**: HTML con lista de fondos y enlaces a páginas individuales
- **Formato de enlace**:
```
entidad.php?auth=&send=&mercado=V&rut=8638&grupo=&tipoentidad=RGFMU&vig=VI&row=AAAw+cAAhAABPt6AAA&control=svs&pestania=1
```

### 3. Página Individual de Fondo (✅ FUNCIONA)
```
https://www.cmfchile.cl/institucional/mercados/entidad.php?mercado=V&rut=8638&grupo=&tipoentidad=RGFMU&row=AAAw+cAAhAABPt6AAA&vig=VI&control=svs&pestania=68
```
- **Status**: 200 OK cuando se incluyen TODOS los parámetros
- **Parámetros críticos**:
  - `mercado=V` (Mercado de Valores)
  - `rut=8638` (RUT del fondo SIN dígito verificador)
  - `tipoentidad=RGFMU` (Registro General de Fondos Mutuos)
  - `row=AAAw+cAAhAABPt6AAA` ⚠️ **ID único por fondo (CRÍTICO)**
  - `vig=VI` (Vigente)
  - `control=svs`
  - `pestania=68` (Pestaña "Folleto Informativo")

### 4. Endpoint de Descarga PDF (❌ OBSOLETO)
```
https://www.cmfchile.cl/603/ver_folleto_fm.php
```
- **Status**: 404 Not Found
- **Problema**: URL antigua, ya no se usa

## Flujo de Navegación Descubierto

```
1. Listado de fondos (consulta.php)
   ↓
2. Extraer parámetro "row" único por fondo
   ↓
3. Acceder a página individual con pestania=68
   ↓
4. Página muestra tabs: "Folletos Informativos Vigentes"
   ↓
5. JavaScript/AJAX carga los PDFs disponibles
```

## Hallazgos Clave

### ✅ Parámetro "row" es CRÍTICO
- Cada fondo tiene un ID único tipo: `AAAw+cAAhAABPt6AAA`
- **NO** se puede construir, debe extraerse del listado
- Es un ROWID de base de datos Oracle

### ✅ Ejemplo Funcional
**Fondo**: "BCI CARTERA DINÁMICA CONSERVADORA"
- RUT: 8638-K
- URL: `entidad.php?mercado=V&rut=8638&row=AAAw+cAAhAABPt6AAA&tipoentidad=RGFMU&vig=VI&control=svs&pestania=68`

## Estrategia Recomendada con Selenium

### Opción 1: Scraping con Selenium (COMPLETO)
1. Navegar a `consulta.php` para obtener listado
2. Para cada fondo, extraer:
   - RUT
   - Parámetro `row`
3. Construir URL con `pestania=68`
4. Usar Selenium para:
   - Cargar la página
   - Esperar carga de JavaScript/AJAX
   - Extraer enlaces a PDFs
   - Descargar PDFs

### Opción 2: Scraping Híbrido (MÁS RÁPIDO)
1. Usar requests/BeautifulSoup para extraer lista + parámetros `row`
2. Cachear mapeo: `{rut_fondo: row_id}`
3. Solo usar Selenium cuando necesitemos el PDF:
   - Navegar a URL con `pestania=68`
   - Extraer y descargar PDF

## Próximos Pasos

1. ✅ Implementar extracción de parámetro `row` desde `consulta.php`
2. ⏳ Configurar Selenium con Chrome headless
3. ⏳ Implementar navegación a pestaña de folletos
4. ⏳ Extraer y descargar PDFs
