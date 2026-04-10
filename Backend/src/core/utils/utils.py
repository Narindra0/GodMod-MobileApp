import json
from decimal import Decimal
from datetime import datetime, date

class DecimalEncoder(json.JSONEncoder):
    """
    Encodeur JSON personnalisé pour gérer les objets Decimal, datetime et date.
    """
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)

def safe_json_dumps(obj, **kwargs):
    """
    Serialize an object to a JSON formatted string, handling Decimals and datetimes.
    """
    if 'cls' not in kwargs:
        kwargs['cls'] = DecimalEncoder
    return json.dumps(obj, **kwargs)


def _update_config_flag(flag_name, new_value):
    import os

    config_path = os.path.join(os.path.dirname(__file__), "config.py")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        updated = False
        for i, line in enumerate(lines):
            if line.strip().startswith(flag_name):
                lines[i] = f"{flag_name} = {new_value}\n"
                updated = True
                break
        if updated:
            with open(config_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            import importlib
            import sys

            if "src.core.config" in sys.modules:
                importlib.reload(sys.modules["src.core.config"])
            return True
        else:
            return False
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(f"Erreur lors de la mise à jour du flag {flag_name} : {e}", exc_info=True)
        return False


def update_global_intelligence_flags(new_value):
    import os

    config_path = os.path.join(os.path.dirname(__file__), "config.py")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        updated_count = 0
        flags_to_update = ["USE_INTELLIGENCE_AMELIOREE", "USE_SELECTION_AMELIOREE"]
        for i, line in enumerate(lines):
            line_strip = line.strip()
            for flag in flags_to_update:
                if line_strip.startswith(flag):
                    lines[i] = f"{flag} = {new_value}\n"
                    updated_count += 1
        if updated_count > 0:
            with open(config_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            import importlib
            import sys

            if "src.core.config" in sys.modules:
                importlib.reload(sys.modules["src.core.config"])
            return True
        return False
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(f"Erreur lors de la mise à jour globale des flags : {e}", exc_info=True)
        return False
