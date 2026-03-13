#!/usr/bin/env python3
"""
Script pour lister toutes les équipes de la base de données GODMOD
"""

from src.core.database import get_db_connection

def lister_equipes():
    """Liste toutes les équipes présentes dans la base de données"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, nom FROM equipes ORDER BY nom')
            equipes = cursor.fetchall()
            
            print("=== ÉQUIPES DANS LA BASE DE DONNÉES GODMOD ===")
            print(f"Total: {len(equipes)} équipes\n")
            
            for i, row in enumerate(equipes, 1):
                print(f"{i:2d}. {row[0]:2d}. {row[1]}")
                
    except Exception as e:
        print(f"Erreur lors de la lecture des équipes: {e}")

if __name__ == "__main__":
    lister_equipes()
