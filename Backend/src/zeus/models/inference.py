import os
from typing import Any, Dict, Optional, Tuple

from stable_baselines3 import PPO

from ...core import config
from ...core.zeus_finance import get_zeus_bankroll
from ..environment.betting_env import ACTION_SPACE_CONFIG
from ..utils.rng_bias import calculer_biais_rng
from ..utils.risk_manager import RiskManager

_ZEUS_MODEL = None


def get_zeus_model(model_path: str = None) -> Optional[PPO]:
    global _ZEUS_MODEL
    if _ZEUS_MODEL is None:
        path = model_path or config.ZEUS_MODEL_PATH
        if os.path.exists(path):
            try:
                _ZEUS_MODEL = PPO.load(path)
            except Exception as e:
                print(f"❌ Erreur chargement ZEUS : {e}")
                return None
        else:
            return None
    return _ZEUS_MODEL


def obtenir_action_details(action_id: int) -> Dict:
    """Retourne le type de pari et initialise le montant."""
    val = ACTION_SPACE_CONFIG.get(action_id, "Aucun")
    if isinstance(val, dict):
        return val
    return {"type": val, "montant_ar": 0}


def predire_pari_zeus(model: PPO, match_data: Dict, conn: Any) -> Tuple[int, Dict]:
    from ..environment.observation import ObservationContext, construire_observation
    context = ObservationContext(
        equipe_dom_id=match_data["equipe_dom_id"],
        equipe_ext_id=match_data["equipe_ext_id"],
        journee=match_data["journee"],
        cote_1=match_data["cote_1"],
        cote_x=match_data["cote_x"],
        cote_2=match_data["cote_2"],
    )
    obs = construire_observation(context, conn)
    action, _ = model.predict(obs, deterministic=True)
    action_id = int(action)
    
    # 1. Obtenir les détails de base (Type de pari)
    details = obtenir_action_details(action_id)
    type_pari = details["type"]
    
    # 2. Calculer la mise Kelly (ZEUS v2)
    if type_pari != "Aucun":
        try:
            bias = calculer_biais_rng(conn)
            bankroll = get_zeus_bankroll(conn=conn)
            
            # Identifier la cote jouée
            cote_key = f"cote_{type_pari.lower()}" if type_pari != "N" else "cote_x"
            cote_jouee = float(match_data.get(cote_key, 0))
            
            if cote_jouee > 1.0:
                ev = bias.get_ev(type_pari, cote_jouee)
                risk_mgr = RiskManager(bankroll)
                details["montant_ar"] = risk_mgr.calculer_mise_kelly(ev, cote_jouee, bankroll)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Erreur calcul mise Kelly ZEUS : {e}")
            details["montant_ar"] = 0

    return action_id, details


def formater_decision_zeus(action_details: Dict) -> str:
    pari_type = action_details["type"]
    montant_ar = action_details.get("montant_ar", 0)
    if pari_type == "Aucun":
        return "[yellow]Abstention[/]"
    label = "Prudent" if montant_ar < 2000 else "Conviction"
    color = "cyan" if label == "Prudent" else "bold cyan"
    return f"[{color}]{pari_type} ({label})[/]"
