import os
import joblib
import numpy as np
from typing import Dict, Tuple, Any, Optional

# Optional pandas import
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

from dotenv import load_dotenv

load_dotenv()

# Locked 7 features in exact order
REQUIRED_FEATURES = [
    "attempt_count",
    "hint_count",
    "ms_first_response",
    "skill_id",
    "bottom_hint",
    "actions",
    "overlap_time"
]

# Configurable risk thresholds
HIGH_RISK_THRESHOLD = float(os.getenv("HIGH_RISK_THRESHOLD", "0.60"))
MEDIUM_RISK_THRESHOLD = float(os.getenv("MEDIUM_RISK_THRESHOLD", "0.30"))
DEFAULT_RESPONSE_TIME_MS = float(os.getenv("DEFAULT_RESPONSE_TIME_MS", "5000.0"))

# Relative directory resolve
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.getenv("MODELS_DIR", os.path.join(BASE_DIR, "models"))

# Search paths for model files — backend/models/ first, then user Downloads, then project root
_SEARCH_DIRS = [
    MODELS_DIR,
    os.path.join(BASE_DIR, "models"),
    r"D:\Downloads",
    r"C:\Users\Hp\Downloads",
    BASE_DIR,
]

def _find_model_file(filename: str) -> Optional[str]:
    """Search multiple directories for a model .pkl file."""
    for directory in _SEARCH_DIRS:
        candidate = os.path.join(directory, filename)
        if os.path.exists(candidate):
            return candidate
    return None

XGB_PATH = os.getenv("XGB_MODEL_PATH") or _find_model_file("eduinsight_xgb.pkl") or os.path.join(MODELS_DIR, "eduinsight_xgb.pkl")
RF_PATH  = os.getenv("RF_MODEL_PATH")  or _find_model_file("eduinsight_rf.pkl")  or os.path.join(MODELS_DIR, "eduinsight_rf.pkl")

class MLModelService:
    def __init__(self):
        self.xgb_model = None
        self.rf_model = None
        self.load_models()

    def load_models(self):
        """Loads XGBoost and Random Forest pre-trained models from backend/models/."""
        if os.path.exists(XGB_PATH):
            try:
                self.xgb_model = joblib.load(XGB_PATH)
                print(f"[MLService] Loaded XGBoost model successfully from {XGB_PATH}")
            except Exception as e:
                print(f"[MLService] Error loading XGBoost model: {e}")
                self.xgb_model = None
        else:
            print(f"[MLService] Warning: XGBoost model not found at {XGB_PATH}")

        if os.path.exists(RF_PATH):
            try:
                self.rf_model = joblib.load(RF_PATH)
                print(f"[MLService] Loaded Random Forest model successfully from {RF_PATH}")
            except Exception as e:
                print(f"[MLService] Error loading Random Forest model: {e}")
                self.rf_model = None
        else:
            print(f"[MLService] Warning: Random Forest model not found at {RF_PATH}")

    def prepare_features(self, feature_dict: Dict[str, Any]) -> Any:
        """
        Constructs model input with exact 7 features in exact order.
        Converts features to numeric and replaces missing/NaN values with 0.
        """
        row = []
        for feat in REQUIRED_FEATURES:
            val = feature_dict.get(feat, 0)
            try:
                val = float(val)
                if np.isnan(val):
                    val = 0.0
            except (ValueError, TypeError):
                val = 0.0
            row.append(val)

        arr = np.array([row], dtype=np.float32)

        if HAS_PANDAS:
            return pd.DataFrame(arr, columns=REQUIRED_FEATURES)
        return arr

    def predict_risk(self, feature_dict: Dict[str, Any], model_type: str = "xgb") -> Tuple[float, str, str]:
        """
        Predicts student learning risk probability and risk level.
        Uses model.classes_ to locate the exact probability index for class 0 (incorrect/risk class).
        Returns: (risk_probability, risk_level, model_used)
        """
        model = self.xgb_model if model_type == "xgb" else self.rf_model
        model_name = "XGBoost" if model_type == "xgb" else "Random Forest"

        if model is None:
            if self.xgb_model is not None:
                model = self.xgb_model
                model_name = "XGBoost"
            elif self.rf_model is not None:
                model = self.rf_model
                model_name = "Random Forest"
            else:
                # Graceful heuristic fallback if .pkl files are not placed yet
                att = float(feature_dict.get("attempt_count", 1))
                hnt = float(feature_dict.get("hint_count", 0))
                ms = float(feature_dict.get("ms_first_response", DEFAULT_RESPONSE_TIME_MS))
                
                # Baseline risk calculation pending .pkl placement
                base_prob = 0.15 + (att - 1) * 0.25 + hnt * 0.20 + (1 if ms > 8000 else 0) * 0.10
                risk_probability = max(0.05, min(0.95, float(base_prob)))
                
                if risk_probability >= HIGH_RISK_THRESHOLD:
                    risk_level = "HIGH"
                elif risk_probability >= MEDIUM_RISK_THRESHOLD:
                    risk_level = "MEDIUM"
                else:
                    risk_level = "LOW"
                    
                return risk_probability, risk_level, "XGBoost (Pending .pkl model)"

        features_input = self.prepare_features(feature_dict)

        # Calculate prediction probabilities
        probabilities = model.predict_proba(features_input)[0]

        # Dynamically locate index for class 0 (incorrect/risk class)
        classes = getattr(model, "classes_", np.array([0, 1]))
        if 0 in classes:
            class0_idx = np.where(classes == 0)[0][0]
        else:
            class0_idx = 0  # Fallback to index 0

        risk_probability = float(probabilities[class0_idx])

        # Classify risk level based on configurable thresholds
        if risk_probability >= HIGH_RISK_THRESHOLD:
            risk_level = "HIGH"
        elif risk_probability >= MEDIUM_RISK_THRESHOLD:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        return risk_probability, risk_level, model_name

ml_service = MLModelService()
