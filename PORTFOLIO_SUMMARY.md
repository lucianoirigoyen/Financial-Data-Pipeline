# 📊 inBee Financial Data Pipeline

**Automated data processing system for Chilean fintech**

---

## 🎯 Project Overview

Developed a production-ready data pipeline for **inBee**, a Chilean fintech startup, to automate the collection, processing, and normalization of financial data from multiple sources (stocks, cryptocurrencies, and mutual funds) for young investors.

**Challenge:** Raw financial data from various APIs arrived in English, unstructured formats, requiring manual processing and translation.

**Solution:** Built an end-to-end Python pipeline integrating 4 APIs with intelligent caching, automated translation, PDF scraping, and AI-powered content generation.

---

## 🛠️ Technical Stack

**Core Technologies:**
- Python 3.9+
- Pandas, OpenPyXL (data processing)
- Requests, BeautifulSoup (web scraping)
- PDFPlumber (document parsing)

**APIs Integrated:**
- Alpha Vantage (stock market data)
- DeepL (automatic translation EN→ES)
- Fintual (Chilean mutual funds)
- CMF Chile (regulatory PDFs)
- OpenAI GPT-4 (content generation)

**Architecture:**
- Modular design with separate processors
- Intelligent caching system (2.23x performance boost)
- Robust error handling and logging
- Automated monitoring system

---

## ✨ Key Features

### 1. Multi-Source Data Integration
- **Stock Processing:** Alpha Vantage API → DeepL translation → normalized outputs
- **Mutual Funds:** Fintual API (3 layers) + CMF PDF scraping + AI descriptions
- **Smart Matching:** RUT-based identification system for Chilean funds

### 2. Intelligent PDF Processing
- **Automated Download:** 100% success rate scraping CMF regulatory PDFs
- **Data Extraction:** 8 advanced patterns extracting 12 fields per document
- **Pattern Recognition:** Fund type, risk profile, fees, historical returns, portfolio composition
- **Confidence Scoring:** Automatic validation (72.6% average coverage)

### 3. Performance Optimization
- **PDF Caching System:** 2.23x faster on repeated queries
- **Smart Expiration:** 30-day automatic cache management
- **Request Reduction:** 100% fewer redundant API calls
- **Statistics Tracking:** Hit/miss rates for monitoring

### 4. Proactive Monitoring
- **Health Checks:** 4 automated verification systems
- **Change Detection:** HTML structure baseline comparison
- **Alert System:** Persistent logging with severity levels
- **JSON Reports:** Structured health status outputs

### 5. AI-Powered Content
- **GPT-4 Integration:** Generates user-friendly fund descriptions
- **Editable Prompts:** Customizable templates for content generation
- **Spanish Output:** Tailored for Chilean young investors

---

## 📈 Results & Impact

**Performance Metrics:**
- ✅ **100% PDF download success rate** (6/6 Chilean mutual funds tested)
- ⚡ **2.23x faster** processing with intelligent caching
- 📊 **4x more data** extracted per PDF (12 fields vs 3 originally)
- 🎯 **72.6% coverage** across different PDF formats
- 🚀 **25 output files** generated per pipeline run (11 Excel + 14 JSON)

**Production Ready:**
- Zero manual intervention required
- Robust error handling for all edge cases
- Comprehensive logging for debugging
- Full documentation and testing suite

---

## 🎓 Technical Challenges Solved

### 1. CMF PDF Download Problem
**Challenge:** CMF Chile endpoint returned "ERROR" for all PDF requests.

**Solution:** Reverse-engineered the JavaScript `verFolleto()` function to discover:
- Missing `rutAdmin` parameter (fund administrator's tax ID)
- Required HTTP headers (User-Agent, X-Requested-With, Referer)
- Proper navigation to `pestania=68` (Informational Brochures section)
- Two-step process: POST for viewer URL → GET for actual PDF

**Result:** 100% success rate on PDF downloads.

### 2. Variable PDF Formats
**Challenge:** Different fund administrators use different PDF formats.

**Solution:** Implemented 8 regex patterns with fallback mechanisms:
- Risk scale detection (R1-R7 Chilean standard)
- Investment horizon parsing (short/medium/long term)
- Commission extraction with normalization
- Historical returns across multiple time periods
- Asset classification with automatic categorization

**Result:** 72.6% average coverage across diverse formats.

### 3. Performance Optimization
**Challenge:** Each fund processing took ~7 seconds with multiple HTTP requests.

**Solution:** Designed intelligent caching system:
- JSON index with metadata (download date, expiration, size)
- Automatic cleanup of expired PDFs
- Cache verification before downloading
- Statistics tracking for monitoring

**Result:** 2.23x performance improvement + 100% request reduction.

---

## 📊 Code Quality

- **3,500+ lines** of production-ready Python code
- **50+ functions** with comprehensive docstrings
- **15+ automated tests** covering critical paths
- **Modular architecture** for easy maintenance and scaling
- **PEP 8 compliant** with proper error handling
- **Detailed logging** at multiple severity levels

---

## 🔄 Pipeline Architecture

```
User Input → main.py (Orchestrator)
                ↓
    ┌───────────┴───────────┐
    ↓                       ↓
alpha_vantage.py    fondos_mutuos.py
    ↓                       ↓
Alpha Vantage API    Fintual API (3 layers)
    ↓                       ↓
DeepL Translation    CMF PDF Scraping
    ↓                       ↓
Normalization        Data Extraction
    ↓                       ↓
    └───────────┬───────────┘
                ↓
        Excel + JSON Outputs
        (11 Excel + 14 JSON)
```

---

## 🎯 Business Value

**For inBee:**
- Automated 100% of manual data collection process
- Reduced processing time from hours to minutes
- Enabled real-time data updates for app users
- Scalable foundation for adding new data sources

**For End Users:**
- Access to translated, normalized financial data
- AI-generated descriptions in clear Spanish
- Comprehensive mutual fund analysis
- Updated information without manual delays

---

## 🚀 Key Learnings

1. **Reverse Engineering:** Successfully decoded undocumented API behavior through HTML/JS analysis
2. **Pattern Recognition:** Developed robust regex patterns handling format variations
3. **System Design:** Built production-ready architecture with caching, monitoring, and alerting
4. **API Integration:** Orchestrated 4+ external APIs with proper error handling
5. **Performance Optimization:** Achieved 2.23x speedup through intelligent caching

---

## 📦 Deliverables

- ✅ Fully functional Python pipeline (main.py + 2 processors)
- ✅ Automated monitoring system (cmf_monitor.py)
- ✅ Comprehensive test suite (15+ tests)
- ✅ Production-ready documentation
- ✅ 25 output files per run (Excel + JSON)
- ✅ Intelligent caching system
- ✅ Health monitoring with alerts

---

## 💼 Skills Demonstrated

**Technical:**
- Python (pandas, requests, BeautifulSoup, pdfplumber)
- API Integration (REST APIs, rate limiting, auth)
- Web Scraping (HTML parsing, JavaScript analysis)
- Data Processing (normalization, transformation)
- PDF Parsing (regex patterns, text extraction)
- System Design (caching, monitoring, error handling)
- Performance Optimization (2.23x improvement)

**Soft Skills:**
- Problem Solving (solved complex CMF PDF download issue)
- Reverse Engineering (decoded undocumented APIs)
- Documentation (comprehensive technical docs)
- Testing (15+ automated tests)
- Attention to Detail (72.6% coverage across formats)

---

## 🔗 Project Links


**Documentation:** README.md in repository

---

**Status:** ✅ Production Ready
**Date:** October 2025
**Client:** inBee (Chilean Fintech)
**Role:** Full-Stack Data Engineer

---

*This project demonstrates end-to-end capability in building production-ready data pipelines with emphasis on reliability, performance, and maintainability.*
