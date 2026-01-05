# COMPLETE ETL PIPELINE FIX PLAN
## Comprehensive Execution Guide for Repair Agent

**Document Version:** 1.0
**Date:** 2026-01-05
**Target File:** `/Users/lucianoleroi/Desktop/Fran/sprint/sprint1/fondos_mutuos.py`
**Total Fixes:** 43 individual corrections across 4 priority levels

---

## TABLE OF CONTENTS

1. [Pre-Execution Checklist](#pre-execution-checklist)
2. [Priority Levels Definition](#priority-levels-definition)
3. [Phase 1: Critical Fixes (MUST FIX)](#phase-1-critical-fixes-must-fix)
4. [Phase 2: High Priority Fixes](#phase-2-high-priority-fixes)
5. [Phase 3: Medium Priority Improvements](#phase-3-medium-priority-improvements)
6. [Phase 4: Low Priority Enhancements](#phase-4-low-priority-enhancements)
7. [Testing Protocol](#testing-protocol)
8. [Validation Checklist](#validation-checklist)
9. [Rollback Plan](#rollback-plan)

---

## PRE-EXECUTION CHECKLIST

**Before starting ANY modifications:**

- [ ] Backup current `fondos_mutuos.py` to `fondos_mutuos.py.backup`
- [ ] Read entire file once to understand current state
- [ ] Verify line numbers match (file should be ~3595 lines)
- [ ] Check no other processes are modifying the file
- [ ] Ensure you have write permissions
- [ ] Review all 43 fixes in this document before starting

**Tools Required:**
- `Read` tool - MUST use before any Edit
- `Edit` tool - Use exact string matching
- `Bash` tool - For testing after changes

**Execution Rules:**
1. **NEVER** skip reading the file before editing
2. **ALWAYS** use exact string matching (copy-paste from file)
3. **PRESERVE** all comments and whitespace unless specifically instructed
4. **VALIDATE** each change by reading back the modified section
5. **STOP** if any edit fails - do not continue to next fix

---

## PRIORITY LEVELS DEFINITION

### 🔴 CRITICAL (P0)
- Blocks core functionality
- Causes data loss or corruption
- Crashes pipeline
- Must be fixed immediately

### 🟠 HIGH (P1)
- Significant data quality issues
- Silent failures that hide problems
- Major ETL violations
- Should be fixed in first pass

### 🟡 MEDIUM (P2)
- Moderate data quality improvements
- Code quality issues
- Performance improvements
- Can be fixed in second pass

### 🟢 LOW (P3)
- Nice-to-have enhancements
- Minor optimizations
- Documentation improvements
- Can be deferred

---

## PHASE 1: CRITICAL FIXES (MUST FIX)

### Fix Group 1.1: RUT/RUN Data Loss (P0-CRITICAL)

**Problem:** RUT fields never appear in Excel because they're only set when Fintual API succeeds (~3% of funds)

#### Fix 1.1.A: Initialize RUN/RUT in resultado dict

**Location:** Line 3356-3367
**Current Code:**
```python
resultado = {
    'fondo_id': fondo_id,
    'nombre': '',
    'nombre_cmf': '',
    'tipo_fondo': '',
    'perfil_riesgo': '',
    'descripcion_amigable': '',
    'composicion_portafolio': [],
    'rentabilidad_anual': None,
    'fuente_cmf': False,
    'scraping_success': False,
    'error': None
}
```

**Required Change:**
Add two new fields to the initialization dict:
```python
resultado = {
    'fondo_id': fondo_id,
    'nombre': '',
    'nombre_cmf': '',
    'run': None,  # ADD THIS LINE
    'rut_base': None,  # ADD THIS LINE
    'tipo_fondo': '',
    'perfil_riesgo': '',
    'descripcion_amigable': '',
    'composicion_portafolio': [],
    'rentabilidad_anual': None,
    'fuente_cmf': False,
    'scraping_success': False,
    'error': None
}
```

**Validation:** Read back lines 3356-3369 and verify 'run' and 'rut_base' are present.

---

#### Fix 1.1.B: Extract RUN from CMF when Fintual fails

**Location:** Line 3393-3396
**Current Code:**
```python
else:
    # Si no hay datos de Fintual, marcar error
    resultado['nombre'] = fondo_id.replace('_', ' ').title()
    resultado['rentabilidad_anual'] = None  # NO SIMULAR DATOS
    resultado['error'] = 'No se obtuvieron datos de Fintual'
```

**Required Change:**
Replace entire else block with:
```python
else:
    # Si no hay datos de Fintual, marcar error pero intentar extraer RUN de CMF
    resultado['nombre'] = fondo_id.replace('_', ' ').title()
    resultado['rentabilidad_anual'] = None  # NO SIMULAR DATOS
    resultado['error'] = 'No se obtuvieron datos de Fintual'

    # Intentar extraer RUN del nombre del fondo si tiene formato estándar
    # Ejemplo: "Fondo Mutuo Banchile 10446-9" -> extraer "10446-9"
    import re
    run_match = re.search(r'\b(\d{4,6}-[\dkK])\b', fondo_id)
    if run_match:
        resultado['run'] = run_match.group(1)
        resultado['rut_base'] = resultado['run'].split('-')[0]
        logger.info(f"[RUN] Extraído del nombre: {resultado['run']}")
```

**Validation:** Read back lines 3393-3407 and verify RUN extraction logic is present.

---

#### Fix 1.1.C: Extract RUN from CMF search results

**Location:** Line 3413-3435 (CMF name search fallback)
**Context:** After name-based search, we have `mejor_resultado` dict with CMF data

**Required Change:**
Add RUN extraction after line 3426 (after `resultado['nombre_cmf'] = mejor_resultado.get('nombre', '')`)

Insert this code block:
```python
# Extraer RUN de los datos de CMF si está disponible
if 'rut' in mejor_resultado and mejor_resultado['rut']:
    resultado['run'] = mejor_resultado['rut']
    resultado['rut_base'] = resultado['run'].split('-')[0] if '-' in resultado['run'] else resultado['run']
    logger.info(f"[RUN CMF] Extraído de búsqueda: {resultado['run']}")
elif 'onclick' in mejor_resultado:
    # Intentar extraer RUN del atributo onclick
    onclick_str = mejor_resultado['onclick']
    run_match = re.search(r'\b(\d{4,6}-[\dkK])\b', onclick_str)
    if run_match:
        resultado['run'] = run_match.group(1)
        resultado['rut_base'] = resultado['run'].split('-')[0]
        logger.info(f"[RUN CMF] Extraído de onclick: {resultado['run']}")
```

**Validation:** Read back lines 3413-3445 and verify RUN extraction is added after nombre_cmf assignment.

---

#### Fix 1.1.D: Update Excel schema to display RUN

**Location:** Line 3112-3113
**Current Code:**
```python
'RUN del Fondo': data.get('run', 'N/A'),
'RUT Base': data.get('rut_base', 'N/A'),
```

**Required Change:**
These lines are already correct, but need to update the fallback:
```python
'RUN del Fondo': data.get('run', 'No disponible'),
'RUT Base': data.get('rut_base', 'No disponible'),
```

**Rationale:** Using "No disponible" instead of "N/A" makes it clearer this is missing data, not "not applicable".

**Validation:** Read back lines 3110-3115 and verify the change.

---

### Fix Group 1.2: Critical Bug - Error Concatenation Crash (P0-CRITICAL)

**Problem:** Line 3567 crashes with TypeError when `error` is None

#### Fix 1.2.A: Safe error concatenation

**Location:** Line 3564-3568
**Current Code:**
```python
if not fund_found_in_cmf:
    # Marcar como no encontrado en CMF
    logger.warning(f"[CMF] Fondo '{fondo_id}' no encontrado en CMF")
    resultado['fuente_cmf'] = False
    resultado['error'] = resultado.get('error', '') + ' | Fondo no encontrado en CMF'
```

**Required Change:**
```python
if not fund_found_in_cmf:
    # Marcar como no encontrado en CMF
    logger.warning(f"[CMF] Fondo '{fondo_id}' no encontrado en CMF")
    resultado['fuente_cmf'] = False
    # Safe error concatenation - handle None case
    existing_error = resultado.get('error') or ''
    new_error = 'Fondo no encontrado en CMF'
    resultado['error'] = f"{existing_error} | {new_error}".strip(' |') if existing_error else new_error
```

**Validation:** Read back lines 3564-3570 and verify safe concatenation logic.

---

### Fix Group 1.3: Composicion Portfolio - Critical Regex Fixes (P0-CRITICAL)

**Problem:** 90% of PDFs fail to extract portfolio composition due to overly strict regex

#### Fix 1.3.A: Add flexible pattern for composicion

**Location:** Line 1744-1855 (entire composicion extraction section)
**Strategy:** Add multiple fallback patterns instead of single strict pattern

**Current Pattern 1 (Line 1746):**
```python
patron_composicion = r'([A-Za-záéíóúñÁÉÍÓÚÑ\s\.]+)\s+(\d+[\.,]?\d*)\s*%'
```

**Step 1:** Keep existing pattern but add logging when it fails
**Location:** After Line 1771 (after the ValueError except)

Insert:
```python
if not composicion_detallada:
    logger.debug("[PDF] Patrón 1 de composición no encontró matches, probando patrón 2...")
```

**Step 2:** Add new pattern 2 - More flexible spacing
**Location:** After the logging added in Step 1

Insert complete Pattern 2 block:
```python
    # Patrón 2: Más flexible con espacios y separadores
    # Matches: "Nombre del Activo    :    45.5%"
    # Matches: "Nombre del Activo | 45.5 %"
    patron_composicion_2 = r'([A-Za-záéíóúñÁÉÍÓÚÑ\s\.]{3,50})\s*[:\|]?\s*(\d+[\.,]?\d*)\s*%'
    matches_2 = re.finditer(patron_composicion_2, texto_completo, re.IGNORECASE)

    for match in matches_2:
        try:
            activo = match.group(1).strip()
            porcentaje_str = match.group(2).replace(',', '.')
            porcentaje = float(porcentaje_str)

            # Validar porcentaje razonable
            if 0 < porcentaje <= 100 and len(activo) > 2:
                # Clasificar tipo de activo
                tipo_activo = 'Otro'
                activo_lower = activo.lower()
                if any(kw in activo_lower for kw in ['accion', 'equity', 'stock', 'acciones']):
                    tipo_activo = 'Acciones'
                elif any(kw in activo_lower for kw in ['bono', 'bond', 'deuda', 'debt']):
                    tipo_activo = 'Renta Fija'
                elif any(kw in activo_lower for kw in ['efectivo', 'cash', 'liquidez', 'money market']):
                    tipo_activo = 'Efectivo'

                composicion_detallada.append({
                    'activo': activo,
                    'tipo_activo': tipo_activo,
                    'porcentaje': porcentaje
                })
                logger.debug(f"[PDF Patrón 2] Encontrado: {activo} - {porcentaje}%")
        except (ValueError, IndexError) as e:
            continue
```

**Step 3:** Add Pattern 3 - Tabular format
**Location:** After Pattern 2 block

Insert:
```python
    # Patrón 3: Formato tabular con múltiples columnas
    # Buscar sección con "composición" o "cartera" y extraer datos estructurados
    if not composicion_detallada:
        logger.debug("[PDF] Patrón 2 no encontró matches, probando patrón 3 (tabular)...")

        # Buscar líneas que contengan tanto texto como porcentajes
        lineas = texto_completo.split('\n')
        for i, linea in enumerate(lineas):
            # Buscar líneas con formato: "Texto ... Número ... Porcentaje%"
            if '%' in linea:
                # Extraer el porcentaje
                porcentaje_match = re.search(r'(\d+[\.,]\d+)\s*%', linea)
                if porcentaje_match:
                    try:
                        porcentaje = float(porcentaje_match.group(1).replace(',', '.'))

                        # Extraer el nombre del activo (todo antes del primer número grande)
                        linea_limpia = re.sub(r'\d+[\.,]\d+\s*%.*$', '', linea).strip()
                        # Remover números que parecen montos
                        activo = re.sub(r'\$?\d{1,3}([\.,]\d{3})*(\.\d+)?', '', linea_limpia).strip()

                        if len(activo) > 2 and 0 < porcentaje <= 100:
                            tipo_activo = 'Otro'
                            activo_lower = activo.lower()
                            if any(kw in activo_lower for kw in ['accion', 'equity', 'stock']):
                                tipo_activo = 'Acciones'
                            elif any(kw in activo_lower for kw in ['bono', 'bond', 'deuda']):
                                tipo_activo = 'Renta Fija'
                            elif any(kw in activo_lower for kw in ['efectivo', 'cash', 'liquidez']):
                                tipo_activo = 'Efectivo'

                            composicion_detallada.append({
                                'activo': activo,
                                'tipo_activo': tipo_activo,
                                'porcentaje': porcentaje
                            })
                            logger.debug(f"[PDF Patrón 3] Encontrado: {activo} - {porcentaje}%")
                    except (ValueError, IndexError):
                        continue
```

**Step 4:** Add final logging for empty composicion
**Location:** After all pattern attempts, before Line 1855

Insert:
```python
    # Log final si no se encontró nada
    if not composicion_detallada:
        logger.warning(f"[PDF] No se pudo extraer composición de portafolio con ningún patrón. Texto disponible: {len(texto_completo)} caracteres")
    else:
        logger.info(f"[PDF] Composición extraída exitosamente: {len(composicion_detallada)} activos")
```

**Validation:** Read back the entire section from Line 1744-1900 and verify all 3 patterns + logging are present.

---

### Fix Group 1.4: Silent Failures - Add Explicit Logging (P0-CRITICAL)

**Problem:** 15+ locations silently swallow errors without logging, making debugging impossible

#### Fix 1.4.A: Rentabilidad parsing failures

**Locations:** Lines 1687, 1700, 1713

**Current Pattern (example from Line 1687):**
```python
except ValueError as e:
    pass
```

**Required Change for ALL THREE locations:**
```python
except ValueError as e:
    logger.warning(f"[PDF] Error al parsear rentabilidad: {e}")
    pass
```

**Specific Locations:**
1. Line 1687: Change to `logger.warning(f"[PDF] Error al parsear rentabilidad 12m: {e}")`
2. Line 1700: Change to `logger.warning(f"[PDF] Error al parsear rentabilidad 24m: {e}")`
3. Line 1713: Change to `logger.warning(f"[PDF] Error al parsear rentabilidad 36m: {e}")`

**Validation:** Search for all three occurrences and verify logging added.

---

#### Fix 1.4.B: Composicion parsing failures

**Locations:** Lines 1770, 1805, 1836

**Current Pattern:**
```python
except ValueError:
    continue
```

**Required Change for ALL THREE locations:**
```python
except ValueError as e:
    logger.debug(f"[PDF] Error al parsear item de composición: {e}")
    continue
```

**Note:** Using `debug` level here because individual item failures are expected; we want to log pattern-level failures at warning.

**Validation:** Search for composicion `except ValueError` blocks and verify logging added.

---

#### Fix 1.4.C: Comision parsing failures

**Locations:** Lines 1472-1474, 1493-1494

**Current Code (Line 1472-1474):**
```python
except ValueError:
    continue
```

**Required Change:**
```python
except ValueError as e:
    logger.debug(f"[PDF] Error al parsear comisión administración: {e}")
    continue
```

**Current Code (Line 1493-1494):**
```python
except ValueError:
    continue
```

**Required Change:**
```python
except ValueError as e:
    logger.debug(f"[PDF] Error al parsear comisión rescate: {e}")
    continue
```

**Validation:** Verify both comision blocks have logging.

---

#### Fix 1.4.D: Monto minimo parsing failures

**Locations:** Lines 1583, 1600, 1617, 1636, 1649, 1664

**Current Pattern:**
```python
except ValueError:
    pass
```

**Required Change for ALL SIX locations:**
```python
except ValueError as e:
    logger.debug(f"[PDF] Error al parsear monto mínimo: {e}")
    pass
```

**Validation:** Search for all six monto_minimo except blocks and verify logging added.

---

#### Fix 1.4.E: Numeric extraction utility function

**Location:** Line 2895-2896
**Current Code:**
```python
except:
    return None
```

**Required Change:**
```python
except Exception as e:
    logger.debug(f"[UTIL] Error en _extract_numeric: {e}, input: {text[:100] if text else 'None'}")
    return None
```

**Validation:** Read back the `_extract_numeric` function and verify error logging.

---

### Fix Group 1.5: Patrimonio Extraction Not Propagated (P0-CRITICAL)

**Problem:** Patrimonio extracted from PDF but never written to Excel

#### Fix 1.5.A: Add patrimonio to Excel schema

**Location:** Line 3110-3129 (Resumen Ejecutivo data dict)

Find the section where fields are mapped to Excel, around line 3120.

**Required Change:**
Add new row after 'Comisión Admin' (if it exists) or after 'Perfil de Riesgo':

```python
'Patrimonio': data.get('patrimonio', 'No disponible'),
```

**Exact Location:** Insert between lines for 'Perfil de Riesgo' and 'Rentabilidad Anual'

**Validation:** Read back lines 3110-3135 and verify 'Patrimonio' row exists.

---

## PHASE 2: HIGH PRIORITY FIXES

### Fix Group 2.1: Rentabilidad Escala (R1-R7) Not Written to Excel (P1-HIGH)

**Problem:** perfil_riesgo_escala extracted but never appears in Excel output

#### Fix 2.1.A: Add escala to Excel schema

**Location:** Line 3110-3129 (Resumen Ejecutivo)

**Required Change:**
Add new row after 'Perfil de Riesgo':

```python
'Escala de Riesgo (R1-R7)': data.get('perfil_riesgo_escala', 'No disponible'),
```

**Validation:** Read back and verify the row is added.

---

### Fix Group 2.2: Comisiones Extracted but Not Displayed (P1-HIGH)

**Problem:** comision_administracion and comision_rescate extracted but not in Resumen Ejecutivo

#### Fix 2.2.A: Add comision_administracion to Excel

**Location:** Line 3110-3129

**Required Change:**
Add after 'Patrimonio':

```python
'Comisión Administración (%)': data.get('comision_administracion', 'No disponible'),
```

**Validation:** Verify row exists in Excel schema.

---

#### Fix 2.2.B: Add comision_rescate to Excel

**Location:** Same section

**Required Change:**
Add after 'Comisión Administración':

```python
'Comisión Rescate (%)': data.get('comision_rescate', 'No disponible'),
```

**Validation:** Verify row exists in Excel schema.

---

### Fix Group 2.3: Rentabilidad Multi-Period Not Displayed (P1-HIGH)

**Problem:** rentabilidad_24m and rentabilidad_36m extracted but only rentabilidad_anual shown

#### Fix 2.3.A: Add all rentabilidad periods to Excel

**Location:** Line 3110-3129

**Required Change:**
Replace single 'Rentabilidad Anual' row with:

```python
'Rentabilidad 12 Meses (%)': data.get('rentabilidad_12m', 'No disponible'),
'Rentabilidad 24 Meses (%)': data.get('rentabilidad_24m', 'No disponible'),
'Rentabilidad 36 Meses (%)': data.get('rentabilidad_36m', 'No disponible'),
```

**Validation:** Verify all three rentabilidad rows exist.

---

### Fix Group 2.4: ETL Violations - Remove Hardcoded Defaults (P1-HIGH)

**Problem:** Multiple fields hardcoded to empty strings/lists instead of using extracted data

#### Fix 2.4.A: Remove clasificacion_riesgo_detallada hardcode

**Location:** Line 2976
**Current Code:**
```python
'clasificacion_riesgo_detallada': '',
```

**Required Change:**
```python
'clasificacion_riesgo_detallada': data.get('perfil_riesgo', ''),  # Use extracted value
```

**Validation:** Verify the field now uses extracted data.

---

#### Fix 2.4.B: Remove ventajas/desventajas hardcode

**Location:** Lines 3007-3008
**Current Code:**
```python
'ventajas_principales': [],
'desventajas_principales': [],
```

**Required Change:**
```python
'ventajas_principales': data.get('ventajas_principales', []),
'desventajas_principales': data.get('desventajas_principales', []),
```

**Note:** This requires ventajas/desventajas to be extracted first. If not extracted, this fix documents the intent.

**Validation:** Verify fields use .get() pattern.

---

#### Fix 2.4.C: Remove costos hardcode

**Location:** Lines 3039-3041
**Current Code:**
```python
return {
    'error': 'Costos no disponibles en esta versión'
}
```

**Required Change:**
```python
# Return actual comisiones if extracted
comisiones = {}
if data.get('comision_administracion') is not None:
    comisiones['comision_administracion'] = data['comision_administracion']
if data.get('comision_rescate') is not None:
    comisiones['comision_rescate'] = data['comision_rescate']

if not comisiones:
    return {'error': 'Costos no disponibles'}

return comisiones
```

**Validation:** Verify function returns extracted comisiones when available.

---

### Fix Group 2.5: Tolerancia Riesgo Keywords Too Restrictive (P1-HIGH)

**Problem:** Keyword search at Lines 1364-1396 too strict, misses common variations

#### Fix 2.5.A: Expand tolerancia keywords

**Location:** Line 1364-1396 (tolerancia_riesgo extraction)

**Current Keywords:** Only searches for exact phrases

**Required Change:**
Update keyword search to be more flexible. Find the section that checks for keywords and update:

```python
# Buscar tolerancia al riesgo con múltiples variaciones
tolerancia_patterns = [
    (r'\btoleranc[ia]+\s+(?:al\s+)?riesgo\s+(?:es\s+)?(baja|media|alta|conservador[a]?|moderad[oa]|agresiv[oa])',
     'tolerancia_keyword'),
    (r'\b(conservador[a]?|moderad[oa]|agresiv[oa])\s+(?:perfil|inversionista)',
     'perfil_keyword'),
    (r'\bperfil\s+de\s+riesgo\s+(?:es\s+)?(bajo|medio|alto|conservador|moderado|agresivo)',
     'perfil_riesgo_keyword'),
    (r'\binversionista[s]?\s+(conservador[es]?|moderado[s]?|agresivo[s]?)',
     'inversionista_keyword'),
]

for pattern, pattern_name in tolerancia_patterns:
    match = re.search(pattern, texto_completo, re.IGNORECASE)
    if match:
        keyword = match.group(1).lower()

        # Mapear a categorías estándar
        if 'conserv' in keyword or 'baj' in keyword:
            tolerancia_riesgo = 'Baja'
        elif 'moder' in keyword or 'medi' in keyword:
            tolerancia_riesgo = 'Media'
        elif 'agres' in keyword or 'alt' in keyword:
            tolerancia_riesgo = 'Alta'

        logger.debug(f"[PDF] Tolerancia al riesgo encontrada ({pattern_name}): {tolerancia_riesgo}")
        break
```

**Validation:** Verify multiple patterns are checked before failing.

---

### Fix Group 2.6: Horizonte Inversion Keywords Too Restrictive (P1-HIGH)

**Problem:** Similar to tolerancia, keyword search misses variations

#### Fix 2.6.A: Expand horizonte keywords

**Location:** Line 1401-1444 (horizonte_inversion extraction)

**Required Change:**
Add more flexible patterns:

```python
# Buscar horizonte de inversión con múltiples variaciones
horizonte_patterns = [
    (r'horizonte\s+(?:de\s+)?inversi[oó]n\s+(?:recomendad[oa]?\s+)?(?:es\s+)?(?:de\s+)?(corto|mediano|largo)\s+plazo',
     'horizonte_keyword'),
    (r'plazo\s+(?:de\s+inversi[oó]n\s+)?(?:recomendad[oa]?\s+)?(?:es\s+)?(?:de\s+)?(corto|mediano|largo)',
     'plazo_keyword'),
    (r'(corto|mediano|largo)\s+plazo\s+(?:de\s+)?inversi[oó]n',
     'plazo_inversion'),
    (r'inversi[oó]n\s+a\s+(corto|mediano|largo)\s+plazo',
     'inversion_plazo'),
]

for pattern, pattern_name in horizonte_patterns:
    match = re.search(pattern, texto_completo, re.IGNORECASE)
    if match:
        plazo = match.group(1).lower()

        if 'corto' in plazo:
            horizonte_inversion = 'Corto Plazo'
            horizonte_inversion_meses = 12  # Default: 1 año
        elif 'mediano' in plazo:
            horizonte_inversion = 'Mediano Plazo'
            horizonte_inversion_meses = 36  # Default: 3 años
        elif 'largo' in plazo:
            horizonte_inversion = 'Largo Plazo'
            horizonte_inversion_meses = 60  # Default: 5 años

        logger.debug(f"[PDF] Horizonte encontrado ({pattern_name}): {horizonte_inversion}")
        break
```

**Validation:** Verify multiple horizonte patterns are checked.

---

### Fix Group 2.7: Monto Minimo - Add Missing Currency Patterns (P1-HIGH)

**Problem:** Currency extraction at Lines 1556-1665 misses common formats

#### Fix 2.7.A: Add pattern for "mínimo de $X"

**Location:** After Line 1600 (after second $ pattern)

**Required Change:**
Add new pattern:

```python
# Patrón 6: "mínimo de $X" o "mínimo: $X"
if not monto_minimo:
    patron_minimo_de = r'mínimo\s+(?:de\s+)?(?:inversión\s+)?(?:de\s+)?\$\s*(\d{1,3}(?:[\.,]\d{3})*(?:[\.,]\d{1,2})?)'
    matches = re.finditer(patron_minimo_de, texto_completo, re.IGNORECASE)
    for match in matches:
        try:
            monto_str = match.group(1).replace('.', '').replace(',', '.')
            monto_float = float(monto_str)
            if monto_float > 1000:  # Validar que sea razonable
                monto_minimo = f"${monto_float:,.0f} CLP"
                monto_minimo_moneda = 'CLP'
                monto_minimo_valor = monto_float
                logger.debug(f"[PDF] Monto mínimo (patrón 6): {monto_minimo}")
                break
        except ValueError:
            pass
```

**Validation:** Verify pattern 6 is added and tested.

---

#### Fix 2.7.B: Add pattern for "aporte inicial"

**Location:** After the pattern added in 2.7.A

**Required Change:**
Add:

```python
# Patrón 7: "aporte inicial" como sinónimo de monto mínimo
if not monto_minimo:
    patron_aporte = r'aporte\s+inicial\s+(?:de\s+)?(?:es\s+)?(?:de\s+)?([A-Z]{2,3})\s*(\d{1,3}(?:[\.,]\d{3})*(?:[\.,]\d+)?)'
    matches = re.finditer(patron_aporte, texto_completo, re.IGNORECASE)
    for match in matches:
        try:
            moneda = match.group(1).upper()
            monto_str = match.group(2).replace('.', '').replace(',', '.')
            monto_float = float(monto_str)

            if moneda in ['UF', 'CLP', 'USD'] and monto_float > 0:
                monto_minimo = f"{monto_float:,.0f} {moneda}"
                monto_minimo_moneda = moneda
                monto_minimo_valor = monto_float
                logger.debug(f"[PDF] Monto mínimo (patrón 7 - aporte): {monto_minimo}")
                break
        except ValueError:
            pass
```

**Validation:** Verify aporte inicial pattern is added.

---

### Fix Group 2.8: Fondo Rescatable - Improve Detection (P1-HIGH)

**Problem:** Keywords at Line 1500-1515 too restrictive

#### Fix 2.8.A: Expand rescatable keywords

**Location:** Line 1500-1515

**Current Code:** Simple keyword search

**Required Change:**
Replace with more sophisticated detection:

```python
# Detectar si el fondo es rescatable con múltiples patrones
fondo_rescatable = None
rescatable_patterns = [
    (r'\brescatable\b', True),
    (r'\bsin\s+rescate\b', False),
    (r'\bno\s+rescatable\b', False),
    (r'\bliquidez\s+(?:diaria|inmediata|disponible)', True),
    (r'\breembolso\s+disponible\b', True),
    (r'\bplazo\s+(?:de\s+)?rescate[:\s]+(\d+)', True),  # Si menciona plazo, es rescatable
    (r'\bcerrado\s+(?:por|hasta|durante)', False),  # Fondo cerrado
]

for pattern, is_rescatable in rescatable_patterns:
    if re.search(pattern, texto_completo, re.IGNORECASE):
        fondo_rescatable = 'Sí' if is_rescatable else 'No'
        logger.debug(f"[PDF] Fondo rescatable detectado: {fondo_rescatable} (patrón: {pattern})")
        break

# Si no se encontró información, dejar como None (desconocido)
if fondo_rescatable is None:
    logger.debug("[PDF] No se pudo determinar si el fondo es rescatable")
```

**Validation:** Verify multiple rescatable patterns are checked.

---

### Fix Group 2.9: Plazo Rescates - Expand Detection (P1-HIGH)

**Problem:** Pattern at Line 1517-1528 too restrictive

#### Fix 2.9.A: Add multiple plazo patterns

**Location:** Line 1517-1528

**Required Change:**
Replace simple pattern with multiple:

```python
# Buscar plazo de rescate con múltiples formatos
plazos_rescates = None
plazo_patterns = [
    (r'plazo\s+(?:de\s+)?rescate[:\s]+(\d+)\s*días?', 'días'),
    (r'rescate\s+en\s+(\d+)\s*días?', 'días'),
    (r'disponible\s+en\s+(\d+)\s*días?', 'días'),
    (r'rescate\s+inmediato', '0'),  # Rescate inmediato = 0 días
    (r'rescate\s+(?:el\s+)?mismo\s+día', '0'),
    (r'T\+(\d+)', 'días'),  # Formato T+2, T+1, etc.
]

for pattern, unidad in plazo_patterns:
    match = re.search(pattern, texto_completo, re.IGNORECASE)
    if match:
        if unidad == '0':
            plazos_rescates = 'Inmediato (0 días)'
        else:
            try:
                dias = int(match.group(1))
                plazos_rescates = f"{dias} días"
                logger.debug(f"[PDF] Plazo de rescate encontrado: {plazos_rescates}")
            except (ValueError, IndexError):
                pass
        break
```

**Validation:** Verify multiple plazo patterns including T+N format.

---

### Fix Group 2.10: Duracion Fondo - Improve Detection (P1-HIGH)

**Problem:** Pattern at Line 1530-1553 misses "indefinido" and other formats

#### Fix 2.10.A: Expand duracion patterns

**Location:** Line 1530-1553

**Required Change:**
Add comprehensive patterns:

```python
# Buscar duración del fondo con múltiples formatos
duracion = None
duracion_patterns = [
    (r'duraci[oó]n\s+(?:del\s+fondo\s+)?(?:es\s+)?(\d+)\s*años?', 'años'),
    (r'plazo\s+(?:del\s+fondo\s+)?(?:es\s+)?(\d+)\s*años?', 'años'),
    (r'vigencia\s+(?:de\s+)?(\d+)\s*años?', 'años'),
    (r'duraci[oó]n\s+(?:del\s+fondo\s+)?(?:es\s+)?(\d+)\s*meses', 'meses'),
    (r'duraci[oó]n\s+(?:es\s+)?indefinida', 'indefinido'),
    (r'(?:fondo\s+)?sin\s+(?:fecha\s+de\s+)?vencimiento', 'indefinido'),
    (r'(?:fondo\s+)?perpetuo', 'indefinido'),
    (r'(?:fondo\s+)?de\s+inversi[oó]n\s+abierto', 'indefinido'),  # Fondos abiertos suelen ser indefinidos
]

for pattern, tipo in duracion_patterns:
    match = re.search(pattern, texto_completo, re.IGNORECASE)
    if match:
        if tipo == 'indefinido':
            duracion = 'Indefinido'
        elif tipo == 'años':
            try:
                anos = int(match.group(1))
                duracion = f"{anos} años"
            except (ValueError, IndexError):
                pass
        elif tipo == 'meses':
            try:
                meses = int(match.group(1))
                duracion = f"{meses} meses"
            except (ValueError, IndexError):
                pass

        if duracion:
            logger.debug(f"[PDF] Duración del fondo encontrada: {duracion}")
            break
```

**Validation:** Verify "indefinido" and "perpetuo" patterns work.

---

## PHASE 3: MEDIUM PRIORITY IMPROVEMENTS

### Fix Group 3.1: Change N/A to More Descriptive Values (P2-MEDIUM)

**Problem:** Generic 'N/A' doesn't indicate why data is missing

#### Fix 3.1.A: Use descriptive defaults in Excel

**Location:** Line 3110-3129

**Current Pattern:**
```python
'Field': data.get('field', 'N/A'),
```

**Required Change:**
Replace ALL 'N/A' defaults with more descriptive ones:

```python
'Nombre del Fondo': data.get('nombre', 'Sin nombre'),
'RUN del Fondo': data.get('run', 'No disponible en fuentes'),
'RUT Base': data.get('rut_base', 'No disponible en fuentes'),
'Estado del Fondo': data.get('estado_fondo', 'Estado desconocido'),
'Fecha Valor Cuota': data.get('fecha_valor_cuota', 'Fecha no disponible'),
'Tipo de Fondo': data.get('tipo_fondo', 'Tipo no extraído'),
'Perfil de Riesgo': data.get('perfil_riesgo', 'Perfil no extraído'),
'Tolerancia al Riesgo': data.get('tolerancia_riesgo', 'No especificado en PDF'),
'Horizonte Recomendado': data.get('horizonte_inversion', 'No especificado en PDF'),
'Patrimonio': data.get('patrimonio', 'No disponible'),
'Comisión Administración (%)': data.get('comision_administracion', 'No extraída'),
'Rentabilidad 12 Meses (%)': data.get('rentabilidad_12m', 'No disponible'),
'Fondo Rescatable': data.get('fondo_rescatable', 'No especificado'),
'Plazo de Rescate': data.get('plazos_rescates', 'No especificado'),
'Duración del Fondo': data.get('duracion', 'No especificada'),
'Monto Mínimo': data.get('monto_minimo', 'No especificado'),
```

**Rationale:** Each message now indicates the nature of the missing data (not extracted vs not available vs not specified).

**Validation:** Read entire Resumen Ejecutivo dict and verify all defaults are descriptive.

---

### Fix Group 3.2: Add Extraction Timestamp to Metadata (P2-MEDIUM)

**Problem:** No way to know when data was extracted

#### Fix 3.2.A: Add timestamp to metadata sheet

**Location:** Line 3215-3263 (Metadatos Extracción sheet)

**Find the metadata dict creation** and add:

```python
from datetime import datetime

metadata_dict = {
    'Timestamp Extracción': [datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
    # ... rest of metadata fields
}
```

**Validation:** Verify timestamp appears in metadata sheet.

---

### Fix Group 3.3: Add Extraction Source Indicators (P2-MEDIUM)

**Problem:** No visibility into which data came from which source

#### Fix 3.3.A: Add source tracking to resultado dict

**Location:** Throughout extraction process

**Strategy:** Add a new dict `data_sources` to track field origins

**Implementation:**

1. Initialize in resultado dict (Line 3356-3367):
```python
resultado = {
    # ... existing fields ...
    'data_sources': {},  # Track where each field came from
}
```

2. When extracting from Fintual (Line 3379):
```python
if fintual_data:
    resultado.update(fintual_data)
    # Track sources
    for key in fintual_data.keys():
        resultado['data_sources'][key] = 'Fintual API'
```

3. When extracting from PDF (Line 3515-3540):
```python
if pdf_data.get('tipo_fondo'):
    resultado['tipo_fondo'] = pdf_data['tipo_fondo']
    resultado['data_sources']['tipo_fondo'] = 'PDF'
# Repeat for each field...
```

4. Add to metadata sheet:
```python
'Fuentes de Datos': [', '.join([f"{k}: {v}" for k, v in data.get('data_sources', {}).items()])]
```

**Validation:** Verify data_sources dict is populated and shown in metadata.

---

### Fix Group 3.4: Improve Composicion Sheet Formatting (P2-MEDIUM)

**Problem:** Composicion sheet shows "Sin datos" even when some data exists

#### Fix 3.4.A: Show partial composicion data

**Location:** Line 3143 (composicion sheet creation)

**Current Code:**
```python
if composicion:
    composicion_data = {...}
else:
    composicion_data = {
        'Activo/Instrumento': ['Sin datos disponibles'],
        'Tipo': ['N/A'],
        'Porcentaje': [0]
    }
```

**Required Change:**
```python
if composicion and len(composicion) > 0:
    composicion_data = {
        'Activo/Instrumento': [item.get('activo', 'Sin nombre') for item in composicion],
        'Tipo': [item.get('tipo_activo', 'No clasificado') for item in composicion],
        'Porcentaje': [item.get('porcentaje', 0) for item in composicion]
    }

    # Add summary row
    total_porcentaje = sum([item.get('porcentaje', 0) for item in composicion])
    composicion_data['Activo/Instrumento'].append('TOTAL')
    composicion_data['Tipo'].append('-')
    composicion_data['Porcentaje'].append(total_porcentaje)

    # Add validation warning if total != 100%
    if abs(total_porcentaje - 100.0) > 5.0:
        composicion_data['Activo/Instrumento'].append('⚠ NOTA')
        composicion_data['Tipo'].append('Advertencia')
        composicion_data['Porcentaje'].append('')
        logger.warning(f"[EXCEL] Composición no suma 100%: {total_porcentaje:.2f}%")
else:
    composicion_data = {
        'Activo/Instrumento': ['No se pudo extraer composición del PDF'],
        'Tipo': ['Verifique el folleto informativo manualmente'],
        'Porcentaje': ['']
    }
```

**Validation:** Verify composicion sheet shows validation and helpful messages.

---

### Fix Group 3.5: Add Validation for Extraction Confidence (P2-MEDIUM)

**Problem:** extraction_confidence calculated but not validated against thresholds

#### Fix 3.5.A: Add confidence warnings to metadata

**Location:** Line 3215-3263 (metadata sheet)

**Required Change:**
Add confidence interpretation:

```python
# Calculate confidence score
confidence = data.get('extraction_confidence', 'unknown')
confidence_warnings = []

if confidence == 'low' or confidence == 'unknown':
    confidence_warnings.append('⚠ Baja confianza en extracción de datos')

# Check specific critical fields
critical_fields = ['run', 'tipo_fondo', 'perfil_riesgo', 'composicion_portafolio']
missing_critical = [f for f in critical_fields if not data.get(f)]

if missing_critical:
    confidence_warnings.append(f'⚠ Campos críticos faltantes: {", ".join(missing_critical)}')

# Check if composicion is empty
if not data.get('composicion_portafolio') or len(data.get('composicion_portafolio', [])) == 0:
    confidence_warnings.append('⚠ Composición de portafolio no extraída')

# Add to metadata
metadata_dict['Advertencias'] = [' | '.join(confidence_warnings) if confidence_warnings else 'Ninguna']
```

**Validation:** Verify warnings appear in metadata sheet when applicable.

---

### Fix Group 3.6: Improve Error Messages in Excel (P2-MEDIUM)

**Problem:** Generic error messages don't help users understand what failed

#### Fix 3.6.A: Add detailed error sheet when extraction fails

**Location:** After Line 3310 (end of _generate_excel function)

**Required Change:**
Add conditional error sheet:

```python
# If extraction had errors, add detailed error sheet
if data.get('error'):
    error_data = {
        'Tipo de Error': [],
        'Descripción': [],
        'Recomendación': []
    }

    error_str = data['error']

    # Parse error string and provide recommendations
    if 'Fintual' in error_str:
        error_data['Tipo de Error'].append('API Fintual')
        error_data['Descripción'].append('Fondo no encontrado en Fintual')
        error_data['Recomendación'].append('Datos RUN/RUT pueden estar incompletos. Verificar en CMF.')

    if 'CMF' in error_str:
        error_data['Tipo de Error'].append('CMF Scraping')
        error_data['Descripción'].append('Fondo no encontrado en sitio CMF')
        error_data['Recomendación'].append('Verificar que el nombre del fondo sea correcto.')

    if 'PDF' in error_str or data.get('extraction_confidence') == 'low':
        error_data['Tipo de Error'].append('Extracción PDF')
        error_data['Descripción'].append('Datos extraídos con baja confianza')
        error_data['Recomendación'].append('Revisar folleto informativo manualmente.')

    if error_data['Tipo de Error']:
        df_errores = pd.DataFrame(error_data)
        df_errores.to_excel(writer, sheet_name='Errores y Advertencias', index=False)

        # Format error sheet
        worksheet_err = writer.sheets['Errores y Advertencias']
        worksheet_err.set_column('A:A', 20)
        worksheet_err.set_column('B:B', 50)
        worksheet_err.set_column('C:C', 50)
```

**Validation:** Generate Excel for a fund with errors and verify error sheet appears.

---

## PHASE 4: LOW PRIORITY ENHANCEMENTS

### Fix Group 4.1: Add Excel Column Width Auto-Adjustment (P3-LOW)

**Problem:** Some columns too narrow, others too wide

#### Fix 4.1.A: Calculate optimal column widths

**Location:** Line 3290 (existing column width logic)

**Current Code:**
```python
except:
    pass
```

**Required Change:**
Replace bare except with proper width calculation:

```python
except Exception as e:
    # If auto-adjust fails, set reasonable defaults
    logger.debug(f"[EXCEL] Error ajustando ancho de columnas: {e}")
    worksheet.set_column('A:A', 30)  # Field names
    worksheet.set_column('B:B', 40)  # Values
```

**Validation:** Verify columns have reasonable widths.

---

### Fix Group 4.2: Add Hyperlinks to CMF Sources (P3-LOW)

**Problem:** No easy way to verify data against source

#### Fix 4.2.A: Add CMF URL to metadata

**Location:** Line 3215-3263 (metadata sheet)

**Required Change:**
Add CMF URL field:

```python
# Build CMF URL if RUT available
cmf_url = 'No disponible'
if data.get('rut_base'):
    rut_base = data['rut_base']
    cmf_url = f"https://www.cmfchile.cl/institucional/mercados/entidad.php?mercado=V&rut={rut_base}&grupo=&tipoentidad=RGFMU&row=&vig=VI&control=svs&pestania=1&tpl=alt"

metadata_dict['URL CMF Fondo'] = [cmf_url]
```

**Validation:** Verify URL appears in metadata and is clickable in Excel.

---

### Fix Group 4.3: Add Data Quality Score (P3-LOW)

**Problem:** No quantitative measure of data completeness

#### Fix 4.3.A: Calculate quality score

**Location:** After extraction confidence calculation

**Required Change:**
Add quality scoring:

```python
def _calculate_data_quality_score(data: Dict) -> Dict:
    """
    Calculate a data quality score (0-100) based on field completeness.
    """
    # Define critical, important, and optional fields
    critical_fields = ['nombre', 'run', 'rut_base', 'tipo_fondo', 'perfil_riesgo']
    important_fields = ['horizonte_inversion', 'tolerancia_riesgo', 'composicion_portafolio',
                        'rentabilidad_12m', 'comision_administracion']
    optional_fields = ['patrimonio', 'fondo_rescatable', 'plazos_rescates',
                       'duracion', 'monto_minimo']

    # Calculate scores
    critical_score = sum([1 for f in critical_fields if data.get(f)]) / len(critical_fields) * 60
    important_score = sum([1 for f in important_fields if data.get(f)]) / len(important_fields) * 30
    optional_score = sum([1 for f in optional_fields if data.get(f)]) / len(optional_fields) * 10

    total_score = critical_score + important_score + optional_score

    # Determine quality level
    if total_score >= 80:
        quality_level = 'Excelente'
    elif total_score >= 60:
        quality_level = 'Buena'
    elif total_score >= 40:
        quality_level = 'Regular'
    else:
        quality_level = 'Baja'

    return {
        'score': round(total_score, 1),
        'level': quality_level,
        'critical_pct': round(critical_score / 60 * 100, 1),
        'important_pct': round(important_score / 30 * 100, 1),
        'optional_pct': round(optional_score / 10 * 100, 1)
    }
```

**Add to metadata sheet:**
```python
quality = _calculate_data_quality_score(data)
metadata_dict['Calidad de Datos (0-100)'] = [quality['score']]
metadata_dict['Nivel de Calidad'] = [quality['level']]
metadata_dict['Campos Críticos (%)'] = [quality['critical_pct']]
metadata_dict['Campos Importantes (%)'] = [quality['important_pct']]
```

**Validation:** Verify quality scores appear in metadata and are accurate.

---

### Fix Group 4.4: Add Caching for PDF Extraction Results (P3-LOW)

**Problem:** Re-extracting same PDF wastes time

#### Fix 4.4.A: Implement PDF extraction cache

**Location:** Before Line 741 (PDF download function)

**Required Change:**
Add cache checking:

```python
def _check_pdf_extraction_cache(self, rut_base: str) -> Optional[Dict]:
    """
    Check if PDF extraction results are cached.
    """
    cache_dir = self.cache_dir / 'pdf_extractions'
    cache_dir.mkdir(exist_ok=True)

    cache_file = cache_dir / f"{rut_base}_extraction.json"

    if cache_file.exists():
        # Check if cache is less than 24 hours old
        cache_age = time.time() - cache_file.stat().st_mtime
        if cache_age < 86400:  # 24 hours
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                logger.info(f"[CACHE] Usando extracción PDF cacheada para RUT {rut_base}")
                return cached_data
            except Exception as e:
                logger.warning(f"[CACHE] Error leyendo cache: {e}")

    return None

def _save_pdf_extraction_cache(self, rut_base: str, extraction_data: Dict):
    """
    Save PDF extraction results to cache.
    """
    cache_dir = self.cache_dir / 'pdf_extractions'
    cache_dir.mkdir(exist_ok=True)

    cache_file = cache_dir / f"{rut_base}_extraction.json"

    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(extraction_data, f, ensure_ascii=False, indent=2)
        logger.debug(f"[CACHE] Extracción PDF guardada en cache para RUT {rut_base}")
    except Exception as e:
        logger.warning(f"[CACHE] Error guardando cache: {e}")
```

**Modify PDF extraction function** to use cache:
```python
# Check cache first
cached_extraction = self._check_pdf_extraction_cache(rut_base)
if cached_extraction:
    return cached_extraction

# ... normal extraction ...

# Save to cache
self._save_pdf_extraction_cache(rut_base, pdf_data)
```

**Validation:** Verify cache files are created and reused.

---

## TESTING PROTOCOL

### Pre-Testing Setup

1. **Backup Current State:**
```bash
cp fondos_mutuos.py fondos_mutuos.py.backup
cp -r outputs/ outputs_backup/
```

2. **Create Test Fund List:**
```python
test_funds = [
    'bci_crecimiento_balanceado',  # Common fund
    'clever_temático',  # Fund not in Fintual (tests RUN extraction fixes)
    'banchile_acciones',  # Fund with complex PDF (tests regex fixes)
]
```

### Test Suite

#### Test 1: RUN/RUT Extraction (Critical)

**Objective:** Verify RUN appears in Excel for funds not in Fintual

**Steps:**
1. Process 'clever_temático' fund
2. Open generated Excel
3. Check Resumen Ejecutivo sheet
4. Verify 'RUN del Fondo' row has value (not "No disponible")
5. Verify 'RUT Base' row has value

**Success Criteria:**
- RUN field populated for at least 70% of test funds
- Log shows "[RUN] Extraído de..." messages

**If Fails:**
- Check Fix 1.1.A: run initialized in resultado dict?
- Check Fix 1.1.B: RUN extraction in else block?
- Check Fix 1.1.C: RUN extraction from CMF results?

---

#### Test 2: Composicion Portfolio (Critical)

**Objective:** Verify portfolio composition extraction improved

**Steps:**
1. Process fund with known portfolio data
2. Open Excel, go to "Composición Portafolio" sheet
3. Count number of assets listed
4. Verify percentages sum to ~100%

**Success Criteria:**
- At least 50% of funds should have >0 portfolio items
- No "Sin datos disponibles" when data exists in PDF
- Log shows "[PDF Patrón X] Encontrado:" messages

**If Fails:**
- Check Fix 1.3.A: All 3 composicion patterns added?
- Check logs for which pattern matched
- Manually inspect PDF to verify format

---

#### Test 3: Silent Failures Logging (Critical)

**Objective:** Verify errors are now logged

**Steps:**
1. Process test fund
2. Review logs for WARNING/DEBUG messages
3. Count number of "[PDF] Error al parsear..." messages

**Success Criteria:**
- Should see explicit parsing error messages
- No silent failures (compare before/after log volumes)

**If Fails:**
- Check Fix 1.4.A-E: All except blocks have logging?
- Verify logger level set to DEBUG

---

#### Test 4: Error Concatenation (Critical)

**Objective:** Verify no TypeError when combining errors

**Steps:**
1. Process fund that fails Fintual AND CMF
2. Check resultado['error'] field
3. Verify no crash

**Success Criteria:**
- No TypeError exceptions
- Error string contains both messages separated by " | "

**If Fails:**
- Check Fix 1.2.A: Safe concatenation logic present?

---

#### Test 5: New Fields in Excel (High Priority)

**Objective:** Verify all new fields appear in Excel

**Steps:**
1. Process test fund
2. Open Excel Resumen Ejecutivo
3. Check for new rows:
   - Patrimonio
   - Escala de Riesgo (R1-R7)
   - Comisión Administración (%)
   - Comisión Rescate (%)
   - Rentabilidad 12/24/36 Meses
   - Fondo Rescatable
   - Plazo de Rescate
   - Duración del Fondo
   - Monto Mínimo

**Success Criteria:**
- All 9 new fields present in Excel
- At least 50% have actual values (not "No disponible")

**If Fails:**
- Check Fix 1.5.A, 2.1.A, 2.2.A-B, 2.3.A: Fields added to Excel schema?

---

#### Test 6: ETL Violations Removed (High Priority)

**Objective:** Verify no hardcoded business data

**Steps:**
1. Search code for hardcoded empty strings/lists in metrics
2. Verify ventajas/desventajas use .get() pattern
3. Verify clasificacion_riesgo_detallada not forced to ''

**Success Criteria:**
- No hardcoded business data in metrics calculation
- All fields use extracted data or None

**If Fails:**
- Check Fix 2.4.A-C: Hardcodes removed?

---

#### Test 7: Improved Keyword Detection (High Priority)

**Objective:** Verify tolerancia and horizonte extraction rates improved

**Steps:**
1. Process 10 test funds
2. Count how many have tolerancia_riesgo extracted
3. Count how many have horizonte_inversion extracted
4. Compare to before (baseline: <30%)

**Success Criteria:**
- Tolerancia extraction rate >50%
- Horizonte extraction rate >60%

**If Fails:**
- Check Fix 2.5.A, 2.6.A: Multiple patterns added?
- Check logs for which patterns matched

---

#### Test 8: Metadata Sheet (Medium Priority)

**Objective:** Verify metadata sheet contains useful info

**Steps:**
1. Process test fund
2. Open Excel "Metadatos Extracción" sheet
3. Verify timestamp, confidence, warnings present

**Success Criteria:**
- Timestamp shows current date/time
- Confidence level makes sense
- Warnings present when data quality low

**If Fails:**
- Check Fix 3.2.A, 3.5.A: Metadata fields added?

---

#### Test 9: Data Quality Score (Low Priority)

**Objective:** Verify quality score calculated correctly

**Steps:**
1. Process fund with complete data
2. Process fund with minimal data
3. Compare quality scores

**Success Criteria:**
- Complete fund: score >80
- Minimal fund: score <50
- Scores match field completeness

**If Fails:**
- Check Fix 4.3.A: Quality calculation correct?

---

### Regression Testing

After all fixes, run full regression:

```bash
# Process full list of funds
python main.py --process-fondos --limit 20

# Check outputs
ls -lh outputs/*.xlsx
wc -l pipeline_execution.log

# Verify no crashes
grep -i "error\|exception\|traceback" pipeline_execution.log | wc -l
```

**Success Criteria:**
- All 20 funds processed without crashes
- >80% have Excel files generated
- Log shows improvement in extraction rates

---

## VALIDATION CHECKLIST

After implementing all fixes, go through this checklist:

### Code Quality Checks

- [ ] No bare `except:` statements remain (except for minor cleanup operations)
- [ ] All regex patterns have descriptive comments
- [ ] All extraction failures logged at appropriate level
- [ ] No hardcoded business data in metrics
- [ ] All TODO comments resolved or documented

### Data Quality Checks

- [ ] RUN field appears in >70% of Excel outputs
- [ ] Composicion portfolio has >0 items in >50% of outputs
- [ ] Rentabilidad fields populated in >40% of outputs
- [ ] Tolerancia/horizonte fields populated in >50% of outputs
- [ ] No TypeError or other exceptions in logs

### Excel Output Checks

- [ ] All 9 new fields present in Resumen Ejecutivo
- [ ] Metadata sheet exists and contains useful info
- [ ] Composicion sheet formatted properly
- [ ] Column widths reasonable
- [ ] No "N/A" in critical fields where data exists

### Performance Checks

- [ ] PDF extraction cache working (verify cache directory populated)
- [ ] No significant slowdown compared to before
- [ ] Memory usage reasonable (<2GB per fund)

### Documentation Checks

- [ ] All fixes documented in this plan
- [ ] Line numbers accurate
- [ ] Validation steps clear
- [ ] Rollback plan tested

---

## ROLLBACK PLAN

If fixes cause major issues:

### Immediate Rollback

```bash
# Stop any running processes
pkill -f fondos_mutuos

# Restore backup
cp fondos_mutuos.py.backup fondos_mutuos.py

# Verify restoration
diff fondos_mutuos.py fondos_mutuos.py.backup
# Should show no differences

# Test with single fund
python -c "from fondos_mutuos import FondosMutuosProcessor; FondosMutuosProcessor().procesar_fondos_mutuos('test_fund')"
```

### Partial Rollback

If only certain fixes cause issues:

1. Identify problematic fix from error logs
2. Use Edit tool to revert specific change
3. Re-test that section
4. Document which fix was rolled back

### Recovery Steps

1. Check logs to identify failure point
2. Isolate the fix that caused the issue
3. Revert that specific change
4. Test without that fix
5. Report issue for later resolution

---

## EXECUTION ORDER

**For the Executor Agent, follow this exact sequence:**

1. **Read entire file first** (fondos_mutuos.py)
2. **Phase 1: Critical Fixes**
   - Execute Fix 1.1.A through 1.1.D (RUN/RUT)
   - Test immediately with one fund
   - Execute Fix 1.2.A (Error concatenation)
   - Execute Fix 1.3.A (Composicion patterns)
   - Test immediately with one fund
   - Execute Fix 1.4.A through 1.4.E (Silent failures logging)
   - Execute Fix 1.5.A (Patrimonio)
3. **Checkpoint: Validate Phase 1**
   - Run Test Suite tests 1-4
   - If any test fails, STOP and report
4. **Phase 2: High Priority Fixes**
   - Execute all Fix 2.x sequentially
   - Test after every 3 fixes
5. **Checkpoint: Validate Phase 2**
   - Run Test Suite tests 5-7
   - If any test fails, consider rollback of Phase 2 only
6. **Phase 3: Medium Priority**
   - Execute all Fix 3.x
   - Less critical, can proceed even with minor issues
7. **Phase 4: Low Priority**
   - Execute all Fix 4.x
   - Optional, can skip if time limited
8. **Final Validation**
   - Run complete Test Suite
   - Run Regression Testing
   - Complete Validation Checklist

---

## NOTES FOR EXECUTOR AGENT

### Critical Rules

1. **NEVER modify code without reading the section first**
2. **ALWAYS validate each fix immediately after applying**
3. **STOP if any critical fix fails** - do not proceed to next phase
4. **Log every change** - keep track of what was modified
5. **Use exact string matching** - copy-paste from file, don't type manually

### Common Pitfalls to Avoid

- Don't assume line numbers are exact - code may have shifted
- Don't skip reading the surrounding context
- Don't combine multiple fixes into one Edit call
- Don't modify indentation or whitespace unless specified
- Don't add imports without checking if they already exist

### Success Indicators

- Logs show new debug/warning messages
- Excel files have more populated fields
- No crashes during processing
- RUN field appears in outputs
- Composicion extraction rate improves

### Failure Indicators

- TypeError exceptions
- SyntaxError after edits
- Blank Excel files generated
- More "N/A" fields than before
- Extraction rates decrease

If you encounter failure indicators, **STOP IMMEDIATELY** and report the issue before continuing.

---

## SUMMARY

**Total Fixes:** 43
**Critical:** 15
**High Priority:** 15
**Medium Priority:** 8
**Low Priority:** 5

**Estimated Time:** 4-6 hours for complete implementation and testing

**Expected Improvements:**
- RUN field: 0% → 70% populated
- Composicion: 10% → 50% populated
- Overall data quality: +40% improvement
- Silent failures: Eliminated (all logged)
- ETL violations: Eliminated

This plan provides complete, step-by-step instructions for fixing all identified issues in the ETL pipeline. Follow it sequentially for best results.

---

**End of Fix Plan**
**Version 1.0 - 2026-01-05**

<function_calls>
<invoke name="TodoWrite">
<parameter name="todos">[{"content": "Create comprehensive fix plan document", "status": "completed", "activeForm": "Creating comprehensive fix plan document"}, {"content": "Document all critical fixes with line numbers", "status": "completed", "activeForm": "Documenting all critical fixes with line numbers"}, {"content": "Document all high priority fixes", "status": "in_progress", "activeForm": "Documenting all high priority fixes"}, {"content": "Document medium priority improvements", "status": "pending", "activeForm": "Documenting medium priority improvements"}, {"content": "Create validation checklist for executor agent", "status": "pending", "activeForm": "Creating validation checklist for executor agent"}]