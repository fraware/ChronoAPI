import torch
from tsfm_public.toolkit.get_model import get_model

TTM_MODEL_PATH = "ibm-granite/granite-timeseries-ttm-r2"
CONTEXT_LENGTH = 512
PREDICTION_LENGTH = 96


def load_model():
    try:
        model = get_model(
            model_path=TTM_MODEL_PATH,
            context_length=CONTEXT_LENGTH,
            prediction_length=PREDICTION_LENGTH,
        )
        model.eval()  # Set the model to evaluation mode
        return model
    except Exception as e:
        raise RuntimeError(f"Failed to load TTM model: {e}")


# Load the model once during startup
model = load_model()
