from __future__ import annotations

import sys
import json
from pathlib import Path
from datetime import datetime
import base64
import mimetypes
import hashlib
import hmac
import secrets
import threading
import re
from modules.chat_history import (
    save_conversation,
    load_conversation,
    list_conversations
)
from io import BytesIO

from openai import OpenAI
from pypdf import PdfReader
from docx import Document
BASE_DIR = Path(__file__).resolve().parent

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

FEEDBACK_LOG = BASE_DIR / "data" / "feedback.jsonl"

FEEDBACK_LOG.parent.mkdir(
    parents=True,
    exist_ok=True
)

FEEDBACK_LOG.touch(
    exist_ok=True
)

import streamlit as st


# ============================================================
# 小冲AI - 用户注册 / 登录 / 多用户数据隔离
# ============================================================

USER_DB_FILE = BASE_DIR / "data" / "users.json"
USER_DB_FILE.parent.mkdir(parents=True, exist_ok=True)

_USER_DB_LOCK = threading.Lock()
PASSWORD_ITERATIONS = 200_000


def _read_users() -> dict:
    if not USER_DB_FILE.exists():
        return {}
    try:
        data = json.loads(USER_DB_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_users(users: dict) -> None:
    USER_DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = USER_DB_FILE.with_suffix(".tmp")
    temp_file.write_text(
        json.dumps(users, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    temp_file.replace(USER_DB_FILE)


def _normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def _valid_username(username: str) -> bool:
    username = (username or "").strip()
    return bool(
        re.fullmatch(
            r"[A-Za-z0-9_\-\u4e00-\u9fff]{2,30}",
            username
        )
    )


def _hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS
    )
    return salt.hex(), password_hash.hex()


def register_account(username: str, password: str, confirm_password: str) -> tuple[bool, str]:
    username_raw = (username or "").strip()
    username_key = _normalize_username(username_raw)

    if not _valid_username(username_raw):
        return False, "账号只能包含中文、字母、数字、下划线或横杠，长度为2~30个字符。"
    if len(password or "") < 6:
        return False, "密码至少需要6位。"
    if password != confirm_password:
        return False, "两次输入的密码不一致。"

    with _USER_DB_LOCK:
        users = _read_users()
        if username_key in users:
            return False, "该账号已经注册，请直接登录。"

        salt_hex, password_hash = _hash_password(password)
        users[username_key] = {
            "username": username_raw,
            "password_salt": salt_hex,
            "password_hash": password_hash,
            "role": "普通员工",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        _write_users(users)

    return True, "注册成功，请使用新账号登录。"


def authenticate_account(username: str, password: str) -> tuple[bool, dict | None]:
    username_key = _normalize_username(username)
    users = _read_users()
    user = users.get(username_key)
    if not user:
        return False, None

    # HR后台禁用的账号不能登录
    if user.get("disabled", False):
        return False, None

    salt_hex = user.get("password_salt", "")
    saved_hash = user.get("password_hash", "")
    if not salt_hex or not saved_hash:
        return False, None

    try:
        _, current_hash = _hash_password(password, salt_hex)
    except Exception:
        return False, None

    if not hmac.compare_digest(current_hash, saved_hash):
        return False, None

    return True, user


def _current_account() -> str:
    return st.session_state.get("auth_username", "") or ""


def _account_prefix(username: str | None = None) -> str:
    username = username or _current_account()
    normalized = _normalize_username(username)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]
    return f"u_{digest}__"


# 保存聊天历史模块中的原始函数，然后在 app.py 内做账号隔离
_raw_save_conversation = save_conversation
_raw_load_conversation = load_conversation
_raw_list_conversations = list_conversations


def save_conversation(messages: list[dict], chat_id: str | None = None):
    username = _current_account()
    if not username:
        return chat_id

    has_user_message = any(item.get("role") == "user" for item in (messages or []))
    if not has_user_message:
        return chat_id

    prefix = _account_prefix(username)
    if chat_id and not str(chat_id).startswith(prefix):
        chat_id = None

    if not chat_id:
        chat_id = prefix + datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    return _raw_save_conversation(messages, chat_id)


def load_conversation(chat_id: str):
    if not chat_id:
        return None
    if not str(chat_id).startswith(_account_prefix()):
        return None
    return _raw_load_conversation(chat_id)


def list_conversations(search_text: str = "", limit: int = 30):
    prefix = _account_prefix()
    records = _raw_list_conversations(search_text="", limit=5000)
    records = [
        item for item in records
        if str(item.get("id", "")).startswith(prefix)
    ]

    search_text = (search_text or "").strip().lower()
    if search_text:
        records = [
            item for item in records
            if search_text in str(item.get("title", "")).lower()
        ]

    return records[:limit]


def _reset_user_workspace():
    st.session_state["current_chat_id"] = None
    st.session_state["messages_employee"] = [
        {
            "role": "assistant",
            "content": (
                "你好，我是小冲AI助手 👋\n\n"
                "你可以问我公司制度问题，也可以上传图片、PDF、Word等资料让我分析。"
            )
        }
    ]
    st.session_state["messages_hr"] = [
        {
            "role": "assistant",
            "content": "你好，这里是HR管理端，可以查看制度信息、知识库状态和员工反馈。"
        }
    ]
    st.session_state["office_intent"] = None
    st.session_state["agent_state"] = {
        "current_intent": None,
        "slots": {},
        "waiting_for": []
    }
    st.session_state["pending_employee_question"] = None
    st.session_state["pending_hr_question"] = None
    st.session_state["role"] = "普通员工"
    st.session_state["hr_authenticated"] = False


def render_login_page() -> bool:
    if st.session_state.get("auth_logged_in", False):
        return True

    st.markdown(
        """
        <div style="max-width:560px;margin:50px auto 20px auto;text-align:center;">
            <div style="font-size:44px;font-weight:800;color:#111827;">🤖 小冲AI</div>
            <div style="margin-top:8px;font-size:16px;color:#6b7280;">企业智能办公助手</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    left, center, right = st.columns([1, 1.35, 1])
    with center:
        login_tab, register_tab = st.tabs(["登录", "注册账号"])

        with login_tab:
            login_username = st.text_input(
                "账号",
                key="auth_login_username",
                placeholder="请输入账号"
            )
            login_password = st.text_input(
                "密码",
                type="password",
                key="auth_login_password",
                placeholder="请输入密码"
            )

            if st.button(
                "登录小冲AI",
                type="primary",
                width="stretch",
                key="auth_login_button"
            ):
                ok, user = authenticate_account(login_username, login_password)
                if ok and user:
                    st.session_state["auth_logged_in"] = True
                    st.session_state["auth_username"] = _normalize_username(login_username)
                    st.session_state["auth_display_name"] = user.get("username") or login_username.strip()
                    _reset_user_workspace()
                    st.rerun()
                else:
                    st.error("账号或密码错误。")

        with register_tab:
            register_username = st.text_input(
                "创建账号",
                key="auth_register_username",
                placeholder="例如：zhangsan 或 张三"
            )
            register_password = st.text_input(
                "设置密码",
                type="password",
                key="auth_register_password",
                placeholder="至少6位"
            )
            register_confirm = st.text_input(
                "确认密码",
                type="password",
                key="auth_register_confirm",
                placeholder="再次输入密码"
            )

            if st.button(
                "立即注册",
                type="primary",
                width="stretch",
                key="auth_register_button"
            ):
                ok, message = register_account(
                    register_username,
                    register_password,
                    register_confirm
                )
                if ok:
                    st.success(message)
                    st.info("注册完成后，请切换到“登录”页登录。")
                else:
                    st.warning(message)

        st.caption("普通用户注册后默认进入员工端；HR管理端仍需要管理员密码验证。")

    return False


def logout_current_account():
    try:
        save_conversation(
            st.session_state.get("messages_employee", []),
            st.session_state.get("current_chat_id")
        )
    except Exception as e:
        print("退出前保存会话失败：", e)

    st.session_state["auth_logged_in"] = False
    st.session_state["auth_username"] = ""
    st.session_state["auth_display_name"] = ""
    _reset_user_workspace()


from config import settings
from rag.embeddings import EmbeddingClient
from rag.vector_store import LocalVectorStore
from rag.indexer import build_index
from rag.retriever import Retriever
from agents.policy_agent import PolicyAgent
from modules.intent_router import (
    detect_office_intent,
    DISPLAY_NAMES
)
from agents.smart_router import route_request
from modules.document_agent import (
    render_document_task
)
from onboarding.exporter import build_onboarding_docx
from onboarding.storage import save_onboarding_record, load_onboarding_records
from onboarding.company import (
    find_company_map,
    save_company_map,
    load_company_locations,
    save_company_locations,
    parse_locations_text,
    locations_to_text,
)


st.set_page_config(
    page_title="小冲AI欢迎您来到公司",
    layout="wide",
    initial_sidebar_state="expanded",
)


APP_CSS = r"""
<style>

/* =========================
   整体页面
========================= */

.stApp {
    background: #ffffff;
    color: #202123;
}

.block-container {
    max-width: 980px;
    padding-top: 24px;
    padding-bottom: 120px;
}


/* =========================
   顶部栏
========================= */

[data-testid="stHeader"] {
    background: rgba(255,255,255,0.95);
}


/* =========================
   左侧栏
========================= */

[data-testid="stSidebar"] {
    background: #f7f7f8;
    border-right: 1px solid #e5e7eb;
}

[data-testid="stSidebar"] * {
    color: #202123 !important;
}

.sidebar-brand {
    padding: 12px 4px 20px 4px;
}

.sidebar-brand-title {
    font-size: 20px;
    font-weight: 700;
    color: #111827 !important;
}

.sidebar-brand-sub {
    font-size: 12px;
    color: #6b7280 !important;
    margin-top: 4px;
}


/* =========================
   聊天消息
========================= */

[data-testid="stChatMessage"] {
    background: transparent;
    border: none;
    padding-top: 14px;
    padding-bottom: 14px;
}

[data-testid="stChatMessageContent"] {
    max-width: 850px;
}


/* =========================
   输入框
========================= */

[data-testid="stChatInput"] {
    border-radius: 24px;
    border: 1px solid #d1d5db;
    background: #ffffff;
    box-shadow: 0 4px 18px rgba(0,0,0,0.05);
}


/* =========================
   普通按钮
========================= */

.stButton > button {
    border-radius: 10px;
    border: 1px solid #d1d5db;
    background: #ffffff;
    color: #202123;
    font-weight: 500;
}

.stButton > button:hover {
    border-color: #9ca3af;
    background: #f9fafb;
}


/* =========================
   Primary按钮
========================= */

.stButton > button[kind="primary"] {
    background: #111827;
    color: white;
    border: none;
}

.stButton > button[kind="primary"]:hover {
    background: #000000;
}


/* =========================
   输入框、选择框
========================= */

input,
textarea,
[data-baseweb="select"] > div {
    border-radius: 10px !important;
}


/* =========================
   Expander
========================= */

[data-testid="stExpander"] {
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    background: #ffffff;
}


/* =========================
   隐藏过重装饰
========================= */

.hero,
.side-card,
.sidebar-status {
    box-shadow: none !important;
}

hr {
    border-color: #eeeeee !important;
}
/* =========================================================
   右侧主内容整体居中
========================================================= */

[data-testid="stAppViewContainer"] .main .block-container {
    max-width: 1050px !important;

    margin-left: auto !important;
    margin-right: auto !important;

    padding-left: 30px !important;
    padding-right: 30px !important;

    padding-top: 28px !important;
}


/* =========================================================
   聊天消息宽度
========================================================= */

[data-testid="stChatMessage"] {
    max-width: 1000px !important;

    margin-left: auto !important;
    margin-right: auto !important;
}


/* =========================================================
   聊天输入框居中
========================================================= */

[data-testid="stChatInput"] {
    max-width: 1000px !important;

    margin-left: auto !important;
    margin-right: auto !important;
}


/* =========================================================
   Tabs 居中
========================================================= */

.stTabs [data-baseweb="tab-list"] {
    justify-content: center !important;
}

/* =========================================================
   修复侧边栏 Primary 按钮文字颜色
   ========================================================= */
section[data-testid="stSidebar"] .stButton > button[kind="primary"],
section[data-testid="stSidebar"] .stButton > button[kind="primary"] *,
section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"],
section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] * {
    color: #ffffff !important;
}

/* 登录/注册区域输入框更清晰 */
section[data-testid="stSidebar"] input {
    color: #111827 !important;
    background: #ffffff !important;
}

/* 登录/注册 Expander */
section[data-testid="stSidebar"] [data-testid="stExpander"] {
    background: #ffffff !important;
    border: 1px solid #d9dde5 !important;
    border-radius: 12px !important;
}

/* 错误和提示区域文字保持可读 */
section[data-testid="stSidebar"] [data-testid="stAlert"] * {
    color: inherit !important;
}

</style>
"""

st.markdown(
    APP_CSS,
    unsafe_allow_html=True
)


@st.cache_resource(show_spinner=False)
def create_services():
    embedder = EmbeddingClient(settings.api_key, settings.base_url, settings.embedding_model)
    store = LocalVectorStore(settings.vector_store_path, settings.metadata_path)
    retriever = Retriever(embedder, store, settings.top_k)
    agent = PolicyAgent(
        api_key=settings.api_key,
        base_url=settings.base_url,
        model=settings.chat_model,
        retriever=retriever,
        min_score=settings.min_score,
        hitl_log_path=settings.hitl_log_path,
    )
    return embedder, store, agent


def load_hitl_records() -> list[dict]:
    path = settings.hitl_log_path
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows[::-1]


from datetime import datetime


# ==============================
# V4 AI智能运营优化中心
# 员工问题反馈闭环
# ==============================

AI_QUESTION_LOG = Path("data/ai_questions.jsonl")
# ==============================
# 用户反馈记录
# ==============================
# ==============================
# 员工回答评价日志
# ==============================

BASE_DIR = Path(__file__).resolve().parent

FEEDBACK_LOG = BASE_DIR / "data" / "feedback.jsonl"


def save_feedback(question, answer, status):

    FEEDBACK_LOG.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    record = {
        "time": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "question": question,
        "answer": answer,
        "status": status,
        "username": st.session_state.get("auth_username", "")
    }

    with open(
        FEEDBACK_LOG,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(
            json.dumps(
                record,
                ensure_ascii=False
            ) + "\n"
        )

    print("===== 员工反馈保存成功 =====")
    print(record)
    print("文件位置：", FEEDBACK_LOG.resolve())


    

def load_feedback():

    if not FEEDBACK_LOG.exists():
        return []

    rows = []

    for line in FEEDBACK_LOG.read_text(
        encoding="utf-8"
    ).splitlines():

        if not line.strip():
            continue

        try:
            rows.append(
                json.loads(line)
            )
        except Exception:
            pass

    return rows[::-1]


FEEDBACK_LOG = Path("data/feedback.jsonl")



def save_ai_question_record(question, answer, sources=None):
    """记录员工咨询，用于HR分析和知识库优化"""
    AI_QUESTION_LOG.parent.mkdir(exist_ok=True)

    failed_keywords = [
        "未找到",
        "没有找到",
        "无法回答",
        "请向HR确认",
        "知识库暂未"
    ]

    status = "success"
    if any(k in answer for k in failed_keywords):
        status = "failed"

    record = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "question": question,
        "answer": answer,
        "status": status,
        "source_count": len(sources or []),
        "username": st.session_state.get("auth_username", "")
    }

    with open(AI_QUESTION_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_ai_question_records():
    if not AI_QUESTION_LOG.exists():
        return []

    rows = []
    for line in AI_QUESTION_LOG.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows[::-1]


def load_feedback():

    if not FEEDBACK_LOG.exists():
        return []

    rows = []

    for line in FEEDBACK_LOG.read_text(
        encoding="utf-8"
    ).splitlines():

        if not line.strip():
            continue

        try:
            rows.append(
                json.loads(line)
            )
        except Exception:
            pass

    return rows[::-1]



def render_ai_operation_center():

    """HR智能运营优化中心"""

    st.markdown("## 📊 AI智能运营优化中心")

    st.caption(
        "分析员工咨询情况、员工真实评价和未解决问题，帮助HR持续完善知识库。"
    )


    # ==============================
    # 读取两类数据
    # ==============================

    records = load_ai_question_records()

    feedbacks = load_feedback()


    # ==============================
    # 1. 员工真实评价统计
    # ==============================

    good = len([
        x for x in feedbacks
        if x.get("status") == "success"
    ])

    bad = len([
        x for x in feedbacks
        if x.get("status") == "failed"
    ])

    feedback_total = good + bad

    satisfaction = (
        good / feedback_total * 100
        if feedback_total > 0
        else 0
    )


    st.divider()

    st.subheader("👍 员工回答评价")

    f1, f2, f3 = st.columns(3)

    with f1:
        st.metric(
            "回答正确",
            good
        )

    with f2:
        st.metric(
            "回答不正确",
            bad
        )

    with f3:
        st.metric(
            "用户认可率",
            f"{satisfaction:.1f}%"
        )


    # ==============================
    # 2. 员工反馈的不正确回答
    # ==============================

    st.divider()

    st.subheader("👎 员工反馈待优化问题")

    bad_feedbacks = [
        x for x in feedbacks
        if x.get("status") == "failed"
    ]

    if not bad_feedbacks:

        st.success(
            "当前没有员工反馈的错误回答。"
        )

    else:

        for item in bad_feedbacks[:50]:

            with st.container(border=True):

                st.write(
                    "**员工问题：**",
                    item.get(
                        "question",
                        "-"
                    )
                )

                st.write(
                    "**AI回答：**",
                    item.get(
                        "answer",
                        "-"
                    )
                )

                st.caption(
                    f"反馈时间：{item.get('time', '-')}"
                )


    # ==============================
    # 3. AI自动判断统计
    # ==============================

    total = len(records)

    success = len([
        x for x in records
        if x.get("status") == "success"
    ])

    failed = total - success


    st.divider()

    st.subheader("🤖 AI回答情况")

    c1, c2, c3 = st.columns(3)

    with c1:
        st.metric(
            "员工咨询总量",
            total
        )

    with c2:
        st.metric(
            "AI有效回答",
            success
        )

    with c3:

        rate = (
            success / total * 100
            if total > 0
            else 0
        )

        st.metric(
            "回答有效率",
            f"{rate:.1f}%"
        )


    # ==============================
    # 4. AI自动识别的未解决问题
    # ==============================

    st.divider()

    st.subheader("❌ AI自动识别未解决问题")

    failed_rows = [
        x for x in records
        if x.get("status") == "failed"
    ]

    if not failed_rows:

        st.success(
            "当前没有发现明显无法回答的问题。"
        )

    else:

        for item in failed_rows[:50]:

            with st.container(border=True):

                st.write(
                    "**员工问题：**",
                    item.get(
                        "question",
                        "-"
                    )
                )

                st.caption(
                    item.get(
                        "time",
                        ""
                    )
                )

                st.write(
                    "**AI回答：**",
                    item.get(
                        "answer",
                        "-"
                    )
                )


    # ==============================
    # 5. 高频问题
    # ==============================

    st.divider()

    st.subheader("📈 高频问题")

    counter = {}

    for item in records:

        q = item.get(
            "question",
            ""
        ).strip()

        if not q:
            continue

        counter[q] = (
            counter.get(q, 0) + 1
        )


    if not counter:

        st.info(
            "暂无咨询数据。"
        )

    else:

        for q, n in sorted(
            counter.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]:

            st.write(
                f"🔥 {q} （{n}次）"
            )

def get_kb_files() -> list[str]:
    supported = {".docx", ".pdf", ".txt", ".md"}
    return sorted(
        p.name for p in settings.knowledge_dir.iterdir()
        if p.is_file() and p.suffix.lower() in supported
    )


def get_chunk_count(store) -> int:
    if not store.exists:
        return 0
    try:
        store.load()
        return len(store.metadata)
    except Exception:
        return 0


def init_session():
    st.session_state.setdefault("auth_logged_in", False)
    st.session_state.setdefault("auth_username", "")
    st.session_state.setdefault("auth_display_name", "")
    st.session_state.setdefault("role", "普通员工")
    st.session_state.setdefault("hr_authenticated", False)
    st.session_state.setdefault("pending_employee_question", None)
    st.session_state.setdefault("pending_hr_question", None)
    st.session_state.setdefault("office_intent",None)
    st.session_state.setdefault(
    "current_chat_id",
    None
)
    st.session_state.setdefault(
    "agent_state",
    {
        "current_intent": None,
        "slots": {},
        "waiting_for": []
    }
    )
    st.session_state.setdefault(
        "messages_employee",
        [{
            "role": "assistant",
            "content": "你好，我是小冲AI助手 👋\n\n你可以直接问我考勤、请假、加班、休假、培训、考核、奖惩等公司制度问题。",
        }],
    )
    st.session_state.setdefault(
        "messages_hr",
        [
            {
                "role":"assistant",
                "content":
                "你好，这里是HR管理端，可以查看制度信息、知识库状态和员工反馈。"
            }
        ]
    )
    st.session_state.setdefault("onboarding_step", 0)
    st.session_state.setdefault("onboarding_saved", False)
    st.session_state.setdefault("onboarding_work_summary", "")
    st.session_state.setdefault("onboarding_attendance_summary", "")
    st.session_state.setdefault(
        "onboarding_data",
        {
            "basic": {},
            "work_analysis": {"summary": "", "confirmed": False},
            "office_map": {"confirmed": False},
            "attendance": {"summary": "", "confirmed": False},
        },
    )


def hero(title: str, subtitle: str, admin: bool = False):
    kicker = "HR ADMIN CONSOLE" if admin else "EMPLOYEE SERVICE CENTER"
    st.markdown(
        f'''<div class="hero">
              <div class="hero-kicker">{kicker}</div>
              <div class="hero-title">{title}</div>
              <div class="hero-subtitle">{subtitle}</div>
            </div>''',
        unsafe_allow_html=True,
    )


def render_sources(sources: list[dict]):
    if not sources:
        st.info("本次没有可展示的检索依据。")
        return
    for i, src in enumerate(sources, start=1):
        heading = src.get("heading") or "未标注章节"
        page = src.get("page")
        page_text = f" · 第 {page} 页" if page else ""
        score = src.get("score", 0.0)
        if score >= 0.75:
            confidence = "高相关"
        elif score >= 0.45:
            confidence = "中等相关"
        else:
            confidence = "辅助参考"
        with st.container(border=True):
            col_a, col_b = st.columns([5, 1])
            with col_a:
                st.markdown(f"**依据 {i} · {src.get('source', '未知文件')}**")
                st.caption(f"{heading}{page_text}")
            with col_b:
                st.markdown(f"**{confidence}**")
                st.caption(f"{score:.3f}")
            st.write(src.get("text", ""))

def build_chat_history(messages, max_rounds=6):

    history = []

    # 最多取最近 6 轮，避免上下文太长
    recent_messages = messages[-max_rounds * 2:]

    for item in recent_messages:

        role = item.get("role")
        content = item.get("content", "")

        if role not in ("user", "assistant"):
            continue

        if not content:
            continue

        history.append({
            "role": role,
            "content": content
        })

    return history


# ============================================================
# 小冲AI 多模态能力
# 支持：
# 1. 图片识别 / OCR
# 2. PDF / Word / TXT / Markdown 解析
# 3. 图片 + 公司制度联合分析
# 4. 图片 + 文档 + 问题联合分析
# ============================================================

VISION_MODEL = "qwen3-vl-plus"


def is_image_file(file_name: str) -> bool:
    """判断上传文件是否为图片。"""
    file_name = (file_name or "").lower()

    return file_name.endswith(
        (
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
        )
    )


def image_bytes_to_data_url(
    file_name: str,
    file_bytes: bytes,
) -> str:
    """把图片 bytes 转成 OpenAI 兼容的 data URL。"""

    mime_type, _ = mimetypes.guess_type(
        file_name
    )

    if not mime_type:
        mime_type = "image/jpeg"

    encoded = base64.b64encode(
        file_bytes
    ).decode("utf-8")

    return (
        f"data:{mime_type};base64,{encoded}"
    )


def analyze_image_with_qwen(
    file_name: str,
    file_bytes: bytes,
    question: str,
) -> str:
    """
    调用 Qwen-VL 识别图片。
    可处理：
    - 普通照片
    - 截图
    - 表格
    - 考勤截图
    - 通知
    - 票据
    - 办公资料
    """

    client = OpenAI(
        api_key=settings.api_key,
        base_url=settings.base_url,
    )

    image_url = image_bytes_to_data_url(
        file_name,
        file_bytes,
    )

    user_question = (
        (question or "").strip()
        or "请识别并分析这张图片。"
    )

    prompt = f"""
你是“小冲AI”，公司的智能办公助手。

员工上传了一张图片。

员工的问题是：

{user_question}

请认真查看图片并回答。

要求：

1. 优先回答员工真正提出的问题。
2. 如果图片中存在文字，请提取重要文字。
3. 如果是表格、考勤截图、通知、票据或办公资料，请提取关键字段。
4. 如果图片包含日期、时间、姓名、金额、状态、审批结果等信息，请尽量结构化整理。
5. 看不清楚或不能确认的内容，要明确说明。
6. 不允许编造图片中不存在的信息。
7. 使用简洁、自然、专业的中文回答。
8. 不要向员工介绍后台模型、OCR、视觉模型等技术实现。
""".strip()

    response = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt,
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_url
                        },
                    },
                ],
            }
        ],
        temperature=0.1,
    )

    return (
        response
        .choices[0]
        .message
        .content
        or "暂时没有识别到有效内容。"
    )


def extract_uploaded_file_text(
    file_name: str,
    file_bytes: bytes,
) -> str:
    """
    提取 PDF / Word / TXT / Markdown 文本。
    """

    lower_name = (
        file_name
        or ""
    ).lower()

    try:

        # TXT / Markdown
        if lower_name.endswith(
            (
                ".txt",
                ".md",
            )
        ):
            return (
                file_bytes.decode(
                    "utf-8",
                    errors="ignore",
                )
            )[:30000]

        # PDF
        if lower_name.endswith(".pdf"):

            reader = PdfReader(
                BytesIO(file_bytes)
            )

            texts = []

            for page in reader.pages[:30]:

                page_text = (
                    page.extract_text()
                    or ""
                )

                if page_text.strip():
                    texts.append(
                        page_text
                    )

            return (
                "\n".join(texts)
            )[:30000]

        # Word
        if lower_name.endswith(".docx"):

            document = Document(
                BytesIO(file_bytes)
            )

            texts = []

            for paragraph in document.paragraphs:

                paragraph_text = (
                    paragraph.text
                    or ""
                ).strip()

                if paragraph_text:
                    texts.append(
                        paragraph_text
                    )

            # 同时读取 Word 表格
            for table in document.tables:

                for row in table.rows:

                    cells = [
                        (
                            cell.text
                            or ""
                        ).strip()
                        for cell in row.cells
                    ]

                    if any(cells):
                        texts.append(
                            " | ".join(cells)
                        )

            return (
                "\n".join(texts)
            )[:30000]

    except Exception as e:

        return (
            f"文件解析失败：{e}"
        )

    return ""


def should_use_company_knowledge(
    question: str,
) -> bool:
    """
    判断图片问题是否需要继续结合企业知识库。
    例如：
    “这个考勤截图算迟到吗？”
    图片负责提取打卡时间，RAG负责查询公司迟到规定。
    """

    question = (
        question
        or ""
    ).lower()

    keywords = [
        "公司",
        "制度",
        "规定",
        "考勤",
        "打卡",
        "迟到",
        "早退",
        "请假",
        "休假",
        "年假",
        "病假",
        "婚假",
        "加班",
        "调休",
        "审批",
        "工资",
        "薪资",
        "奖金",
        "奖惩",
        "处分",
        "合同",
        "报销",
        "培训",
        "考核",
        "入职",
        "离职",
        "人事",
        "hr",
    ]

    return any(
        keyword in question
        for keyword in keywords
    )



def render_chat(
    messages_key,
    show_sources=False,
    input_key="chat_input",
    pending_key=None
):
    # ============================================================
    # 0. 基础状态
    # ============================================================
    messages = st.session_state[messages_key]

    st.session_state.setdefault("office_intent", None)
    st.session_state.setdefault(
        "agent_state",
        {
            "current_intent": None,
            "slots": {},
            "waiting_for": []
        }
    )

    # ============================================================
    # 1. 显示历史聊天记录
    # ============================================================
    for i, message in enumerate(messages):

        avatar = (
            "👤"
            if message.get("role") == "user"
            else "🤖"
        )

        with st.chat_message(
            message.get("role", "assistant"),
            avatar=avatar
        ):
            # ----------------------------------------------------
            # 显示历史附件
            # ----------------------------------------------------
            attachments = message.get("attachments", [])

            for attachment in attachments:

                if attachment.get("kind") == "image":

                    image_data = attachment.get("data")

                    if image_data:
                        st.image(
                            image_data,
                            caption=attachment.get("name", "图片"),
                            width="stretch"
                        )

                else:
                    st.caption(
                        "📎 " + attachment.get("name", "附件")
                    )

            # ----------------------------------------------------
            # 显示消息正文
            # ----------------------------------------------------
            content = message.get("content", "")

            if content:
                st.markdown(content)

            # ----------------------------------------------------
            # HR端显示知识库来源
            # ----------------------------------------------------
            if (
                show_sources
                and message.get("sources")
            ):
                with st.expander(
                    "🔎 查看本次制度检索依据"
                ):
                    render_sources(
                        message["sources"]
                    )

            # ----------------------------------------------------
            # 员工端评价
            # ----------------------------------------------------
            if (
                messages_key == "messages_employee"
                and message.get("role") == "assistant"
                and message.get("question")
                and message.get("content")
            ):
                st.divider()

                feedback_status = message.get("feedback")

                if feedback_status == "success":

                    st.success("👍 已评价")

                elif feedback_status == "failed":

                    st.warning(
                        "👎 已评价，已提交给HR优化。"
                    )

                else:

                    st.write(
                        "这个回答是否解决了您的问题？"
                    )

                    col1, col2 = st.columns(2)

                    with col1:

                        if st.button(
                            "👍",
                            key=(
                                f"{input_key}_"
                                f"{messages_key}_"
                                f"good_{i}"
                            ),
                            width="stretch"
                        ):
                            save_feedback(
                                message["question"],
                                message["content"],
                                "success"
                            )

                            message["feedback"] = "success"
                            st.rerun()

                    with col2:

                        if st.button(
                            "👎",
                            key=(
                                f"{input_key}_"
                                f"{messages_key}_"
                                f"bad_{i}"
                            ),
                            width="stretch"
                        ):
                            save_feedback(
                                message["question"],
                                message["content"],
                                "failed"
                            )

                            message["feedback"] = "failed"
                            st.rerun()

    # ============================================================
    # 2. 智能办公 Word 生成区域
    # ============================================================
    current_office_intent = st.session_state.get(
        "office_intent"
    )

    if (
        messages_key == "messages_employee"
        and current_office_intent
        and current_office_intent != "hr_monthly_report"
    ):
        document_name = DISPLAY_NAMES.get(
            current_office_intent,
            "办公文档"
        )

        with st.expander(
            f"📄 填写《{document_name}》信息",
            expanded=False
        ):
            render_document_task(
                current_office_intent
            )

    # ============================================================
    # 3. 获取快捷问题
    # ============================================================
    if pending_key:

        pending_question = st.session_state.get(
            pending_key
        )

    elif messages_key == "messages_employee":

        pending_question = st.session_state.get(
            "pending_employee_question"
        )

    else:

        pending_question = None

    # ============================================================
    # 4. ChatGPT 风格聊天输入框
    # ============================================================
    prompt = st.chat_input(
        "发消息，或按 + 添加文件/图片",
        key=input_key,
        accept_file="multiple",
        file_type=[
            "jpg",
            "jpeg",
            "png",
            "webp",
            "pdf",
            "docx",
            "txt",
            "md"
        ]
    )

    # ============================================================
    # 5. 解析聊天输入
    # ============================================================
    typed_question = ""
    uploaded_files = []

    if prompt is not None:

        if isinstance(prompt, str):

            typed_question = prompt.strip()

        else:

            typed_question = (
                getattr(
                    prompt,
                    "text",
                    ""
                )
                or ""
            ).strip()

            uploaded_files = list(
                getattr(
                    prompt,
                    "files",
                    []
                )
                or []
            )

    # ============================================================
    # 6. 得到最终问题
    # ============================================================
    question = (
        pending_question
        or typed_question
    )

    if (
        not question
        and not uploaded_files
    ):
        return

    # ============================================================
    # 7. 清除快捷问题
    # ============================================================
    if pending_key:

        st.session_state[pending_key] = None

    elif messages_key == "messages_employee":

        st.session_state[
            "pending_employee_question"
        ] = None

    # ============================================================
    # 8. 处理上传附件
    # ============================================================
    attachments = []

    # 一次最多5个附件
    uploaded_files = uploaded_files[:5]

    for file in uploaded_files:

        try:
            file_bytes = file.getvalue()

        except Exception:
            continue

        # 单个附件最大10MB
        if len(file_bytes) > 10 * 1024 * 1024:

            st.warning(
                f"{file.name} 超过10MB，已跳过。"
            )

            continue

        attachments.append(
            {
                "name": file.name,
                "type": getattr(
                    file,
                    "type",
                    ""
                ),
                "data": file_bytes,
                "kind": (
                    "image"
                    if is_image_file(
                        file.name
                    )
                    else "file"
                )
            }
        )

    # 只上传附件没有文字
    if (
        not question
        and attachments
    ):
        question = (
            "请帮我识别并分析这个附件。"
        )

    # ============================================================
    # 9. 构建聊天历史
    # ============================================================
    history = []

    for item in messages[-10:]:

        role = item.get("role")
        history_content = item.get(
            "content",
            ""
        )

        if (
            role in (
                "user",
                "assistant"
            )
            and history_content
        ):
            history.append(
                {
                    "role": role,
                    "content": history_content
                }
            )

    # ============================================================
    # 10. 保存当前用户消息
    # ============================================================
    messages.append(
        {
            "role": "user",
            "content": question,
            "attachments": attachments
        }
    )
    # ============================================================
    # 11. 分类附件
    # ============================================================
    image_attachments = [
        item
        for item in attachments
        if item.get("kind") == "image"
    ]

    document_attachments = [
        item
        for item in attachments
        if item.get("kind") == "file"
    ]

    # ============================================================
    # 12. 初始化AI回答
    # ============================================================
    answer = ""
    sources = []

    # ============================================================
    # 13. AI处理
    # ============================================================
    with st.spinner(
        "小冲AI正在思考..."
    ):

        # ========================================================
        # A. 用户上传了附件
        # ========================================================
        if attachments:

            if messages_key == "messages_employee":

                st.session_state[
                    "office_intent"
                ] = None

            # ----------------------------------------------------
            # A1. 图片识别
            # ----------------------------------------------------
            image_results = []

            for attachment in image_attachments:

                try:

                    image_answer = (
                        analyze_image_with_qwen(
                            attachment["name"],
                            attachment["data"],
                            question
                        )
                    )

                    image_results.append(
                        (
                            f"【图片："
                            f"{attachment['name']}】\n"
                            f"{image_answer}"
                        )
                    )

                except Exception as e:

                    image_results.append(
                        (
                            f"【图片："
                            f"{attachment['name']}】\n"
                            f"图片识别失败：{e}"
                        )
                    )

            # ----------------------------------------------------
            # A2. PDF / Word / TXT / MD
            # ----------------------------------------------------
            document_results = []

            for attachment in document_attachments:

                try:

                    extracted_text = (
                        extract_uploaded_file_text(
                            attachment["name"],
                            attachment["data"]
                        )
                    )

                except Exception as e:

                    extracted_text = (
                        f"文件解析失败：{e}"
                    )

                if extracted_text:

                    document_results.append(
                        (
                            f"【文件："
                            f"{attachment['name']}】\n\n"
                            f"{extracted_text}"
                        )
                    )

            # ----------------------------------------------------
            # A3. 存在文档：交给原Agent结合知识库回答
            # ----------------------------------------------------
            if document_results:

                image_context = "\n\n".join(
                    image_results
                )

                document_context = "\n\n".join(
                    document_results
                )

                # 防止上下文过长
                document_context = (
                    document_context[:50000]
                )

                file_question = f"""
员工上传了附件，并提出问题：

{question}

图片识别结果：

{image_context if image_context else "没有上传图片。"}

文件中提取到的内容：

{document_context}

请根据员工上传的附件内容回答问题。

如果问题同时涉及公司现行制度，
请结合公司知识库中的资料进行判断。

要求：

1. 不得编造附件中不存在的信息。
2. 公司制度、审批要求、金额、时间等信息，如果知识库没有明确规定，不得自行编造。
3. 优先直接回答员工真正提出的问题。
4. 内容较长时请分点整理。
5. 不要向员工展示RAG、向量检索、相似度等后台技术信息。
""".strip()

                result = agent.ask(
                    file_question,
                    history
                )

                answer = (
                    result.answer
                    or ""
                ).strip()

                sources = (
                    result.sources
                    or []
                )

            # ----------------------------------------------------
            # A4. 只有图片
            # ----------------------------------------------------
            elif image_results:

                image_context = "\n\n".join(
                    image_results
                )

                # 图片问题涉及公司制度时：
                # 图片负责识别事实，RAG负责查询制度
                if should_use_company_knowledge(
                    question
                ):

                    multimodal_question = f"""
员工上传了图片，并提出问题：

{question}

图片识别结果如下：

{image_context}

请结合公司当前知识库回答员工的问题。

要求：

1. 图片中的事实以图片识别结果为基础。
2. 公司制度、审批、时间、处罚、金额等规则必须以公司知识库为依据。
3. 如果知识库没有明确规定，要明确说没有找到，不要自行编造。
4. 最终回答要直接告诉员工结论、依据和建议。
5. 不要向员工展示RAG、向量检索、视觉模型等后台技术信息。
""".strip()

                    result = agent.ask(
                        multimodal_question,
                        history
                    )

                    answer = (
                        result.answer
                        or ""
                    ).strip()

                    sources = (
                        result.sources
                        or []
                    )

                else:

                    answer = image_context
                    sources = []

            # ----------------------------------------------------
            # A5. 附件读取失败
            # ----------------------------------------------------
            else:

                answer = (
                    "没有从上传的附件中读取到有效内容。"
                )

                sources = []

        # ========================================================
        # B. 普通文字聊天
        # ========================================================
        else:

            # ----------------------------------------------------
            # B1. HR端继续使用原RAG
            # ----------------------------------------------------
            if messages_key == "messages_hr":

                result = agent.ask(
                    question,
                    history
                )

                answer = (
                    result.answer
                    or ""
                ).strip()

                sources = (
                    result.sources
                    or []
                )

            # ----------------------------------------------------
            # B2. 员工端使用 SmartRouter
            # ----------------------------------------------------
            else:

                route_result = route_request(
                    question,
                    history=history,
                    current_intent=(
                        st.session_state
                        .get(
                            "agent_state",
                            {}
                        )
                        .get(
                            "current_intent"
                        )
                    ),
                    has_image=False,
                    has_file=False
                )

                intent = route_result.get(
                    "intent",
                    "general_chat"
                )

                print(
                    "========== 小冲AI Router =========="
                )
                print(
                    "用户问题：",
                    question
                )
                print(
                    "识别意图：",
                    intent
                )
                print(
                    "置信度：",
                    route_result.get(
                        "confidence"
                    )
                )
                print(
                    "调用工具：",
                    route_result.get(
                        "tool"
                    )
                )
                print(
                    "提取字段：",
                    route_result.get(
                        "fields"
                    )
                )
                print(
                    "==================================="
                )

                # --------------------------------------------
                # 合并Agent已提取字段
                # --------------------------------------------
                old_slots = (
                    st.session_state[
                        "agent_state"
                    ].get(
                        "slots",
                        {}
                    )
                )

                new_slots = (
                    route_result.get(
                        "fields",
                        {}
                    )
                )

                if not isinstance(
                    new_slots,
                    dict
                ):
                    new_slots = {}

                for key, value in new_slots.items():

                    if value not in (
                        "",
                        None,
                        []
                    ):
                        old_slots[
                            key
                        ] = value

                st.session_state[
                    "agent_state"
                ][
                    "slots"
                ] = old_slots

                # --------------------------------------------
                # B2-1. HR月报
                # --------------------------------------------
                if intent == "hr_monthly_report":

                    st.session_state[
                        "office_intent"
                    ] = None

                    st.session_state[
                        "agent_state"
                    ][
                        "current_intent"
                    ] = intent

                    answer = (
                        "好的，我已经识别到您需要生成"
                        "《HR月度运营报告》。\n\n"
                        "该报告需要读取HR运营数据，"
                        "请进入HR管理端的"
                        "“AI运营优化”页面生成。"
                    )

                    sources = []

                # --------------------------------------------
                # B2-2. 智能办公Word任务
                # --------------------------------------------
                elif intent in (
                    "leave_request",
                    "overtime_request",
                    "interview_invitation",
                    "onboarding_notice",
                    "employment_certificate",
                    "training_notice",
                    "meeting_minutes"
                ):

                    st.session_state[
                        "office_intent"
                    ] = intent

                    st.session_state[
                        "agent_state"
                    ][
                        "current_intent"
                    ] = intent

                    document_name = (
                        DISPLAY_NAMES.get(
                            intent,
                            "办公文档"
                        )
                    )

                    answer = (
                        f"可以，我来帮您生成"
                        f"《{document_name}》。\n\n"
                        f"请点击下方的 "
                        f"**“填写《{document_name}》信息”**，"
                        f"补充必要资料后即可生成 Word 文件。"
                    )

                    sources = []

                # --------------------------------------------
                # B2-3. 公司制度问题
                # --------------------------------------------
                elif intent == "policy_qa":

                    st.session_state[
                        "office_intent"
                    ] = None

                    st.session_state[
                        "agent_state"
                    ][
                        "current_intent"
                    ] = None

                    result = agent.ask(
                        question,
                        history
                    )

                    answer = (
                        result.answer
                        or ""
                    ).strip()

                    sources = (
                        result.sources
                        or []
                    )

                # --------------------------------------------
                # B2-4. 普通聊天
                # --------------------------------------------
                else:

                    st.session_state[
                        "office_intent"
                    ] = None

                    st.session_state[
                        "agent_state"
                    ][
                        "current_intent"
                    ] = None

                    result = agent.ask(
                        question,
                        history
                    )

                    answer = (
                        result.answer
                        or ""
                    ).strip()

                    sources = (
                        result.sources
                        or []
                    )

    # ============================================================
    # 14. 最终回答安全检查
    # ============================================================
    if not str(answer).strip():

        # 再兜底尝试一次原Agent
        try:

            result = agent.ask(
                question,
                history
            )

            answer = (
                result.answer
                or ""
            ).strip()

            sources = (
                result.sources
                or []
            )

        except Exception as e:

            print(
                "备用AI回答失败：",
                e
            )

            answer = ""

    if not str(answer).strip():

        answer = (
            "抱歉，我这次没有成功生成回答。"
            "请重新描述一下您的问题，我会重新处理。"
        )

        sources = []

    print(
        "========== 最终回答检查 =========="
    )
    print(
        "question =",
        question
    )
    print(
        "answer =",
        repr(answer)
    )
    print(
        "sources =",
        sources
    )
    print(
        "=================================="
    )

    # ============================================================
    # 15. 保存AI回答
    # 注意：必须始终执行，不能缩进到“answer为空”判断里
    # ============================================================
    messages.append(
        {
            "role": "assistant",
            "content": answer,
            "sources": sources,
            "question": question,
            "feedback": None
        }
    )


    # ============================================================
    # 保存员工历史会话
    # 必须在 AI 回答已经加入 messages 之后保存
    # ============================================================
    if messages_key == "messages_employee":

        try:

            chat_id = save_conversation(
                messages,
                st.session_state.get(
                    "current_chat_id"
                )
            )

            st.session_state[
                "current_chat_id"
            ] = chat_id

        except Exception as e:

            print(
                "保存历史会话失败：",
                e
            )

    # ============================================================
    # 16. 保存AI运营数据
    # ============================================================
    try:

        save_ai_question_record(
            question,
            answer,
            sources
        )

    except Exception:

        pass

    # ============================================================
    # 17. 刷新页面
    # ============================================================
    st.rerun()


def quick_questions():
    st.markdown('<div class="section-title">常用服务</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-subtitle">点击一个常见问题，马上开始咨询</div>', unsafe_allow_html=True)
    items = [
        ("⏰ 考勤打卡", "忘记打卡了怎么办？"),
        ("🗓️ 请假休假", "请两天假需要谁审批？"),
        ("🌙 加班调休", "员工加班需要提前申请吗？"),
        ("📚 培训考核", "公司的培训管理有什么要求？"),
    ]
    cols = st.columns(4)
    for idx, ((label, question), col) in enumerate(zip(items, cols)):
        with col:
            if st.button(label, key=f"quick_{idx}", width="stretch"):
                st.session_state.pending_employee_question = question
                



def reset_onboarding():
    st.session_state.onboarding_step = 0
    st.session_state.onboarding_saved = False
    st.session_state.onboarding_work_summary = ""
    st.session_state.onboarding_attendance_summary = ""
    st.session_state.onboarding_data = {
        "basic": {},
        "work_analysis": {"summary": "", "confirmed": False},
        "office_map": {"confirmed": False},
        "attendance": {"summary": "", "confirmed": False},
    }


def onboarding_header(step: int):
    steps = ["开始", "基本信息", "主要工作分析", "办公地图", "考勤制度", "完成"]
    progress = min(step / (len(steps) - 1), 1.0)
    st.progress(progress)
    chips = "".join(
        f'<span class="step-chip">{"✓ " if i < step else ""}{name}</span>'
        for i, name in enumerate(steps)
    )
    st.markdown(chips, unsafe_allow_html=True)


def _generate_work_analysis(basic: dict) -> str:
    department = basic.get("department", "")
    position = basic.get("position", "")
    question = f"""
这是一项新员工入职培训任务。
员工所属部门：{department}
员工岗位：{position}

请只依据公司知识库中与“岗位职责、岗位说明、部门职责、工作内容”有关的资料，
为这名新员工整理一份“主要工作分析”。

请按以下结构输出：
1. 主要工作职责
2. 日常工作内容
3. 主要协作部门/岗位
4. 需要重点掌握的事项
5. 入职初期建议优先了解的工作

要求：
- 只使用公司资料中能够支持的信息。
- 如果知识库没有该岗位的明确职责，不要自行编造，直接说明“当前知识库暂未找到该岗位的明确职责，请向直属领导或 HR 确认”。
- 不要出现 RAG、检索结果、S1/S2 等后台术语。
""".strip()
    result = agent.ask(question, [])
    return result.answer


def _generate_attendance_summary() -> str:
    question = """
这是一项新员工入职培训任务。
请只依据公司现行制度资料，为新员工整理“考勤管理制度”重点。

请尽量覆盖：
1. 上下班与打卡要求
2. 迟到、早退相关规定
3. 忘记打卡或考勤异常如何处理
4. 请假申请与审批流程
5. 加班相关要求
6. 其他新员工必须注意的考勤事项

要求：
- 只依据公司制度资料回答，不得自行补充公司没有规定的数字、时间或处罚标准。
- 如果某一项制度资料没有明确规定，写“现有制度资料中暂未找到明确规定，建议向人事行政部确认”。
- 回答要适合新员工阅读，简洁、分点说明。
- 不要出现 RAG、检索结果、S1/S2 等后台术语。
""".strip()
    result = agent.ask(question, [])
    return result.answer

from pathlib import Path
from PIL import Image


def render_company_map_and_locations():

    from pathlib import Path
    from PIL import Image

    st.subheader("🏢 公司办公地图和位置")

    # =========================
    # 公司地图
    # =========================

    company_map = None

    # 推荐这样写，避免启动目录不同导致找不到图片
    map_path = (
        Path(__file__).resolve().parent
        / "assets"
        / "company_map.png"
    )

    if map_path.exists():

        # 保存地图路径，后面 onboarding 还能继续使用
        company_map = str(map_path)

        # 打开图片
        img = Image.open(map_path)

        # 显示图片
        st.image(
            img,
            caption="当前公司办公地图",
            width="stretch"
        )

    else:

        st.warning(
            "暂未找到公司办公地图，请联系HR管理员上传。"
        )


    # =========================
    # 办公位置
    # =========================

    st.divider()

    st.subheader("📍 常用办公区域")

    locations = [
        "人事行政部：办理入职、考勤、请假",
        "财务部：报销、费用业务",
        "会议室：培训、会议",
        "生产车间：现场生产区域",
        "食堂：员工就餐区域",
    ]


    for item in locations:

        st.info(item)


    # =========================
    # 返回地图和位置
    # =========================

    return company_map, locations 

def render_onboarding():
    step = st.session_state.onboarding_step
    data = st.session_state.onboarding_data

    st.markdown(
        '''<div class="onboarding-hero">
             <div style="font-size:22px;font-weight:800;color:#172033;">👋 新员工入职培训</div>
             <div style="margin-top:7px;color:#667085;line-height:1.7;">
             新员工培训聚焦三个真正影响上手效率的内容：主要工作分析、公司办公地图和位置、考勤管理制度。
             完成后可生成个人培训与入职引导记录。
             </div>
           </div>''',
        unsafe_allow_html=True,
    )
    onboarding_header(step)
    st.write("")

    if step == 0:
        st.markdown("### 欢迎加入公司 👋")
        st.write("这不是一份泛泛的入职清单，而是帮助你尽快回答三个实际问题：**我要做什么、公司各位置在哪里、考勤应该怎么做。**")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.info("**① 主要工作分析**\n\n结合你的部门和岗位，从岗位职责资料中整理主要工作、协作对象和上手重点。")
        with c2:
            st.info("**② 公司办公地图和位置**\n\n查看 HR 上传的实际办公地图，快速找到人事、财务、会议室、车间等常用位置。")
        with c3:
            st.info("**③ 考勤管理制度**\n\n从公司制度中整理打卡、考勤异常、请假和加班等新人必须知道的事项。")
        if st.button("开始新员工培训 →", type="primary", width="stretch"):
            st.session_state.onboarding_step = 1
            st.rerun()
        return

    if step == 1:
        st.markdown("### 基本信息")
        st.caption("系统将根据部门和岗位生成更贴近你的工作分析。")
        basic = data.get("basic", {})
        with st.form("onboarding_basic_form"):
            name = st.text_input("姓名 *", value=basic.get("name", ""))
            departments = ["请选择", "综合管理部", "技术部", "质量部", "生产部", "销售部", "采购部", "财务部", "其他"]
            current_dep = basic.get("department", "请选择")
            dep_index = departments.index(current_dep) if current_dep in departments else 0
            department = st.selectbox("所属部门 *", departments, index=dep_index)
            position = st.text_input("岗位 *", value=basic.get("position", ""), placeholder="例如：机器视觉工程师")
            start_date = st.date_input("入职日期")
            submitted = st.form_submit_button("保存并进入主要工作分析", type="primary", width="stretch")
        if submitted:
            if not name.strip() or department == "请选择" or not position.strip():
                st.error("请先填写姓名、部门和岗位。")
            else:
                data["basic"] = {
                    "name": name.strip(),
                    "department": department,
                    "position": position.strip(),
                    "start_date": start_date.isoformat(),
                }
                data["work_analysis"] = {"summary": "", "confirmed": False}
                st.session_state.onboarding_work_summary = ""
                st.session_state.onboarding_step = 2
                st.rerun()
        return

    if step == 2:
        basic = data.get("basic", {})
        st.markdown("### ① 主要工作分析")
        st.caption(f"当前岗位：{basic.get('department', '-')} / {basic.get('position', '-')}")
        st.write("系统会从公司知识库中的岗位职责、岗位说明或部门职责资料中整理内容；没有资料时不会凭空编造。")

        if not store.exists:
            st.warning("知识库尚未建立，请联系 HR 管理员先重建知识库索引。")
        else:
            if st.button("✨ 生成我的主要工作分析", type="primary", width="stretch"):
                with st.spinner("正在读取岗位职责资料并整理工作分析……"):
                    summary = _generate_work_analysis(basic)
                st.session_state.onboarding_work_summary = summary
                data["work_analysis"]["summary"] = summary
                data["work_analysis"]["confirmed"] = False

        summary = st.session_state.onboarding_work_summary or data.get("work_analysis", {}).get("summary", "")
        if summary:
            with st.container(border=True):
                st.markdown(summary)
            confirmed = st.checkbox(
                "我已阅读并了解本岗位的主要工作内容",
                value=bool(data.get("work_analysis", {}).get("confirmed", False)),
                key="work_analysis_confirm",
            )
            data["work_analysis"] = {"summary": summary, "confirmed": confirmed}
        else:
            confirmed = False
            st.info("点击上方按钮生成主要工作分析。若当前知识库没有岗位职责，请让 HR 将岗位职责库加入 knowledge_base 后重新建立索引。")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("← 返回基本信息", key="work_back", width="stretch"):
                st.session_state.onboarding_step = 1
                st.rerun()
        with col2:
            if st.button("进入办公地图 →", key="work_next", type="primary",  width="stretch", disabled=not confirmed):
                st.session_state.onboarding_step = 3
                st.rerun()
        return

    if step == 3:
        st.markdown("### ② 公司办公地图和位置")
        st.caption("这里展示 HR 配置的实际办公地图和常用位置，不由 AI 猜测公司布局。")
        company_map, locations = render_company_map_and_locations()

        has_location_info = bool(company_map or locations)
        current_confirmed = bool(data.get("office_map", {}).get("confirmed", False))
        confirmed = st.checkbox(
            "我已查看并了解当前提供的公司办公地图和常用位置",
            value=current_confirmed,
            key="office_map_confirm",
            disabled=not has_location_info,
        )
        data["office_map"] = {"confirmed": confirmed}

        if not has_location_info:
            st.info("需要 HR 至少上传一张公司办公地图，或配置一条办公位置说明，才能完成本步骤。")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("← 返回工作分析", key="map_back",  width="stretch"):
                st.session_state.onboarding_step = 2
                st.rerun()
        with col2:
            if st.button("进入考勤制度 →", key="map_next", type="primary",  width="stretch", disabled=not confirmed):
                st.session_state.onboarding_step = 4
                st.rerun()
        return

    if step == 4:
        st.markdown("### ③ 考勤管理制度")
        st.caption("系统从当前企业制度资料中整理新人最需要掌握的考勤要求。")

        if not store.exists:
            st.warning("知识库尚未建立，请联系 HR 管理员先重建知识库索引。")
        else:
            if st.button("📘 生成考勤制度培训要点", type="primary", width="stretch"):
                with st.spinner("正在读取考勤、请假和加班制度……"):
                    summary = _generate_attendance_summary()
                st.session_state.onboarding_attendance_summary = summary
                data["attendance"]["summary"] = summary
                data["attendance"]["confirmed"] = False

        summary = st.session_state.onboarding_attendance_summary or data.get("attendance", {}).get("summary", "")
        if summary:
            with st.container(border=True):
                st.markdown(summary)
            confirmed = st.checkbox(
                "我已阅读并了解公司的考勤管理制度",
                value=bool(data.get("attendance", {}).get("confirmed", False)),
                key="attendance_confirm",
            )
            data["attendance"] = {"summary": summary, "confirmed": confirmed}
        else:
            confirmed = False
            st.info("点击上方按钮生成考勤制度培训要点。")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("← 返回办公地图", key="attendance_back", width="stretch"):
                st.session_state.onboarding_step = 3
                st.rerun()
        with col2:
            if st.button("完成新员工培训 ✓", key="attendance_finish", type="primary", width="stretch", disabled=not confirmed):
                st.session_state.onboarding_step = 5
                st.rerun()
        return

    if step == 5:
        basic = data.get("basic", {})
        if not st.session_state.onboarding_saved:
            record = {
                "account": st.session_state.get("auth_username", ""),
                "name": basic.get("name", ""),
                "department": basic.get("department", ""),
                "position": basic.get("position", ""),
                "start_date": basic.get("start_date", ""),
                "work_analysis_completed": int(bool(data.get("work_analysis", {}).get("confirmed"))),
                "office_map_completed": int(bool(data.get("office_map", {}).get("confirmed"))),
                "attendance_completed": int(bool(data.get("attendance", {}).get("confirmed"))),
                "work_analysis_summary": data.get("work_analysis", {}).get("summary", ""),
                "attendance_summary": data.get("attendance", {}).get("summary", ""),
                "status": "已完成",
            }
            save_onboarding_record(settings.onboarding_log_path, record)
            st.session_state.onboarding_saved = True

        st.success("🎉 新员工培训已完成！")
        st.markdown(f"### {basic.get('name', '')}，欢迎加入公司")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("所属部门", basic.get("department", "-"))
        with c2:
            st.metric("岗位", basic.get("position", "-"))
        with c3:
            st.metric("培训模块", "3/3")
        with c4:
            st.metric("完成度", "100%")

        st.markdown("#### 已完成培训")
        t1, t2, t3 = st.columns(3)
        with t1:
            st.success("✅ 主要工作分析")
        with t2:
            st.success("✅ 公司办公地图和位置")
        with t3:
            st.success("✅ 考勤管理制度")

        company_map = find_company_map(settings.assets_dir)
        locations = load_company_locations(settings.company_locations_path)
        docx_bytes = build_onboarding_docx(data, company_map, locations)
        filename = f"{basic.get('name', '新员工')}_新员工培训与入职引导记录.docx"
        st.download_button(
            "📄 下载新员工培训记录 Word",
            data=docx_bytes,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            width="stretch",
            type="primary",
        )
        st.caption("文档会汇总基本信息、主要工作分析、办公地图/位置和考勤制度培训结果。")

        if st.button("重新开始一次新员工培训", key="onboarding_restart", width="stretch"):
            reset_onboarding()
            st.rerun()


def render_company_location_admin():
    st.markdown("#### 🗺️ 公司办公地图与位置管理")
    st.caption("员工端只展示这里由 HR 配置的真实公司信息，系统不会自动猜测办公区域。")

    current_map = find_company_map(settings.assets_dir)
    if current_map:
        st.image(str(current_map), caption="当前公司办公地图", width="stretch")
    else:
        st.info("当前还没有上传公司办公地图。")

    uploaded = st.file_uploader(
        "上传或替换公司办公地图",
        type=["png", "jpg", "jpeg", "webp"],
        key="company_map_upload",
        help="建议上传办公楼平面图、厂区地图或经过整理的办公位置示意图。",
    )
    if uploaded is not None:
        if st.button("保存公司办公地图", width="stretch", type="primary"):
            try:
                save_company_map(settings.assets_dir, uploaded.name, uploaded.getvalue())
                st.success("办公地图已更新。")
                st.rerun()
            except Exception as exc:
                st.error(f"保存失败：{exc}")

    locations = load_company_locations(settings.company_locations_path)
    initial_text = locations_to_text(locations)
    st.markdown("##### 常用位置说明")
    st.caption("每行填写一个位置，格式：`位置名称|用途或路线说明`。例如：`人事行政部|办理入职、考勤和请假事项`。")
    text_value = st.text_area(
        "办公位置",
        value=initial_text,
        height=180,
        key="company_locations_text",
        label_visibility="collapsed",
        placeholder="人事行政部|办理入职、考勤和请假事项\n财务部|报销及费用相关事项\n会议室A|新人培训及部门会议",
    )
    if st.button("保存办公位置说明", width="stretch"):
        parsed = parse_locations_text(text_value)
        save_company_locations(settings.company_locations_path, parsed)
        st.success(f"已保存 {len(parsed)} 条办公位置说明。")
        st.rerun()

def inject_chat_style():

    st.markdown(
        """
<style>

/* ================================
   全局背景
================================ */

.stApp{

    background:#f7f8fa;

}


/* ================================
   左侧栏
================================ */

section[data-testid="stSidebar"]{

    background:#ffffff;

    border-right:
    1px solid #e5e7eb;

}


section[data-testid="stSidebar"] > div{

    padding:
    18px 16px;

}



/* logo */

.ai-logo{

    font-size:
    34px;

    font-weight:
    800;

    color:
    #111827;

    margin-bottom:
    4px;

}



.ai-subtitle{

    font-size:
    14px;

    color:
    #9ca3af;

    margin-bottom:
    25px;

}



/* 导航按钮 */

.nav-card{

    background:
    #f9fafb;

    border:
    1px solid #eeeeee;

    border-radius:
    14px;

    padding:
    12px;

    margin-bottom:
    10px;

    font-size:
    16px;

    color:
    #374151;

}


/* ================================
   主页面
================================ */


.main-container{

    max-width:
    1000px;

    margin:
    auto;

}



/* 标题 */

.ai-title{

    text-align:
    center;


    font-size:
    42px;


    font-weight:
    800;


    color:
    #111827;


    margin-top:
    25px;


    margin-bottom:
    8px;

}



.ai-welcome{

    text-align:
    center;


    font-size:
    16px;


    color:
    #6b7280;


    margin-bottom:
    35px;

}



/* 欢迎卡 */

.welcome-card{


    background:
    white;


    border-radius:
    20px;


    padding:
    30px;


    border:
    1px solid #eeeeee;


    box-shadow:
    0 4px 15px rgba(0,0,0,0.03);


}



/* 聊天气泡 */


div[data-testid="stChatMessage"]{


    background:white;


    border-radius:
    18px;


    border:
    1px solid #eeeeee;


}



/* tab */

.stTabs [data-baseweb="tab-list"]{


    justify-content:
    center;


}


.stTabs [data-baseweb="tab"]{


    font-size:
    16px;

    font-weight:
    600;

}



/* 底部输入 */


div[data-testid="stChatInput"]{


    border-radius:
    18px !important;


}


/* 隐藏streamlit默认 */

#MainMenu{

    visibility:hidden;

}


footer{

    visibility:hidden;

}


</style>

        """,
        unsafe_allow_html=True
    )


# ============================================================
# HR后台 - 注册用户管理
# ============================================================

def render_user_admin():

    st.markdown("## 👥 注册用户管理")

    st.caption(
        "查看小冲AI注册账号，并进行启用、禁用、密码重置和删除。"
    )

    users = _read_users()

    if not users:

        st.info(
            "当前还没有注册用户。"
        )

        return

    # --------------------------------------------------------
    # 简单统计
    # --------------------------------------------------------

    total_users = len(users)

    disabled_users = sum(
        1
        for user in users.values()
        if user.get("disabled", False)
    )

    normal_users = (
        total_users
        - disabled_users
    )

    c1, c2, c3 = st.columns(3)

    with c1:
        st.metric(
            "注册用户",
            total_users
        )

    with c2:
        st.metric(
            "正常账号",
            normal_users
        )

    with c3:
        st.metric(
            "已禁用",
            disabled_users
        )

    st.divider()

    # --------------------------------------------------------
    # 用户列表
    # --------------------------------------------------------

    for username_key, user in sorted(
        users.items(),
        key=lambda item: (
            item[1].get(
                "created_at",
                ""
            )
        ),
        reverse=True
    ):

        display_name = (
            user.get("username")
            or username_key
        )

        created_at = user.get(
            "created_at",
            "-"
        )

        role = user.get(
            "role",
            "普通员工"
        )

        disabled = bool(
            user.get(
                "disabled",
                False
            )
        )

        with st.container(
            border=True
        ):

            top1, top2, top3 = st.columns(
                [2.2, 1.5, 1.3]
            )

            with top1:

                st.markdown(
                    f"### 👤 {display_name}"
                )

                st.caption(
                    f"账号ID：{username_key}"
                )

            with top2:

                st.write(
                    f"**注册时间：** {created_at}"
                )

                st.write(
                    f"**角色：** {role}"
                )

            with top3:

                if disabled:

                    st.error(
                        "已禁用"
                    )

                else:

                    st.success(
                        "正常"
                    )

            # =================================================
            # 账号启用 / 禁用
            # =================================================

            col1, col2 = st.columns(
                [1, 2]
            )

            with col1:

                if disabled:

                    if st.button(
                        "✅ 启用账号",
                        key=f"enable_user_{username_key}",
                        width="stretch"
                    ):

                        users[
                            username_key
                        ][
                            "disabled"
                        ] = False

                        _write_users(
                            users
                        )

                        st.success(
                            f"{display_name} 已启用。"
                        )

                        st.rerun()

                else:

                    if st.button(
                        "⛔ 禁用账号",
                        key=f"disable_user_{username_key}",
                        width="stretch"
                    ):

                        users[
                            username_key
                        ][
                            "disabled"
                        ] = True

                        _write_users(
                            users
                        )

                        st.success(
                            f"{display_name} 已禁用。"
                        )

                        st.rerun()

            # =================================================
            # 密码重置
            # =================================================

            with col2:

                with st.expander(
                    "🔑 重置密码"
                ):

                    new_password = st.text_input(
                        "新密码",
                        type="password",
                        key=f"new_password_{username_key}",
                        placeholder="至少6位"
                    )

                    confirm_password = st.text_input(
                        "确认新密码",
                        type="password",
                        key=f"confirm_password_{username_key}",
                        placeholder="再次输入新密码"
                    )

                    if st.button(
                        "确认重置密码",
                        key=f"reset_password_{username_key}",
                        width="stretch"
                    ):

                        if len(
                            new_password
                        ) < 6:

                            st.warning(
                                "新密码至少需要6位。"
                            )

                        elif (
                            new_password
                            != confirm_password
                        ):

                            st.warning(
                                "两次输入的密码不一致。"
                            )

                        else:

                            salt_hex, password_hash = (
                                _hash_password(
                                    new_password
                                )
                            )

                            users[
                                username_key
                            ][
                                "password_salt"
                            ] = salt_hex

                            users[
                                username_key
                            ][
                                "password_hash"
                            ] = password_hash

                            _write_users(
                                users
                            )

                            st.success(
                                f"{display_name} 的密码已经重置。"
                            )

            # =================================================
            # 删除账号
            # =================================================

            with st.expander(
                "🗑️ 删除账号"
            ):

                st.warning(
                    "删除后该账号将不能再登录。历史会话文件不会自动删除。"
                )

                confirm_delete = st.checkbox(
                    f"我确认删除账号：{display_name}",
                    key=f"confirm_delete_{username_key}"
                )

                if st.button(
                    "永久删除账号",
                    key=f"delete_user_{username_key}",
                    type="primary",
                    width="stretch",
                    disabled=not confirm_delete
                ):

                    users.pop(
                        username_key,
                        None
                    )

                    _write_users(
                        users
                    )

                    st.success(
                        f"{display_name} 已删除。"
                    )

                    st.rerun()




def inject_mobile_style():
    """
    小冲AI移动端适配
    重点优化：
    1. 手机标题不过度换行
    2. 页面左右留白更合理
    3. Tab 更紧凑
    4. 聊天气泡更舒服
    5. 输入框固定在底部
    6. 侧边栏在手机上更好用
    """

    st.markdown(
        """
<style>

/* =========================================================
   通用微调
   ========================================================= */

html, body {
    -webkit-text-size-adjust: 100%;
}

[data-testid="stAppViewContainer"] {
    background: #f7f8fa !important;
}

/* 页面内容不要太宽 */
[data-testid="stAppViewContainer"] .main .block-container {
    max-width: 980px !important;
}

/* 聊天消息整体 */
div[data-testid="stChatMessage"] {
    background: #ffffff !important;
    border: 1px solid #edf0f3 !important;
    border-radius: 18px !important;
    box-shadow: 0 2px 10px rgba(15, 23, 42, 0.035) !important;
}

/* Tab 更简洁 */
.stTabs [data-baseweb="tab-list"] {
    gap: 8px !important;
    border-bottom: 1px solid #e5e7eb !important;
}

.stTabs [data-baseweb="tab"] {
    height: 44px !important;
    padding-left: 14px !important;
    padding-right: 14px !important;
    font-size: 15px !important;
}

/* 输入框 */
[data-testid="stChatInput"] {
    border-radius: 22px !important;
    border: 1px solid #d7dce3 !important;
    background: #ffffff !important;
    box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08) !important;
}

/* =========================================================
   手机端
   ========================================================= */

@media (max-width: 768px) {

    /* 页面主体 */
    [data-testid="stAppViewContainer"] .main .block-container {
        max-width: 100% !important;

        padding-top: 10px !important;
        padding-left: 14px !important;
        padding-right: 14px !important;

        /* 给底部固定输入框留空间 */
        padding-bottom: 125px !important;
    }

    /* Streamlit 顶部栏不要占太多 */
    [data-testid="stHeader"] {
        height: 48px !important;
        background: rgba(247, 248, 250, 0.96) !important;
        backdrop-filter: blur(10px);
    }

    /* 主标题：手机上不要夸张 */
    .xiaochong-main-title {
        font-size: 29px !important;
        line-height: 1.28 !important;
        letter-spacing: -0.8px !important;
        margin-top: 6px !important;
        margin-bottom: 18px !important;
        padding-left: 4px !important;
        padding-right: 4px !important;
        white-space: normal !important;
    }

    /* Tabs 占满宽度，两栏平均 */
    .stTabs [data-baseweb="tab-list"] {
        width: 100% !important;
        justify-content: stretch !important;
        gap: 0 !important;
        margin-bottom: 12px !important;
    }

    .stTabs [data-baseweb="tab"] {
        flex: 1 1 50% !important;
        justify-content: center !important;
        min-width: 0 !important;
        padding: 0 6px !important;
        font-size: 15px !important;
        white-space: nowrap !important;
    }

    /* 聊天消息 */
    div[data-testid="stChatMessage"] {
        width: 100% !important;
        max-width: 100% !important;

        border-radius: 16px !important;

        margin-top: 8px !important;
        margin-bottom: 10px !important;

        padding: 10px 12px !important;

        box-shadow: none !important;
    }

    /* 聊天正文文字 */
    [data-testid="stChatMessageContent"] {
        max-width: 100% !important;
        font-size: 16px !important;
        line-height: 1.72 !important;
    }

    [data-testid="stChatMessageContent"] p {
        margin-top: 4px !important;
        margin-bottom: 9px !important;
    }

    /* 头像区域紧凑一点 */
    [data-testid="stChatMessageAvatarUser"],
    [data-testid="stChatMessageAvatarAssistant"] {
        transform: scale(0.9);
    }

    /* =====================================================
       底部输入框固定
       ===================================================== */

    [data-testid="stBottom"] {
        position: fixed !important;

        left: 0 !important;
        right: 0 !important;
        bottom: 0 !important;

        z-index: 999 !important;

        padding:
            10px 14px
            calc(10px + env(safe-area-inset-bottom))
            14px !important;

        background:
            linear-gradient(
                180deg,
                rgba(247,248,250,0) 0%,
                rgba(247,248,250,0.96) 26%,
                rgba(247,248,250,1) 100%
            ) !important;
    }

    [data-testid="stBottom"] > div {
        width: 100% !important;
        max-width: 100% !important;
    }

    [data-testid="stChatInput"] {
        width: 100% !important;
        max-width: 100% !important;

        margin-left: auto !important;
        margin-right: auto !important;

        border-radius: 24px !important;

        background: #ffffff !important;

        box-shadow:
            0 8px 26px rgba(15, 23, 42, 0.10)
            !important;
    }

    /* 输入框文字 */
    [data-testid="stChatInput"] textarea {
        font-size: 16px !important;
        line-height: 1.45 !important;
    }

    /* =====================================================
       手机侧边栏
       ===================================================== */

    section[data-testid="stSidebar"] {
        width: min(88vw, 340px) !important;
        min-width: min(88vw, 340px) !important;
        max-width: min(88vw, 340px) !important;

        background: #ffffff !important;
    }

    section[data-testid="stSidebar"] > div {
        padding: 14px 14px 26px 14px !important;
    }

    section[data-testid="stSidebar"] .ai-logo {
        font-size: 27px !important;
        margin-bottom: 2px !important;
    }

    section[data-testid="stSidebar"] .ai-subtitle {
        font-size: 13px !important;
        margin-bottom: 14px !important;
    }

    /* 侧栏按钮不要太高 */
    section[data-testid="stSidebar"] .stButton > button {
        min-height: 42px !important;
        border-radius: 12px !important;
    }

    /* 侧栏文字输入框 */
    section[data-testid="stSidebar"] input {
        font-size: 16px !important;
    }

    /* Expander 紧凑 */
    section[data-testid="stSidebar"] [data-testid="stExpander"] {
        border-radius: 12px !important;
    }

    /* =====================================================
       表单 / 文件 / 按钮
       ===================================================== */

    .stButton > button,
    .stDownloadButton > button {
        min-height: 42px !important;
        font-size: 15px !important;
    }

    [data-testid="stFileUploader"] {
        border-radius: 14px !important;
    }

    /* metric 手机端不要太拥挤 */
    [data-testid="stMetric"] {
        padding: 8px !important;
    }

    /* 减少分割线间距 */
    hr {
        margin-top: 12px !important;
        margin-bottom: 12px !important;
    }

    /* 隐藏底部默认 footer */
    footer {
        visibility: hidden !important;
        height: 0 !important;
    }
}


/* =========================================================
   超小屏幕
   ========================================================= */

@media (max-width: 390px) {

    .xiaochong-main-title {
        font-size: 27px !important;
    }

    .stTabs [data-baseweb="tab"] {
        font-size: 14px !important;
    }

    [data-testid="stChatMessageContent"] {
        font-size: 15px !important;
    }

}


/* =====================================================
   隐藏 Streamlit 默认底部标识
   ===================================================== */

/* Hosted with Streamlit */
footer {
    display: none !important;
}


/* 右下角 Streamlit 水印 */
[data-testid="stDecoration"] {
    display: none !important;
}


/* 状态组件 */
[data-testid="stStatusWidget"] {
    display: none !important;
}


/* Deploy 按钮 */
.stDeployButton {
    display: none !important;
}


/* Main 菜单 */
#MainMenu {
    display: none !important;
}


/* Streamlit badge */
.viewerBadge_container__1QSob {
    display: none !important;
}


/* 手机底部空间减少 */
@media (max-width:768px){

    [data-testid="stAppViewContainer"] .main .block-container {
        padding-bottom:90px !important;
    }

}

</style>
        """,
        unsafe_allow_html=True
    )




# ============================================================
# PC / 手机设备识别
# 同一个网址，自动切换两套界面
# ============================================================

def is_mobile_device() -> bool:
    """
    根据浏览器 User-Agent 判断是否为手机/平板。
    也支持 URL 参数：
        ?view=mobile
        ?view=desktop
    用于手动测试两套界面。
    """

    # 手动覆盖，方便开发时测试
    try:
        forced_view = st.query_params.get("view", "")
    except Exception:
        forced_view = ""

    if isinstance(forced_view, list):
        forced_view = forced_view[0] if forced_view else ""

    forced_view = str(forced_view).lower().strip()

    if forced_view == "mobile":
        return True

    if forced_view == "desktop":
        return False

    # 自动判断
    try:
        user_agent = (
            st.context.headers.get(
                "User-Agent",
                ""
            )
            or ""
        ).lower()
    except Exception:
        user_agent = ""

    mobile_keywords = (
        "android",
        "iphone",
        "ipod",
        "ipad",
        "mobile",
        "windows phone",
        "harmonyos",
        "micromessenger",
    )

    return any(
        keyword in user_agent
        for keyword in mobile_keywords
    )


def inject_desktop_page_style():
    """
    PC端专用样式。
    不使用手机端 fixed / overflow 规则，
    避免不同桌面浏览器出现空白或布局错乱。
    """

    st.markdown(
        """
<style>

/* =========================================================
   PC端 - 小冲AI
   ========================================================= */

@media (min-width: 769px) {

    [data-testid="stAppViewContainer"] .main .block-container {
        max-width: 1080px !important;
        padding-top: 28px !important;
        padding-left: 34px !important;
        padding-right: 34px !important;
        padding-bottom: 110px !important;
    }

    .xiaochong-main-title {
        text-align: center !important;
        font-size: 40px !important;
        line-height: 1.2 !important;
        font-weight: 800 !important;
        color: #111827 !important;
        letter-spacing: -1px !important;
        margin-top: 14px !important;
        margin-bottom: 28px !important;
    }

    .stTabs [data-baseweb="tab-list"] {
        justify-content: center !important;
        gap: 14px !important;
    }

    .stTabs [data-baseweb="tab"] {
        font-size: 16px !important;
        min-height: 46px !important;
        padding-left: 18px !important;
        padding-right: 18px !important;
    }

    div[data-testid="stChatMessage"] {
        max-width: 920px !important;
        margin-left: auto !important;
        margin-right: auto !important;
        border-radius: 18px !important;
    }

    [data-testid="stChatInput"] {
        max-width: 920px !important;
        margin-left: auto !important;
        margin-right: auto !important;
        border-radius: 22px !important;
    }

    section[data-testid="stSidebar"] {
        width: 350px !important;
        min-width: 350px !important;
        max-width: 350px !important;
    }

}

/* 不破坏 Streamlit 关键 DOM，只隐藏普通 footer/menu */
#MainMenu {
    visibility: hidden !important;
}

footer {
    visibility: hidden !important;
    height: 0 !important;
}

</style>
        """,
        unsafe_allow_html=True
    )


def inject_mobile_page_style():
    """
    手机端专用样式。
    只在手机会话中注入，不会影响电脑浏览器。
    """

    st.markdown(
        """
<style>

/* =========================================================
   手机端 - 小冲AI
   ========================================================= */

html, body {
    -webkit-text-size-adjust: 100%;
}

[data-testid="stAppViewContainer"] {
    background: #f7f8fa !important;
}

[data-testid="stAppViewContainer"] .main .block-container {
    max-width: 100% !important;
    padding-top: 8px !important;
    padding-left: 14px !important;
    padding-right: 14px !important;
    padding-bottom: 110px !important;
}

.xiaochong-mobile-brand {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 4px 2px 10px 2px;
    font-size: 17px;
    font-weight: 750;
    color: #111827;
}

.xiaochong-main-title {
    text-align: center !important;
    font-size: 29px !important;
    line-height: 1.25 !important;
    font-weight: 800 !important;
    color: #111827 !important;
    letter-spacing: -0.6px !important;
    margin-top: 18px !important;
    margin-bottom: 20px !important;
}

.stTabs [data-baseweb="tab-list"] {
    width: 100% !important;
    justify-content: stretch !important;
    gap: 0 !important;
    margin-bottom: 12px !important;
}

.stTabs [data-baseweb="tab"] {
    flex: 1 1 50% !important;
    justify-content: center !important;
    min-width: 0 !important;
    padding-left: 4px !important;
    padding-right: 4px !important;
    font-size: 15px !important;
    white-space: nowrap !important;
}

div[data-testid="stChatMessage"] {
    width: 100% !important;
    max-width: 100% !important;
    margin-top: 8px !important;
    margin-bottom: 10px !important;
    padding: 10px 11px !important;
    background: #ffffff !important;
    border: 1px solid #e8ebef !important;
    border-radius: 17px !important;
    box-shadow: none !important;
}

[data-testid="stChatMessageContent"] {
    max-width: 100% !important;
    font-size: 16px !important;
    line-height: 1.72 !important;
}

[data-testid="stChatMessageContent"] p {
    margin-top: 4px !important;
    margin-bottom: 8px !important;
}

[data-testid="stChatInput"] {
    width: 100% !important;
    max-width: 100% !important;
    margin-left: auto !important;
    margin-right: auto !important;
    border-radius: 22px !important;
    border: 1px solid #d7dce3 !important;
    background: #ffffff !important;
    box-shadow: 0 8px 24px rgba(15,23,42,0.08) !important;
}

[data-testid="stChatInput"] textarea {
    font-size: 16px !important;
    line-height: 1.45 !important;
}

/* 手机侧边栏 = 抽屉菜单 */
section[data-testid="stSidebar"] {
    width: min(88vw, 340px) !important;
    min-width: min(88vw, 340px) !important;
    max-width: min(88vw, 340px) !important;
    background: #ffffff !important;
}

section[data-testid="stSidebar"] > div {
    padding: 14px 14px 24px 14px !important;
}

section[data-testid="stSidebar"] .ai-logo {
    font-size: 27px !important;
    margin-bottom: 2px !important;
}

section[data-testid="stSidebar"] .ai-subtitle {
    font-size: 13px !important;
    margin-bottom: 12px !important;
}

section[data-testid="stSidebar"] .stButton > button {
    min-height: 42px !important;
    border-radius: 12px !important;
}

section[data-testid="stSidebar"] input {
    font-size: 16px !important;
}

/* 按钮更适合触控 */
.stButton > button,
.stDownloadButton > button {
    min-height: 42px !important;
    font-size: 15px !important;
}

/* Streamlit 普通底部 footer 隐藏 */
#MainMenu {
    visibility: hidden !important;
}

footer {
    visibility: hidden !important;
    height: 0 !important;
}

/* 不再强行隐藏/修改 stBottom、stDecoration 等内部关键DOM，
   避免不同浏览器渲染不一致 */

</style>
        """,
        unsafe_allow_html=True
    )



def desktop_sidebar(kb_files: list[str], store):

    with st.sidebar:

        # =====================================================
        # 1. 品牌
        # =====================================================
        st.markdown(
            """
            <div class="ai-logo">
                🤖 小冲AI
            </div>

            <div class="ai-subtitle">
                企业智能办公助手
            </div>
            """,
            unsafe_allow_html=True
        )

        # =====================================================
        # 2. 登录状态
        # 不登录也可以直接使用小冲AI
        # 登录后才保存个人历史会话
        # =====================================================
        is_logged_in = st.session_state.get(
            "auth_logged_in",
            False
        )

        if is_logged_in:

            display_name = (
                st.session_state.get(
                    "auth_display_name"
                )
                or st.session_state.get(
                    "auth_username"
                )
                or "用户"
            )

            st.success(
                f"👤 已登录：{display_name}"
            )

            if st.button(
                "退出登录",
                width="stretch",
                key="account_logout"
            ):

                logout_current_account()
                st.rerun()

        else:

            st.caption(
                "👤 当前：游客模式"
            )

            st.caption(
                "不登录也可以直接使用小冲AI；登录后可保存自己的历史会话。"
            )

            with st.expander(
                "🔐 登录 / 注册账号",
                expanded=False
            ):

                login_tab, register_tab = st.tabs(
                    [
                        "登录",
                        "注册"
                    ]
                )

                # ---------------------------------------------
                # 登录
                # ---------------------------------------------
                with login_tab:

                    login_username = st.text_input(
                        "账号",
                        key="sidebar_login_username",
                        placeholder="请输入账号"
                    )

                    login_password = st.text_input(
                        "密码",
                        type="password",
                        key="sidebar_login_password",
                        placeholder="请输入密码"
                    )

                    if st.button(
                        "登录",
                        type="primary",
                        width="stretch",
                        key="sidebar_login_button"
                    ):

                        if not login_username.strip():

                            st.warning(
                                "请输入账号。"
                            )

                        elif not login_password:

                            st.warning(
                                "请输入密码。"
                            )

                        else:

                            ok, user = authenticate_account(
                                login_username,
                                login_password
                            )

                            if ok and user:

                                st.session_state[
                                    "auth_logged_in"
                                ] = True

                                st.session_state[
                                    "auth_username"
                                ] = _normalize_username(
                                    login_username
                                )

                                st.session_state[
                                    "auth_display_name"
                                ] = (
                                    user.get("username")
                                    or login_username.strip()
                                )

                                # 登录时清理游客临时会话，
                                # 防止游客内容混入用户账号
                                _reset_user_workspace()

                                st.rerun()

                            else:

                                st.error(
                                    "账号不存在、密码错误，或该账号已被管理员禁用。"
                                )

                # ---------------------------------------------
                # 注册
                # ---------------------------------------------
                with register_tab:

                    register_username = st.text_input(
                        "创建账号",
                        key="sidebar_register_username",
                        placeholder="例如：zhangsan 或 张三"
                    )

                    register_password = st.text_input(
                        "设置密码",
                        type="password",
                        key="sidebar_register_password",
                        placeholder="至少6位"
                    )

                    register_confirm = st.text_input(
                        "确认密码",
                        type="password",
                        key="sidebar_register_confirm",
                        placeholder="再次输入密码"
                    )

                    if st.button(
                        "注册账号",
                        type="primary",
                        width="stretch",
                        key="sidebar_register_button"
                    ):

                        if not register_username.strip():

                            st.warning(
                                "请先输入要注册的账号。"
                            )

                            ok = False
                            message = ""

                        elif not register_password:

                            st.warning(
                                "请先设置密码。"
                            )

                            ok = False
                            message = ""

                        else:

                            ok, message = register_account(
                                register_username,
                                register_password,
                                register_confirm
                            )

                        if ok:

                            st.success(
                                message
                            )

                            st.caption(
                                "注册完成后切换到“登录”页即可登录。"
                            )

                        elif message:

                            st.warning(
                                message
                            )

        st.divider()

        # =====================================================
        # 3. 使用身份
        # =====================================================
        st.markdown(
            "### 👤 使用身份"
        )

        role = st.radio(
            "",
            [
                "普通员工",
                "HR管理员"
            ],
            index=(
                0
                if st.session_state.role == "普通员工"
                else 1
            ),
            key="role_select",
            label_visibility="collapsed"
        )

        if role != st.session_state.role:

            st.session_state.role = role
            st.rerun()

        # =====================================================
        # 4. HR管理员验证
        # HR管理端仍需要管理员密码
        # =====================================================
        if st.session_state.role == "HR管理员":

            if not st.session_state.hr_authenticated:

                password = st.text_input(
                    "管理员密码",
                    type="password",
                    placeholder="请输入管理员密码",
                    key="hr_password"
                )

                if st.button(
                    "进入管理端",
                    width="stretch",
                    key="hr_login"
                ):

                    if password == settings.hr_password:

                        st.session_state[
                            "hr_authenticated"
                        ] = True

                        st.rerun()

                    else:

                        st.error(
                            "密码错误，请重新输入。"
                        )

            else:

                st.success(
                    "✓ HR管理员已验证"
                )

                if st.button(
                    "退出HR管理端",
                    width="stretch",
                    key="hr_logout"
                ):

                    st.session_state[
                        "hr_authenticated"
                    ] = False

                    st.session_state[
                        "role"
                    ] = "普通员工"

                    st.rerun()

        st.divider()

        # =====================================================
        # 5. 新建会话
        # =====================================================
        if st.button(
            "＋ 新建会话",
            width="stretch",
            key="new_chat"
        ):

            # 登录用户先保存当前会话
            try:

                if (
                    st.session_state.role == "普通员工"
                    and st.session_state.get(
                        "auth_logged_in",
                        False
                    )
                ):

                    save_conversation(
                        st.session_state.get(
                            "messages_employee",
                            []
                        ),
                        st.session_state.get(
                            "current_chat_id"
                        )
                    )

            except Exception as e:

                print(
                    "保存当前会话失败：",
                    e
                )

            if st.session_state.role == "普通员工":

                st.session_state[
                    "current_chat_id"
                ] = None

                st.session_state[
                    "messages_employee"
                ] = [
                    {
                        "role": "assistant",
                        "content":
                            "你好，我是小冲AI助手 👋\n\n"
                            "你可以直接问我公司制度问题，"
                            "也可以上传图片、PDF、Word等资料让我分析。"
                    }
                ]

                st.session_state[
                    "office_intent"
                ] = None

                st.session_state[
                    "agent_state"
                ] = {
                    "current_intent": None,
                    "slots": {},
                    "waiting_for": []
                }

            else:

                st.session_state[
                    "messages_hr"
                ] = [
                    {
                        "role": "assistant",
                        "content":
                            "你好，这里是HR管理端，可以查看制度信息、知识库状态和员工反馈。"
                    }
                ]

            st.rerun()

        # =====================================================
        # 6. 历史会话
        # 游客模式不做持久化，登录后显示个人历史
        # =====================================================
        if st.session_state.role == "普通员工":

            st.write("")

            if st.session_state.get(
                "auth_logged_in",
                False
            ):

                search_text = st.text_input(
                    "搜索历史会话",
                    placeholder="🔍 搜索历史会话",
                    label_visibility="collapsed",
                    key="chat_history_search"
                )

                st.markdown(
                    "#### 最近会话"
                )

                history_list = list_conversations(
                    search_text=search_text,
                    limit=30
                )

                with st.container(
                    height=300,
                    border=False
                ):

                    if not history_list:

                        st.caption(
                            "暂无历史会话"
                        )

                    for item in history_list:

                        chat_id = item.get(
                            "id"
                        )

                        title = item.get(
                            "title",
                            "新会话"
                        )

                        is_current = (
                            chat_id
                            == st.session_state.get(
                                "current_chat_id"
                            )
                        )

                        button_title = (
                            f"● {title}"
                            if is_current
                            else title
                        )

                        if st.button(
                            button_title,
                            key=f"history_{chat_id}",
                            width="stretch"
                        ):

                            old_messages = (
                                load_conversation(
                                    chat_id
                                )
                            )

                            if old_messages is not None:

                                st.session_state[
                                    "messages_employee"
                                ] = old_messages

                                st.session_state[
                                    "current_chat_id"
                                ] = chat_id

                                st.session_state[
                                    "office_intent"
                                ] = None

                                st.session_state[
                                    "agent_state"
                                ] = {
                                    "current_intent": None,
                                    "slots": {},
                                    "waiting_for": []
                                }

                            st.rerun()

            else:

                st.info(
                    "游客可以正常聊天、上传图片和文件。登录后可保存并查看自己的历史会话。"
                )



def mobile_sidebar(kb_files: list[str], store):
    """
    手机端抽屉菜单：
    账号、身份、新建会话、历史会话都放在这里。
    """

    with st.sidebar:

        st.markdown(
            """
            <div class="ai-logo">
                🤖 小冲AI
            </div>
            <div class="ai-subtitle">
                企业智能办公助手
            </div>
            """,
            unsafe_allow_html=True
        )

        # =====================================================
        # 账号区域
        # =====================================================
        is_logged_in = st.session_state.get(
            "auth_logged_in",
            False
        )

        if is_logged_in:

            display_name = (
                st.session_state.get(
                    "auth_display_name"
                )
                or st.session_state.get(
                    "auth_username"
                )
                or "用户"
            )

            st.success(
                f"👤 {display_name}"
            )

            if st.button(
                "退出登录",
                width="stretch",
                key="mobile_account_logout"
            ):
                logout_current_account()
                st.rerun()

        else:

            st.caption(
                "当前：游客模式"
            )

            with st.expander(
                "🔐 登录 / 注册",
                expanded=False
            ):

                login_tab, register_tab = st.tabs(
                    ["登录", "注册"]
                )

                with login_tab:

                    login_username = st.text_input(
                        "账号",
                        key="mobile_login_username",
                        placeholder="请输入账号"
                    )

                    login_password = st.text_input(
                        "密码",
                        type="password",
                        key="mobile_login_password",
                        placeholder="请输入密码"
                    )

                    if st.button(
                        "登录",
                        type="primary",
                        width="stretch",
                        key="mobile_login_button"
                    ):

                        if not login_username.strip():

                            st.warning(
                                "请输入账号。"
                            )

                        elif not login_password:

                            st.warning(
                                "请输入密码。"
                            )

                        else:

                            ok, user = authenticate_account(
                                login_username,
                                login_password
                            )

                            if ok and user:

                                st.session_state[
                                    "auth_logged_in"
                                ] = True

                                st.session_state[
                                    "auth_username"
                                ] = _normalize_username(
                                    login_username
                                )

                                st.session_state[
                                    "auth_display_name"
                                ] = (
                                    user.get("username")
                                    or login_username.strip()
                                )

                                _reset_user_workspace()
                                st.rerun()

                            else:

                                st.error(
                                    "账号不存在、密码错误，或账号已被禁用。"
                                )

                with register_tab:

                    register_username = st.text_input(
                        "创建账号",
                        key="mobile_register_username",
                        placeholder="账号"
                    )

                    register_password = st.text_input(
                        "设置密码",
                        type="password",
                        key="mobile_register_password",
                        placeholder="至少6位"
                    )

                    register_confirm = st.text_input(
                        "确认密码",
                        type="password",
                        key="mobile_register_confirm",
                        placeholder="再次输入密码"
                    )

                    if st.button(
                        "注册账号",
                        type="primary",
                        width="stretch",
                        key="mobile_register_button"
                    ):

                        ok, message = register_account(
                            register_username,
                            register_password,
                            register_confirm
                        )

                        if ok:
                            st.success(message)
                        else:
                            st.warning(message)

        st.divider()

        # =====================================================
        # 身份
        # =====================================================
        st.markdown("#### 使用身份")

        role = st.radio(
            "",
            ["普通员工", "HR管理员"],
            index=(
                0
                if st.session_state.role == "普通员工"
                else 1
            ),
            key="mobile_role_select",
            label_visibility="collapsed"
        )

        if role != st.session_state.role:
            st.session_state.role = role
            st.rerun()

        if st.session_state.role == "HR管理员":

            if not st.session_state.hr_authenticated:

                password = st.text_input(
                    "管理员密码",
                    type="password",
                    key="mobile_hr_password"
                )

                if st.button(
                    "进入HR管理端",
                    width="stretch",
                    key="mobile_hr_login"
                ):

                    if password == settings.hr_password:

                        st.session_state[
                            "hr_authenticated"
                        ] = True

                        st.rerun()

                    else:

                        st.error("密码错误。")

            else:

                st.success("HR管理员已验证")

        st.divider()

        # =====================================================
        # 新建会话
        # =====================================================
        if st.button(
            "＋ 新建会话",
            width="stretch",
            key="mobile_new_chat"
        ):

            try:

                if (
                    st.session_state.role == "普通员工"
                    and st.session_state.get(
                        "auth_logged_in",
                        False
                    )
                ):

                    save_conversation(
                        st.session_state.get(
                            "messages_employee",
                            []
                        ),
                        st.session_state.get(
                            "current_chat_id"
                        )
                    )

            except Exception as e:
                print("保存当前会话失败：", e)

            if st.session_state.role == "普通员工":

                st.session_state[
                    "current_chat_id"
                ] = None

                st.session_state[
                    "messages_employee"
                ] = [
                    {
                        "role": "assistant",
                        "content":
                            "你好，我是小冲AI助手 👋\n\n"
                            "你可以直接问我公司制度问题，"
                            "也可以上传图片、PDF、Word等资料让我分析。"
                    }
                ]

                st.session_state[
                    "office_intent"
                ] = None

                st.session_state[
                    "agent_state"
                ] = {
                    "current_intent": None,
                    "slots": {},
                    "waiting_for": []
                }

            else:

                st.session_state[
                    "messages_hr"
                ] = [
                    {
                        "role": "assistant",
                        "content":
                            "你好，这里是HR管理端。"
                    }
                ]

            st.rerun()

        # =====================================================
        # 历史会话
        # =====================================================
        if (
            st.session_state.role == "普通员工"
            and st.session_state.get(
                "auth_logged_in",
                False
            )
        ):

            with st.expander(
                "🕘 历史会话",
                expanded=False
            ):

                search_text = st.text_input(
                    "搜索历史",
                    placeholder="搜索历史会话",
                    label_visibility="collapsed",
                    key="mobile_history_search"
                )

                history_list = list_conversations(
                    search_text=search_text,
                    limit=20
                )

                if not history_list:
                    st.caption("暂无历史会话")

                for item in history_list:

                    chat_id = item.get("id")
                    title = item.get(
                        "title",
                        "新会话"
                    )

                    if st.button(
                        title,
                        key=f"mobile_history_{chat_id}",
                        width="stretch"
                    ):

                        old_messages = load_conversation(
                            chat_id
                        )

                        if old_messages is not None:

                            st.session_state[
                                "messages_employee"
                            ] = old_messages

                            st.session_state[
                                "current_chat_id"
                            ] = chat_id

                            st.session_state[
                                "office_intent"
                            ] = None

                            st.session_state[
                                "agent_state"
                            ] = {
                                "current_intent": None,
                                "slots": {},
                                "waiting_for": []
                            }

                        st.rerun()


init_session()
inject_chat_style()

# ============================================================
# 自动判断设备
# ============================================================
MOBILE_MODE = is_mobile_device()

if MOBILE_MODE:
    inject_mobile_page_style()
else:
    inject_desktop_page_style()


if not settings.api_key:
    st.error(
        "未检测到 DASHSCOPE_API_KEY。"
        "请检查当前项目或父级目录中的 .env 配置。"
    )
    st.stop()


embedder, store, agent = create_services()
kb_files = get_kb_files()
chunk_count = get_chunk_count(store)
hitl_records = load_hitl_records()
onboarding_records = load_onboarding_records(
    settings.onboarding_log_path
)


# ============================================================
# 两套侧边栏
# ============================================================
if MOBILE_MODE:
    mobile_sidebar(
        kb_files,
        store
    )
else:
    desktop_sidebar(
        kb_files,
        store
    )


# ============================================================
# 普通员工页面
# ============================================================
def render_employee_desktop():

    st.markdown(
        """
        <div class="xiaochong-main-title">
            有什么可以帮助你呢？
        </div>
        """,
        unsafe_allow_html=True
    )

    employee_tab_chat, employee_tab_onboard = st.tabs(
        [
            "💬 综合管理助手",
            "👋 新员工培训"
        ]
    )

    with employee_tab_chat:

        if not store.exists:

            st.warning(
                "知识库尚未初始化，请联系 HR 管理员。"
            )

        else:

            render_chat(
                "messages_employee",
                show_sources=False,
                input_key="employee_chat_input"
            )

    with employee_tab_onboard:
        render_onboarding()


def render_employee_mobile():

    st.markdown(
        """
        <div class="xiaochong-mobile-brand">
            <span>🤖</span>
            <span>小冲AI</span>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        """
        <div class="xiaochong-main-title">
            有什么可以帮助你呢？
        </div>
        """,
        unsafe_allow_html=True
    )

    employee_tab_chat, employee_tab_onboard = st.tabs(
        [
            "💬 综合管理助手",
            "👋 新员工培训"
        ]
    )

    with employee_tab_chat:

        if not store.exists:

            st.warning(
                "知识库尚未初始化，请联系HR管理员。"
            )

        else:

            render_chat(
                "messages_employee",
                show_sources=False,
                input_key="employee_chat_input_mobile"
            )

    with employee_tab_onboard:
        render_onboarding()


# ============================================================
# HR 页面
# ============================================================
def render_hr_page():

    if not st.session_state.hr_authenticated:

        hero(
            "HR 管理中心",
            "这里用于制度问答溯源、知识库维护与人工审核。"
            "请先在左侧完成管理员验证。",
            admin=True,
        )

        st.info(
            "🔐 请在左侧输入 HR 管理员密码后进入管理端。"
        )

        return

    hero(
        "HR 管理中心",
        "统一查看制度问答依据、知识库状态与需要人工确认的员工问题。",
        admin=True,
    )

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.metric(
            "知识文件",
            len(kb_files),
            "个"
        )

    with c2:
        st.metric(
            "知识切块",
            chunk_count,
            "条"
        )

    with c3:
        st.metric(
            "HITL 记录",
            len(hitl_records),
            "条"
        )

    with c4:
        st.metric(
            "新人培训完成",
            len(onboarding_records),
            "人"
        )

    st.write("")

    (
        tab_chat,
        tab_kb,
        tab_onboarding,
        tab_hitl,
        tab_ai,
        tab_users
    ) = st.tabs(
        [
            "💬 智能问答",
            "📚 知识库管理",
            "👋 新员工培训",
            "🧑‍💼 人工审核",
            "📊 AI运营优化",
            "👥 用户管理"
        ]
    )

    with tab_chat:

        st.markdown(
            '<div class="section-title">HR 制度问答</div>',
            unsafe_allow_html=True
        )

        st.markdown(
            '<div class="section-subtitle">'
            '回答下方可展开查看原始制度依据和相关度，'
            '员工端不会展示这些信息。'
            '</div>',
            unsafe_allow_html=True
        )

        if not store.exists:

            st.warning(
                "尚未建立知识库索引。"
            )

        else:

            render_chat(
                "messages_hr",
                show_sources=True,
                input_key=(
                    "hr_chat_input_mobile"
                    if MOBILE_MODE
                    else "hr_chat_input"
                )
            )

    with tab_kb:

        st.markdown(
            '<div class="section-title">知识库管理</div>',
            unsafe_allow_html=True
        )

        st.markdown(
            '<div class="section-subtitle">'
            '查看当前制度文件和已建立的知识切块。'
            '</div>',
            unsafe_allow_html=True
        )

        fcol, scol = st.columns(
            [1, 1.6],
            gap="large"
        )

        with fcol:

            st.markdown(
                "#### 📁 当前知识文件"
            )

            if not kb_files:

                st.info(
                    "knowledge_base 目录中暂无支持的文件。"
                )

            else:

                for name in kb_files:

                    with st.container(
                        border=True
                    ):

                        st.markdown(
                            f"📄 **{name}**"
                        )

                        st.caption(
                            "已纳入知识库扫描范围"
                        )

        with scol:

            st.markdown(
                "#### 🧩 知识切块预览"
            )

            if store.exists:

                try:

                    store.load()

                    for item in store.metadata[:8]:

                        title = (
                            f"{item.get('source', '未知文件')} · "
                            f"{item.get('heading') or '未标注章节'}"
                        )

                        with st.expander(
                            title
                        ):

                            st.caption(
                                f"Chunk ID：{item.get('id', '-')}"
                            )

                            st.write(
                                item.get(
                                    "text",
                                    ""
                                )
                            )

                except Exception as e:

                    st.error(
                        f"索引读取失败：{e}"
                    )

            else:

                st.info(
                    "当前还没有可预览的知识切块。"
                )

    with tab_onboarding:

        st.markdown(
            '<div class="section-title">新员工培训管理</div>',
            unsafe_allow_html=True
        )

        record_tab, map_tab = st.tabs(
            [
                "📋 培训完成记录",
                "🗺️ 办公地图与位置配置"
            ]
        )

        with record_tab:

            if not onboarding_records:

                st.info(
                    "暂时还没有新员工完成培训。"
                )

            else:

                rows = []

                for item in onboarding_records:

                    rows.append(
                        {
                            "姓名": item.get("name", "-"),
                            "部门": item.get("department", "-"),
                            "岗位": item.get("position", "-"),
                            "入职日期": item.get("start_date", "-"),
                            "工作分析":
                                "✅"
                                if item.get("work_analysis_completed")
                                else "—",
                            "办公地图":
                                "✅"
                                if item.get("office_map_completed")
                                else "—",
                            "考勤制度":
                                "✅"
                                if item.get("attendance_completed")
                                else "—",
                            "状态": item.get("status", "-"),
                            "完成时间": item.get("submitted_at", "-"),
                        }
                    )

                st.dataframe(
                    rows,
                    width="stretch",
                    hide_index=True
                )

        with map_tab:
            render_company_location_admin()

    with tab_hitl:

        st.markdown(
            '<div class="section-title">人工审核队列</div>',
            unsafe_allow_html=True
        )

        if not hitl_records:

            st.success(
                "🎉 当前没有待人工确认的记录。"
            )

        else:

            for idx, item in enumerate(
                hitl_records,
                start=1
            ):

                with st.container(
                    border=True
                ):

                    st.markdown(
                        f"**#{idx}  {item.get('question', '-')}**"
                    )

                    st.caption(
                        f"提交时间：{item.get('time', '-')}"
                    )

                    st.write(
                        f"**触发原因：** {item.get('reason', '-')}"
                    )

                    st.caption(
                        f"当前状态：{item.get('status', 'pending')}"
                    )

    with tab_ai:

        render_ai_operation_center()

    with tab_users:

        render_user_admin()


# ============================================================
# 页面路由
# ============================================================
if st.session_state.role == "普通员工":

    if MOBILE_MODE:
        render_employee_mobile()
    else:
        render_employee_desktop()

else:

    render_hr_page()
