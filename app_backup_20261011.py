from __future__ import annotations

import sys
import json
from pathlib import Path
from datetime import datetime
from pyexpat.errors import messages
from unittest import result
import base64
import mimetypes

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
        "status": status
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
        "source_count": len(sources or [])
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
    st.session_state.setdefault("role", "普通员工")
    st.session_state.setdefault("hr_authenticated", False)
    st.session_state.setdefault("pending_employee_question", None)
    st.session_state.setdefault("pending_hr_question", None)
    st.session_state.setdefault("office_intent",None)
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

def render_chat(
    messages_key,
    show_sources=False,
    input_key="chat_input",
    pending_key=None
):

    # ============================================================
    # 0. 获取当前聊天记录
    # ============================================================

    messages = st.session_state[messages_key]


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

            attachments = message.get(
                "attachments",
                []
            )

            for attachment in attachments:

                if (
                    attachment.get("kind")
                    == "image"
                ):

                    image_data = attachment.get(
                        "data"
                    )

                    if image_data:

                        st.image(
                            image_data,
                            caption=attachment.get(
                                "name",
                                "图片"
                            ),
                            width="stretch"
                        )

                else:

                    st.caption(
                        "📎 "
                        + attachment.get(
                            "name",
                            "附件"
                        )
                    )


            # ----------------------------------------------------
            # 显示消息正文
            # ----------------------------------------------------

            content = message.get(
                "content",
                ""
            )

            if content:

                st.markdown(
                    content
                )


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
            ):

                st.divider()

                feedback_status = (
                    message.get(
                        "feedback"
                    )
                )


                # 已评价：正确
                if (
                    feedback_status
                    == "success"
                ):

                    st.success(
                        "👍 已评价"
                    )


                # 已评价：不正确
                elif (
                    feedback_status
                    == "failed"
                ):

                    st.warning(
                        "👎 已评价，已提交给HR优化。"
                    )


                # 尚未评价
                else:

                    st.write(
                        "这个回答是否解决了您的问题？"
                    )

                    col1, col2 = (
                        st.columns(2)
                    )


                    # ============================================
                    # 回答正确
                    # ============================================

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
                                message[
                                    "question"
                                ],
                                message[
                                    "content"
                                ],
                                "success"
                            )

                            message[
                                "feedback"
                            ] = "success"

                            st.rerun()


                    # ============================================
                    # 回答不正确
                    # ============================================

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
                                message[
                                    "question"
                                ],
                                message[
                                    "content"
                                ],
                                "failed"
                            )

                            message[
                                "feedback"
                            ] = "failed"

                            st.rerun()



    # ============================================================
    # 2. 智能办公 Word 生成区域
    #
    # 上一轮识别到：
    # 请假申请
    # 加班申请
    # 面试邀请
    # 入职通知
    # 在职证明
    # 培训通知
    # 会议纪要
    #
    # 就在聊天区域显示表单
    # ============================================================

    current_office_intent = (
        st.session_state.get(
            "office_intent"
        )
    )


    if (
        messages_key == "messages_employee"
        and current_office_intent
        and current_office_intent
        != "hr_monthly_report"
    ):

        document_name = (
            DISPLAY_NAMES.get(
                current_office_intent,
                "办公文档"
            )
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

        pending_question = (
            st.session_state.get(
                pending_key
            )
        )

    elif (
        messages_key
        == "messages_employee"
    ):

        pending_question = (
            st.session_state.get(
                "pending_employee_question"
            )
        )

    else:

        pending_question = None



    # ============================================================
    # 4. ChatGPT 风格聊天输入框
    #
    # 左边 + 可上传：
    #
    # 图片
    # PDF
    # Word
    # TXT
    # Markdown
    # ============================================================

    prompt = st.chat_input(

        "发消息或按 + 添加文件/图片……",

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

        # --------------------------------------------------------
        # 兼容普通字符串
        # --------------------------------------------------------

        if isinstance(
            prompt,
            str
        ):

            typed_question = (
                prompt.strip()
            )


        # --------------------------------------------------------
        # Streamlit 新版 ChatInputValue
        # --------------------------------------------------------

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


    # 没有文字
    # 也没有上传文件
    if (
        not question
        and not uploaded_files
    ):

        return



    # ============================================================
    # 7. 清除快捷问题
    # ============================================================

    if pending_key:

        st.session_state[
            pending_key
        ] = None


    elif (
        messages_key
        == "messages_employee"
    ):

        st.session_state[
            "pending_employee_question"
        ] = None



    # ============================================================
    # 8. 处理上传附件
    # ============================================================

    attachments = []


    # 一次最多5个附件
    uploaded_files = (
        uploaded_files[:5]
    )


    for file in uploaded_files:

        try:

            file_bytes = (
                file.getvalue()
            )

        except Exception:

            continue


        # --------------------------------------------------------
        # 单个附件最大10MB
        # --------------------------------------------------------

        if (
            len(file_bytes)
            > 10 * 1024 * 1024
        ):

            st.warning(
                f"{file.name} 超过10MB，已跳过。"
            )

            continue


        attachments.append(
            {
                "name":
                    file.name,

                "type":
                    getattr(
                        file,
                        "type",
                        ""
                    ),

                "data":
                    file_bytes,

                "kind":
                    (
                        "image"
                        if is_image_file(
                            file.name
                        )
                        else "file"
                    )
            }
        )



    # ============================================================
    # 9. 如果只上传文件，没有输入文字
    # ============================================================

    if (
        not question
        and attachments
    ):

        question = (
            "请帮我识别并分析这个附件。"
        )



    # ============================================================
    # 10. 构建聊天历史
    #
    # 注意：
    # 当前问题还没有加入 messages
    # 所以这里都是之前的聊天
    # ============================================================

    history = []


    for item in messages[-10:]:

        role = item.get(
            "role"
        )

        history_content = (
            item.get(
                "content",
                ""
            )
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
                    "role":
                        role,

                    "content":
                        history_content
                }
            )



    # ============================================================
    # 11. 保存当前用户消息
    # ============================================================

    messages.append(
        {
            "role":
                "user",

            "content":
                question,

            "attachments":
                attachments
        }
    )



    # ============================================================
    # 12. 分类附件
    # ============================================================

    image_attachments = [

        item

        for item in attachments

        if (
            item.get("kind")
            == "image"
        )
    ]


    document_attachments = [

        item

        for item in attachments

        if (
            item.get("kind")
            == "file"
        )
    ]



    # ============================================================
    # 13. 初始化AI回答
    # ============================================================

    answer = ""

    sources = []



    # ============================================================
    # 14. AI处理
    # ============================================================

    with st.spinner(
        "小冲AI正在思考..."
    ):


        # ========================================================
        # A. 用户上传了附件
        # ========================================================

        if attachments:

            # 上传附件时
            # 关闭上一个办公文档表单

            if (
                messages_key
                == "messages_employee"
            ):

                st.session_state[
                    "office_intent"
                ] = None


            # ====================================================
            # A1. 图片识别
            # ====================================================

            image_results = []


            for attachment in (
                image_attachments
            ):

                try:

                    image_answer = (
                        analyze_image_with_qwen(

                            attachment[
                                "name"
                            ],

                            attachment[
                                "data"
                            ],

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



            # ====================================================
            # A2. PDF / Word / TXT / MD
            # ====================================================

            document_results = []


            for attachment in (
                document_attachments
            ):

                try:

                    extracted_text = (
                        extract_uploaded_file_text(

                            attachment[
                                "name"
                            ],

                            attachment[
                                "data"
                            ]
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



            # ====================================================
            # A3. 同时存在文件
            #
            # 文件内容交给原来的 agent
            # 同时可以把图片识别结果作为背景信息
            # ====================================================

            if document_results:

                image_context = (
                    "\n\n".join(
                        image_results
                    )
                )


                document_context = (
                    "\n\n".join(
                        document_results
                    )
                )


                # 防止上传内容太多
                document_context = (
                    document_context[
                        :50000
                    ]
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
                )

                sources = (
                    result.sources
                )



            # ====================================================
            # A4. 只有图片
            # ====================================================

            elif image_results:

                answer = "\n\n".join(
                    image_results
                )

                sources = []



            # ====================================================
            # A5. 附件读取失败
            # ====================================================

            else:

                answer = (
                    "没有从上传的附件中读取到有效内容。"
                )

                sources = []



        # ========================================================
        # B. 普通文字聊天
        # ========================================================

        else:

            office_intent = None


            # ----------------------------------------------------
            # 员工端：
            # 先判断是不是智能办公任务
            # ----------------------------------------------------

            if (
                messages_key
                == "messages_employee"
            ):

                office_intent = (
                    detect_office_intent(
                        question
                    )
                )



            # ====================================================
            # B1. 智能办公任务
            # ====================================================

            if office_intent:

                st.session_state[
                    "office_intent"
                ] = office_intent


                # ------------------------------------------------
                # HR月度运营报告
                # ------------------------------------------------

                if (
                    office_intent
                    == "hr_monthly_report"
                ):

                    answer = (
                        "好的，我已经识别到您需要生成"
                        "《HR月度运营报告》。\n\n"
                        "该报告需要读取HR运营数据，"
                        "请进入HR管理端的"
                        "“AI运营”页面生成。"
                    )



                # ------------------------------------------------
                # 其他办公Word
                # ------------------------------------------------

                else:

                    document_name = (
                        DISPLAY_NAMES.get(
                            office_intent,
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



            # ====================================================
            # B2. 普通制度问答
            # ====================================================

            else:

                # 如果上一轮打开过Word表单
                # 现在用户改问普通问题
                # 自动关闭表单

                if (
                    messages_key
                    == "messages_employee"
                ):

                    st.session_state[
                        "office_intent"
                    ] = None


                result = agent.ask(
                    question,
                    history
                )


                answer = (
                    result.answer
                )


                sources = (
                    result.sources
                )



    # ============================================================
    # 15. 保存AI回答
    #
    # 注意：
    # 这里必须使用 answer / sources
    #
    # 不要写 result.answer
    # ============================================================

    messages.append(
        {
            "role":
                "assistant",

            "content":
                answer,

            "sources":
                sources,

            "question":
                question,

            "feedback":
                None
        }
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

def sidebar(kb_files:list[str],store):


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

        if st.button(
            "＋ 新建会话",
            width="stretch"
        ):


            if st.session_state.role=="普通员工":

                st.session_state[
                    "messages_employee"
                ]=[]


            else:

                st.session_state[
                    "messages_hr"
                ]=[]


            st.rerun()



        st.text_input(

            "搜索会话",

            placeholder="搜索历史会话",

            label_visibility="collapsed"

        )



        st.divider()



        st.markdown(
            "### 👤 使用身份"
        )



        role=st.radio(

            "",

            [
                "普通员工",
                "HR管理员"
            ],

            index=
            0
            if st.session_state.role=="普通员工"
            else
            1

        )



        if role != st.session_state.role:

            st.session_state.role=role

            st.rerun()



        if (
            st.session_state.role
            =="HR管理员"
        ):


            if not st.session_state.hr_authenticated:


                password=st.text_input(

                    "管理员密码",

                    type="password"

                )


                if st.button(
                    "进入管理端",
                    width="stretch"
                ):


                    if password==settings.hr_password:

                        st.session_state.hr_authenticated=True

                        st.rerun()

                    else:

                        st.error(
                            "密码错误"
                        )


            else:


                st.success(
                    "HR已登录"
                )


        st.divider()
init_session()
inject_chat_style()
if not settings.api_key:
    st.error("未检测到 DASHSCOPE_API_KEY。请检查当前项目或父级目录中的 .env 配置。")
    st.stop()

embedder, store, agent = create_services()
kb_files = get_kb_files()
chunk_count = get_chunk_count(store)
hitl_records = load_hitl_records()
onboarding_records = load_onboarding_records(settings.onboarding_log_path)
sidebar(kb_files, store)


if st.session_state.role == "普通员工":

    st.markdown(
        """
        <div style="
            text-align:center;
            margin-top:10px;
            margin-bottom:26px;
            font-size:38px;
            font-weight:800;
            color:#111827;
            letter-spacing:-1px;
        ">
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
            st.warning("知识库尚未初始化，请联系 HR 管理员。")

        else:
            render_chat(
                "messages_employee",
                show_sources=False,
                input_key="employee_chat_input"
            )

    with employee_tab_onboard:
        render_onboarding()
else:
    if not st.session_state.hr_authenticated:
        hero(
            "HR 管理中心",
            "这里用于制度问答溯源、知识库维护与人工审核。请先在左侧完成管理员验证。",
            admin=True,
        )
        st.info("🔐 请在左侧输入 HR 管理员密码后进入管理端。")
        st.stop()

    hero(
        "HR 管理中心",
        "统一查看制度问答依据、知识库状态与需要人工确认的员工问题，让智能问答结果可追溯、可管理。",
        admin=True,
    )
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("知识文件", len(kb_files), "个")
    with c2:
        st.metric("知识切块", chunk_count, "条")
    with c3:
        st.metric("HITL 记录", len(hitl_records), "条")
    with c4:
        st.metric("新人培训完成", len(onboarding_records), "人")

    st.write("")
    tab_chat, tab_kb, tab_onboarding, tab_hitl, tab_ai = st.tabs(
        ["💬 智能问答", "📚 知识库管理", "👋 新员工培训", "🧑‍💼 人工审核", "📊 AI运营优化"]
    )

    with tab_chat:
        st.markdown('<div class="section-title">HR 制度问答</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-subtitle">回答下方可展开查看原始制度依据和相关度，员工端不会展示这些信息。</div>', unsafe_allow_html=True)
        if not store.exists:
            st.warning("尚未建立知识库索引，请先在左侧点击“重建知识库索引”。")
        else:
            render_chat(
                "messages_hr",
                show_sources=True,
                input_key="hr_chat_input",
             
            )

    with tab_kb:
        st.markdown('<div class="section-title">知识库管理</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-subtitle">查看当前制度文件和已建立的知识切块。新增文件后请重新建立索引。</div>', unsafe_allow_html=True)
        fcol, scol = st.columns([1, 1.6], gap="large")
        with fcol:
            st.markdown("#### 📁 当前知识文件")
            if not kb_files:
                st.info("knowledge_base 目录中暂无支持的文件。")
            else:
                for name in kb_files:
                    with st.container(border=True):
                        st.markdown(f"📄 **{name}**")
                        st.caption("已纳入知识库扫描范围")
        with scol:
            st.markdown("#### 🧩 知识切块预览")
            if store.exists:
                try:
                    store.load()
                    for item in store.metadata[:8]:
                        title = f"{item.get('source', '未知文件')} · {item.get('heading') or '未标注章节'}"
                        with st.expander(title):
                            st.caption(f"Chunk ID：{item.get('id', '-')}")
                            st.write(item.get("text", ""))
                except Exception as e:
                    st.error(f"索引读取失败：{e}")
            else:
                st.info("当前还没有可预览的知识切块。")

    with tab_onboarding:
        st.markdown('<div class="section-title">新员工培训管理</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-subtitle">培训内容聚焦主要工作分析、公司办公地图和位置、考勤管理制度。</div>', unsafe_allow_html=True)

        record_tab, map_tab = st.tabs(["📋 培训完成记录", "🗺️ 办公地图与位置配置"])

        with record_tab:
            if not onboarding_records:
                st.info("暂时还没有新员工完成培训。")
            else:
                rows = []
                for item in onboarding_records:
                    rows.append({
                        "姓名": item.get("name", "-"),
                        "部门": item.get("department", "-"),
                        "岗位": item.get("position", "-"),
                        "入职日期": item.get("start_date", "-"),
                        "工作分析": "✅" if item.get("work_analysis_completed") else "—",
                        "办公地图": "✅" if item.get("office_map_completed") else "—",
                        "考勤制度": "✅" if item.get("attendance_completed") else "—",
                        "状态": item.get("status", "-"),
                        "完成时间": item.get("submitted_at", "-"),
                    })
                st.dataframe(rows, width="stretch", hide_index=True)

        with map_tab:
            render_company_location_admin()

    with tab_hitl:
        st.markdown('<div class="section-title">人工审核队列</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-subtitle">集中查看薪资、合同、处分等需要 HR 进一步确认的问题。</div>', unsafe_allow_html=True)
        if not hitl_records:
            st.success("🎉 当前没有待人工确认的记录。")
        else:
            for idx, item in enumerate(hitl_records, start=1):
                with st.container(border=True):
                    top_a, top_b = st.columns([5, 1])
                    with top_a:
                        st.markdown(f"**#{idx}  {item.get('question', '-')}**")
                        st.caption(f"提交时间：{item.get('time', '-')}")
                    with top_b:
                        st.markdown("**待确认**")
                    st.write(f"**触发原因：** {item.get('reason', '-')}")
                    st.caption(f"当前状态：{item.get('status', 'pending')}")


    with tab_ai:
        render_ai_operation_center()
        feedbacks = load_feedback()

def load_feedback():

    path = Path("data/feedback.jsonl")

    if not path.exists():
        return []

    rows = []

    for line in path.read_text(
        encoding="utf-8"
    ).splitlines():

        if not line.strip():
            continue

        try:
            rows.append(
                json.loads(line)
            )
        except:
            pass

    return rows
