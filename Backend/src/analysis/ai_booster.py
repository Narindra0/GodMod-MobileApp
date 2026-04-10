import json
import logging
import os
import re
import requests
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List
import time
from ..core.system import config
from ..core.utils.utils import safe_json_dumps

logger = logging.getLogger(__name__)

# Suivi des IAs désactivées automatiquement
DISABLED_IAS = set()

_SYSTEM_PROMPT_AUDIT = """Tu es un auditeur de performance spécialisé dans les systèmes de paris automatisés sur football virtuel.

## Contexte du système
Le système utilise deux stratégies simultanées et indépendantes :
- **PRISMA** : Stratégie quantitative, cibles de cotes à valeur, taux de réussite attendu ≥ 60%
- **ZEUS** : Agent autonome avec money management (mise fixe combinée: 1000 Ar, stop-loss à 2000 Ar). Un win rate < 50% peut rester rentable si le money management est solide.

## Format des données d'entrée
Les paris te sont fournis sous format texte structuré, une ligne par pari, avec :
- Journée, équipes, prédiction, fiabilité, cote, résultat, profit net, stratégie

## Ta mission
1. Sépare strictement les paris PRISMA et ZEUS
2. Identifie les patterns de performance sur la période (séries, dérives, corrélations de cotes)
3. Évalue la santé du money management de ZEUS (drawdown, rebonds, exposition maximale)
4. Formule des recommandations actionnables et spécifiques

## Instructions de réponse
- Raisonne d'abord en 3-5 phrases avant de produire le JSON
- Retourne ensuite UNIQUEMENT le JSON valide ci-dessous, sans balises markdown

{
  "prisma_audit": {
    "summary": "<X/N gagnés, win rate, ROI, tendance sur la période>",
    "win_rate": <float>,
    "roi": <float>,
    "max_losing_streak": <int>,
    "strengths": ["..."],
    "weaknesses": ["..."],
    "detailed_analysis": "<patterns de cotes, valeur détectée, dérives>",
    "recommendations": ["conseil actionnable 1", "..."]
  },
  "zeus_audit": {
    "summary": "<efficacité Martingale, cycles de rebond, exposition max>",
    "win_rate": <float>,
    "roi": <float>,
    "max_drawdown": <float>,
    "max_stake_reached": <float>,
    "strengths": ["..."],
    "weaknesses": ["..."],
    "detailed_analysis": "<cycles de perte/rebond, risque de ruin, cohérence Kelly>",
    "recommendations": ["conseil actionnable 1", "..."]
  }
}
"""

def perform_cycle_audit_async(journee: int, session_id: int, start_j: int = None, end_j: int = None):
    """Lance l'audit rétrospectif d'une période en arrière-plan."""
    import threading
    from ..core.db.database import get_db_connection
    
    def _run_audit():
        try:
            with get_db_connection(write=True) as conn:
                perform_cycle_audit(journee, session_id, conn, start_j, end_j)
        except Exception as e:
            logger.error(f"[AI-AUDIT] Erreur audit asynchrone J{journee}: {e}")
    
    thread = threading.Thread(target=_run_audit, daemon=True)
    thread.start()
    if start_j and end_j:
        logger.info(f"[AI-AUDIT] Audit ciblé J{start_j}-J{end_j} lancé en arrière-plan")
    else:
        logger.info(f"[AI-AUDIT] Audit du cycle J{journee} lancé en arrière-plan")


def perform_cycle_audit(current_journee: int, session_id: int, conn, start_j: int = None, end_j: int = None) -> bool:
    """
    Réalise un audit rétrospectif des journées de paris (cycle par défaut de 10 ou plage définie).
    Sépare clairement les actions PRISMA et ZEUS dans le prompt IA.
    """
    if start_j is None:
        start_j = max(1, current_journee - 9)
    if end_j is None:
        end_j = current_journee
    
    logger.info(f"[AI-AUDIT] Début audit rétrospectif : J{start_j} à J{end_j}")
    
    try:
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT hp.journee, hp.type_pari, hp.cote_jouee, hp.profit_net, hp.resultat as success,
                   hp.strategie,
                   e1.nom as dom, e2.nom as ext,
                   p.technical_details, p.fiabilite, p.prediction
            FROM historique_paris hp
            LEFT JOIN predictions p ON hp.prediction_id = p.id
            LEFT JOIN matches m ON p.match_id = m.id
            LEFT JOIN equipes e1 ON m.equipe_dom_id = e1.id
            LEFT JOIN equipes e2 ON m.equipe_ext_id = e2.id
            WHERE hp.session_id = %s AND hp.journee BETWEEN %s AND %s
            ORDER BY hp.journee ASC
        """, (session_id, start_j, end_j))
        
        bets = cursor.fetchall()
        if not bets:
            logger.warning(f"[AI-AUDIT] Aucun pari trouvé pour le cycle J{start_j}-J{end_j}. Audit annulé.")
            return False
            
        lines_prisma = ["--- PARIS PRISMA ---"]
        lines_zeus = ["--- PARIS ZEUS ---"]
        
        for b in bets:
            # Gestion basique car certains paris ZEUS emprunts n'ont pas de prédiction rattachée
            status = "GAGNÉ" if b['success'] == 1 else ("PERDU" if b['success'] == 0 else "ATTENTE")
            profit = f"{b['profit_net']:,} Ar" if b['profit_net'] else "0 Ar"
            dom = b['dom'] or 'Unknown'
            ext = b['ext'] or 'Unknown'
            pred = b['prediction'] or '?'
            fiab = float(b['fiabilite'] or 0)
            
            criteria = ""
            if b['technical_details']:
                try:
                    tech = json.loads(b['technical_details']) if isinstance(b['technical_details'], str) else b['technical_details']
                    weights = tech.get('weights', {})
                    sorted_weights = sorted(weights.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
                    criteria = ", ".join([f"{k}:{v:.1f}" for k, v in sorted_weights])
                except:
                    pass
            
            line_str = (
                f"J{b['journee']}: {dom} vs {ext} | "
                f"Pari: {pred} ({fiab:.2f}) | "
                f"Cote: {b['cote_jouee']} | Résultat: {status} ({profit})"
            )
            if criteria:
                line_str += f" | Critères: {criteria}"
                
            if b.get('strategie') == 'ZEUS':
                lines_zeus.append(line_str)
            else:
                lines_prisma.append(line_str)
            
        full_data = "\n".join(["Audit rétrospectif des paris\n"] + lines_prisma + ["\n"] + lines_zeus)
        
        report = _get_ai_audit_report(full_data)
        if not report:
            return False
            
        cursor.execute("""
            INSERT INTO ai_cycle_audits (session_id, start_journee, end_journee, report_json)
            VALUES (%s, %s, %s, %s)
        """, (session_id, start_j, end_j, safe_json_dumps(report, ensure_ascii=False)))
        
        conn.commit()
        logger.info(f"[AI-AUDIT] Audit J{start_j}-J{end_j} complété et enregistré.")
        return True
        
    except Exception as e:
        logger.error(f"[AI-AUDIT] Erreur lors de l'audit : {e}", exc_info=True)
        return False

def _extract_json(text: str) -> dict:
    """Extrait et parse le premier bloc JSON trouvé dans un texte."""
    try:
        # Recherche d'un bloc {...} (greedy pour prendre tout le JSON)
        match = re.search(r'(\{.*\})', text, re.DOTALL)
        if match:
            json_text = match.group(1)
            # Nettoyage basique (parfois l'IA met des ```json ... ```)
            json_text = json_text.strip()
            return json.loads(json_text)
        return json.loads(text) # Fallback si pas de match, on tente le texte entier
    except Exception as e:
        logger.error(f"[AI-AUDIT] Échec extraction JSON : {e}")
        return None

def _get_ai_audit_report(data_text: str) -> dict:
    """Interroge l'IA pour générer le rapport d'audit.
    Priorité : OpenRouter -> Gemini -> Groq.
    """
    # 1. Tentative avec OpenRouter (Principal + Fallbacks internes)

    openrouter_key = getattr(config, "OPENROUTER_API_KEY", None)
    if openrouter_key:
        openrouter_models = [
            config.OPENROUTER_MODEL,
            "google/gemini-2.0-flash-exp:free",
            "mistralai/mistral-7b-instruct:free"
        ]
        
        for model_name in openrouter_models:
            try:
                logger.info(f"[AI-AUDIT] Appel de OpenRouter ({model_name})...")
                url = "https://openrouter.ai/api/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://godmod.app",
                    "X-Title": "GodMod AI Booster"
                }
                payload = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT_AUDIT},
                        {"role": "user", "content": data_text}
                    ],
                    "temperature": 0.4
                }
                
                response = requests.post(url, json=payload, headers=headers, timeout=60)
                if response.status_code == 200:
                    result = response.json()
                    raw_content = result['choices'][0]['message']['content']
                    logger.info(f"[AI-AUDIT] Rapport généré avec succès par OpenRouter ({model_name}).")
                    return _extract_json(raw_content)
                else:
                    logger.warning(f"[AI-AUDIT] Échec OpenRouter {model_name} ({response.status_code}): {response.text[:100]}...")
            except Exception as e:
                logger.warning(f"[AI-AUDIT] Erreur OpenRouter {model_name}: {e}...")
        
        logger.warning("[AI-AUDIT] Épuisement des modèles OpenRouter. Basculement vers Gemini...")
    else:
        logger.info("[AI-AUDIT] OPENROUTER_API_KEY non trouvée, passage au fallback (Gemini)")

    # 2. Fallback Gemini
    api_key = getattr(config, "GEMINI_API_KEY", None)
    if api_key:
        try:
            logger.info(f"[AI-AUDIT] Appel de Gemini ({getattr(config, 'GEMINI_MODEL', 'gemini-1.5-flash')})...")
            from google import genai
            client = genai.Client(api_key=api_key)
            model = getattr(config, "GEMINI_MODEL", "gemini-1.5-flash")
            
            response = client.models.generate_content(
                model=model,
                contents=f"{_SYSTEM_PROMPT_AUDIT}\n\nDonnées du cycle :\n{data_text}",
                config={"response_mime_type": "application/json", "temperature": 0.3},
            )
            logger.info("[AI-AUDIT] Rapport généré avec succès par Gemini.")
            return json.loads(response.text)
        except Exception as e:
            logger.warning(f"[AI-AUDIT] Échec Gemini ({e}) | Basculement vers le prochain fallback...")
    else:
        logger.info("[AI-AUDIT] GEMINI_API_KEY non trouvée, passage au fallback (Groq)")
        
    # 3. Fallback Groq
    groq_key = getattr(config, "GROQ_API_KEY", None)
    if groq_key:
        try:
            logger.info(f"[AI-AUDIT] Appel de Groq ({getattr(config, 'GROQ_MODEL', 'llama-3.1-8b-instant')})...")
            from groq import Groq
            g_client = Groq(api_key=groq_key)
            g_model = getattr(config, "GROQ_MODEL", "llama-3.1-8b-instant")
            
            completion = g_client.chat.completions.create(
                model=g_model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT_AUDIT},
                    {"role": "user", "content": data_text}
                ],
                response_format={"type": "json_object"}
            )
            logger.info("[AI-AUDIT] Rapport généré avec succès par Groq.")
            return _extract_json(completion.choices[0].message.content)
        except Exception as ge:
            logger.error(f"[AI-AUDIT] Échec total de l'Audit IA (Dernier fallback: Groq): {ge}")
    else:
        logger.error("[AI-AUDIT] GROQ_API_KEY non trouvée, et aucun autre fallback disponible. Impossible de générer l'audit.")
                
    return None
