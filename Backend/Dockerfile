FROM python:3.10-slim

# Éviter la génération de fichiers .pyc et activer le mode non-interactif
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Définir le répertoire de travail
WORKDIR /app

# Installer les dépendances système nécessaires (psycopg2, etc.)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copier le fichier requirements.txt
COPY requirements.txt .

# Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Copier le reste de l'application
COPY . .

# Créer les dossiers nécessaires (persistants ou non)
RUN mkdir -p data logs models

# Exposition du port (Hugging Face utilise 7860 par défaut)
EXPOSE 7860

# Lancer l'application
# On utilise main.py qui gère à la fois l'API et la surveillance
CMD ["python", "main.py"]
