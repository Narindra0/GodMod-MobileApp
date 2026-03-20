from . import config
from .database import get_db_connection


def initialize_prisma_db():
    """Initialise le bankroll PRISMA en DB (via migration si nécessaire)"""
    from .prisma_finance import get_prisma_bankroll

    bankroll = get_prisma_bankroll()
    print(f"[PRISMA] Bankroll initialisé à {bankroll} Ar")
    return True


def initialize_team_logos():
    """Vérifie et peuple les logos des équipes s'ils sont manquants"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Vérifie s'il y a des équipes sans logo
            cursor.execute("SELECT COUNT(*) as count FROM equipes WHERE logo_url IS NULL OR logo_url = ''")
            missing_logos_count = cursor.fetchone()["count"]

            if missing_logos_count > 0:
                print(f"{missing_logos_count} équipe(s) sans logo trouvé(s), mise à jour en cours...")

                updated_count = 0
                for team_name, logo_url in config.TEAM_LOGOS.items():
                    cursor.execute(
                        "UPDATE equipes SET logo_url = %s WHERE nom = %s AND (logo_url IS NULL OR logo_url = '')",
                        (logo_url, team_name),
                    )
                    if cursor.rowcount > 0:
                        print(f"[OK] Logo mis à jour pour : {team_name}")
                        updated_count += 1

                # Vérifie aussi avec les alias
                for alias, canonical_name in config.TEAM_ALIASES.items():
                    if canonical_name in config.TEAM_LOGOS:
                        logo_url = config.TEAM_LOGOS[canonical_name]
                        cursor.execute(
                            "UPDATE equipes SET logo_url = %s WHERE nom = %s AND (logo_url IS NULL OR logo_url = '')",
                            (logo_url, alias),
                        )
                        if cursor.rowcount > 0:
                            print(f"[OK] Logo mis à jour pour alias : {alias}")
                            updated_count += 1

                conn.commit()
                print(f"Terminé ! {updated_count} logos mis à jour.")
                return True
            else:
                print("Toutes les équipes ont déjà des logos.")
                return False

    except Exception as e:
        print(f"Erreur lors de l'initialisation des logos: {e}")
        return False


def initialize_all():
    """Initialise toutes les données requises au démarrage"""
    print("[START] Initialisation des données...")

    prisma_initialized = initialize_prisma_db()
    logos_updated = initialize_team_logos()

    if prisma_initialized or logos_updated:
        print("[OK] Initialisation terminée avec succès!")
    else:
        print("[INFO] Toutes les données sont déjà initialisées.")


if __name__ == "__main__":
    initialize_all()
