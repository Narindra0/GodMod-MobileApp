import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List
import time
from ..core import config
from ..core.utils import safe_json_dumps

logger = logging.getLogger(__name__)

# Suivi des IAs désactivées automatiquement
DISABLED_IAS = set()

_SYSTEM_PROMPT_AUDIT = """Tu es un auditeur de performance pour un système de paris automatisé sur football virtuel.
Le système utilise deux Intelligences (Stratégies) distinctes simultanément :
1. PRISMA : Stratégie quantitative visant des cotes de valeur avec un taux de réussite cible de 60%+.
2. ZEUS : Stratégie autonome (Agent de pari) qui sert de filet de sécurité avec gestion agressive du capital (Martingale/Kelly).

Contexte :
- Les matchs sont simulés algorithmiquement.
- Un taux < 50% pour PRISMA sur 10J indique une faille. Pour ZEUS, un taux plus bas peut être rentable selon son money management systématique.

Ta mission :
Analyse les paris fournis et sépare strictement tes conclusions entre PRISMA et ZEUS.
Retourne UNIQUEMENT ce JSON valide, respectant scrupuleusement la structure ci-dessous, sans texte avant ni après :
{
  "prisma_audit": {
    "summary": "<Résumé spécifique à PRISMA: X/10 gagnés, ROI, tendance>",
    "win_rate": <float, ex: 0.65>,
    "strengths": ["point fort PRISMA", ...],
    "weaknesses": ["point faible PRISMA", ...],
    "detailed_analysis": "<Analyse des patterns PRISMA, valeur des cotes, corrélation>",
    "recommendations": ["actionable advice PRISMA"]
  },
  "zeus_audit": {
    "summary": "<Résumé spécifique à ZEUS: efficacité de la gestion de mise, rebonds>",
    "win_rate": <float, ex: 0.45>,
    "strengths": ["point fort ZEUS", ...],
    "weaknesses": ["point faible ZEUS", ...],
    "detailed_analysis": "<Analyse factuelle des cycles ZEUS et de l'absorption des pertes>",
    "recommendations": ["actionable advice ZEUS"]
  }
}
"""

def perform_cycle_audit_async(journee: int, session_id: int):
    """Lance l'audit rétrospectif du cycle en arrière-plan."""
    import threading
    from ..core.database import get_db_connection
    
    def _run_audit():
        try:
            with get_db_connection(write=True) as conn:
                perform_cycle_audit(journee, session_id, conn)
        except Exception as e:
            logger.error(f"[AI-AUDIT] Erreur audit asynchrone J{journee}: {e}")
    
    thread = threading.Thread(target=_run_audit, daemon=True)
    thread.start()
    logger.info(f"[AI-AUDIT] Audit du cycle J{journee} lancé en arrière-plan")


def perform_cycle_audit(current_journee: int, session_id: int, conn) -> bool:
    """
    Réalise un audit rétrospectif des DERNIÈRES journées de paris (cycle de 10).
    Sépare clairement les actions PRISMA et ZEUS dans le prompt IA.
    """
    start_j = max(1, current_journee - 9)
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

def _get_ai_audit_report(data_text: str) -> dict:
    """Interroge l'IA pour générer le rapport d'audit."""
    api_key = getattr(config, "GEMINI_API_KEY", None)
    if not api_key:
        return None
        
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        model = getattr(config, "GEMINI_MODEL", "gemini-1.5-flash")
        
        response = client.models.generate_content(
            model=model,
            contents=f"{_SYSTEM_PROMPT_AUDIT}\n\nDonnées du cycle :\n{data_text}",
            config={"response_mime_type": "application/json", "temperature": 0.3},
        )
        return json.loads(response.text)
    except Exception as e:
        logger.warning(f"[AI-AUDIT] Échec Gemini, tentative Groq... ({e})")
        
        groq_key = getattr(config, "GROQ_API_KEY", None)
        if groq_key:
            try:
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
                return json.loads(completion.choices[0].message.content)
            except Exception as ge:
                logger.error(f"[AI-AUDIT] Échec total Audit IA: {ge}")
                
    return None
