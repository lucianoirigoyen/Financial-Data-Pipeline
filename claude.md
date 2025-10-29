# 🏗️ Sprint 1: Pipeline Automatización Datos Financieros - inBee

## 📌 Contexto del Proyecto

inBee es una fintech chilena que centraliza información de activos financieros (acciones, criptomonedas, fondos mutuos) para presentarla de forma clara a jóvenes/inversores.

**Fuentes de datos actuales:**

- **Alpha Vantage API**: acciones, criptos, forex, índices (datos en inglés)
- **Fintual API**: fondos mutuos (datos básicos)
- **CMF Chile**: PDFs descargables con detalle completo de fondos mutuos

**Problema:** Los datos llegan en bruto, en inglés y poco amigables para usuarios finales.

**Solución:** Pipeline automático que procese, traduzca y normalice datos, generando outputs claros en español.

## 🎯 Objetivos Técnicos Específicos

### 1. Procesamiento Alpha Vantage

- Consumir API OVERVIEW de Alpha Vantage
- Traducir automáticamente campos al español usando DeepL API
- Normalizar porcentajes (ej: "15.5%" → 0.155)
- Generar output en JSON y Excel

### 2. Procesamiento Fondos Mutuos

- Obtener datos básicos de Fintual API
- Descargar automáticamente PDFs desde CMF Chile
- Extraer via scraping: tipo de fondo, perfil de riesgo, composición de portafolio
- Generar descripción amigable usando IA con prompt editable
- Normalizar porcentajes de portafolio
- Output en JSON y Excel

## 📂 Estructura de Archivos Requerida

```
sprint1/
├── main.py                 # Script principal orquestador
├── alpha_vantage.py        # Procesamiento datos Alpha Vantage
├── fondos_mutuos.py        # Procesamiento Fintual + CMF
├── prompts/
│   └── fondos_prompt.txt   # Prompt editable para descripción fondos
├── requirements.txt        # Dependencias Python
├── .env                    # Variables de entorno (API keys)
├── outputs/
│   ├── output_overview.xlsx
│   └── output_fondos.xlsx
└── README.md              # Documentación técnica
```

## 🔑 Configuración de APIs y Variables de Entorno

### Archivo .env requerido:

```env
ALPHAVANTAGE_API_KEY=your_alphavantage_key
DEEPL_API_KEY=your_deepl_key
```

### APIs a utilizar:

**Alpha Vantage OVERVIEW:**

- Endpoint: `https://www.alphavantage.co/query?function=OVERVIEW&symbol={SYMBOL}&apikey={API_KEY}`
- Ejemplo real: `https://www.alphavantage.co/query?function=OVERVIEW&symbol=IBM&apikey=demo`

**DeepL Translation:**

- Endpoint: `https://api-free.deepl.com/v2/translate`
- Traducir de EN → ES

**CMF Chile:**

- Base URL: `http://www.cmfchile.cl`
- Buscar y descargar PDFs de fondos mutuos específicos

## 🛠️ Dependencias Técnicas

### requirements.txt:

```
requests>=2.31.0
pandas>=2.0.0
openpyxl>=3.1.0
python-dotenv>=1.0.0
pdfplumber>=0.9.0
deepl>=1.15.0
```

## 📋 Especificaciones Técnicas Detalladas

### 1. alpha_vantage.py

**Función principal:** `procesar_alpha_vantage(symbol: str) -> dict`

**Flujo específico:**

1. Hacer request a Alpha Vantage OVERVIEW API
2. Validar respuesta y manejo de errores (rate limits, API key inválida)
3. Extraer campos relevantes:
   - Symbol, Name, Description, Sector, Industry
   - MarketCapitalization, PERatio, DividendYield, etc.
4. Normalizar porcentajes (convertir strings con % a float)
5. Traducir campos de texto usando DeepL API
6. Generar Excel con pandas
7. Retornar diccionario estructurado

**Estructura output esperada:**

```python
{
    "symbol": str,
    "name": str,
    "description_es": str,  # Traducida al español
    "sector_es": str,       # Traducido al español
    "industry_es": str,     # Traducido al español
    "market_cap": float,
    "pe_ratio": float,
    "dividend_yield": float,  # Normalizado (0.025 no 2.5%)
    # ... otros campos relevantes
}
```

### 2. fondos_mutuos.py

**Función principal:** `procesar_fondos_mutuos(fondo_id: str) -> dict`

**Flujo específico:**

1. **Fase 1 - Fintual API:**

   - Obtener datos básicos del fondo
   - Extraer nombre, rentabilidad básica

2. **Fase 2 - CMF PDF Download:**

   - Construir URL de descarga PDF CMF
   - Descargar PDF usando requests
   - Validar descarga exitosa

3. **Fase 3 - PDF Scraping:**

   - Usar pdfplumber para extraer texto
   - Buscar patrones específicos para:
     - Tipo de fondo (conservador/balanceado/agresivo)
     - Perfil de riesgo
     - Tabla de composición de portafolio
   - Extraer porcentajes y normalizar

4. **Fase 4 - Descripción IA:**

   - Cargar prompt desde `prompts/fondos_prompt.txt`
   - Enviar datos extraídos a modelo de IA (usar OpenAI API o similar)
   - Generar descripción amigable (máx 500 palabras)

5. **Fase 5 - Output:**
   - Generar Excel con pandas
   - Retornar diccionario estructurado

**Estructura output esperada:**

```python
{
    "nombre": str,
    "descripcion_amigable": str,  # Generada por IA, máx 500 palabras
    "tipo_fondo": str,           # conservador/balanceado/agresivo
    "perfil_riesgo": str,
    "composicion_portafolio": [
        {
            "activo": str,
            "porcentaje": float  # Normalizado (0.35 no 35%)
        }
    ],
    "rentabilidad_12m": float,   # Si disponible
    # ... otros campos relevantes
}
```

### 3. prompts/fondos_prompt.txt

**Contenido del archivo (editable):**

```
Eres un experto en finanzas que debe generar descripciones claras y amigables de fondos mutuos para jóvenes inversores chilenos.

CONTEXTO:
- Nombre del fondo: {nombre_fondo}
- Tipo de fondo: {tipo_fondo}
- Perfil de riesgo: {perfil_riesgo}
- Composición principal: {composicion_top5}

TAREA:
Genera una descripción de máximo 500 palabras que explique:
1. Qué es este fondo y su estrategia de inversión
2. Para qué perfil de inversionista es adecuado
3. Principales activos en los que invierte
4. Nivel de riesgo en términos simples
5. Horizonte de inversión recomendado

TONO: Profesional pero accesible, evita jerga técnica compleja.
FORMATO: Párrafos cortos y claros.
```

### 4. main.py

**Script orquestador principal:**

```python
"""
Pipeline principal para procesamiento de datos financieros inBee
Ejecuta procesamiento de Alpha Vantage y Fondos Mutuos
"""

import os
from dotenv import load_dotenv
from alpha_vantage import procesar_alpha_vantage
from fondos_mutuos import procesar_fondos_mutuos
import json

def main():
    # Cargar variables de entorno
    load_dotenv()

    # Validar API keys
    if not os.getenv('ALPHAVANTAGE_API_KEY'):
        raise ValueError("ALPHAVANTAGE_API_KEY no encontrada en .env")

    print("🚀 Iniciando pipeline inBee Sprint 1...")

    # Ejemplo 1: Procesar acción de Disney
    print("\n📈 Procesando acción Disney (DIS)...")
    resultado_disney = procesar_alpha_vantage("DIS")

    # Guardar resultado
    with open('outputs/disney_data.json', 'w', encoding='utf-8') as f:
        json.dump(resultado_disney, f, indent=2, ensure_ascii=False)

    # Ejemplo 2: Procesar fondo mutuo Santander
    print("\n🏦 Procesando fondo mutuo Santander...")
    # Nota: ID específico debe ser investigado en API de Fintual
    resultado_fondo = procesar_fondos_mutuos("santander_conservador_id")

    # Guardar resultado
    with open('outputs/fondo_santander_data.json', 'w', encoding='utf-8') as f:
        json.dump(resultado_fondo, f, indent=2, ensure_ascii=False)

    print("\n✅ Pipeline completado exitosamente")
    print("📁 Revisa carpeta outputs/ para los resultados")

if __name__ == "__main__":
    main()
```

## ⚠️ Requisitos Críticos de Implementación

### 1. Manejo de Errores Robusto

- Validar todas las respuestas API antes de procesar
- Implementar reintentos para rate limits
- Manejar casos donde PDFs no se pueden descargar
- Logging detallado de errores

### 2. Validación de Datos

- Verificar que porcentajes sumen 100% en portafolios
- Validar formato de datos antes de normalizar
- Comprobar que traducciones no estén vacías

### 3. Configuración Flexible

- Todas las API keys en .env
- Prompts de IA editables en archivos externos
- Configuración de timeouts y reintentos

### 4. Performance

- Cachear respuestas de API cuando sea posible
- Procesar PDFs de manera eficiente
- Limitar llamadas simultáneas a APIs

## 🧪 Casos de Prueba Requeridos

### Test Alpha Vantage:

- Symbol válido: "DIS" (Disney)
- Symbol inválido: "INVALID123"
- API key inválida
- Rate limit alcanzado

### Test Fondos Mutuos:

- Fondo Santander existente
- PDF no disponible en CMF
- PDF corrupto o ilegible
- Datos faltantes en scraping

## 📊 Formato de Outputs Excel

### output_overview.xlsx:

| Campo          | Tipo  | Descripción                      |
| -------------- | ----- | -------------------------------- |
| Symbol         | str   | Símbolo ticker                   |
| Nombre         | str   | Nombre empresa                   |
| Sector         | str   | Sector (en español)              |
| Industria      | str   | Industria (en español)           |
| Descripción    | str   | Descripción (en español)         |
| Market Cap     | float | Capitalización de mercado        |
| P/E Ratio      | float | Ratio precio/ganancia            |
| Dividend Yield | float | Rentabilidad dividendo (decimal) |

### output_fondos.xlsx:

| Campo         | Tipo  | Descripción                 |
| ------------- | ----- | --------------------------- |
| Nombre        | str   | Nombre del fondo            |
| Tipo          | str   | Tipo de fondo               |
| Perfil Riesgo | str   | Perfil de riesgo            |
| Descripción   | str   | Descripción generada por IA |
| Activo 1      | str   | Principal activo            |
| % Activo 1    | float | Porcentaje (decimal)        |
| ...           | ...   | Otros activos principales   |

## 📖 Documentación README.md

Debe incluir:

1. **Instalación:** Cómo instalar dependencias
2. **Configuración:** Cómo configurar .env
3. **Ejecución:** Cómo ejecutar el pipeline
4. **Customización:** Cómo editar prompts de IA
5. **Troubleshooting:** Errores comunes y soluciones
6. **API Limits:** Limitaciones conocidas de cada API

## ⚡ Criterios de Éxito

### Funcionalidad:

- [ ] Pipeline ejecuta sin errores con datos reales
- [ ] Traducciones de Alpha Vantage funcionan correctamente
- [ ] Scraping de PDFs CMF extrae datos relevantes
- [ ] Descripción de fondos se genera automáticamente
- [ ] Outputs en Excel se crean correctamente
- [ ] Porcentajes se normalizan adecuadamente

### Código:

- [ ] Modular y bien documentado
- [ ] Manejo robusto de errores
- [ ] Configuración flexible
- [ ] Sin datos hardcodeados
- [ ] Cumple estándares PEP 8

### Outputs:

- [ ] JSON estructurado correctamente
- [ ] Excel legible y bien formateado
- [ ] Descripciones en español claro
- [ ] Datos precisos y actualizados

## 🚨 Restricciones Importantes

1. **NO inventar datos** - Todo debe venir de APIs reales
2. **NO hardcodear información** - Usar configuración externa
3. **NO generar ejemplos ficticios** - Solo datos reales de prueba
4. **SÍ comentar código extensivamente** - Para mantenimiento futuro
5. **SÍ manejar errores robustamente** - Para entorno productivo
6. **SÍ mantener modularidad** - Para escalabilidad

---

**Nota:** Este es un MVP para producción. El código debe ser robusto, bien documentado y fácil de mantener para futuros sprints.
