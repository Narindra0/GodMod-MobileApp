import logging
import os
from logging.handlers import RotatingFileHandler
from . import config

def setup_app_logging():
    """
    Configure un logging robuste avec rotation de fichiers.
    - prisma.log : Journal principal (Max 5MB, 5 backups)
    - zeus.log : Journal spécifique ZEUS
    """
    logs_dir = getattr(config, 'LOGS_DIR', 'logs')
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)

    log_format = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Handler Fichier Principal (Rotation)
    main_handler = RotatingFileHandler(
        os.path.join(logs_dir, "prisma.log"),
        maxBytes=5*1024*1024, # 5MB
        backupCount=5,
        encoding='utf-8'
    )
    main_handler.setFormatter(log_format)
    main_handler.setLevel(logging.INFO) # Toujours capturer INFO dans le fichier

    # Handler Console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)

    # Racine du logger
    root_logger = logging.getLogger()
    # On évite de dupliquer les handlers si setup est appelé plusieurs fois
    if not root_logger.handlers:
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(main_handler)
        root_logger.addHandler(console_handler)

    logging.info("📝 Système de logging initialisé avec rotation (5MB/file).")
