from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "车间智能助手"
    secret_key: str = "dev-secret-change-me"
    access_token_expire_minutes: int = 60 * 24 * 7
    database_url: str = "postgresql+psycopg2://workshop:workshop@localhost:5432/workshop"
    # SQLite for local/tests when DATABASE_URL not set to postgres
    use_sqlite: bool = False
    sqlite_path: str = "./data/workshop.db"

    wechat_token: str = "workshop_dev_token"
    wechat_app_id: str = ""
    wechat_app_secret: str = ""
    wechat_encoding_aes_key: str = ""

    default_tenant_name: str = "演示鞋厂"
    admin_username: str = "admin"
    admin_password: str = "admin123"

    web_dist_dir: str = "web/dist"


@lru_cache
def get_settings() -> Settings:
    return Settings()
