from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    log_level: str = "INFO"
    database_url: str = "sqlite:///./test.db"
    secret_key: str = "Azerty123"
    worker_count: int = 4

    # Kafka configuration
    kafka_bootstrap_servers: str = "kafka:9092"
    kafka_input_topic: str = "forecast_requests"
    kafka_output_topic: str = "forecast_responses"

    class Config:
        env_file = ".env"
        extra = (
            "allow"  # Allow extra environment variables that are not explicitly defined
        )


settings = Settings()
