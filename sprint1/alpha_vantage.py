"""
Módulo COMPLETO para procesamiento de datos de Alpha Vantage API
Extrae TODOS los datos disponibles: Acciones, Criptomonedas, Forex, Índices
Incluye traducción automática completa con DeepL
"""

import os
import requests
import pandas as pd
import logging
import time
import re
from datetime import datetime
from typing import Dict, Optional, List, Tuple
import deepl
from dotenv import load_dotenv
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils.dataframe import dataframe_to_rows

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AlphaVantageCompleteProcessor:
    """Clase DINÁMICA para procesar TODOS los datos de Alpha Vantage"""

    def __init__(self):
        self.api_key = os.getenv('ALPHAVANTAGE_API_KEY')
        self.deepl_key = os.getenv('DEEPL_API_KEY')

        if not self.api_key:
            raise ValueError("ALPHAVANTAGE_API_KEY no encontrada en variables de entorno")

        if self.deepl_key:
            self.translator = deepl.Translator(self.deepl_key)
        else:
            logger.warning("DEEPL_API_KEY no encontrada, las traducciones no funcionarán")
            self.translator = None

        # Patrones para identificar tipos de campos dinámicamente
        self.text_field_patterns = [
            r'name', r'description', r'sector', r'industry', r'address', r'assettype',
            r'country', r'currency', r'exchange', r'officialsite'
        ]

        # Patrones para campos numéricos
        self.numeric_patterns = [
            r'capitalization', r'ebitda', r'ratio', r'value', r'eps', r'revenue',
            r'profit', r'margin', r'return', r'share', r'growth', r'price',
            r'target', r'beta', r'week', r'moving', r'average', r'outstanding',
            r'float', r'percent', r'rating'
        ]

        # Patrones para porcentajes
        self.percentage_patterns = [
            r'yield', r'margin', r'return', r'growth', r'percent'
        ]

    def _make_api_request(self, function: str, symbol: str, from_currency: str = None,
                         to_currency: str = None, retries: int = 3) -> Optional[Dict]:
        """Realizar request a Alpha Vantage para diferentes funciones"""
        url = f"https://www.alphavantage.co/query"

        if function == 'OVERVIEW':
            params = {
                'function': 'OVERVIEW',
                'symbol': symbol,
                'apikey': self.api_key
            }
        elif function == 'CURRENCY_EXCHANGE_RATE':
            params = {
                'function': 'CURRENCY_EXCHANGE_RATE',
                'from_currency': from_currency,
                'to_currency': to_currency,
                'apikey': self.api_key
            }
        elif function == 'DIGITAL_CURRENCY_DAILY':
            params = {
                'function': 'DIGITAL_CURRENCY_DAILY',
                'symbol': symbol,
                'market': 'USD',
                'apikey': self.api_key
            }

        for attempt in range(retries):
            try:
                logger.info(f"Request {function} para {symbol} (intento {attempt + 1})")
                response = requests.get(url, params=params, timeout=30)
                response.raise_for_status()

                data = response.json()

                if 'Error Message' in data:
                    logger.error(f"Error de API: {data['Error Message']}")
                    return None

                if 'Note' in data:
                    logger.warning(f"Rate limit: {data['Note']}")
                    if attempt < retries - 1:
                        time.sleep(60)
                        continue
                    return None

                return data

            except requests.exceptions.RequestException as e:
                logger.error(f"Error en request (intento {attempt + 1}): {e}")
                if attempt < retries - 1:
                    time.sleep(5)
                    continue
                return None

        return None

    def _identify_text_fields(self, data: Dict) -> List[str]:
        """Identificar dinámicamente campos de texto para traducir"""
        text_fields = []

        for field_name, field_value in data.items():
            if isinstance(field_value, str) and field_value and field_value != 'None':
                # Verificar si el campo contiene texto (no solo números)
                if not field_value.replace('.', '').replace(',', '').replace('-', '').replace('%', '').replace('$', '').isdigit():
                    # Verificar si coincide con patrones de texto
                    field_lower = field_name.lower()
                    if any(re.search(pattern, field_lower) for pattern in self.text_field_patterns):
                        text_fields.append(field_name)
                    # También incluir campos que parecen contener texto descriptivo
                    elif len(field_value) > 50 and ' ' in field_value:
                        text_fields.append(field_name)

        return text_fields

    def _translate_all_text_fields(self, data: Dict) -> Dict:
        """Traducir DINÁMICAMENTE todos los campos de texto al español"""
        if not self.translator:
            return data

        # CAMPOS PROHIBIDOS: No traducir identificadores técnicos críticos
        FORBIDDEN_TRANSLATION_FIELDS = {
            'Symbol', 'symbol', 'SYMBOL',
            'Exchange', 'exchange', 'EXCHANGE',
            'Currency', 'currency', 'CURRENCY',
            'AssetType', 'assettype', 'ASSETTYPE',
            'CIK', 'cik',
            'FiscalYearEnd', 'fiscalyearend',
            'Ticker', 'ticker', 'TICKER',
            'ISIN', 'isin',
            'CUSIP', 'cusip'
        }

        logger.info("Identificando y traduciendo campos de texto...")

        text_fields = self._identify_text_fields(data)

        # Filtrar campos prohibidos
        text_fields_to_translate = [
            field for field in text_fields
            if field not in FORBIDDEN_TRANSLATION_FIELDS
        ]

        filtered_count = len(text_fields) - len(text_fields_to_translate)
        if filtered_count > 0:
            logger.info(f"Campos técnicos protegidos (NO traducir): {filtered_count}")

        logger.info(f"Campos a traducir: {text_fields_to_translate}")

        for field in text_fields_to_translate:
            if field in data and data[field]:
                original = data[field]
                try:
                    translated = self.translator.translate_text(original, target_lang='ES')
                    data[f"{field}_es"] = translated.text
                    logger.debug(f"Traducido {field}: {original[:50]}... -> {translated.text[:50]}...")
                except Exception as e:
                    logger.warning(f"Error traduciendo {field}: {e}")
                    data[f"{field}_es"] = original

        return data

    def _identify_numeric_fields(self, data: Dict) -> Tuple[List[str], List[str]]:
        """Identificar dinámicamente campos numéricos y porcentajes"""
        numeric_fields = []
        percentage_fields = []

        for field_name, field_value in data.items():
            if field_value and field_value != 'None':
                field_lower = field_name.lower()
                field_str = str(field_value)

                # Verificar si es numérico
                is_numeric = False
                is_percentage = False

                # Limpiar valor para verificar si es numérico
                cleaned_value = field_str.replace(',', '').replace('$', '').replace('%', '').replace('-', '').strip()

                try:
                    # Intentar convertir a float
                    if cleaned_value and cleaned_value != 'None':
                        float(cleaned_value)
                        is_numeric = True

                        # Verificar si es porcentaje
                        if '%' in field_str or any(re.search(pattern, field_lower) for pattern in self.percentage_patterns):
                            is_percentage = True

                except ValueError:
                    # También verificar patrones de campos numéricos conocidos
                    if any(re.search(pattern, field_lower) for pattern in self.numeric_patterns):
                        is_numeric = True

                if is_numeric:
                    numeric_fields.append(field_name)
                    if is_percentage:
                        percentage_fields.append(field_name)

        return numeric_fields, percentage_fields

    def _normalize_all_numeric_fields(self, data: Dict) -> Dict:
        """Normalizar DINÁMICAMENTE todos los campos numéricos"""
        logger.info("Identificando y normalizando campos numéricos...")

        numeric_fields, percentage_fields = self._identify_numeric_fields(data)

        logger.info(f"Campos numéricos identificados: {len(numeric_fields)}")
        logger.info(f"Campos de porcentaje identificados: {len(percentage_fields)}")

        for field in numeric_fields:
            if field in data and data[field]:
                try:
                    value = data[field]

                    if isinstance(value, str):
                        cleaned_value = value.replace(',', '').replace('$', '').replace('%', '').strip()
                        if cleaned_value and cleaned_value != 'None' and cleaned_value != '-':
                            numeric_value = float(cleaned_value)

                            if field in percentage_fields and '%' in str(value):
                                data[f"{field}_normalized"] = numeric_value / 100
                            else:
                                data[f"{field}_normalized"] = numeric_value
                    else:
                        data[f"{field}_normalized"] = float(value)

                except (ValueError, TypeError) as e:
                    logger.debug(f"No se pudo normalizar {field}: {e}")
                    data[f"{field}_normalized"] = None

        return data

    def _generate_complete_analysis(self, data: Dict) -> Dict:
        """Generar análisis financiero COMPLETO con TODOS los datos dinámicamente"""
        analysis = {
            'fecha_analisis_completo': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'analisis_fundamental': {},
            'analisis_tecnico': {},
            'analisis_analistas': {},
            'metricas_valoracion': {},
            'metricas_rentabilidad': {},
            'metricas_crecimiento': {},
            'metricas_liquidez': {},
            'recomendacion_completa': '',
            'riesgos_completos': [],
            'oportunidades_completas': [],
            'campos_disponibles': [],
            'campos_procesados': 0
        }

        try:
            # Recopilar todos los campos disponibles
            analysis['campos_disponibles'] = list(data.keys())
            analysis['campos_procesados'] = len(data)

            # Análisis Fundamental DINÁMICO
            fundamental_data = {}

            # Buscar campos fundamentales dinámicamente
            for field_name, field_value in data.items():
                field_lower = field_name.lower()
                if '_normalized' in field_name:
                    if 'market' in field_lower and 'cap' in field_lower:
                        fundamental_data['market_cap_usd'] = field_value
                        fundamental_data['market_cap_formatted'] = self._format_large_number(field_value)
                    elif 'ebitda' in field_lower:
                        fundamental_data['ebitda'] = field_value
                    elif 'revenue' in field_lower and 'ttm' in field_lower:
                        fundamental_data['revenue_ttm'] = field_value
                    elif 'gross' in field_lower and 'profit' in field_lower:
                        fundamental_data['gross_profit'] = field_value
                    elif 'book' in field_lower and 'value' in field_lower:
                        fundamental_data['book_value'] = field_value
                    elif 'shares' in field_lower and 'outstanding' in field_lower:
                        fundamental_data['shares_outstanding'] = field_value
                    elif 'shares' in field_lower and 'float' in field_lower:
                        fundamental_data['shares_float'] = field_value

            analysis['analisis_fundamental'] = fundamental_data

            # Análisis Técnico DINÁMICO
            technical_data = {}

            # Buscar campos técnicos dinámicamente
            for field_name, field_value in data.items():
                field_lower = field_name.lower()
                if '_normalized' in field_name:
                    if '52week' in field_lower and 'high' in field_lower:
                        technical_data['precio_52w_alto'] = field_value
                    elif '52week' in field_lower and 'low' in field_lower:
                        technical_data['precio_52w_bajo'] = field_value
                    elif '50day' in field_lower and ('moving' in field_lower or 'average' in field_lower):
                        technical_data['media_movil_50d'] = field_value
                    elif '200day' in field_lower and ('moving' in field_lower or 'average' in field_lower):
                        technical_data['media_movil_200d'] = field_value
                    elif 'beta' in field_lower:
                        technical_data['beta'] = field_value
                        technical_data['volatilidad_clasificacion'] = self._classify_beta(field_value)

            analysis['analisis_tecnico'] = technical_data

            # Análisis de Analistas DINÁMICO
            analyst_data = {}
            ratings = {}

            # Buscar campos de analistas dinámicamente
            for field_name, field_value in data.items():
                field_lower = field_name.lower()
                if '_normalized' in field_name:
                    if 'analyst' in field_lower and 'target' in field_lower and 'price' in field_lower:
                        analyst_data['precio_objetivo'] = field_value
                    elif 'analyst' in field_lower and 'rating' in field_lower:
                        if 'strongbuy' in field_lower:
                            ratings['strong_buy'] = field_value or 0
                        elif 'buy' in field_lower and 'strongbuy' not in field_lower:
                            ratings['buy'] = field_value or 0
                        elif 'hold' in field_lower:
                            ratings['hold'] = field_value or 0
                        elif 'sell' in field_lower and 'strongsell' not in field_lower:
                            ratings['sell'] = field_value or 0
                        elif 'strongsell' in field_lower:
                            ratings['strong_sell'] = field_value or 0

            # Calcular total y consenso
            total_analysts = sum(ratings.values())
            analyst_data.update(ratings)
            analyst_data['total_analistas'] = total_analysts
            analyst_data['consenso'] = self._calculate_analyst_consensus_dynamic(ratings)

            analysis['analisis_analistas'] = analyst_data

            # Métricas de Valoración COMPLETAS
            analysis['metricas_valoracion'] = {
                'pe_ratio': data.get('PERatio_normalized'),
                'pe_trailing': data.get('TrailingPE_normalized'),
                'pe_forward': data.get('ForwardPE_normalized'),
                'peg_ratio': data.get('PEGRatio_normalized'),
                'price_to_book': data.get('PriceToBookRatio_normalized'),
                'price_to_sales': data.get('PriceToSalesRatioTTM_normalized'),
                'ev_to_revenue': data.get('EVToRevenue_normalized'),
                'ev_to_ebitda': data.get('EVToEBITDA_normalized'),
                'valoracion_resumen': self._assess_valuation(data)
            }

            # Métricas de Rentabilidad COMPLETAS
            analysis['metricas_rentabilidad'] = {
                'profit_margin': data.get('ProfitMargin_normalized'),
                'operating_margin': data.get('OperatingMarginTTM_normalized'),
                'roa': data.get('ReturnOnAssetsTTM_normalized'),
                'roe': data.get('ReturnOnEquityTTM_normalized'),
                'eps': data.get('EPS_normalized'),
                'diluted_eps': data.get('DilutedEPSTTM_normalized'),
                'revenue_per_share': data.get('RevenuePerShareTTM_normalized'),
                'rentabilidad_clasificacion': self._classify_profitability(data)
            }

            # Métricas de Crecimiento COMPLETAS
            analysis['metricas_crecimiento'] = {
                'earnings_growth_yoy': data.get('QuarterlyEarningsGrowthYOY_normalized'),
                'revenue_growth_yoy': data.get('QuarterlyRevenueGrowthYOY_normalized'),
                'crecimiento_clasificacion': self._classify_growth(data)
            }

            # Dividendos COMPLETOS
            analysis['dividendos'] = {
                'dividend_per_share': data.get('DividendPerShare_normalized'),
                'dividend_yield': data.get('DividendYield_normalized'),
                'dividend_date': data.get('DividendDate'),
                'ex_dividend_date': data.get('ExDividendDate'),
                'dividend_clasificacion': self._classify_dividend(data.get('DividendYield_normalized'))
            }

            # Estructura Corporativa
            analysis['estructura_corporativa'] = {
                'percent_insiders': data.get('PercentInsiders_normalized'),
                'percent_institutions': data.get('PercentInstitutions_normalized'),
                'governance_score': self._calculate_governance_score(data)
            }

        except Exception as e:
            logger.warning(f"Error en análisis completo: {e}")

        return analysis

    def _format_large_number(self, num: float) -> str:
        """Formatear números grandes"""
        if not num:
            return "N/A"

        if num >= 1e12:
            return f"${num/1e12:.2f}T"
        elif num >= 1e9:
            return f"${num/1e9:.2f}B"
        elif num >= 1e6:
            return f"${num/1e6:.2f}M"
        elif num >= 1e3:
            return f"${num/1e3:.2f}K"
        else:
            return f"${num:.2f}"

    def _classify_beta(self, beta: float) -> str:
        """Clasificar volatilidad por beta"""
        if not beta:
            return "No disponible"
        if beta < 0.5:
            return "Muy Baja Volatilidad"
        elif beta < 1.0:
            return "Baja Volatilidad"
        elif beta < 1.5:
            return "Volatilidad Moderada"
        elif beta < 2.0:
            return "Alta Volatilidad"
        else:
            return "Muy Alta Volatilidad"

    def _calculate_analyst_consensus(self, data: Dict) -> str:
        """Calcular consenso de analistas (método legacy)"""
        strong_buy = data.get('AnalystRatingStrongBuy_normalized', 0)
        buy = data.get('AnalystRatingBuy_normalized', 0)
        hold = data.get('AnalystRatingHold_normalized', 0)
        sell = data.get('AnalystRatingSell_normalized', 0)
        strong_sell = data.get('AnalystRatingStrongSell_normalized', 0)

        return self._calculate_analyst_consensus_dynamic({
            'strong_buy': strong_buy,
            'buy': buy,
            'hold': hold,
            'sell': sell,
            'strong_sell': strong_sell
        })

    def _calculate_analyst_consensus_dynamic(self, ratings: Dict) -> str:
        """Calcular consenso de analistas dinámicamente"""
        strong_buy = ratings.get('strong_buy', 0)
        buy = ratings.get('buy', 0)
        hold = ratings.get('hold', 0)
        sell = ratings.get('sell', 0)
        strong_sell = ratings.get('strong_sell', 0)

        total = strong_buy + buy + hold + sell + strong_sell
        if total == 0:
            return "Sin cobertura"

        positive = strong_buy + buy
        negative = sell + strong_sell

        if positive / total > 0.6:
            return "Fuertemente Positivo"
        elif positive / total > 0.4:
            return "Moderadamente Positivo"
        elif negative / total > 0.4:
            return "Negativo"
        else:
            return "Neutral"

    def _assess_valuation(self, data: Dict) -> str:
        """Evaluar valoración general"""
        pe = data.get('PERatio_normalized')
        if not pe:
            return "No disponible"

        if pe < 15:
            return "Potencialmente Subvalorada"
        elif pe < 25:
            return "Valoración Razonable"
        elif pe < 40:
            return "Posible Sobrevaloración"
        else:
            return "Altamente Sobrevalorada"

    def _classify_profitability(self, data: Dict) -> str:
        """Clasificar rentabilidad"""
        roe = data.get('ReturnOnEquityTTM_normalized')
        if not roe:
            return "No disponible"

        if roe > 0.20:
            return "Excelente Rentabilidad"
        elif roe > 0.15:
            return "Buena Rentabilidad"
        elif roe > 0.10:
            return "Rentabilidad Moderada"
        elif roe > 0:
            return "Baja Rentabilidad"
        else:
            return "Sin Rentabilidad"

    def _classify_growth(self, data: Dict) -> str:
        """Clasificar crecimiento"""
        earnings_growth = data.get('QuarterlyEarningsGrowthYOY_normalized')
        if not earnings_growth:
            return "No disponible"

        if earnings_growth > 0.25:
            return "Alto Crecimiento"
        elif earnings_growth > 0.10:
            return "Crecimiento Moderado"
        elif earnings_growth > 0:
            return "Crecimiento Lento"
        else:
            return "Decrecimiento"

    def _classify_dividend(self, dividend_yield: float) -> str:
        """Clasificar dividendo"""
        if not dividend_yield:
            return "Sin dividendos"

        if dividend_yield > 0.06:
            return "Alto dividendo"
        elif dividend_yield > 0.03:
            return "Dividendo moderado"
        elif dividend_yield > 0:
            return "Bajo dividendo"
        else:
            return "Sin dividendos"

    def _calculate_governance_score(self, data: Dict) -> str:
        """Calcular puntuación de gobierno corporativo"""
        institutions = data.get('PercentInstitutions_normalized', 0)

        if institutions > 0.70:
            return "Excelente - Alta confianza institucional"
        elif institutions > 0.50:
            return "Buena - Confianza institucional moderada"
        elif institutions > 0.30:
            return "Regular - Baja confianza institucional"
        else:
            return "Pobre - Muy baja confianza institucional"

    def _generate_complete_excel(self, data: Dict, analysis: Dict, symbol: str) -> None:
        """Generar Excel COMPLETO con TODAS las hojas y datos"""
        filename = f"outputs/analisis_COMPLETO_{symbol}.xlsx"

        try:
            with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                # HOJA 1: INFORMACIÓN GENERAL COMPLETA
                general_data = {
                    'Campo': ['Símbolo', 'Nombre', 'Nombre (ES)', 'Tipo de Activo', 'Tipo de Activo (ES)',
                             'Sector', 'Sector (ES)', 'Industria', 'Industria (ES)', 'País', 'Moneda',
                             'Bolsa', 'Sitio Web', 'Dirección', 'Dirección (ES)', 'CIK',
                             'Fin Año Fiscal', 'Último Trimestre'],
                    'Valor': [
                        data.get('Symbol', ''),
                        data.get('Name', ''),
                        data.get('Name_es', ''),
                        data.get('AssetType', ''),
                        data.get('AssetType_es', ''),
                        data.get('Sector', ''),
                        data.get('Sector_es', ''),
                        data.get('Industry', ''),
                        data.get('Industry_es', ''),
                        data.get('Country', ''),
                        data.get('Currency', ''),
                        data.get('Exchange', ''),
                        data.get('OfficialSite', ''),
                        data.get('Address', ''),
                        data.get('Address_es', ''),
                        data.get('CIK', ''),
                        data.get('FiscalYearEnd', ''),
                        data.get('LatestQuarter', '')
                    ]
                }
                pd.DataFrame(general_data).to_excel(writer, sheet_name='1_Info_General', index=False)

                # HOJA 2: MÉTRICAS FINANCIERAS COMPLETAS
                financial_data = {
                    'Métrica': ['Capitalización de Mercado', 'EBITDA', 'Ingresos TTM', 'Ganancia Bruta TTM',
                               'EPS Diluido', 'Valor en Libros', 'Acciones en Circulación', 'Acciones Flotantes',
                               'Margen de Ganancia', 'Margen Operativo', 'ROA', 'ROE', 'Ingresos por Acción'],
                    'Valor Original': [
                        data.get('MarketCapitalization', ''),
                        data.get('EBITDA', ''),
                        data.get('RevenueTTM', ''),
                        data.get('GrossProfitTTM', ''),
                        data.get('DilutedEPSTTM', ''),
                        data.get('BookValue', ''),
                        data.get('SharesOutstanding', ''),
                        data.get('SharesFloat', ''),
                        data.get('ProfitMargin', ''),
                        data.get('OperatingMarginTTM', ''),
                        data.get('ReturnOnAssetsTTM', ''),
                        data.get('ReturnOnEquityTTM', ''),
                        data.get('RevenuePerShareTTM', '')
                    ],
                    'Valor Normalizado': [
                        analysis['analisis_fundamental'].get('market_cap_formatted', ''),
                        self._format_large_number(data.get('EBITDA_normalized')),
                        self._format_large_number(data.get('RevenueTTM_normalized')),
                        self._format_large_number(data.get('GrossProfitTTM_normalized')),
                        data.get('DilutedEPSTTM_normalized', ''),
                        data.get('BookValue_normalized', ''),
                        f"{data.get('SharesOutstanding_normalized', 0):,.0f}" if data.get('SharesOutstanding_normalized') else '',
                        f"{data.get('SharesFloat_normalized', 0):,.0f}" if data.get('SharesFloat_normalized') else '',
                        f"{data.get('ProfitMargin_normalized', 0)*100:.2f}%" if data.get('ProfitMargin_normalized') else '',
                        f"{data.get('OperatingMarginTTM_normalized', 0)*100:.2f}%" if data.get('OperatingMarginTTM_normalized') else '',
                        f"{data.get('ReturnOnAssetsTTM_normalized', 0)*100:.2f}%" if data.get('ReturnOnAssetsTTM_normalized') else '',
                        f"{data.get('ReturnOnEquityTTM_normalized', 0)*100:.2f}%" if data.get('ReturnOnEquityTTM_normalized') else '',
                        data.get('RevenuePerShareTTM_normalized', '')
                    ]
                }
                pd.DataFrame(financial_data).to_excel(writer, sheet_name='2_Metricas_Financieras', index=False)

                # HOJA 3: VALORACIÓN Y RATIOS COMPLETOS
                valuation_data = {
                    'Ratio': ['P/E Ratio', 'P/E Trailing', 'P/E Forward', 'PEG Ratio', 'Price/Book',
                             'Price/Sales', 'EV/Revenue', 'EV/EBITDA', 'Beta'],
                    'Valor': [
                        data.get('PERatio_normalized', ''),
                        data.get('TrailingPE_normalized', ''),
                        data.get('ForwardPE_normalized', ''),
                        data.get('PEGRatio_normalized', ''),
                        data.get('PriceToBookRatio_normalized', ''),
                        data.get('PriceToSalesRatioTTM_normalized', ''),
                        data.get('EVToRevenue_normalized', ''),
                        data.get('EVToEBITDA_normalized', ''),
                        data.get('Beta_normalized', '')
                    ],
                    'Interpretación': [
                        analysis['metricas_valoracion'].get('valoracion_resumen', ''),
                        'Ratio P/E basado en ganancias históricas',
                        'Ratio P/E basado en proyecciones',
                        'Ratio PEG para evaluar crecimiento vs precio',
                        'Ratio precio vs valor en libros',
                        'Ratio precio vs ventas',
                        'Enterprise Value vs ingresos',
                        'Enterprise Value vs EBITDA',
                        analysis['analisis_tecnico'].get('volatilidad_clasificacion', '')
                    ]
                }
                pd.DataFrame(valuation_data).to_excel(writer, sheet_name='3_Valoracion_Ratios', index=False)

                # HOJA 4: ANÁLISIS TÉCNICO COMPLETO
                technical_data = {
                    'Indicador Técnico': ['Precio 52 Sem Alto', 'Precio 52 Sem Bajo', 'Media Móvil 50 Días',
                                         'Media Móvil 200 Días', 'Beta', 'Clasificación Volatilidad'],
                    'Valor': [
                        f"${data.get('52WeekHigh_normalized', 0):.2f}" if data.get('52WeekHigh_normalized') else '',
                        f"${data.get('52WeekLow_normalized', 0):.2f}" if data.get('52WeekLow_normalized') else '',
                        f"${data.get('50DayMovingAverage_normalized', 0):.2f}" if data.get('50DayMovingAverage_normalized') else '',
                        f"${data.get('200DayMovingAverage_normalized', 0):.2f}" if data.get('200DayMovingAverage_normalized') else '',
                        data.get('Beta_normalized', ''),
                        analysis['analisis_tecnico'].get('volatilidad_clasificacion', '')
                    ]
                }
                pd.DataFrame(technical_data).to_excel(writer, sheet_name='4_Analisis_Tecnico', index=False)

                # HOJA 5: ANÁLISIS DE ANALISTAS COMPLETO
                analyst_data = {
                    'Rating': ['Strong Buy', 'Buy', 'Hold', 'Sell', 'Strong Sell', 'TOTAL', 'Consenso'],
                    'Cantidad': [
                        data.get('AnalystRatingStrongBuy_normalized', 0),
                        data.get('AnalystRatingBuy_normalized', 0),
                        data.get('AnalystRatingHold_normalized', 0),
                        data.get('AnalystRatingSell_normalized', 0),
                        data.get('AnalystRatingStrongSell_normalized', 0),
                        analysis['analisis_analistas'].get('total_analistas', 0),
                        analysis['analisis_analistas'].get('consenso', '')
                    ],
                    'Precio Objetivo': [
                        f"${data.get('AnalystTargetPrice_normalized', 0):.2f}" if data.get('AnalystTargetPrice_normalized') else '',
                        '', '', '', '', '',
                        f"${data.get('AnalystTargetPrice_normalized', 0):.2f}" if data.get('AnalystTargetPrice_normalized') else ''
                    ]
                }
                pd.DataFrame(analyst_data).to_excel(writer, sheet_name='5_Analistas', index=False)

                # HOJA 6: DIVIDENDOS Y CRECIMIENTO
                dividend_growth_data = {
                    'Concepto': ['Dividendo por Acción', 'Yield de Dividendo', 'Fecha Dividendo', 'Ex-Dividendo',
                                'Clasificación Dividendo', 'Crecimiento Ganancias YoY', 'Crecimiento Ingresos YoY',
                                'Clasificación Crecimiento'],
                    'Valor': [
                        f"${data.get('DividendPerShare_normalized', 0):.2f}" if data.get('DividendPerShare_normalized') else 'No paga',
                        f"{data.get('DividendYield_normalized', 0)*100:.2f}%" if data.get('DividendYield_normalized') else 'No paga',
                        data.get('DividendDate', 'N/A'),
                        data.get('ExDividendDate', 'N/A'),
                        analysis['dividendos'].get('dividend_clasificacion', ''),
                        f"{data.get('QuarterlyEarningsGrowthYOY_normalized', 0)*100:.2f}%" if data.get('QuarterlyEarningsGrowthYOY_normalized') else '',
                        f"{data.get('QuarterlyRevenueGrowthYOY_normalized', 0)*100:.2f}%" if data.get('QuarterlyRevenueGrowthYOY_normalized') else '',
                        analysis['metricas_crecimiento'].get('crecimiento_clasificacion', '')
                    ]
                }
                pd.DataFrame(dividend_growth_data).to_excel(writer, sheet_name='6_Dividendos_Crecimiento', index=False)

                # HOJA 7: ESTRUCTURA CORPORATIVA
                corporate_data = {
                    'Aspecto Corporativo': ['% Insiders', '% Instituciones', 'Score Governance'],
                    'Valor': [
                        f"{data.get('PercentInsiders_normalized', 0)*100:.2f}%" if data.get('PercentInsiders_normalized') else '',
                        f"{data.get('PercentInstitutions_normalized', 0)*100:.2f}%" if data.get('PercentInstitutions_normalized') else '',
                        analysis['estructura_corporativa'].get('governance_score', '')
                    ]
                }
                pd.DataFrame(corporate_data).to_excel(writer, sheet_name='7_Estructura_Corp', index=False)

                # HOJA 8: DESCRIPCIÓN COMPLETA
                description_data = {
                    'Descripción Original': [data.get('Description', 'No disponible')],
                    'Descripción en Español': [data.get('Description_es', 'No disponible')]
                }
                pd.DataFrame(description_data).to_excel(writer, sheet_name='8_Descripcion', index=False)

            logger.info(f"Excel COMPLETO generado: {filename}")

        except Exception as e:
            logger.error(f"Error generando Excel completo: {e}")

    def process_crypto(self, symbol: str) -> Dict:
        """Procesar una criptomoneda con TODOS los datos"""
        logger.info(f" PROCESAMIENTO COMPLETO para cripto: {symbol}")

        raw_data = self._make_api_request('DIGITAL_CURRENCY_DAILY', symbol)
        if not raw_data:
            return {'error': f'No se pudieron obtener datos de crypto para {symbol}'}

        try:
            meta_data = raw_data.get('Meta Data', {})
            time_series = raw_data.get('Time Series (Digital Currency Daily)', {})

            if not time_series:
                return {'error': f'No hay datos de series de tiempo para {symbol}'}

            latest_date = max(time_series.keys())
            latest_data = time_series[latest_date]

            processed_data = {
                'Symbol': symbol,
                'AssetType': 'Cryptocurrency',
                'Name': f'{symbol} Cryptocurrency',
                'Description': f'Datos diarios de la criptomoneda {symbol}',
                'Currency': 'USD',
                'LatestDate': latest_date,
                'OpenPrice': latest_data.get('1. open'),
                'HighPrice': latest_data.get('2. high'),
                'LowPrice': latest_data.get('3. low'),
                'ClosePrice': latest_data.get('4. close'),
                'Volume': latest_data.get('5. volume'),
                'MarketCap': latest_data.get('6. market cap (USD)'),
                'CurrencyCode': meta_data.get('2. Digital Currency Code'),
                'CurrencyName': meta_data.get('3. Digital Currency Name'),
                'MarketCode': meta_data.get('4. Market Code'),
                'MarketName': meta_data.get('5. Market Name'),
                'LastRefreshed': meta_data.get('6. Last Refreshed'),
                'TimeZone': meta_data.get('7. Time Zone')
            }

            data = self._translate_all_text_fields(processed_data)

            crypto_numeric_fields = ['OpenPrice', 'HighPrice', 'LowPrice', 'ClosePrice', 'Volume', 'MarketCap']
            for field in crypto_numeric_fields:
                if field in data and data[field]:
                    try:
                        data[f"{field}_normalized"] = float(data[field])
                    except (ValueError, TypeError):
                        data[f"{field}_normalized"] = None

            analysis = self._generate_crypto_analysis(data)

            result = {**data, **analysis, 'asset_type': 'cryptocurrency'}
            logger.info(f" Procesamiento COMPLETO de crypto terminado para {symbol}")
            return result

        except Exception as e:
            logger.error(f"Error procesando crypto {symbol}: {e}")
            return {'error': str(e), 'symbol': symbol}

    def process_forex(self, from_currency: str, to_currency: str) -> Dict:
        """Procesar un par de forex con TODOS los datos"""
        logger.info(f" PROCESAMIENTO COMPLETO para forex: {from_currency}/{to_currency}")

        # Hacer request para datos de forex
        raw_data = self._make_api_request('CURRENCY_EXCHANGE_RATE', None, from_currency, to_currency)
        if not raw_data:
            return {'error': f'No se pudieron obtener datos de forex para {from_currency}/{to_currency}'}

        try:
            forex_data = raw_data.get('Realtime Currency Exchange Rate', {})

            if not forex_data:
                return {'error': f'No hay datos de forex para {from_currency}/{to_currency}'}

            # Crear estructura de datos
            processed_data = {
                'Symbol': f'{from_currency}/{to_currency}',
                'AssetType': 'Currency Exchange',
                'Name': f'{forex_data.get("2. From_Currency Name", from_currency)} to {forex_data.get("4. To_Currency Name", to_currency)}',
                'Description': f'Tasa de cambio en tiempo real de {from_currency} a {to_currency}',
                'FromCurrencyCode': forex_data.get('1. From_Currency Code'),
                'FromCurrencyName': forex_data.get('2. From_Currency Name'),
                'ToCurrencyCode': forex_data.get('3. To_Currency Code'),
                'ToCurrencyName': forex_data.get('4. To_Currency Name'),
                'ExchangeRate': forex_data.get('5. Exchange Rate'),
                'LastRefreshed': forex_data.get('6. Last Refreshed'),
                'TimeZone': forex_data.get('7. Time Zone'),
                'BidPrice': forex_data.get('8. Bid Price'),
                'AskPrice': forex_data.get('9. Ask Price')
            }

            # Traducir campos
            data = self._translate_all_text_fields(processed_data)

            # Normalizar campos numéricos específicos de forex
            forex_numeric_fields = ['ExchangeRate', 'BidPrice', 'AskPrice']
            for field in forex_numeric_fields:
                if field in data and data[field]:
                    try:
                        data[f"{field}_normalized"] = float(data[field])
                    except (ValueError, TypeError):
                        data[f"{field}_normalized"] = None

            # Generar análisis específico para forex
            analysis = self._generate_forex_analysis(data)

            result = {**data, **analysis, 'asset_type': 'forex'}
            logger.info(f" Procesamiento COMPLETO de forex terminado para {from_currency}/{to_currency}")
            return result

        except Exception as e:
            logger.error(f"Error procesando forex {from_currency}/{to_currency}: {e}")
            return {'error': str(e), 'symbol': f'{from_currency}/{to_currency}'}

    def _generate_crypto_analysis(self, data: Dict) -> Dict:
        """Generar análisis específico para criptomonedas"""
        analysis = {
            'fecha_analisis_crypto': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'precio_actual': data.get('ClosePrice_normalized'),
            'precio_alto_24h': data.get('HighPrice_normalized'),
            'precio_bajo_24h': data.get('LowPrice_normalized'),
            'volumen_24h': data.get('Volume_normalized'),
            'market_cap': data.get('MarketCap_normalized'),
            'volatilidad_diaria': None,
            'clasificacion_crypto': 'Activo Digital'
        }

        try:
            if (data.get('HighPrice_normalized') and data.get('LowPrice_normalized') and
                data.get('ClosePrice_normalized')):
                high = data['HighPrice_normalized']
                low = data['LowPrice_normalized']
                close = data['ClosePrice_normalized']

                volatilidad = ((high - low) / close) * 100 if close > 0 else 0
                analysis['volatilidad_diaria'] = round(volatilidad, 2)

                if volatilidad > 10:
                    analysis['clasificacion_volatilidad'] = 'Muy Alta Volatilidad'
                elif volatilidad > 5:
                    analysis['clasificacion_volatilidad'] = 'Alta Volatilidad'
                elif volatilidad > 2:
                    analysis['clasificacion_volatilidad'] = 'Volatilidad Moderada'
                else:
                    analysis['clasificacion_volatilidad'] = 'Baja Volatilidad'
        except:
            pass

        return analysis

    def _generate_forex_analysis(self, data: Dict) -> Dict:
        """Generar análisis específico para forex"""
        analysis = {
            'fecha_analisis_forex': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'tasa_cambio': data.get('ExchangeRate_normalized'),
            'spread': None,
            'clasificacion_par': 'Par de Divisas'
        }

        # Calcular spread si tenemos bid y ask
        try:
            if data.get('BidPrice_normalized') and data.get('AskPrice_normalized'):
                bid = data['BidPrice_normalized']
                ask = data['AskPrice_normalized']
                spread = ask - bid
                analysis['spread'] = round(spread, 6)
                analysis['spread_percentage'] = round((spread / ask) * 100, 4) if ask > 0 else 0
        except:
            pass

        return analysis

    def process_stock(self, symbol: str) -> Dict:
        """Procesar una acción con TODOS los datos"""
        logger.info(f" PROCESAMIENTO COMPLETO para acción: {symbol}")

        # Hacer request para obtener TODOS los datos
        raw_data = self._make_api_request('OVERVIEW', symbol)
        if not raw_data:
            return {'error': f'No se pudieron obtener datos para {symbol}'}

        # Traducir TODOS los campos de texto
        data = self._translate_all_text_fields(raw_data)

        # Normalizar TODOS los campos numéricos
        data = self._normalize_all_numeric_fields(data)

        analysis = self._generate_complete_analysis(data)

        result = {**data, **analysis, 'asset_type': 'stock'}

        self._generate_complete_excel(data, analysis, symbol)

        logger.info(f" Procesamiento COMPLETO terminado para {symbol}")
        return result

    def process_all_assets_consolidated(self, stocks: List[str], cryptos: List[str],
                                      forex_pairs: List[tuple]) -> Dict:
        """Procesar TODOS los activos y consolidar en UN SOLO EXCEL"""
        logger.info(" PROCESAMIENTO CONSOLIDADO DE TODOS LOS ACTIVOS")

        all_results = {
            'stocks': [],
            'cryptos': [],
            'forex': [],
            'summary': {
                'total_assets': 0,
                'successful': 0,
                'failed': 0,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        }

        # Procesar acciones
        logger.info(f" Procesando {len(stocks)} acciones...")
        for stock in stocks:
            try:
                result = self.process_stock(stock)
                if 'error' not in result:
                    all_results['stocks'].append(result)
                    all_results['summary']['successful'] += 1
                else:
                    logger.error(f"Error en acción {stock}: {result['error']}")
                    all_results['summary']['failed'] += 1
                time.sleep(12)  # Rate limit
            except Exception as e:
                logger.error(f"Error procesando acción {stock}: {e}")
                all_results['summary']['failed'] += 1

        # Procesar criptomonedas
        logger.info(f" Procesando {len(cryptos)} criptomonedas...")
        for crypto in cryptos:
            try:
                result = self.process_crypto(crypto)
                if 'error' not in result:
                    all_results['cryptos'].append(result)
                    all_results['summary']['successful'] += 1
                else:
                    logger.error(f"Error en crypto {crypto}: {result['error']}")
                    all_results['summary']['failed'] += 1
                time.sleep(12)  # Rate limit
            except Exception as e:
                logger.error(f"Error procesando crypto {crypto}: {e}")
                all_results['summary']['failed'] += 1

        # Procesar forex
        logger.info(f" Procesando {len(forex_pairs)} pares de forex...")
        for from_curr, to_curr in forex_pairs:
            try:
                result = self.process_forex(from_curr, to_curr)
                if 'error' not in result:
                    all_results['forex'].append(result)
                    all_results['summary']['successful'] += 1
                else:
                    logger.error(f"Error en forex {from_curr}/{to_curr}: {result['error']}")
                    all_results['summary']['failed'] += 1
                time.sleep(12)  # Rate limit
            except Exception as e:
                logger.error(f"Error procesando forex {from_curr}/{to_curr}: {e}")
                all_results['summary']['failed'] += 1

        all_results['summary']['total_assets'] = len(stocks) + len(cryptos) + len(forex_pairs)

        # Generar Excel CONSOLIDADO
        self._generate_consolidated_excel(all_results)

        logger.info(" PROCESAMIENTO CONSOLIDADO COMPLETO")
        return all_results

    def _generate_consolidated_excel(self, all_results: Dict) -> None:
        """Generar UN SOLO Excel con TODOS los activos consolidados"""
        filename = "outputs/ALPHAVANTAGE_CONSOLIDADO_COMPLETO.xlsx"

        try:
            with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                summary_data = {
                    'Métrica': ['Fecha de Análisis', 'Total de Activos', 'Procesados Exitosamente',
                               'Fallos', 'Acciones Analizadas', 'Criptomonedas Analizadas',
                               'Pares Forex Analizados'],
                    'Valor': [
                        all_results['summary']['timestamp'],
                        all_results['summary']['total_assets'],
                        all_results['summary']['successful'],
                        all_results['summary']['failed'],
                        len(all_results['stocks']),
                        len(all_results['cryptos']),
                        len(all_results['forex'])
                    ]
                }
                pd.DataFrame(summary_data).to_excel(writer, sheet_name='0_RESUMEN_EJECUTIVO', index=False)

                if all_results['stocks']:
                    stocks_consolidated = []
                    for stock in all_results['stocks']:
                        stock_row = {
                            'Símbolo': stock.get('Symbol', ''),
                            'Nombre': stock.get('Name', ''),
                            'Nombre_ES': stock.get('Name_es', ''),
                            'Sector': stock.get('Sector', ''),
                            'Sector_ES': stock.get('Sector_es', ''),
                            'Industria': stock.get('Industry', ''),
                            'Industria_ES': stock.get('Industry_es', ''),
                            'Market_Cap_USD': stock.get('MarketCapitalization_normalized', ''),
                            'Market_Cap_Formateado': stock.get('analisis_fundamental', {}).get('market_cap_formatted', ''),
                            'P/E_Ratio': stock.get('PERatio_normalized', ''),
                            'Beta': stock.get('Beta_normalized', ''),
                            'ROE_Pct': f"{stock.get('ReturnOnEquityTTM_normalized', 0)*100:.2f}%" if stock.get('ReturnOnEquityTTM_normalized') else '',
                            'Dividend_Yield_Pct': f"{stock.get('DividendYield_normalized', 0)*100:.2f}%" if stock.get('DividendYield_normalized') else '',
                            'Total_Analistas': stock.get('analisis_analistas', {}).get('total_analistas', ''),
                            'Consenso_Analistas': stock.get('analisis_analistas', {}).get('consenso', ''),
                            'Precio_Objetivo': f"${stock.get('AnalystTargetPrice_normalized', 0):.2f}" if stock.get('AnalystTargetPrice_normalized') else '',
                            'Clasificación_Rentabilidad': stock.get('metricas_rentabilidad', {}).get('rentabilidad_clasificacion', ''),
                            'Clasificación_Volatilidad': stock.get('analisis_tecnico', {}).get('volatilidad_clasificacion', ''),
                            'Valoración_Resumen': stock.get('metricas_valoracion', {}).get('valoracion_resumen', ''),
                            'Revenue_TTM': self._format_large_number(stock.get('RevenueTTM_normalized')),
                            'Profit_Margin_Pct': f"{stock.get('ProfitMargin_normalized', 0)*100:.2f}%" if stock.get('ProfitMargin_normalized') else '',
                            'Precio_52W_Alto': f"${stock.get('52WeekHigh_normalized', 0):.2f}" if stock.get('52WeekHigh_normalized') else '',
                            'Precio_52W_Bajo': f"${stock.get('52WeekLow_normalized', 0):.2f}" if stock.get('52WeekLow_normalized') else '',
                            'País': stock.get('Country', ''),
                            'Bolsa': stock.get('Exchange', ''),
                            'Sitio_Web': stock.get('OfficialSite', '')
                        }
                        stocks_consolidated.append(stock_row)

                    pd.DataFrame(stocks_consolidated).to_excel(writer, sheet_name='1_ACCIONES_TODAS', index=False)

                if all_results['cryptos']:
                    cryptos_consolidated = []
                    for crypto in all_results['cryptos']:
                        crypto_row = {
                            'Símbolo': crypto.get('Symbol', ''),
                            'Nombre': crypto.get('Name', ''),
                            'Nombre_ES': crypto.get('Name_es', ''),
                            'Precio_Actual': f"${crypto.get('ClosePrice_normalized', 0):,.2f}" if crypto.get('ClosePrice_normalized') else '',
                            'Precio_Alto_24h': f"${crypto.get('HighPrice_normalized', 0):,.2f}" if crypto.get('HighPrice_normalized') else '',
                            'Precio_Bajo_24h': f"${crypto.get('LowPrice_normalized', 0):,.2f}" if crypto.get('LowPrice_normalized') else '',
                            'Volumen_24h': f"{crypto.get('Volume_normalized', 0):,.0f}" if crypto.get('Volume_normalized') else '',
                            'Market_Cap_USD': self._format_large_number(crypto.get('MarketCap_normalized')),
                            'Volatilidad_Diaria_Pct': f"{crypto.get('volatilidad_diaria', 0):.2f}%" if crypto.get('volatilidad_diaria') else '',
                            'Clasificación_Volatilidad': crypto.get('clasificacion_volatilidad', ''),
                            'Fecha_Datos': crypto.get('LatestDate', ''),
                            'Última_Actualización': crypto.get('LastRefreshed', ''),
                            'Zona_Horaria': crypto.get('TimeZone', ''),
                            'Código_Moneda': crypto.get('CurrencyCode', ''),
                            'Nombre_Moneda': crypto.get('CurrencyName', '')
                        }
                        cryptos_consolidated.append(crypto_row)

                    pd.DataFrame(cryptos_consolidated).to_excel(writer, sheet_name='2_CRIPTOS_TODAS', index=False)

                # HOJA 4: TODOS LOS PARES FOREX CONSOLIDADOS
                if all_results['forex']:
                    forex_consolidated = []
                    for forex in all_results['forex']:
                        forex_row = {
                            'Par': forex.get('Symbol', ''),
                            'Nombre': forex.get('Name', ''),
                            'Nombre_ES': forex.get('Name_es', ''),
                            'Moneda_Origen': forex.get('FromCurrencyCode', ''),
                            'Nombre_Moneda_Origen': forex.get('FromCurrencyName', ''),
                            'Moneda_Destino': forex.get('ToCurrencyCode', ''),
                            'Nombre_Moneda_Destino': forex.get('ToCurrencyName', ''),
                            'Tasa_Cambio': forex.get('ExchangeRate_normalized', ''),
                            'Precio_Bid': forex.get('BidPrice_normalized', ''),
                            'Precio_Ask': forex.get('AskPrice_normalized', ''),
                            'Spread': forex.get('spread', ''),
                            'Spread_Porcentaje': f"{forex.get('spread_percentage', 0):.4f}%" if forex.get('spread_percentage') else '',
                            'Última_Actualización': forex.get('LastRefreshed', ''),
                            'Zona_Horaria': forex.get('TimeZone', '')
                        }
                        forex_consolidated.append(forex_row)

                    pd.DataFrame(forex_consolidated).to_excel(writer, sheet_name='3_FOREX_TODOS', index=False)

                if all_results['stocks']:
                    comparative_stocks = []
                    for stock in all_results['stocks']:
                        comp_row = {
                            'Símbolo': stock.get('Symbol', ''),
                            'Nombre_ES': stock.get('Name_es', ''),
                            'Market_Cap_Billones': stock.get('MarketCapitalization_normalized', 0) / 1e12 if stock.get('MarketCapitalization_normalized') else 0,
                            'P/E_Ratio': stock.get('PERatio_normalized', ''),
                            'ROE_Decimal': stock.get('ReturnOnEquityTTM_normalized', ''),
                            'Beta': stock.get('Beta_normalized', ''),
                            'Profit_Margin_Decimal': stock.get('ProfitMargin_normalized', ''),
                            'Revenue_Billones': stock.get('RevenueTTM_normalized', 0) / 1e12 if stock.get('RevenueTTM_normalized') else 0,
                            'Total_Analistas': stock.get('analisis_analistas', {}).get('total_analistas', ''),
                            'Strong_Buy': stock.get('analisis_analistas', {}).get('strong_buy', ''),
                            'Buy': stock.get('analisis_analistas', {}).get('buy', ''),
                            'Hold': stock.get('analisis_analistas', {}).get('hold', ''),
                            'Sell': stock.get('analisis_analistas', {}).get('sell', ''),
                            'Consenso': stock.get('analisis_analistas', {}).get('consenso', '')
                        }
                        comparative_stocks.append(comp_row)

                    pd.DataFrame(comparative_stocks).to_excel(writer, sheet_name='4_COMPARATIVO_ACCIONES', index=False)

                if all_results['stocks']:
                    raw_stocks_data = []
                    for stock in all_results['stocks']:
                        flat_data = {'Símbolo': stock.get('Symbol', '')}

                        for key, value in stock.items():
                            if key not in ['analisis_fundamental', 'analisis_tecnico', 'analisis_analistas',
                                          'metricas_valoracion', 'metricas_rentabilidad', 'metricas_crecimiento',
                                          'dividendos', 'estructura_corporativa']:
                                flat_data[key] = value

                        for analysis_key in ['analisis_fundamental', 'analisis_tecnico', 'analisis_analistas',
                                           'metricas_valoracion', 'metricas_rentabilidad', 'metricas_crecimiento',
                                           'dividendos', 'estructura_corporativa']:
                            if analysis_key in stock and isinstance(stock[analysis_key], dict):
                                for sub_key, sub_value in stock[analysis_key].items():
                                    flat_data[f"{analysis_key}_{sub_key}"] = sub_value

                        raw_stocks_data.append(flat_data)

                    pd.DataFrame(raw_stocks_data).to_excel(writer, sheet_name='5_RAW_ACCIONES_COMPLETO', index=False)

                if all_results['cryptos']:
                    raw_crypto_data = []
                    for crypto in all_results['cryptos']:
                        flat_crypto = {'Símbolo': crypto.get('Symbol', '')}
                        for key, value in crypto.items():
                            flat_crypto[key] = value
                        raw_crypto_data.append(flat_crypto)

                    pd.DataFrame(raw_crypto_data).to_excel(writer, sheet_name='6_RAW_CRYPTOS_COMPLETO', index=False)

                if all_results['forex']:
                    raw_forex_data = []
                    for forex in all_results['forex']:
                        flat_forex = {'Par': forex.get('Symbol', '')}
                        for key, value in forex.items():
                            flat_forex[key] = value
                        raw_forex_data.append(flat_forex)

                    pd.DataFrame(raw_forex_data).to_excel(writer, sheet_name='7_RAW_FOREX_COMPLETO', index=False)

            logger.info(f"Excel CONSOLIDADO generado: {filename}")

        except Exception as e:
            logger.error(f"Error generando Excel consolidado: {e}")
            raise

def procesar_alpha_vantage(symbol: str) -> Dict:
    """
    Función principal para procesar un símbolo según especificaciones de CLAUDE.md

    Flujo:
    1. Hacer request a Alpha Vantage OVERVIEW API
    2. Validar respuesta y manejo de errores
    3. Extraer campos relevantes
    4. Normalizar porcentajes
    5. Traducir campos al español
    6. Generar Excel
    7. Retornar diccionario estructurado

    Returns:
        Dict con estructura definida en CLAUDE.md
    """
    try:
        processor = AlphaVantageCompleteProcessor()
        result = processor.process_stock(symbol)

        if 'error' in result:
            return result

        output = {
            'symbol': result.get('Symbol', ''),
            'name': result.get('Name', ''),
            'description_es': result.get('Description_es', ''),
            'sector_es': result.get('Sector_es', ''),
            'industry_es': result.get('Industry_es', ''),
            'market_cap': result.get('MarketCapitalization_normalized'),
            'pe_ratio': result.get('PERatio_normalized'),
            'dividend_yield': result.get('DividendYield_normalized'),  # Ya normalizado (decimal)
            'beta': result.get('Beta_normalized'),
            'country': result.get('Country', ''),
            'currency': result.get('Currency', ''),
            'exchange': result.get('Exchange', ''),
            'roe': result.get('ReturnOnEquityTTM_normalized'),
            'profit_margin': result.get('ProfitMargin_normalized'),
            'revenue_ttm': result.get('RevenueTTM_normalized'),
            'eps': result.get('EPS_normalized'),
            'fecha_procesamiento': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'analisis_completo': {
                'valoracion': result.get('metricas_valoracion', {}),
                'rentabilidad': result.get('metricas_rentabilidad', {}),
                'tecnico': result.get('analisis_tecnico', {}),
                'analistas': result.get('analisis_analistas', {})
            }
        }

        logger.info(f"Procesamiento completado para {symbol}")
        return output

    except Exception as e:
        logger.error(f"Error en procesamiento: {e}")
        return {'error': str(e), 'symbol': symbol}

def procesar_alpha_vantage_completo(symbol: str) -> Dict:
    """Función principal para procesar COMPLETAMENTE un símbolo de Alpha Vantage"""
    try:
        processor = AlphaVantageCompleteProcessor()
        return processor.process_stock(symbol)
    except Exception as e:
        logger.error(f"Error en procesamiento completo: {e}")
        return {'error': str(e), 'symbol': symbol}

def procesar_todos_los_activos_alphavantage() -> Dict:
    """Procesar TODOS los activos de Alpha Vantage en UN SOLO Excel"""
    try:
        processor = AlphaVantageCompleteProcessor()

        # TODOS los activos que vas a procesar - datos REALES
        stocks_list = ['AAPL', 'MSFT', 'GOOGL', 'TSLA', 'DIS', 'NVDA', 'AMZN', 'META']
        cryptos_list = ['BTC', 'ETH', 'ADA', 'DOT', 'LTC', 'XRP']
        forex_pairs_list = [
            ('USD', 'EUR'),
            ('USD', 'CLP'),
            ('USD', 'JPY'),
            ('EUR', 'CLP'),
            ('GBP', 'USD'),
            ('USD', 'CAD')
        ]

        logger.info(" INICIANDO PROCESAMIENTO COMPLETO DE TODOS LOS ACTIVOS ALPHA VANTAGE")
        logger.info(f" Acciones: {len(stocks_list)} |  Cryptos: {len(cryptos_list)} |  Forex: {len(forex_pairs_list)}")

        return processor.process_all_assets_consolidated(stocks_list, cryptos_list, forex_pairs_list)

    except Exception as e:
        logger.error(f"Error en procesamiento completo de todos los activos: {e}")
        return {'error': str(e)}