from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "quant-bot-sentiment/1.0"

    twitter_bearer_token: str = ""

    coingecko_api_key: str = ""
    cryptopanic_api_key: str = ""
    newsapi_key: str = ""
    
    # New API keys
    coinmarketcap_api_key: str = ""
    marketaux_api_key: str = ""
    finnhub_api_key: str = ""
    fmp_api_key: str = ""

    redis_url: str = "redis://localhost:6379"
    use_redis: bool = False

    sentiment_update_interval: int = 60
    sentiment_history_hours: int = 24

    model_name: str = "burakutf/finetuned-finbert-crypto"

    class Config:
        env_file = ".env"
        env_prefix = "SENTIMENT_"


@lru_cache
def get_settings() -> Settings:
    return Settings()
