📋 PLAN D'EXÉCUTION STRUCTURÉ
🔴 CRITIQUE - À FAIRE IMMÉDIATEMENT (Impact: Pipeline crash pour 36+ fondos)
Tâche 1: Corriger NoneType+str concatenation
Impact: 14.9% des fondos (36/242) crashent actuellement
Fichiers: fondos_mutuos.py
Sous-tâches:
Ligne 859 - Valider rut avant construction Referer header: 'Referer': f'...rut={rut or ""}'
Ligne 907 - Valider pdf_viewer_path n'est pas None/ERROR avant construire URL
Ligne 2771 - Renforcer validation rut_fondo avec cmf_fund.get('rut_fondo', '') or ''
Créer utilitaire safe_str_concat() pour tous les f-strings avec RUT/URL
Audit complet - Grep f".*{.*rut et +.*rut pour trouver autres concat non protégées
Tâche 2: Implémenter retry HTTP avec backoff exponentiel
Impact: Fondos valides échouent sur erreurs réseau temporaires (404, timeouts)
Fichiers: fondos_mutuos.py
Sous-tâches:
Créer fonction request_with_retry(session, url, max_retries=3, backoff=2) avant classe
Remplacer session.get() aux lignes 419, 518, 1343, 1690, 1809
Logger redirects - Ajouter logger.info(f"Redirects: {response.history}") pour détecter URL changes CMF
Validation status codes - Ne retry que 404/503, pas 401/403
🟠 HAUTE PRIORITÉ (Impact: Extraction données 42% → 75%+)
Tâche 3: Améliorer scraping Selenium - Trouver 75%+ des liens PDF
Impact: Actuellement seulement 42% des liens PDF trouvés
Fichiers: fondos_mutuos.py lignes 682-812
Sous-tâches:
Ligne 756 - Élargir XPath avec liste fallback:
selectors = [
    "//a[contains(@onclick, 'verFolleto') or contains(@onclick, 'abrirFolleto')]",
    "//button[contains(@onclick, 'verFolleto')]",
    "//a[contains(@href, '.pdf')]",
    "//*[contains(text(), 'Folleto')]/ancestor::a"
]
Avant ligne 756 - Ajouter scroll page: driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
Ligne 750 - Augmenter timeout de 10s à 20s pour JavaScript tabs
Après ligne 792 - Fallback BeautifulSoup sur driver.page_source si XPath échoue
Tâche 4: Robustifier extraction PDF - Regex decimal/pourcentage
Impact: Warnings "invalid float", rentabilidad null dans ~30% cas
Fichiers: fondos_mutuos.py lignes 1108-1193
Sous-tâches:
Ligne 1114 - Corriger regex comision: r'(\d*[\.,]?\d+)\s*%?' au lieu de r'(\d+[\.,]\d+)'
Après match - Valider comision_str non vide: if not comision_str or comision_str == '.': continue
Lignes 1162-1192 - Appliquer même fix pour rentabilidades (12m, 24m, 36m)
Début fichier - Compiler tous regex module-level pour performance:
REGEX_COMISION = re.compile(r'(\d*[\.,]?\d+)\s*%?')
REGEX_RENTABILIDAD = re.compile(r'[1-5]\s+años?\s+([-]?\d*[\.,]?\d*)\s*%', re.IGNORECASE)
Tâche 5: Ajouter fallback OCR pour PDFs scan/corrompus
Impact: Récupérer données de PDFs avec extraction text < 100 chars
Fichiers: fondos_mutuos.py ligne 992
Sous-tâches:
Vérifier installation - Try import pytesseract/pdf2image au init, logger si manquant
Ligne 998 - Après extraction pdfplumber, ajouter:
if len(texto_completo.strip()) < 100:
    logger.warning("[PDF] Text faible, essai OCR...")
    # Code OCR avec pdf2image + pytesseract
Configuration OCR - dpi=300, first 3 pages seulement (performance)
Logs clairs - logger.info(f"[PDF OCR] Extracted {len(texto)} chars via Tesseract")
🟡 MOYENNE PRIORITÉ (Impact: Complétion données 40% → 75%)
Tâche 6: Améliorer scraper CMF fecha_valor_cuota
Impact: 40% fondos ont fecha_valor_cuota = null
Fichiers: fondos_mutuos.py lignes 1314-1398
Sous-tâches:
Ligne 1352 - Élargir regex date: r'(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})' (accepter YY et YYYY)
Ligne 1340 - Essayer pestania=1 en fallback si pestania=7 retourne vide
Après ligne 1353 - Extraire date depuis tables HTML avec BeautifulSoup si regex échoue
Parser dates flexible - Gérer formats DD/MM/YY, DD-MM-YYYY, YYYY-MM-DD
Tâche 7: Gérer warnings PDF pdfplumber proprement
Impact: Logs pollués, extraction interrompue sur pages corrompues
Fichiers: fondos_mutuos.py lignes 992-1001
Sous-tâches:
Ligne 994 - Wrap extraction par page dans try/except:
for page_num, page in enumerate(pdf.pages, 1):
    try:
        page_text = page.extract_text()
    except Exception as e:
        logger.warning(f"[PDF] Page {page_num} skip: {e}")
        continue
Avant ligne 992 - Valider PDF: if not pdf.metadata or len(pdf.pages) == 0: return error
Ligne 992 - Filtrer warnings pdfplumber: warnings.filterwarnings('ignore', module='pdfplumber')
🟢 BASSE PRIORITÉ (Impact: Qualité code, maintenabilité)
Tâche 8: Réduire complexité ifs imbriqués
Impact: Maintenabilité, lisibilité (audit2.md score 4.5/10)
Fichiers: fondos_mutuos.py lignes 2788-2850, 601-613
Sous-tâches:
Lignes 2788-2850 - Refactor avec guard clauses (early return)
Extraire fonction _map_pdf_data_to_resultado(pdf_data, resultado) pour logique mapping
Lignes 601-613 - Flatten nesting extraction folletos (max 3 niveaux)
Tâche 9: Standardiser langue (español pour domaine CL)
Impact: Cohérence code/logs
Fichiers: fondos_mutuos.py, main.py, alpha_vantage.py
Sous-tâches:
Variables - Renommer fund_code → codigo_fondo, administrator_id → rut_administradora
Logs - Standardiser tous messages en español
Commentaires - Convertir commentaires anglais restants
Tâche 10: Architecture - Séparer responsabilités (audit2.md)
Impact: Maintenabilité long-terme, réutilisabilité
Fichiers: Créer nouveaux modules
Sous-tâches:
Créer cmf_scraper.py - Extraire lignes 397-1790 (scraping CMF)
Créer pdf_extractor.py - Extraire lignes 948-1424 (extraction PDF + OCR)
Créer excel_generator.py - Extraire lignes 2451-2634 (génération Excel)
Réduire fondos_mutuos.py à orchestration uniquement (classe principale + procesar_fondos_mutuos)
🎯 ORDRE D'EXÉCUTION RECOMMANDÉ
Jour 1 (Critique):
Tâche 1 (NoneType) - 2h
Tâche 2 (HTTP retry) - 1h
Test pipeline sur 5-10 fondos - Valider stabilité
Jour 2 (Haute priorité): 4. Tâche 4 (Regex PDF) - 2h 5. Tâche 3 (Selenium) - 3h 6. Test pipeline sur 50 fondos - Vérifier taux extraction Jour 3 (Moyenne priorité): 7. Tâche 5 (OCR fallback) - 3h 8. Tâche 6 (fecha_valor_cuota) - 2h 9. Tâche 7 (warnings PDF) - 1h 10. Test pipeline complet sur 250+ fondos - Comparer avec audit1.md Jour 4-5 (Qualité code - optionnel): 11. Tâche 8 (complexité) - 3h 12. Tâche 9 (langue) - 2h 13. Tâche 10 (architecture) - 6h
📊 MÉTRIQUES DE SUCCÈS ATTENDUES
Métrique	Avant	Après Critique	Après Haute	Après Moyenne
Taux succès pipeline	3.2%	20%	75%	85%
NoneType crashes	36 fondos	0 fondos	0 fondos	0 fondos
Rentabilidad population	0%	30%	70%	75%
Composicion population	0%	40%	80%	85%
Fecha_valor_cuota	8%	15%	50%	75%
PDF liens trouvés	42%	45%	75%	80%
⚠️ CONTRAINTES RESPECTÉES
✅ Pas d'invention de données - Toutes corrections utilisent données réelles (CMF, PDF, Fintual)
✅ Pas de fichiers tests - Validation manuelle avec pipeline sur vrais fondos
✅ Pas de documentation - Code auto-documenté avec docstrings existants
✅ Données manquantes - Retourner None ou [] explicitement, logger clairement La todo list a été créée avec ces 43 sous-tâches. Voulez-vous que je commence par implémenter les tâches critiques (Tâche 1 et 2) ?