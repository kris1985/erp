from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "铁玉兰管家"
    secret_key: str = "dev-secret-change-me"
    access_token_expire_minutes: int = 60 * 24 * 7
    database_url: str = (
        "mysql+pymysql://root:123456@localhost:3306/workshop?charset=utf8mb4"
    )
    # 无本地 MySQL 时可 USE_SQLITE=true；单测自建内存库
    use_sqlite: bool = False
    sqlite_path: str = "./data/workshop.db"

    wechat_token: str = "workshop_dev_token"
    wechat_app_id: str = ""
    wechat_app_secret: str = ""
    wechat_encoding_aes_key: str = ""

    default_tenant_name: str = "演示鞋厂"
    admin_username: str = "admin"
    admin_password: str = "admin123"
    # 员工默认密码；首次登录后须修改
    worker_default_password: str = "123456"

    web_dist_dir: str = "web/dist"
    uploads_dir: str = "./data/uploads"


@lru_cache
def get_settings() -> Settings:
    return Settings()
