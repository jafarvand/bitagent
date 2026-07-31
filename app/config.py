from decimal import Decimal
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        extra="ignore",
    )

    bitagent_mode: Literal["mock", "live"] = "mock"
    exchange_api_base_url: str = "https://devapi.zekabot.com"
    exchange_bot_key_id: str = ""
    exchange_bot_secret: str = ""
    exchange_bot_service_keys: str = ""
    exchange_timeout_seconds: float = 10.0
    bitagent_default_market: str = "BTC_USDT"
    withdrawal_pending_warning_threshold: int = 25
    withdrawal_pending_critical_threshold: int = 100
    market_range_warning_percent: Decimal = Decimal("5.00")
    market_range_critical_percent: Decimal = Decimal("10.00")
    evidence_db_path: str = ".data/bitagent.db"
    evidence_freshness_warning_seconds: int = 120
    bitagent_access_control_mode: Literal["observe", "enforced"] = "observe"
    upstream_security_report_path: str = ".data/upstream-security-report.json"
    release_evidence_directory: str = "integration-input/release-evidence"
    bitagent_chat_enabled: bool = False
    llm_provider: Literal["ollama"] = "ollama"
    ollama_base_url: str = "https://ollama.zekabot.com"
    ollama_model: str = "qwen"
    ollama_username: str = ""
    ollama_password: SecretStr = SecretStr("")
    ollama_timeout_seconds: float = 60.0

    def ollama_credentials(self) -> tuple[str, str]:
        return self.ollama_username, self.ollama_password.get_secret_value()

    def exchange_credentials(self) -> tuple[str, str]:
        """Return explicit client credentials or the first server-style pair."""
        if self.exchange_bot_key_id and self.exchange_bot_secret:
            return self.exchange_bot_key_id, self.exchange_bot_secret
        first_pair = self.exchange_bot_service_keys.split(",", 1)[0].strip()
        if ":" not in first_pair:
            return "", ""
        key_id, secret = first_pair.split(":", 1)
        return key_id.strip(), secret.strip()


settings = Settings()
