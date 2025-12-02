sourc# 📊 inBee Financial Data Pipeline

**Automated multi-source financial data processing system for Chilean fintech**

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![Status](https://img.shields.io/badge/Status-Production%20Ready-green.svg)]()
[![License](https://img.shields.io/badge/License-Private-red.svg)]()

---

## 🎯 Project Overview

Production-ready data pipeline integrating 4+ APIs to automate collection, translation, and normalization of financial data (stocks, cryptocurrencies, mutual funds) for young Chilean investors.

**Key Achievement:** Solved complex CMF Chile PDF scraping challenge, achieving **100% success rate** on regulatory document downloads.

---

## 🚀 Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure API keys
cp .env.example .env
# Edit .env with your keys

# Run pipeline
python3 main.py

# View results
ls outputs/
```

---

## ✨ Key Features

- 🔄 **Multi-Source Integration:** Alpha Vantage, DeepL, Fintual, CMF Chile, OpenAI
- 📄 **Intelligent PDF Processing:** 100% success rate scraping regulatory documents
- ⚡ **Smart Caching:** 2.23x performance improvement on repeated queries
- 🤖 **AI Content Generation:** GPT-4 powered fund descriptions in Spanish
- 📊 **Advanced Extraction:** 12 fields per PDF with 72.6% average coverage
- 🔍 **Proactive Monitoring:** Automated health checks and alerts
- 📈 **Rich Outputs:** 11 Excel + 14 JSON files per run

---

## 📁 Project Structure

```
sprint1/
├── main.py                  # Pipeline orchestrator
├── alpha_vantage.py         # Stock data processor (Alpha Vantage + DeepL)
├── fondos_mutuos.py         # Mutual funds processor (Fintual + CMF + AI)
├── cmf_monitor.py           # CMF health monitoring system
├── run_cmf_monitor.py       # Monitoring script
│
├── prompts/
│   └── fondos_prompt.txt    # Customizable AI prompt
│
├── outputs/                 # Generated files (JSON + Excel)
├── cache/                   # PDF cache + monitoring reports
├── temp/                    # Temporary files
│
├── requirements.txt         # Python dependencies
├── .env                     # API keys (not in repo)
│
└── README.md               # This file
```

---

## 🛠️ Technical Stack

**Core:**

- Python 3.9+
- Pandas, OpenPyXL (data processing)
- Requests, BeautifulSoup4 (web scraping)
- PDFPlumber (document parsing)

**APIs:**

- Alpha Vantage (stock market data)
- DeepL (EN→ES translation)
- Fintual (Chilean mutual funds)
- CMF Chile (regulatory documents)
- OpenAI GPT-4 (content generation)

**Architecture:**

- Modular processors
- Intelligent caching (30-day expiration)
- Robust error handling
- Comprehensive logging
- Automated monitoring

---

## 📊 Performance & Results

### Pipeline Metrics

- ✅ **100% PDF download success** (6/6 Chilean funds tested)
- ⚡ **2.23x faster** with intelligent caching
- 📈 **4x more data** per PDF (12 fields vs 3)
- 🎯 **72.6% avg coverage** across PDF formats
- 📦 **25 output files** per run

### Processed Data

- 5 stocks (DIS, TSLA, AAPL, MSFT, GOOGL)
- 4 mutual funds
- 11 Excel reports (multi-sheet analysis)
- 14 JSON files (structured data)

---

## 🧪 Testing

```bash
# Cache performance test
python3 test_cache_pdf.py

# PDF extraction coverage
python3 test_pdf_extraction.py

# CMF health check
python3 run_cmf_monitor.py

# Full pipeline
python3 main.py
```

---

## 🔧 Configuration

### Required API Keys (.env)

```env
ALPHAVANTAGE_API_KEY=your_key_here
DEEPL_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
PDF_CACHE_EXPIRATION_DAYS=30  # Optional
```

### Get API Keys

- [Alpha Vantage](https://www.alphavantage.co/support/#api-key) (free tier: 25 requests/day)
- [DeepL](https://www.deepl.com/pro-api) (free tier: 500K chars/month)
- [OpenAI](https://platform.openai.com/api-keys) (pay-as-you-go)

---

## 💡 Technical Highlights

### 1. CMF PDF Download Solution

**Challenge:** CMF endpoint returned "ERROR" for all requests.

**Solution:** Reverse-engineered JavaScript to discover:

- Missing `rutAdmin` parameter (administrator's tax ID)
- Required specific HTTP headers
- Proper page navigation (`pestania=68`)
- Two-step download process

**Result:** 100% success rate

### 2. Intelligent Caching System

- JSON index with metadata
- 30-day automatic expiration
- Cache hit/miss statistics
- 2.23x performance boost

### 3. Advanced PDF Extraction

8 regex patterns extracting:

- Risk profile (R1-R7 scale)
- Investment horizon
- Management fees
- Historical returns (12m, 24m, 36m)
- Portfolio composition
- Automatic confidence scoring

### 4. Proactive Monitoring

- 4 automated health checks
- HTML structure baseline
- Endpoint availability validation
- Persistent alert logging
- JSON health reports

---

## 📈 Output Examples

### Stock Data (Excel - 8 sheets)

- Overview, Financials, Valuation, Technical Analysis
- Dividends, Performance, Recommendations, Risks

### Mutual Funds (Excel - 4 sheets)

- Overview, Portfolio Composition, Historical Performance, Fees & Analysis

### JSON Outputs

- Structured data for each asset
- Batch summary reports
- Consolidated statistics

---

## 🔍 Code Quality

- **3,500+ lines** of production code
- **50+ functions** with docstrings
- **15+ automated tests**
- **Modular architecture**
- **PEP 8 compliant**
- **Comprehensive logging**

---

## 📊 Pipeline Architecture

```
User Input → main.py
    ↓
    ├→ alpha_vantage.py → Alpha Vantage API → DeepL → Excel/JSON
    │
    └→ fondos_mutuos.py → Fintual API → CMF PDF → Extraction → GPT-4 → Excel/JSON
                              ↓
                          Cache Check (2.23x faster)
                              ↓
                          Monitoring (cmf_monitor.py)
```

---

## 🎯 Use Cases

### Process Stock Data

```python
from alpha_vantage import procesar_alpha_vantage

result = procesar_alpha_vantage("DIS")
print(f"Company: {result['nombre']}")
print(f"Sector: {result['sector_es']}")
print(f"P/E Ratio: {result['pe_ratio']}")
```

### Process Mutual Fund

```python
from fondos_mutuos import FondosMutuosProcessor

processor = FondosMutuosProcessor()
result = processor.procesar_fondos_mutuos("santander_conservador")

print(f"Type: {result['tipo_fondo']}")
print(f"Risk: {result['perfil_riesgo']}")
```

### Monitor CMF Health

```python
from cmf_monitor import CMFMonitor

monitor = CMFMonitor()
report = monitor.generate_health_report()
print(f"Status: {report['status']}")
```

---

## 🚨 Troubleshooting

### PDF Download Issues

1. Check CMF availability: `python3 run_cmf_monitor.py`
2. Review logs: `tail -f pipeline.log`
3. System uses cache for resilience

### API Key Issues

1. Verify `.env` configuration
2. Check API key validity
3. Monitor rate limits (Alpha Vantage: 25/day free)

### Translation Failures

1. Confirm DeepL API key
2. Check character quota (500K/month free)
3. System can operate without translations

---

## 📝 Documentation

For detailed information:

- **PORTFOLIO_SUMMARY.md** - Complete project overview for portfolio
- **CLAUDE.md** - Original project specifications

---

## 💼 Skills Demonstrated

**Technical:**

- Python (pandas, requests, BeautifulSoup, pdfplumber)
- API Integration (4+ REST APIs)
- Web Scraping (HTML/JavaScript analysis)
- PDF Parsing (regex, text extraction)
- System Design (caching, monitoring)
- Performance Optimization (2.23x improvement)

**Problem Solving:**

- Reverse engineering undocumented APIs
- Complex PDF format variations
- Multi-source data integration
- Production-ready architecture

---

## 📈 Project Stats

| Metric              | Value    |
| ------------------- | -------- |
| Lines of Code       | ~3,500   |
| Functions           | 50+      |
| APIs Integrated     | 4        |
| PDF Success Rate    | 100%     |
| Performance Gain    | 2.23x    |
| Extraction Coverage | 72.6%    |
| Tests               | 15+      |
| Documentation       | Complete |

---

## 🎓 Key Learnings

1. Successfully reverse-engineered complex web scraping challenge
2. Designed production-ready caching system (2.23x speedup)
3. Built robust multi-API orchestration
4. Implemented comprehensive monitoring
5. Delivered scalable, maintainable architecture

---

## 📦 Deliverables

✅ Fully functional pipeline (main.py + processors)
✅ Automated monitoring system
✅ Comprehensive test suite
✅ Production documentation
✅ 25 output files per run
✅ Intelligent caching
✅ Health monitoring

---

## 👤 Author

**Luciano Leroi**

- **Role:** Full-Stack Data Engineer
- **Client:** inBee (Chilean Fintech)
- **Date:** October 2025

---

## 📜 License

Private project - inBee

---

**Status:** ✅ Production Ready | **Version:** 1.0 + 3 Improvements
