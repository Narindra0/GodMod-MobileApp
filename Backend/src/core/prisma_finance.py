import json
import logging
import threading
from pathlib import Path

from ..core.session_manager import get_active_session

logger = logging.getLogger(__name__)

# Stockage fichier pour éviter les locks SQLite sur PRISMA
_file_lock = threading.RLock()
_wallet_path = Path(__file__).resolve().parent.parent / "data" / "Prisma.json"
_DEFAULT_BANKROLL = 20000  # 20 000 Ar dédiés à PRISMA


def _read_wallet() -> int:
    """Lit le bankroll PRISMA depuis Prisma.json (créé si absent)."""
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
    """Enregistre le bankroll PRISMA dans Prisma.json."""
    with _file_lock:
        try:
            _wallet_path.parent.mkdir(parents=True, exist_ok=True)
            _wallet_path.write_text(json.dumps({"bankroll": int(value)}), encoding="utf-8")
        except Exception as e:
            logger.error(f"Erreur écriture Prisma.json : {e}", exc_info=True)


def get_prisma_bankroll():
    """
    Récupère le bankroll dédié à PRISMA depuis Prisma.json.
    """
    return _read_wallet()


def update_prisma_bankroll(session_id, nouveau_bankroll, mise, resultat, cote):
    """
    Met à jour le bankroll de PRISMA après un pari multiple (stockage JSON).
    """
    profit_net = int(mise * cote) - mise if (resultat == 1 and cote is not None) else (-mise if resultat == 0 else 0)
    _write_wallet(nouveau_bankroll)
    logger.info(f"Bankroll PRISMA mis à jour (JSON) : {nouveau_bankroll} Ar (Profit: {profit_net} Ar)")


def deduct_prisma_funds(mise):
    """
    Déduit les fonds du portefeuille PRISMA lors de la création d'un pari (stockage JSON).
    """
    current_bankroll = get_prisma_bankroll()
    new_bankroll = current_bankroll - mise

    if new_bankroll < 0:
        logger.warning(f"Fonds insuffisants PRISMA: {current_bankroll} Ar < {mise} Ar")
        return False, current_bankroll

    # Mettre à jour immédiatement le bankroll
    active_session = get_active_session()
    session_id = active_session["id"]

    update_prisma_bankroll(session_id, new_bankroll, mise, None, None)
    return True, new_bankroll
