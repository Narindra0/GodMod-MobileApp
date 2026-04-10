import logging
from . import config
from .database import get_db_connection
from .session_manager import get_active_session

logger = logging.getLogger(__name__)

_DEFAULT_BANKROLL = config.DEFAULT_BANKROLL

def _read_wallet() -> int:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # On utilise maintenant la clé spécifique bankroll_prisma
            cursor.execute("SELECT value_int FROM prisma_config WHERE key = 'bankroll_prisma'")
            row = cursor.fetchone()
            if row:
                return int(row["value_int"])
            return _DEFAULT_BANKROLL
    except Exception as e:
        logger.error(f"Erreur lecture bankroll PRISMA en DB : {e}", exc_info=True)
        return _DEFAULT_BANKROLL

def _write_wallet(value: int) -> None:
    try:
        with get_db_connection(write=True) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO prisma_config (key, value_int, last_update) VALUES ('bankroll_prisma', %s, CURRENT_TIMESTAMP) "
                "ON CONFLICT (key) DO UPDATE SET value_int = EXCLUDED.value_int, last_update = CURRENT_TIMESTAMP",
                (int(value),),
            )
    except Exception as e:
        logger.error(f"Erreur écriture bankroll PRISMA en DB : {e}", exc_info=True)

def get_prisma_bankroll():
    return _read_wallet()

def is_prisma_stop_loss_active() -> bool:
    return get_prisma_bankroll() < config.BANKROLL_STOP_LOSS

def update_prisma_bankroll(nouveau_bankroll, mise, resultat, cote):
    """Met à jour le bankroll PRISMA global (non spécifique à une session)."""
    _write_wallet(nouveau_bankroll)
    logger.info(f"Bankroll PRISMA (Global) mis à jour : {nouveau_bankroll} Ar")

def deduct_prisma_funds(mise):
    current_bankroll = get_prisma_bankroll()
    if current_bankroll < config.BANKROLL_STOP_LOSS:
        logger.warning(
            f"[STOP-LOSS] Bankroll PRISMA ({current_bankroll} Ar) sous le seuil ({config.BANKROLL_STOP_LOSS} Ar). Pari refusé."
        )
        return False, current_bankroll

    new_bankroll = current_bankroll - mise
    if new_bankroll < 0:
        logger.warning(
            f"Fonds insuffisants PRISMA: {current_bankroll} Ar < {mise} Ar"
        )
        return False, current_bankroll

    update_prisma_bankroll(new_bankroll, mise, None, None)
    return True, new_bankroll
