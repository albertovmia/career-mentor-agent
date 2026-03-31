from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # Telegram
    telegram_bot_token: str = Field(default="", env="TELEGRAM_BOT_TOKEN")
    telegram_user_id: str = Field(default="", env="TELEGRAM_USER_ID")

    # Groq
    groq_api_key: str = Field(default="", env="GROQ_API_KEY")
    groq_model: str = "llama-3.3-70b-versatile"
    groq_model_fallback: str = "llama-3.1-8b-instant"
    max_agent_iterations: int = Field(default=5, env="MAX_AGENT_ITERATIONS")

    # OpenRouter fallback
    openrouter_api_key: str = Field(default="", env="OPENROUTER_API_KEY")
    openrouter_model: str = Field(
        default="google/gemini-2.0-flash-001",
        env="OPENROUTER_MODEL"
    )

    # Google Workspace
    gws_credentials_file: str = Field(
        default="", env="GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE"
    )

    # RapidAPI JSearch
    rapidapi_key: str = Field(default="", env="RAPIDAPI_KEY")

    # SQLite
    db_path: str = Field(default="./data/memory.db", env="DB_PATH")

    # Logging
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
