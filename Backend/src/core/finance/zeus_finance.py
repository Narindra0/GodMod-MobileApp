import logging
from ..system import config
from ..db.database import get_db_connection
from ..system.session_manager import get_active_session

logger = logging.getLogger(__name__)

def get_zeus_bankroll(conn=None):
    """Récupère le capital global actuel de ZEUS."""
    def _read(c):
        cursor = c.cursor()
        cursor.execute("SELECT value_int FROM prisma_config WHERE key = 'bankroll_zeus'")
        row = cursor.fetchone()
        if row:
            return int(row["value_int"])
        return config.DEFAULT_BANKROLL

    if conn:
        return _read(conn)
    try:
        with get_db_connection() as conn:
            return _read(conn)
    except Exception:
        return config.DEFAULT_BANKROLL

def update_zeus_bankroll(nouveau_bankroll, conn=None):
    """Met à jour le capital global de ZEUS."""
    def _write(c):
        cursor = c.cursor()
        cursor.execute(
            "INSERT INTO prisma_config (key, value_int, last_update) VALUES ('bankroll_zeus', %s, CURRENT_TIMESTAMP) "
            "ON CONFLICT (key) DO UPDATE SET value_int = EXCLUDED.value_int, last_update = CURRENT_TIMESTAMP",
            (int(nouveau_bankroll),)
        )

    if conn:
        _write(conn)
    else:
        with get_db_connection(write=True) as conn:
            _write(conn)
    logger.info(f"Bankroll ZEUS (Global) mis à jour : {nouveau_bankroll} Ar")

def is_zeus_stop_loss_active(conn=None):
    """Vérifie si le stop-loss ZEUS est activé."""
    return get_zeus_bankroll(conn) < config.BANKROLL_STOP_LOSS

def record_zeus_combined_bet(session_id, journee, mise, bankroll_apres, conn):
    """Enregistre le mouvement de bankroll initial pour un combiné ZEUS."""
    from ..zeus.database.queries import PariRecord, enregistrer_pari
    
    record = PariRecord(
        session_id=session_id,
        prediction_id=None, # Pas de prédiction simple unique
        journee=journee,
        type_pari='COMBINED',
        mise_ar=int(mise),
        pourcentage_bankroll=0.0, # Optionnel pour combiné
        cote_jouee=None, # Sera mis à jour à la fin
        resultat=None,
        profit_net=None,
        bankroll_apres=int(bankroll_apres),
        probabilite_implicite=None,
        action_id=0,
        strategie='ZEUS'
    )
    # On met aussi à jour le portefeuille global ici par sécurité (déduction de la mise)
    update_zeus_bankroll(bankroll_apres, conn=conn)
    return enregistrer_pari(record, conn)
