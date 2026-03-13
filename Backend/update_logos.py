#!/usr/bin/env python3
"""
Script pour mettre à jour les logos des équipes dans la base de données
"""

import sqlite3
from src.core import config, database

def ajouter_colonne_logo():
    """Ajoute la colonne logo_url si elle n'existe pas"""
    try:
        with database.get_db_connection(write=True) as conn:
            cursor = conn.cursor()
            
            # Vérifier si la colonne existe déjà
            cursor.execute("PRAGMA table_info(equipes)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if 'logo_url' not in columns:
                cursor.execute("ALTER TABLE equipes ADD COLUMN logo_url TEXT")
                print("✅ Colonne logo_url ajoutée avec succès")
            else:
                print("ℹ️ La colonne logo_url existe déjà")
                
    except Exception as e:
        print(f"❌ Erreur lors de l'ajout de la colonne: {e}")

def mettre_a_jour_logo(equipe_nom, logo_url):
    """Met à jour le logo d'une équipe spécifique"""
    try:
        with database.get_db_connection(write=True) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE equipes SET logo_url = ? WHERE nom = ?",
                (logo_url, equipe_nom)
            )
            
            if cursor.rowcount > 0:
                print(f"✅ Logo mis à jour pour {equipe_nom}")
            else:
                print(f"❌ Équipe '{equipe_nom}' non trouvée")
                
    except Exception as e:
        print(f"❌ Erreur lors de la mise à jour du logo: {e}")

def lister_equipes_sans_logo():
    """Liste les équipes qui n'ont pas encore de logo"""
    try:
        with database.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, nom FROM equipes WHERE logo_url IS NULL OR logo_url = '' ORDER BY nom"
            )
            equipes = cursor.fetchall()
            
            if equipes:
                print(f"📋 Équipes sans logo ({len(equipes)}):")
                for i, (id, nom) in enumerate(equipes, 1):
                    print(f"  {i:2d}. {id:2d}. {nom}")
            else:
                print("✅ Toutes les équipes ont un logo!")
                
    except Exception as e:
        print(f"❌ Erreur lors de la lecture: {e}")

def lister_toutes_les_equipes():
    """Liste toutes les équipes avec leurs logos"""
    try:
        with database.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, nom, logo_url FROM equipes ORDER BY nom")
            equipes = cursor.fetchall()
            
            print("=== ÉQUIPES AVEC LOGOS ===")
            for id, nom, logo_url in equipes:
                status = "✅" if logo_url else "❌"
                print(f"{status} {id:2d}. {nom}")
                if logo_url:
                    print(f"    URL: {logo_url}")
                print()
                
    except Exception as e:
        print(f"❌ Erreur lors de la lecture: {e}")

if __name__ == "__main__":
    print("=== GESTION DES LOGOS D'ÉQUIPES ===\n")
    
    # 1. Ajouter la colonne si nécessaire
    print("1. Vérification de la structure de la base...")
    ajouter_colonne_logo()
    print()
    
    # 2. Lister les équipes sans logo
    print("2. Équipes needing logos:")
    lister_equipes_sans_logo()
    print()
    
    # 3. Instructions pour l'utilisateur
    print("=== INSTRUCTIONS ===")
    print("Pour mettre à jour les logos, utilisez:")
    print("python -c \"from update_logos import mettre_a_jour_logo; mettre_a_jour_logo('Nom Équipe', 'URL_DIRECTE')\"")
    print("\nExemple:")
    print("python -c \"from update_logos import mettre_a_jour_logo; mettre_a_jour_logo('London Reds', 'https://i.ibb.co/example/london-reds.png')\"")
    print("\nPour voir toutes les équipes:")
    print("python -c \"from update_logos import lister_toutes_les_equipes; lister_toutes_les_equipes()\"")
