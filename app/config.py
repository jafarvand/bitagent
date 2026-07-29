from decimal import Decimal
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
