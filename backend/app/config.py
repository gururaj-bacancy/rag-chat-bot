from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://ragchat:ragchat@localhost:5432/ragchat"
    test_database_url: str = "postgresql+psycopg://ragchat:ragchat@localhost:5432/ragchat_test"
    anthropic_api_key: str = ""
    voyage_api_key: str = ""


settings = Settings()
