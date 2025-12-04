# Option d'amélioration : GPT-4 Vision pour extraction PDF

## Contexte du problème

### État actuel du système d'extraction PDF

Le pipeline actuel utilise une cascade de 2 méthodes pour extraire données des PDFs de fondos mutuos :

1. **pdfplumber** (méthode principale)
   - Extraction texte basique depuis PDFs natifs
   - Rapide, gratuit, fonctionne sur ~60-70% des PDFs
   - **Échoue** sur : PDFs scanés, images, layouts complexes

2. **Tesseract OCR** (fallback, implémenté lignes 1169-1208)
   - Activation : Si `len(texto_completo) < 100` chars
   - OCR traditionnel sans IA
   - Traite 3 premières pages à 300 DPI
   - **Limitations** :
     - Pas de compréhension sémantique
     - Échoue sur fonts complexes, graphiques, tables multi-colonnes
     - Langue ESP seulement
     - Taux de succès : ~60-75%

### Problèmes identifiés dans l'audit

**Audit findings** (voir `audit1.md`) :
- 96.8% taux d'échec initial (242/250 fondos)
- Après fixes (Tasks 1-6) : taux de succès estimé ~75%
- **25% de PDFs restent problématiques** :
  - Scans de mauvaise qualité
  - Layouts non-standardisés (chaque gestionnaire a son format)
  - Données critiques dans graphiques/images
  - Tables complexes multi-colonnes que regex ne parse pas

### Pourquoi l'OCR traditionnel ne suffit pas

Les PDFs de fondos mutuos chiliens (CMF) ont des caractéristiques complexes :

```
EXEMPLE DE PDF PROBLÉMATIQUE :
┌─────────────────────────────────────────┐
│  [LOGO BCI]    Fondo Mutuo Agresivo     │
│                                          │
│  ┌────────────┐  Rentabilidad 12 meses: │
│  │ [GRAPHIQUE]│  ██████░░ 8,5%          │
│  │  Barres    │                          │
│  └────────────┘  Comisión: 0,65%        │
│                                          │
│  Composición:                            │
│  ┏━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━┓     │
│  ┃ Activo     ┃ Tipo   ┃ %      ┃     │
│  ┣━━━━━━━━━━━━╋━━━━━━━━╋━━━━━━━━┫     │
│  ┃ Apple Inc  ┃ Equity ┃ 15,3%  ┃     │
│  ┗━━━━━━━━━━━━┻━━━━━━━━┻━━━━━━━━┛     │
└─────────────────────────────────────────┘
```

**Problèmes** :
- Tesseract OCR lit "8,5%" mais ne sait pas que c'est "rentabilidad_12m"
- Tables avec bordures Unicode (┃━┏┓) causent parsing errors
- Graphiques contiennent données non extraites par OCR
- Layout multi-colonnes cause lecture dans mauvais ordre

---

## Solution proposée : Fallback GPT-4 Vision

### Architecture : Cascade intelligente à 3 niveaux

```python
def _extract_data_from_pdf(self, pdf_path: str) -> Dict:
    """
    Cascade d'extraction avec 3 fallbacks :
    1. pdfplumber (rapide, gratuit) → 60-70% succès
    2. Tesseract OCR (moyen, gratuit) → +10-15% succès
    3. GPT-4 Vision (lent, payant) → +10-15% succès

    Objectif : 85-95% taux de succès global
    """

    # NIVEAU 1 : pdfplumber (actuel)
    texto = pdfplumber_extract()

    if len(texto) >= 100:
        # Extraction OK, continuer avec regex
        return parse_with_regex(texto)

    # NIVEAU 2 : Tesseract OCR (déjà implémenté)
    texto_ocr = tesseract_fallback()

    if len(texto_ocr) >= 200:
        return parse_with_regex(texto_ocr)

    # NIVEAU 3 : GPT-4 Vision (NOUVEAU - à implémenter)
    if self.openai_key and os.getenv('USE_GPT4_VISION', 'false').lower() == 'true':
        logger.warning(f"[PDF GPT4] OCR failed, using GPT-4 Vision fallback...")
        return gpt4_vision_extract(pdf_path)

    # Aucune méthode n'a fonctionné
    return {'error': 'Todas las extracciones PDF fallaron'}
```

### Implémentation détaillée

#### Fonction `gpt4_vision_extract(pdf_path: str)`

```python
def _extract_with_gpt4_vision(self, pdf_path: str) -> Dict:
    """
    Extraer datos estructurados de PDF usando GPT-4 Vision.

    Méthode :
    1. Convertir PDF en images (pdf2image) - 3 premières pages
    2. Encoder images en base64
    3. Envoyer à GPT-4o avec prompt structuré JSON
    4. Parser réponse JSON
    5. Valider et normaliser données

    Coût estimé : $0.01-0.05 par PDF (selon pages/résolution)
    Latence : 2-5 secondes par PDF

    Returns:
        Dict avec clés extraites : rentabilidad_12m, comision_administracion,
        composicion_portafolio, perfil_riesgo, etc.
    """
    import base64
    from pdf2image import convert_from_path
    from openai import OpenAI

    try:
        # 1. Convertir PDF en images (première 3 pages seulement)
        logger.info(f"[GPT4 VISION] Converting PDF to images: {pdf_path}")
        images = convert_from_path(
            pdf_path,
            dpi=200,  # Plus bas que OCR (300) pour réduire coût API
            first_page=1,
            last_page=3  # Limiter à 3 pages max
        )

        # 2. Encoder images en base64
        image_data_list = []
        for i, img in enumerate(images[:3]):  # Max 3 images
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode()
            image_data_list.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{img_str}",
                    "detail": "high"  # High detail pour extraction précise
                }
            })

        # 3. Construire prompt structuré
        prompt = """
Eres un experto en análisis de documentos financieros chilenos.

TAREA: Extraer datos estructurados de este Folleto Informativo de Fondo Mutuo.

DATOS A EXTRAER (devolver JSON válido):
{
  "nombre_fondo": "Nombre completo del fondo",
  "rentabilidad_12m": 0.085,  // Como decimal (8.5% = 0.085), null si no encontrado
  "rentabilidad_24m": 0.12,   // Como decimal, null si no encontrado
  "rentabilidad_36m": 0.15,   // Como decimal, null si no encontrado
  "comision_administracion": 0.0065,  // Como decimal (0.65% = 0.0065)
  "perfil_riesgo": "R5",  // R1 a R7, extraer de "Perfil de Riesgo"
  "patrimonio": 1500000000,  // En pesos chilenos (CLP), número sin puntos
  "valor_cuota": 1234.56,  // Valor actual de la cuota
  "composicion_portafolio": [  // Top 5-10 activos
    {
      "nombre": "Apple Inc",
      "tipo": "Equity",  // Equity, Fixed Income, Cash, etc.
      "porcentaje": 0.153  // Como decimal (15.3% = 0.153)
    }
  ],
  "moneda": "CLP",  // CLP, USD, UF, etc.
  "fecha_documento": "2024-11-15",  // Formato YYYY-MM-DD
  "extraction_confidence": "high"  // high/medium/low según claridad del documento
}

INSTRUCCIONES:
- Buscar en tablas, gráficos, texto corrido
- Rentabilidades pueden estar como "Rentabilidad 1 año: 8,5%" o en gráficos
- Comisión suele estar como "Comisión de administración: 0,65%"
- Composición puede estar en tabla "Principales Inversiones" o "Composición Cartera"
- Si un dato NO se encuentra, usar null (no inventar)
- Convertir SIEMPRE porcentajes a decimales (8,5% → 0.085)
- Respetar formato JSON válido (comillas dobles, sin trailing commas)

DEVOLVER SOLO EL JSON, SIN TEXTO ADICIONAL.
"""

        # 4. Llamada a GPT-4o Vision API
        client = OpenAI(api_key=self.openai_key)

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt}
                ] + image_data_list
            }
        ]

        logger.info(f"[GPT4 VISION] Sending {len(image_data_list)} images to GPT-4o...")

        response = client.chat.completions.create(
            model="gpt-4o",  # ou "gpt-4-turbo" si budget limité
            messages=messages,
            max_tokens=2000,
            temperature=0.1  # Très bas pour extraction factuelle
        )

        # 5. Parser réponse JSON
        response_text = response.choices[0].message.content.strip()

        # Nettoyer markdown code blocks si présents
        if response_text.startswith("```json"):
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif response_text.startswith("```"):
            response_text = response_text.split("```")[1].split("```")[0].strip()

        resultado = json.loads(response_text)

        # 6. Validation et logs
        logger.info(f"[GPT4 VISION] ✅ Extraction successful")
        logger.info(f"[GPT4 VISION]   Confidence: {resultado.get('extraction_confidence', 'unknown')}")
        logger.info(f"[GPT4 VISION]   Rentabilidad 12m: {resultado.get('rentabilidad_12m')}")
        logger.info(f"[GPT4 VISION]   Comisión: {resultado.get('comision_administracion')}")
        logger.info(f"[GPT4 VISION]   Composición: {len(resultado.get('composicion_portafolio', []))} activos")

        # Ajouter métadonnées
        resultado['extraction_method'] = 'GPT-4 Vision'
        resultado['extraction_timestamp'] = time.strftime('%Y-%m-%d %H:%M:%S')

        # Coût estimé (logging pour tracking)
        # GPT-4o: ~$0.01 per image (high detail)
        estimated_cost = len(image_data_list) * 0.01
        logger.info(f"[GPT4 VISION]   Estimated cost: ${estimated_cost:.3f} USD")

        return resultado

    except json.JSONDecodeError as e:
        logger.error(f"[GPT4 VISION] JSON parse error: {e}")
        logger.error(f"[GPT4 VISION] Raw response: {response_text[:500]}")
        return {'error': f'GPT-4 Vision JSON parse error: {e}'}

    except Exception as e:
        logger.error(f"[GPT4 VISION] Extraction failed: {type(e).__name__}: {e}")
        return {'error': f'GPT-4 Vision extraction failed: {e}'}
```

---

## Configuration requise

### Variables d'environnement (.env)

```bash
# Existant
OPENAI_API_KEY=sk-proj-xxxxx

# NOUVEAU - Activation explicite GPT-4 Vision
USE_GPT4_VISION=true  # false par défaut (opt-in)

# NOUVEAU - Limite budget (optionnel)
GPT4_VISION_MAX_COST_USD=10.00  # Arrêter si coût total > $10
GPT4_VISION_MAX_PDFS=50  # Limiter à 50 PDFs avec Vision par batch
```

### Dépendances Python

```bash
# Déjà installées
pip install openai>=1.0.0
pip install pdf2image
pip install Pillow

# Système (macOS)
brew install poppler  # Déjà requis pour pdf2image
```

---

## Coûts et performances estimés

### Coûts API OpenAI (GPT-4o)

**Pricing GPT-4o (janvier 2025)** :
- Image input (high detail) : ~$0.01 par image
- Text output : ~$0.03 per 1K tokens

**Coût par PDF** :
- 3 pages → 3 images → $0.03
- Output (~500 tokens JSON) → $0.015
- **Total : ~$0.045 par PDF**

**Coût pour 250 fondos** :
- Si 25% utilisent GPT-4 Vision (62 PDFs) → **$2.79 USD**
- Si 50% utilisent GPT-4 Vision (125 PDFs) → **$5.63 USD**
- Si 100% utilisent GPT-4 Vision (250 PDFs) → **$11.25 USD**

### Comparaison coût/bénéfice

| Méthode           | Coût      | Latence/PDF | Taux succès | Coût total (250 fondos) |
|-------------------|-----------|-------------|-------------|-------------------------|
| pdfplumber        | $0        | 0.5s        | 60-70%      | $0                      |
| Tesseract OCR     | $0        | 2-3s        | 70-75%      | $0                      |
| **GPT-4 Vision**  | $0.045    | 3-5s        | **90-95%**  | **$2.79-11.25**         |
| **Cascade 3 niveaux** | $0.045 (25% PDFs) | Variable | **85-95%** | **~$3-6** |

### Performances

**Latence estimée** (250 fondos, cascade intelligente) :
- 175 PDFs → pdfplumber (0.5s) = 88s
- 50 PDFs → Tesseract (2.5s) = 125s
- 25 PDFs → GPT-4 Vision (4s) = 100s
- **Total : ~313s (5 min 13s)** vs ~125s actuels

**Trade-off** : +3 minutes pour +10-20% taux de succès

---

## Avantages et limitations

### ✅ Avantages

1. **Compréhension contextuelle**
   - Comprend "ce graphique montre rentabilité annuelle"
   - Associe valeurs à concepts sémantiques
   - Parse tables complexes sans regex

2. **Robustesse formats**
   - Fonctionne sur PDFs scanés, photographiés, mal formatés
   - Gère layouts non-standardisés (BCI ≠ Santander ≠ Scotia)
   - Extrait données depuis graphiques/images

3. **Taux de succès élevé**
   - Estimation : **90-95%** sur PDFs problématiques
   - Cascade globale : **85-95%** (vs 75% actuel)

4. **Maintenance réduite**
   - Pas de regex fragiles à maintenir
   - S'adapte automatiquement aux nouveaux formats
   - LLM améliore avec le temps

### ❌ Limitations

1. **Coût**
   - $0.045 par PDF vs gratuit pour OCR
   - Budget : ~$3-11 pour 250 fondos (selon usage)
   - Nécessite monitoring coûts

2. **Latence**
   - 3-5s par PDF vs 0.5s pdfplumber
   - Impact : +3 min sur batch 250 fondos

3. **Dépendance externe**
   - Nécessite internet + API OpenAI disponible
   - Rate limits : 500 requests/minute (OK pour usage)
   - Risque service interruption

4. **Hallucinations possibles**
   - LLM peut inventer données si document peu clair
   - Mitigation : `extraction_confidence` + validation
   - Nécessite monitoring qualité

---

## Stratégie d'implémentation recommandée

### Phase 1 : Proof of Concept (1-2 jours)

1. Implémenter `_extract_with_gpt4_vision()` dans `fondos_mutuos.py`
2. Tester sur 10 PDFs problématiques identifiés dans audit
3. Mesurer :
   - Taux de succès (target : >90%)
   - Qualité données (comparer avec ground truth manuel)
   - Coût réel par PDF
   - Latence moyenne

### Phase 2 : Intégration cascade (1 jour)

1. Ajouter fallback niveau 3 dans `_extract_data_from_pdf()`
2. Implémenter variable `USE_GPT4_VISION` (opt-in)
3. Ajouter cost tracking et limites budget
4. Tests sur 50 fondos (mix faciles/difficiles)

### Phase 3 : Production (selon résultats)

**Décision basée sur métriques PoC** :

**SI** :
- Taux succès >90% sur PDFs problématiques
- Pas d'hallucinations détectées
- Coût acceptable (<$15 pour 250 fondos)

**ALORS** :
- Activer en production avec `USE_GPT4_VISION=true`
- Monitor coûts quotidiens
- Créer dashboard qualité extraction

**SINON** :
- Garder comme option manuelle pour PDFs spécifiques
- Continuer amélioration regex + OCR

---

## Prompt structuré pour implémentation

```
CONTEXTE :
Le pipeline actuel d'extraction PDF de fondos mutuos atteint ~75% de taux de succès
après corrections (Tasks 1-6). 25% des PDFs restent problématiques (scanés,
layouts complexes, données dans graphiques).

OBJECTIF :
Ajouter fallback GPT-4 Vision comme 3ème niveau de cascade d'extraction pour
atteindre 85-95% taux de succès global.

TÂCHE :
Implémenter la fonction _extract_with_gpt4_vision() dans fondos_mutuos.py
selon spécifications ci-dessus.

CONTRAINTES :
- Opt-in explicite via USE_GPT4_VISION=true
- Limiter à 3 pages/images max par PDF
- Parser réponse JSON structurée
- Valider données extraites (pas d'hallucinations)
- Logger coûts estimés pour tracking
- Gestion erreurs robuste (API timeout, JSON parse errors)

FICHIERS À MODIFIER :
1. fondos_mutuos.py :
   - Ajouter _extract_with_gpt4_vision() après ligne 1636
   - Intégrer fallback dans _extract_data_from_pdf() lignes 1169-1212
   - Ajouter cost_tracker comme attribut classe

2. .env :
   - Ajouter USE_GPT4_VISION=false (désactivé par défaut)
   - Ajouter GPT4_VISION_MAX_COST_USD=10.00 (optionnel)

LIVRABLES :
- Code fonctionnel avec gestion erreurs complète
- Logs clairs distinction pdfplumber/OCR/GPT4Vision
- Documentation inline des coûts et limites
- AUCUN fichier test ou documentation supplémentaire
- AUCUNE donnée inventée

VALIDATION :
Tester sur 5 PDFs problématiques identifiés dans outputs/batch_fondos_resumen.json
(fondos avec error ou extraction pauvre).

NE PAS :
- Créer fichiers tests
- Créer documentation séparée (tout inline)
- Inventer des données de test
- Activer par défaut (opt-in seulement)
```

---

## Métriques de succès

### KPIs à mesurer après implémentation

1. **Taux de succès global**
   - Target : >85% fondos avec données complètes
   - Mesure : `batch_fondos_resumen.json → exitosos/total`

2. **Qualité extraction GPT-4**
   - Target : <5% hallucinations détectées
   - Mesure : Validation manuelle échantillon 20 fondos
   - Check : `extraction_confidence == 'high'` corrélé avec qualité réelle

3. **Coût réel**
   - Target : <$15 pour 250 fondos
   - Mesure : Somme logs `[GPT4 VISION] Estimated cost`

4. **Latence acceptable**
   - Target : <10 minutes pour batch 250 fondos
   - Mesure : Timestamp début/fin pipeline

### Seuils d'alerte

- **STOP si** coût cumulé > $20 (configurable via GPT4_VISION_MAX_COST_USD)
- **WARNING si** >10% fondos utilisent GPT-4 Vision (indique problème upstream)
- **ERROR si** extraction_confidence == 'low' sur >20% des appels GPT-4

---

## Conclusion

Cette amélioration est **OPTIONNELLE** et devrait être implémentée **SI ET SEULEMENT SI** :

1. Le taux de succès actuel (~75%) est insuffisant pour les besoins métier
2. Budget disponible pour API costs ($3-15 par batch)
3. Latence +3-5 minutes acceptable
4. Phase PoC démontre >90% succès sur PDFs problématiques

**Recommandation** : Implémenter en Phase 1 (PoC) sur 10 PDFs pour valider
avant décision production.

**Alternative low-cost** : Améliorer regex + table parsing HTML (Tâches 7-10)
peut atteindre ~80-85% succès sans coûts API.
