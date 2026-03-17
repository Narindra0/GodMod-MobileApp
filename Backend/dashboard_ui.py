import streamlit as st
import pandas as pd
import time
from datetime import datetime
from src.core import config
st.set_page_config(
    page_title="GODMOD V2 - Intelligence Center",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700&display=swap');
    .main { background-color: #0d1117; }
    .stMetric {
        background: linear-gradient(145deg, #161b22, #0d1117);
        padding: 20px;
        border-radius: 15px;
        border: 1px solid #30363d;
        box-shadow: 0 4px 15px rgba(0,0,0,0.3);
    }
    .big-font {
        font-family: 'Orbitron', sans-serif;
        font-size: 24px !important;
        font-weight: bold;
        color: #58a6ff;
    }
    div[data-testid="stExpander"] {
        border-radius: 10px;
        border: 1px solid #30363d;
    }
    .status-active {
        color: #238636;
        font-weight: bold;
        animation: pulse 2s infinite;
    }
    @keyframes pulse {
        0% { opacity: 0.5; }
        50% { opacity: 1; }
        100% { opacity: 0.5; }
    }
</style>
""", unsafe_allow_html=True)
@st.cache_data(ttl=5)
def load_all_data():
    from src.core.database import get_db_connection
    from src.core.session_manager import get_active_session
    active_session = get_active_session()
    session_id = active_session['id']
    with get_db_connection() as conn:
        df_session = pd.read_sql_query("SELECT score_prisma as score, score_zeus FROM sessions WHERE id = ?", conn, params=(session_id,))
        df_total = pd.read_sql_query("SELECT COUNT(*) as total FROM predictions WHERE session_id = ? AND succes IS NOT NULL", conn, params=(session_id,))
        df_wins = pd.read_sql_query("SELECT COUNT(*) as wins FROM predictions WHERE session_id = ? AND succes = 1", conn, params=(session_id,))
        df_preds = pd.read_sql_query("""
            SELECT m.journee as J, e1.nom as Domicile, e2.nom as Exterieur, p.prediction as Prono, p.resultat as Reel, p.succes
            FROM predictions p
            JOIN matches m ON p.match_id = m.id
            JOIN equipes e1 ON m.equipe_dom_id = e1.id
            JOIN equipes e2 ON m.equipe_ext_id = e2.id
            WHERE p.session_id = ?
            ORDER BY p.id DESC LIMIT 15
        """, conn, params=(session_id,))
        df_results = pd.read_sql_query("""
            SELECT m.journee as J, e1.nom as Domicile, m.score_dom || ' - ' || m.score_ext as Score, e2.nom as Exterieur
            FROM matches m
            JOIN equipes e1 ON m.equipe_dom_id = e1.id
            JOIN equipes e2 ON m.equipe_ext_id = e2.id
            WHERE m.session_id = ? AND m.status = 'TERMINE'
            ORDER BY m.journee DESC, m.id DESC
        """, conn, params=(session_id,))
        df_ranking = pd.read_sql_query("""
            SELECT e.nom as Equipe, c.points as Pts, c.forme as Forme
            FROM classement c
            JOIN equipes e ON c.equipe_id = e.id
            WHERE c.session_id = ? AND c.journee = (SELECT MAX(journee) FROM classement WHERE session_id = ?)
            ORDER BY c.points DESC
        """, conn, params=(session_id, session_id))
        df_trend = pd.read_sql_query(f"SELECT id, (CASE WHEN succes = 1 THEN {config.PRISMA_POINTS_VICTOIRE} ELSE {config.PRISMA_POINTS_DEFAITE} END) as points_gagnes FROM predictions WHERE session_id = ? AND succes IS NOT NULL ORDER BY id", conn, params=(session_id,))
        session_info = pd.DataFrame([active_session])
        return df_session, df_total, df_wins, df_preds, df_results, df_ranking, df_trend, session_info
st.title("⚡ GODMOD V2 | Intelligence Center")
st.markdown(f"*Dernière mise à jour : {datetime.now().strftime('%H:%M:%S')}*")
df_session, df_total, df_wins, df_preds, df_results, df_ranking, df_trend, _ = load_all_data()
score = df_session['score'].iloc[0] if not df_session.empty else 0
wins = df_wins['wins'].iloc[0] if not df_wins.empty else 0
total_history = df_total['total'].iloc[0] if not df_total.empty else 0
win_rate = (wins / total_history * 100) if total_history > 0 else 0
m1, m2, m3, m4 = st.columns(4)
with m1: st.metric("Score Global", f"{score} pts")
with m2: st.metric("Taux de Réussite", f"{win_rate:.1f}%")
with m3: st.metric("Total Prédictions", f"{total_history}")
with m4: st.metric("Victoires", wins)
st.markdown("---")
col_left, col_right = st.columns([2, 1])
with col_left:
    tab_preds, tab_results = st.tabs(["🎯 Prédictions", "📜 Derniers Résultats"])
    with tab_preds:
        st.subheader("Dernières Prédictions")
        if not df_preds.empty:
            st.dataframe(df_preds, use_container_width=True, hide_index=True)
        else:
            st.info("Aucune prédiction disponible.")
    with tab_results:
        st.subheader("Résultats Officiels")
        if not df_results.empty:
            journees = sorted(df_results['J'].unique().tolist(), reverse=True)
            journee_selectionnee = st.selectbox(
                "📅 Sélectionner la journée", 
                journees, 
                index=0,
                key="journee_selector"
            )
            df_filtered = df_results[df_results['J'] == journee_selectionnee]
            st.dataframe(df_filtered, use_container_width=True, hide_index=True)
        else:
            st.info("Aucun résultat enregistré.")
with col_right:
    st.subheader("📊 Top Classement")
    st.dataframe(df_ranking.head(10), use_container_width=True, hide_index=True)
    st.subheader("📈 Courbe de Profit")
    if not df_trend.empty:
        df_trend['Cumulative'] = df_trend['points_gagnes'].cumsum()
        st.line_chart(df_trend.set_index('id')['Cumulative'], height=200)
st.sidebar.title("🛠️ Paramètres")
st.sidebar.markdown(f"**Statut :** <span class='status-active'>LIVE MONITORING</span>", unsafe_allow_html=True)
st.sidebar.markdown("---")
st.sidebar.subheader("🧠 Intelligence & Sélection")
current_intelligence_state = config.USE_INTELLIGENCE_AMELIOREE
new_intelligence_state = st.sidebar.toggle(
    "Intelligence Complète",
    value=current_intelligence_state,
    help="Active simultanément le Mode Multi-Facteurs et la Phase 3 (Sélection Améliorée)"
)
if new_intelligence_state != current_intelligence_state:
    from src.core import utils
    if utils.update_global_intelligence_flags(new_intelligence_state):
        import importlib
        import sys
        if 'src.core.config' in sys.modules:
            importlib.reload(sys.modules['src.core.config'])
            if 'src.analysis.intelligence' in sys.modules:
                importlib.reload(sys.modules['src.analysis.intelligence'])
        if new_intelligence_state:
            st.sidebar.success("✅ Mode Intelligence Complète activé !")
        else:
            st.sidebar.info("ℹ️ Retour au Mode Standard")
        time.sleep(0.5)
        st.rerun()
    else:
        st.sidebar.error("❌ Erreur de mise à jour configuration")
if current_intelligence_state:
    st.sidebar.markdown(
        """
        <div style='background-color: rgba(35, 134, 54, 0.2); padding: 10px; border-radius: 5px; border-left: 3px solid #238636;'>
            <span style='color: #238636; font-weight: bold;'>🟢 SYSTÈME ACTIF</span>
        </div>
        """, 
        unsafe_allow_html=True
    )
else:
    st.sidebar.markdown(
        """
        <div style='background-color: rgba(248, 81, 73, 0.1); padding: 10px; border-radius: 5px; border-left: 3px solid #f85149;'>
            <span style='color: #f85149; font-weight: bold;'>🔴 MODE SIMPLE</span>
        </div>
        """, 
        unsafe_allow_html=True
    )
st.sidebar.markdown("---")
refresh = st.sidebar.slider("Rafraîchissement (sec)", 2, 30, 5)
auto_refresh = st.sidebar.checkbox("Auto-refresh", value=True)
if auto_refresh:
    time.sleep(refresh)
    st.rerun()
