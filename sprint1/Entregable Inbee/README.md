# Pipeline Automatización Datos Financieros - inBee Sprint 1

Pipeline automático para procesamiento de datos financieros que centraliza información de activos financieros (acciones, criptomonedas, fondos mutuos) para presentarla de forma clara a jóvenes inversores chilenos.

## 🎯 Características Principales

- **Procesamiento Alpha Vantage**: Obtiene datos de acciones con traducción automática al español
- **Integración Fondos Mutuos**: Combina datos de Fintual API y scraping de PDFs CMF Chile
- **Traducción Automática**: Utiliza DeepL API para traducir contenido al español
- **Generación IA**: Crea descripciones amigables usando OpenAI GPT
- **Outputs Estructurados**: Genera archivos JSON y Excel listos para uso
- **Manejo de Errores**: Robust error handling y logging detallado

## 📂 Estructura del Proyecto

```
sprint1/
├── main.py                 # Script principal orquestador
├── alpha_vantage.py        # Procesamiento datos Alpha Vantage
├── fondos_mutuos.py        # Procesamiento Fintual + CMF
├── prompts/
│   └── fondos_prompt.txt   # Prompt editable para descripción fondos
├── requirements.txt        # Dependencias Python
├── .env                    # Variables de entorno (API keys)
├── outputs/                # Archivos de salida generados
├── logs/                   # Archivos de log (creado automáticamente)
├── temp/                   # Archivos temporales (creado automáticamente)
└── README.md              # Documentación técnica
```

## ⚡ Instalación Rápida

### 1. Clonar e Instalar Dependencias

```bash
cd sprint1
pip install -r requirements.txt
```

### 2. Configurar Variables de Entorno

Edita el archivo `.env` con tus API keys:

```env
# Requerido - Obtén en: https://www.alphavantage.co/support/#api-key
ALPHAVANTAGE_API_KEY=tu_api_key_alphavantage

# Opcional - Obtén en: https://www.deepl.com/pro-api
DEEPL_API_KEY=tu_api_key_deepl

# Opcional - Para descripciones de fondos con IA
OPENAI_API_KEY=tu_api_key_openai
```

### 3. Ejecutar Pipeline

```bash
python main.py
```

## 🔧 Uso Básico

### Procesar una Acción Individual

```python
from alpha_vantage import procesar_alpha_vantage

# Procesar Disney
resultado = procesar_alpha_vantage("DIS")
print(resultado['name'])  # The Walt Disney Company
print(resultado['sector_es'])  # Sector traducido al español
```

### Procesar un Fondo Mutuo

```python
from fondos_mutuos import procesar_fondos_mutuos

# Procesar fondo
resultado = procesar_fondos_mutuos("santander_conservador")
print(resultado['descripcion_amigable'])  # Descripción generada por IA
```

### Usar el Pipeline Completo

```python
from main import InBeePipeline

pipeline = InBeePipeline()

# Procesar múltiples acciones
acciones = ['DIS', 'AAPL', 'MSFT']
resultado_batch = pipeline.procesar_batch_acciones(acciones)

# Procesar múltiples fondos
fondos = ['fondo1', 'fondo2']
resultado_fondos = pipeline.procesar_batch_fondos(fondos)
```

## 📊 Formato de Outputs

### Datos de Acciones (JSON)

```json
{
  "symbol": "DIS",
  "name": "The Walt Disney Company",
  "description_es": "Descripción en español...",
  "sector_es": "Entretenimiento",
  "industry_es": "Medios y Entretenimiento",
  "market_cap": 147000000000,
  "pe_ratio": 25.4,
  "dividend_yield": 0.025,
  "beta": 1.2
}
```

### Datos de Fondos (JSON)

```json
{
  "nombre": "Fondo Conservador Santander",
  "tipo_fondo": "Conservador",
  "perfil_riesgo": "Bajo",
  "descripcion_amigable": "Descripción generada por IA...",
  "composicion_portafolio": [
    {
      "activo": "Bonos Gobierno",
      "porcentaje": 0.6
    }
  ],
  "rentabilidad_anual": 0.08
}
```

### Archivos Excel Generados

- `output_overview_[SYMBOL].xlsx`: Datos de acciones procesadas
- `output_fondos_[NOMBRE].xlsx`: Datos de fondos mutuos con composición detallada

## 🛠️ Configuración Avanzada

### Personalizar Prompts de IA

Edita `prompts/fondos_prompt.txt` para personalizar las descripciones generadas:

```text
Eres un experto en finanzas que debe generar descripciones claras...

CONTEXTO:
- Nombre del fondo: {nombre_fondo}
- Tipo de fondo: {tipo_fondo}
...
```

### Rate Limits y Timeouts

```python
# Alpha Vantage: 5 llamadas por minuto
pipeline.procesar_batch_acciones(symbols, delay=12.0)  # 12 segundos entre calls

# Ajustar timeouts para requests
# Editar en alpha_vantage.py: requests.get(..., timeout=30)
```

## 🔍 Troubleshooting

### Errores Comunes

#### "ALPHAVANTAGE_API_KEY no encontrada"

```bash
# Verificar que el archivo .env existe y contiene la key
cat .env | grep ALPHAVANTAGE
```

#### "Rate limit alcanzado"

```bash
# Alpha Vantage: máximo 5 calls por minuto
# Esperar 1 minuto o usar API key premium
```

#### "Error descargando PDF CMF"

```bash
# Los PDFs de CMF pueden no estar disponibles
# El sistema usará datos de ejemplo en este caso
```

#### "Error de traducción DeepL"

```bash
# Verificar API key de DeepL o el sistema usará texto original
export DEEPL_API_KEY=tu_key_deepl
```

### Verificar Logs

```bash
# Ver log completo del pipeline
tail -f pipeline.log

# Ver solo errores
grep ERROR pipeline.log
```

### Validar Outputs

```bash
# Listar archivos generados
ls -la outputs/

# Verificar contenido JSON
python -m json.tool outputs/dis_data.json
```

## 📈 Limitaciones Conocidas

### APIs Externas

- **Alpha Vantage Free**: 5 calls/minuto, 500 calls/día
- **DeepL Free**: 500,000 caracteres/mes
- **OpenAI**: Límites según plan contratado

### Scraping CMF

- PDFs pueden no estar siempre disponibles
- Estructura de PDFs puede cambiar
- Sistema usa datos de ejemplo cuando PDF no está disponible

### Fintual API

- API pública limitada
- Algunos fondos pueden no estar disponibles
- Datos pueden estar desactualizados

## Desarrollo y Contribución

### Estructura del Código

- `alpha_vantage.py`: Lógica específica para Alpha Vantage API
- `fondos_mutuos.py`: Lógica para fondos mutuos (Fintual + CMF)
- `main.py`: Orestador principal y batch

### Testing

```bash
# Test individual de módulos
python alpha_vantage.py
python fondos_mutuos.py

# Test del pipeline completo
python main.py
```

### Logging

El sistema genera logs detallados en:

- Consola (stdout)
- Archivo `pipeline.log`

Niveles de log disponibles: DEBUG, INFO, WARNING, ERROR

## 📞 Soporte

Para reportar bugs o solicitar features:

1. Revisar logs: `pipeline.log`
2. Verificar configuración: archivo `.env`
3. Validar conectividad a APIs externas
4. Documentar error y contexto

## 📄 Licencia

Proyecto interno inBee - Sprint 1
Desarrollo para automatización de datos financieros

---

**Desarrollado para inBee con amor **
