import json
import logging
import threading
from pathlib import Path
from ..core.session_manager import get_active_session
from ..core import config
logger = logging.getLogger(__name__)
_file_lock = threading.RLock()
_wallet_path = Path(__file__).resolve().parent.parent.parent / "data" / "Prisma.json"
_DEFAULT_BANKROLL = 20000  
def _read_wallet() -> int:
    with _file_lock:
        try:
            _wallet_path.parent.mkdir(parents=True, exist_ok=True)
            if not _wallet_path.exists():
                _wallet_path.write_text(json.dumps({"bankroll": _DEFAULT_BANKROLL}), encoding="utf-8")
                return _DEFAULT_BANKROLL
            data = json.loads(_wallet_path.read_text(encoding="utf-8") or "{}")
            return int(data.get("bankroll", _DEFAULT_BANKROLL))
        except Exception as e:
            logger.error(f"Erreur lecture Prisma.json : {e}", exc_info=True)
            return _DEFAULT_BANKROLL
def _write_wallet(value: int) -> None:
    with _file_lock:
        try:
            _wallet_path.parent.mkdir(parents=True, exist_ok=True)
            _wallet_path.write_text(json.dumps({"bankroll": int(value)}), encoding="utf-8")
        except Exception as e:
            logger.error(f"Erreur écriture Prisma.json : {e}", exc_info=True)
def get_prisma_bankroll():
    return _read_wallet()
def is_prisma_stop_loss_active() -> bool:
    return get_prisma_bankroll() < config.BANKROLL_STOP_LOSS
def update_prisma_bankroll(session_id, nouveau_bankroll, mise, resultat, cote):
    profit_net = int(mise * cote) - mise if (resultat == 1 and cote is not None) else (-mise if resultat == 0 else 0)
    _write_wallet(nouveau_bankroll)
    logger.info(f"Bankroll PRISMA mis à jour (JSON) : {nouveau_bankroll} Ar (Profit: {profit_net} Ar)")
def deduct_prisma_funds(mise):
    current_bankroll = get_prisma_bankroll()
    if current_bankroll < config.BANKROLL_STOP_LOSS:
        logger.warning(f"[STOP-LOSS] Bankroll PRISMA ({current_bankroll} Ar) sous le seuil ({config.BANKROLL_STOP_LOSS} Ar). Pari refusé.")
        return False, current_bankroll
    new_bankroll = current_bankroll - mise
    if new_bankroll < 0:
        logger.warning(f"Fonds insuffisants PRISMA: {current_bankroll} Ar < {mise} Ar")
        return False, current_bankroll
    active_session = get_active_session()
    session_id = active_session["id"]
    update_prisma_bankroll(session_id, new_bankroll, mise, None, None)
    return True, new_bankroll
