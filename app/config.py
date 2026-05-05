from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Nexora Backend"
    database_url: str = "postgresql+psycopg://nexora:nexora@postgres:5432/nexora"
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: Optional[str] = None
    mqtt_password: Optional[str] = None
    mqtt_topic_pattern: str = "energy/+/+/consumption"
    mqtt_topics: Optional[str] = None
    enable_mqtt: bool = True
    emission_factor_kg_co2e_per_kwh: float = 0.85

    nexora_host: str = "0.0.0.0"
    nexora_port: int = 8001
    nexora_history_window_days: int = 7
    nexora_min_history_samples: int = 24
    nexora_max_recommendations: int = 3
    nexora_high_trigger_multiplier: float = 1.22
    nexora_critical_trigger_multiplier: float = 1.45
    nexora_baseline_short_window: int = 6
    nexora_baseline_long_window: int = 24
    nexora_baseline_short_weight: float = 0.6
    nexora_baseline_long_weight: float = 0.4

    ai_enabled: bool = True
    ai_base_url: str = "http://ai-nexora.kumalabs.tech"
    ai_timeout_seconds: float = 8.0
    ai_retry_count: int = 2
    ai_scheduler_interval_seconds: int = 3600
    jwt_secret_key: str = "change-this-secret-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_minutes: int = 10080
    auth_enabled: bool = True
    redis_url: Optional[str] = None
    bootstrap_admin_email: str = "admin@nexora.local"
    bootstrap_admin_password: str = "admin12345"


settings = Settings()
