"""
PRISMA Training Status Manager
Gestionnaire d'état thread-safe pour le monitoring en temps réel.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
import threading

logger = logging.getLogger(__name__)

class TrainingStatus:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(TrainingStatus, cls).__new__(cls)
                    cls._instance._init_state()
        return cls._instance

    def _init_state(self):
        self.state = {
            "is_training": False,
            "current_model": None,
            "progress": 0,  # 0 to 100
            "step_description": "Initialisation du système...",
            "start_time": None,
            "last_update": datetime.now().isoformat(),
            "models_progress": {
                "xgboost": {"status": "pending", "progress": 0, "accuracy": 0},
                "catboost": {"status": "pending", "progress": 0, "accuracy": 0},
                "lightgbm": {"status": "pending", "progress": 0, "accuracy": 0}
            },
            "logs": []
        }

    def update_global(self, is_training: bool = None, current_model: str = None, description: str = None):
        with self._lock:
            if is_training is not None:
                self.state["is_training"] = is_training
                if is_training:
                    self.state["start_time"] = datetime.now().isoformat()
                else:
                    self.state["current_model"] = None
                    self.state["progress"] = 100
            
            if current_model is not None:
                self.state["current_model"] = current_model
            
            if description is not None:
                self.state["step_description"] = description
                self.add_log(description)
            
            self.state["last_update"] = datetime.now().isoformat()

    def update_model(self, model: str, status: str = None, progress: int = None, accuracy: float = None):
        with self._lock:
            if model in self.state["models_progress"]:
                mod = self.state["models_progress"][model]
                if status: mod["status"] = status
                if progress is not None: mod["progress"] = progress
                if accuracy is not None: mod["accuracy"] = accuracy
                
                # Mettre à jour le progrès global basé sur les 3 modèles (33% chacun)
                total_progress = 0
                for m in self.state["models_progress"].values():
                    if m["status"] == "completed": total_progress += 33.3
                    elif m["status"] == "training": total_progress += (m["progress"] / 3)
                
                self.state["progress"] = min(100, int(total_progress))
                self.state["last_update"] = datetime.now().isoformat()

    def add_log(self, message: str):
        with self._lock:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.state["logs"].append(f"[{timestamp}] {message}")
            if len(self.state["logs"]) > 10:
                self.state["logs"].pop(0)

    def get_status(self) -> Dict:
        with self._lock:
            return self.state.copy()

# Singleton accessible
status_manager = TrainingStatus()
