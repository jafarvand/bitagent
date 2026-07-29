from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bitagent_mode: Literal["mock", "live"] = "mock"
    exchange_api_base_url: str = "https://devapi.zekabot.com"
    exchange_bot_token: str = ""
    exchange_timeout_seconds: float = 10.0
    bitagent_default_market: str = "BTC_USDT"


settings = Settings()
