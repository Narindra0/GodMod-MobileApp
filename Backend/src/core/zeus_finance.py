import logging
from . import config
from .database import get_db_connection
from .session_manager import get_active_session

logger = logging.getLogger(__name__)

def get_zeus_bankroll(session_id=None, conn=None):
    """Récupère le capital actuel de ZEUS pour la session."""
    if session_id is None:
        active_session = get_active_session(conn=conn)
        session_id = active_session['id']
    
    def _read(c):
        cursor = c.cursor()
        cursor.execute("""
            SELECT bankroll_apres FROM historique_paris 
            WHERE session_id = %s AND strategie = 'ZEUS' 
            ORDER BY id_pari DESC LIMIT 1
        """, (session_id,))
        row = cursor.fetchone()
        if row:
            return int(row['bankroll_apres'])
        
        cursor.execute("SELECT capital_initial FROM sessions WHERE id = %s", (session_id,))
        s_row = cursor.fetchone()
        return int(s_row['capital_initial']) if s_row else config.DEFAULT_BANKROLL

    if conn:
        return _read(conn)
    try:
        with get_db_connection() as conn:
            return _read(conn)
    except:
        return config.DEFAULT_BANKROLL

def is_zeus_stop_loss_active(session_id=None, conn=None):
    """Vérifie si le stop-loss ZEUS est activé."""
    return get_zeus_bankroll(session_id, conn) < config.BANKROLL_STOP_LOSS

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
    return enregistrer_pari(record, conn)
