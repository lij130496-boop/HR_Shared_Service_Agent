
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# 优先读取当前项目 .env
load_dotenv(BASE_DIR / ".env", override=False)

# 兼容用户已有的 BailianTest/.env 等父级配置
# 例如:
# D:\python\BailianTest\.env
# D:\python\BailianTest\HR_Shared_Service_Agent_V1_Bailian\app.py
for parent in list(BASE_DIR.parents)[:4]:
    env_path = parent / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)


@dataclass(frozen=True)
class Settings:
    base_dir: Path = BASE_DIR
    knowledge_dir: Path = BASE_DIR / "knowledge_base"
    data_dir: Path = BASE_DIR / "data"

    vector_store_path: Path = BASE_DIR / "data" / "vector_store.npz"
    metadata_path: Path = BASE_DIR / "data" / "vector_metadata.json"
    hitl_log_path: Path = BASE_DIR / "data" / "hitl_log.jsonl"
    onboarding_log_path: Path = BASE_DIR / "data" / "onboarding_records.jsonl"
    company_locations_path: Path = BASE_DIR / "data" / "company_locations.json"
    assets_dir: Path = BASE_DIR / "assets"

    # 阿里云百炼
    api_key: str = os.getenv("DASHSCOPE_API_KEY", "").strip()
    base_url: str = os.getenv(
        "DASHSCOPE_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ).strip()

    chat_model: str = os.getenv(
        "BAILIAN_CHAT_MODEL",
        "qwen-plus",
    ).strip()

    embedding_model: str = os.getenv(
        "BAILIAN_EMBEDDING_MODEL",
        "text-embedding-v4",
    ).strip()

    top_k: int = int(os.getenv("RAG_TOP_K", "5"))
    min_score: float = float(os.getenv("RAG_MIN_SCORE", "0.18"))

    # HR 管理端密码。正式部署时请通过 .env 修改。
    hr_password: str = os.getenv("HR_ADMIN_PASSWORD", "123456").strip()


settings = Settings()
