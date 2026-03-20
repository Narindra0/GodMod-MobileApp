import os
from typing import Any, Dict, Optional, Tuple

from stable_baselines3 import PPO

from ...core import config
from ..environment.betting_env import ACTION_SPACE_CONFIG
from ..environment.observation import ObservationContext, construire_observation

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
    return ACTION_SPACE_CONFIG.get(action_id, {"type": "Aucun", "montant_ar": 0})


def predire_pari_zeus(model: PPO, match_data: Dict, conn: Any) -> Tuple[int, Dict]:
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
    details = obtenir_action_details(action_id)
    return action_id, details


def formater_decision_zeus(action_details: Dict) -> str:
    pari_type = action_details["type"]
    montant_ar = action_details.get("montant_ar", 0)
    if pari_type == "Aucun":
        return "[yellow]Abstention[/]"
    label = "Prudent" if montant_ar < 2000 else "Conviction"
    color = "cyan" if label == "Prudent" else "bold cyan"
    return f"[{color}]{pari_type} ({label})[/]"
