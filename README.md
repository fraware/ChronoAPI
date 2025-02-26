# TTM Forecasting API

This repository provides a RESTful API for real-time time-series forecasting using IBM Research’s TTM model. The service is built using FastAPI and offers endpoints for forecasting, fine-tuning, and monitoring. It also includes Kafka-based data ingestion and Prometheus metrics for integration with dashboards such as Grafana and Kibana. 
 
## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Getting Started](#getting-started)
- [Usage Examples](#usage-examples)
  - [Health Check](#health-check)
  - [Generating Forecasts](#generating-forecasts)
  - [Fine-Tuning the Model](#fine-tuning-the-model)
- [Integrations](#integrations)
  - [Kafka Connector](#kafka-connector)
  - [Monitoring Dashboards](#monitoring-dashboards)
- [Deployment](#deployment)
- [Contributing](#contributing)
- [License](#license)

## Overview

The TTM Forecasting Microservice provides real-time forecasting capabilities by wrapping IBM Research’s TTM model. Organizations can integrate the API into IoT dashboards, financial analytics platforms, or data pipelines with minimal computational overhead. The service supports:

- REST endpoints for inference and fine-tuning.
- Kafka integration for data ingestion.
- Prometheus metrics for monitoring and integration with Grafana/Kibana.
- Comprehensive API documentation via Swagger and ReDoc.

## Features

- **Forecasting API:** Submit historical time-series data to generate forecasts.
- **Fine-Tuning API:** Fine-tune the TTM model on custom datasets.
- **Kafka Connector:** Seamlessly ingest forecast requests via Kafka topics.
- **Monitoring:** Built-in Prometheus metrics for real-time performance monitoring.
- **Interactive Documentation:** Explore and test the API via Swagger UI and ReDoc.

## Getting Started

### Prerequisites

- Python 3.9 or later
- Docker and Docker Compose (for containerized deployment)
- A running Kafka cluster (you can use Docker Compose as provided)

### Installation

1. **Clone the repository:**

   ```bash
   git clone https://github.com/yourusername/ttm-forecasting-microservice.git
   cd ttm-forecasting-microservice
   ```

2. **Install dependencies:**

   ```bash
   pip install -r requirements.txt

   ```

3. **Run the service locally:**

   ```bash
   uvicorn app.main:app --reload
   ```

The API will be available at http://localhost:8000.

4. **Access API Documentation:**

Swagger UI: http://localhost:8000/docs
ReDoc: http://localhost:8000/redoc

## Usage Examples

Below are some sample code snippets to help you get started.

### Health Check

Using Curl:

```bash
curl http://localhost:8000/health
```

Response:

```json
{
  "status": "ok"
}
```

### Generating Forecasts

Sample Request (forecast_sample.json):

```json
{
  "data": [
    {
      "date": "2023-01-01 00:00",
      "HUFL": 1.2,
      "HULL": 0.5,
      "MUFL": 1.0,
      "MULL": 0.8,
      "LUFL": 1.1,
      "LULL": 0.7,
      "OT": 1.3
    },
    {
      "date": "2023-01-01 00:10",
      "HUFL": 1.3,
      "HULL": 0.6,
      "MUFL": 1.1,
      "MULL": 0.9,
      "LUFL": 1.2,
      "LULL": 0.8,
      "OT": 1.4
    }
    // Add enough rows (e.g., 512 rows) for context_length.
  ],
  "context_length": 512,
  "forecast_length": 96,
  "request_id": "test123"
}
```

Submit Request using Curl:

```bash
curl -X POST http://localhost:8000/forecast \
-H "Content-Type: application/json" \
-d @forecast_sample.json
```

Using Python (with `requests`):

```python
import requests
import json

url = "http://localhost:8000/forecast"
payload = {
"data": [
{"date": "2023-01-01 00:00", "HUFL": 1.2, "HULL": 0.5, "MUFL": 1.0, "MULL": 0.8, "LUFL": 1.1, "LULL": 0.7, "OT": 1.3},
# ... add more records to meet context_length requirement
],
"context_length": 512,
"forecast_length": 96,
"request_id": "test123"
}

response = requests.post(url, json=payload)
print(response.json())
```

### Fine-Tuning the Model

Sample Fine-Tuning Request:

Create a JSON file `finetune_sample.json`:

```json
{
  "data": [
    {
      "date": "2023-01-01 00:00",
      "HUFL": 1.2,
      "HULL": 0.5,
      "MUFL": 1.0,
      "MULL": 0.8,
      "LUFL": 1.1,
      "LULL": 0.7,
      "OT": 1.3
    },
    {
      "date": "2023-01-01 00:10",
      "HUFL": 1.3,
      "HULL": 0.6,
      "MUFL": 1.1,
      "MULL": 0.9,
      "LUFL": 1.2,
      "LULL": 0.8,
      "OT": 1.4
    }
    // Add enough data to perform fine-tuning
  ],
  "context_length": 512,
  "forecast_length": 96,
  "fewshot_percent": 5.0,
  "freeze_backbone": true,
  "learning_rate": 0.001,
  "num_epochs": 50,
  "batch_size": 64,
  "loss": "mse",
  "quantile": 0.5,
  "request_id": "finetune_test_001"
}
```

Submit Fine-Tuning Request using Curl:

```bash
curl -X POST http://localhost:8000/finetune \
-H "Content-Type: application/json" \
-d @finetune_sample.json
```

## Integrations

### Kafka Connector

The service includes a Kafka consumer that listens to forecast requests on the configured input topic. To test:

1. **Start Kafka via Docker Compose:**

   ```bash
   docker-compose up -d

   ```

2. **Produce a test message to the `forecast_requests` topic.**
   You can use Kafka CLI tools or write a small producer script in Python. The message format should match the JSON expected by the `/forecast` endpoint.

3. **Monitor the `forecast_responses` topic for forecast results.**

### Monitoring Dashboards

- **Prometheus:**
  The `/metrics` endpoint exposes Prometheus metrics. Configure Prometheus to scrape this endpoint.

- **Grafana:**
  Connect Grafana to Prometheus and create dashboards to visualize:

  - Total forecast requests
  - Processing latency
  - Kafka message statistics

- **Kibana:**
  Configure log shipping (using Filebeat or Fluentd) to send structured logs to Elasticsearch, then build Kibana dashboards to monitor API activity.

## Deployment

### Docker Deployment

1. **Build Docker Image:**

   ```bash
   docker build -t forecasting-service .

   ```

2. **Run with Docker Compose:**

Use the provided `docker-compose.yml` to start the Kafka stack and the forecasting service.

```bash
docker-compose up -d
```

### Production Considerations

- **Auto-scaling:** Configure Kubernetes or Docker Swarm for scaling.
- **Security:** Implement authentication (e.g., API keys, OAuth2) and rate-limiting.
- **Asynchronous Fine-Tuning:** Offload fine-tuning jobs to a task queue (e.g., Celery) for long-running tasks.

## Contributing

Contributions are welcome! Please fork this repository and open a pull request with your changes.

## License

This project is licensed under the MIT License.
