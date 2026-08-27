import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    db_host: str = os.getenv("DB_HOST", "localhost")
    db_port: int = int(os.getenv("DB_PORT", "5432"))
    db_name: str = os.getenv("DB_NAME", "stockpeek")
    db_user: str = os.getenv("DB_USER", "postgres")
    db_password: str = os.getenv("DB_PASSWORD", "postgres")

    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    llm_model_dev: str = os.getenv("LLM_MODEL_DEV", "claude-haiku-4-5-20251001")
    llm_model_prod: str = os.getenv("LLM_MODEL_PROD", "claude-sonnet-4-5")

    @property
    def db_dsn(self) -> str:
        return (
            f"host={self.db_host} port={self.db_port} dbname={self.db_name} "
            f"user={self.db_user} password={self.db_password}"
        )


settings = Settings()
