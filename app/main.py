import logging
import asyncio
import json
import time
import math
import tempfile
import warnings
from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
import pandas as pd
import torch

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from transformers import Trainer, TrainingArguments, EarlyStoppingCallback, set_seed
from torch.optim import AdamW
from torch.optim.lr_scheduler import OneCycleLR

from app.config import settings  # import our settings
from app.model import model  # load the TTM model from our model module
from tsfm_public import TimeSeriesPreprocessor, get_datasets, TrackingCallback
from tsfm_public.toolkit.get_model import get_model

# Configure structured logging using settings
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("forecasting_service")

# Create FastAPI app with API metadata for documentation.
app = FastAPI(
    title="TTM Forecasting Microservice API",
    description=(
        "This API provides real-time forecasting capabilities using IBM Research’s TTM model. "
        "It supports endpoints for health checks, forecasting, fine-tuning the model on custom data, "
        "and metrics collection. Interactive API documentation is available via Swagger (/docs) and ReDoc (/redoc)."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# --- Prometheus Metrics ---
forecast_requests_total = Counter(
    "forecast_requests_total",
    "Total number of forecast requests processed",
    ["method", "endpoint"],
)
forecast_latency_seconds = Histogram(
    "forecast_latency_seconds",
    "Time taken to process forecast requests",
    ["method", "endpoint"],
)
kafka_messages_total = Counter(
    "kafka_messages_total", "Total number of Kafka messages processed", ["status"]
)

# Global preprocessor configuration (adjust as needed)
timestamp_column = "date"
id_columns = []  # Adjust if you have unique IDs per series.
target_columns = ["HUFL", "HULL", "MUFL", "MULL", "LUFL", "LULL", "OT"]
column_specifiers = {
    "timestamp_column": timestamp_column,
    "id_columns": id_columns,
    "target_columns": target_columns,
    "control_columns": [],
}


# Pydantic request model for inference via REST API
class ForecastRequest(BaseModel):
    """
    Request model for generating forecasts.

    Attributes:
        data (list): A list of records, each a dictionary with at least a 'date' and target values.
        context_length (int): Number of historical time steps to use.
        forecast_length (int): Number of future time steps to forecast.
        request_id (str, optional): Optional identifier for correlating requests.
    """

    data: list
    context_length: int = 512
    forecast_length: int = 96
    request_id: str = None


# Pydantic request model for fine-tuning
class FineTuneRequest(BaseModel):
    """
    Request model for fine-tuning the TTM model.

    Attributes:
        data (list): Full dataset as list of records (each record must include a 'date' and target values).
        context_length (int): Historical context length.
        forecast_length (int): Forecast horizon.
        fewshot_percent (float): Percentage of data used for fine-tuning.
        freeze_backbone (bool): Whether to freeze the model backbone during fine-tuning.
        learning_rate (float): Learning rate for training.
        num_epochs (int): Number of training epochs.
        batch_size (int): Batch size for training.
        loss (str): Loss function to use (e.g., "mse" or "pinball").
        quantile (float): Quantile value for pinball loss.
        request_id (str, optional): Optional identifier for correlating requests.
    """

    data: list
    context_length: int = 512
    forecast_length: int = 96
    fewshot_percent: float = 5.0
    freeze_backbone: bool = True
    learning_rate: float = 0.001
    num_epochs: int = 50
    batch_size: int = 64
    loss: str = "mse"
    quantile: float = 0.5
    request_id: str = None


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled error occurred", extra={"url": request.url.path, "error": str(exc)}
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred. Please try again later."},
    )


@app.get(
    "/health",
    summary="Health Check",
    description="Returns the health status of the service.",
)
async def health_check():
    logger.info("Health check requested")
    forecast_requests_total.labels(method="GET", endpoint="/health").inc()
    return {"status": "ok"}


@app.get(
    "/metrics",
    summary="Prometheus Metrics",
    description="Exposes Prometheus metrics for monitoring.",
)
async def metrics():
    """Expose Prometheus metrics."""
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post(
    "/forecast",
    summary="Generate Forecast",
    description="Generates forecast predictions using the TTM model.",
)
async def forecast(req: ForecastRequest):
    start_time = time.time()
    forecast_requests_total.labels(method="POST", endpoint="/forecast").inc()
    logger.info(
        "REST forecast endpoint called",
        extra={
            "context_length": req.context_length,
            "forecast_length": req.forecast_length,
            "request_id": req.request_id,
        },
    )
    try:
        result = run_forecast(req.dict())
        elapsed = time.time() - start_time
        forecast_latency_seconds.labels(method="POST", endpoint="/forecast").observe(
            elapsed
        )
        logger.info(
            "Forecast generated successfully",
            extra={"forecast": result, "request_id": req.request_id},
        )
        return {"forecast": result, "request_id": req.request_id}
    except Exception as e:
        logger.error(
            "Error during REST forecasting",
            extra={"error": str(e), "request_id": req.request_id},
        )
        raise HTTPException(status_code=500, detail="Forecasting failed.")


@app.post(
    "/finetune",
    summary="Fine-Tune Model",
    description="Fine-tunes the TTM model on user-supplied data.",
)
async def finetune(req: FineTuneRequest):
    logger.info("Finetuning endpoint called", extra={"request_id": req.request_id})
    try:
        # Run fine-tuning synchronously (for production, consider running this asynchronously)
        result = run_finetune(req.dict())
        logger.info(
            "Fine-tuning completed",
            extra={"result": result, "request_id": req.request_id},
        )
        return {"evaluation": result, "request_id": req.request_id}
    except Exception as e:
        logger.error(
            "Error during finetuning",
            extra={"error": str(e), "request_id": req.request_id},
        )
        raise HTTPException(status_code=500, detail="Fine-tuning failed.")


def run_forecast(request_data: dict):
    """
    Process input data and run TTM model inference.
    Shared by both REST and Kafka endpoints.
    """
    df = pd.DataFrame(request_data["data"])
    df[timestamp_column] = pd.to_datetime(df[timestamp_column])
    if len(df) < request_data["context_length"]:
        raise ValueError(
            f"Insufficient historical data. At least {request_data['context_length']} rows required."
        )
    tsp = TimeSeriesPreprocessor(
        **column_specifiers,
        context_length=request_data["context_length"],
        prediction_length=request_data["forecast_length"],
        scaling=True,
        encode_categorical=False,
        scaler_type="standard",
    )
    df_recent = df.tail(request_data["context_length"])
    input_tensor = torch.tensor(
        df_recent[target_columns].values, dtype=torch.float32
    ).unsqueeze(0)
    with torch.no_grad():
        forecast_output = model(input_tensor)
    return forecast_output.tolist()


def run_finetune(request_data: dict):
    """
    Fine-tune the TTM model on user-supplied data.
    Performs:
      - Data preprocessing with dynamic splitting
      - Model loading with optional backbone freezing
      - Training using Hugging Face Trainer with early stopping and LR scheduling
      - Evaluation on a test split
    """
    warnings.filterwarnings("ignore")
    SEED = 42
    set_seed(SEED)

    # Create a split config (simple 60/20/20 split)
    n = len(request_data["data"])
    train_end = int(0.6 * n)
    valid_end = int(0.8 * n)
    split_config = {
        "train": [0, train_end],
        "valid": [train_end, valid_end],
        "test": [valid_end, n],
    }

    df = pd.DataFrame(request_data["data"])
    df[timestamp_column] = pd.to_datetime(df[timestamp_column])
    tsp = TimeSeriesPreprocessor(
        **column_specifiers,
        context_length=request_data.get("context_length", 512),
        prediction_length=request_data.get("forecast_length", 96),
        scaling=True,
        encode_categorical=False,
        scaler_type="standard",
    )
    dset_train, dset_val, dset_test = get_datasets(
        tsp,
        df,
        split_config,
        fewshot_fraction=request_data.get("fewshot_percent", 5.0) / 100,
        fewshot_location="first",
    )

    # Load a fresh instance of the model for fine-tuning
    fine_tune_model = get_model(
        model_path="ibm-granite/granite-timeseries-ttm-r2",
        context_length=request_data.get("context_length", 512),
        prediction_length=request_data.get("forecast_length", 96),
        loss=request_data.get("loss", "mse"),
        quantile=request_data.get("quantile", 0.5),
    )

    if request_data.get("freeze_backbone", True):
        for param in fine_tune_model.backbone.parameters():
            param.requires_grad = False

    learning_rate = request_data.get("learning_rate", 0.001)
    num_epochs = request_data.get("num_epochs", 50)
    batch_size = request_data.get("batch_size", 64)

    temp_dir = tempfile.mkdtemp()
    training_args = TrainingArguments(
        output_dir=temp_dir,
        overwrite_output_dir=True,
        learning_rate=learning_rate,
        num_train_epochs=num_epochs,
        do_eval=True,
        evaluation_strategy="epoch",
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        dataloader_num_workers=4,
        report_to="none",
        save_strategy="epoch",
        logging_strategy="epoch",
        save_total_limit=1,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        seed=SEED,
    )

    early_stopping_callback = EarlyStoppingCallback(
        early_stopping_patience=10, early_stopping_threshold=1e-5
    )
    tracking_callback = TrackingCallback()
    optimizer = AdamW(fine_tune_model.parameters(), lr=learning_rate)
    scheduler = OneCycleLR(
        optimizer,
        learning_rate,
        epochs=num_epochs,
        steps_per_epoch=math.ceil(len(dset_train) / batch_size),
    )

    trainer = Trainer(
        model=fine_tune_model,
        args=training_args,
        train_dataset=dset_train,
        eval_dataset=dset_val,
        callbacks=[early_stopping_callback, tracking_callback],
        optimizers=(optimizer, scheduler),
    )

    # Fine-tune the model
    trainer.train()
    eval_result = trainer.evaluate(dset_test)
    return eval_result


# Kafka consumer background task (remains unchanged)
async def kafka_consumer_task():
    consumer = AIOKafkaConsumer(
        settings.kafka_input_topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="forecasting_service_group",
    )
    producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    await consumer.start()
    await producer.start()
    try:
        async for msg in consumer:
            try:
                kafka_messages_total.labels(status="received").inc()
                logger.info(
                    "Received Kafka message",
                    extra={
                        "topic": msg.topic,
                        "partition": msg.partition,
                        "offset": msg.offset,
                    },
                )
                request_data = json.loads(msg.value.decode("utf-8"))
                forecast_result = run_forecast(request_data)
                response = {
                    "forecast": forecast_result,
                    "request_id": request_data.get("request_id"),
                }
                await producer.send_and_wait(
                    settings.kafka_output_topic, json.dumps(response).encode("utf-8")
                )
                kafka_messages_total.labels(status="processed").inc()
                logger.info(
                    "Sent forecast result to Kafka output topic",
                    extra={"response": response},
                )
            except Exception as e:
                kafka_messages_total.labels(status="error").inc()
                logger.error("Error processing Kafka message", extra={"error": str(e)})
    finally:
        await consumer.stop()
        await producer.stop()


@app.on_event("startup")
async def startup_event():
    logger.info("Starting up and launching Kafka consumer task")
    asyncio.create_task(kafka_consumer_task())
