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

    # 排产 Agent（DeepSeek OpenAI 兼容）；缺 key 时规则引擎仍可用
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    schedule_agent_enabled: bool = True
    schedule_agent_data_dir: str = "./data/schedule_agent"
    # Evidence results are short-lived, session-scoped working data rather
    # than a second reporting database.
    analysis_result_ttl_seconds: int = 60 * 60
    analysis_result_max_per_session: int = 200

    # LangSmith（可选）：未配置时军师不受影响；配置后记录每轮 Agent trace。
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_project: str = "workshop-agent"

    # （已退役）旧 Fast Path 旁路开关：Tool-first Direct Path 方案下，
    # query_metric_direct 由主 Agent 路由、工具内确定性执行，不再需要旁路
    # 开关。保留字段兼容旧 .env，不再被链路读取。
    agent_fast_path_enabled: bool = False

    # 对外 MCP（Streamable HTTP）；供外部 AI Agent 只读问数
    mcp_enabled: bool = True
    # 逗号分隔 Origin；* = 任意（含无 Origin 的 API 客户端）；空 = 仅允许无 Origin
    mcp_allowed_origins: str = "*"
    mcp_protocol_version: str = "2025-03-26"


@lru_cache
def get_settings() -> Settings:
    return Settings()
