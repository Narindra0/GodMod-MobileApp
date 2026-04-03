import logging

from . import config
from .database import get_db_connection
from .session_manager import get_active_session

logger = logging.getLogger(__name__)

_DEFAULT_BANKROLL = 20000


def _read_wallet() -> int:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value_int FROM prisma_config WHERE key = 'bankroll'")
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
                "UPDATE prisma_config SET value_int = %s, last_update = CURRENT_TIMESTAMP WHERE key = 'bankroll'",
                (int(value),),
            )
    except Exception as e:
        logger.error(f"Erreur écriture bankroll PRISMA en DB : {e}", exc_info=True)


def get_prisma_bankroll():
    return _read_wallet()


def is_prisma_stop_loss_active() -> bool:
    return get_prisma_bankroll() < config.BANKROLL_STOP_LOSS


def update_prisma_bankroll(session_id, nouveau_bankroll, mise, resultat, cote):
    profit_net = int(mise * cote) - mise if (resultat == 1 and cote is not None) else (-mise if resultat == 0 else 0)
    _write_wallet(nouveau_bankroll)
    logger.info(f"Bankroll PRISMA mis à jour (DB) : {nouveau_bankroll} Ar (Profit: {profit_net} Ar)")


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

    # On délègue à update_prisma_bankroll pour l'écriture DB
    active_session = get_active_session()
    session_id = active_session["id"]
    update_prisma_bankroll(session_id, new_bankroll, mise, None, None)
    return True, new_bankroll
