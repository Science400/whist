from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    tmdb_api_key: str
    database_url: str = "sqlite:///./whist.db"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
