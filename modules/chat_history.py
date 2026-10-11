# -*- coding: utf-8 -*-
"""
小冲AI - 本地聊天历史保存/加载模块

保存内容：
1. data/chat_history.json              会话索引和消息
2. data/chat_attachments/<chat_id>/    上传的图片/文件

特点：
- 支持多会话
- 支持搜索标题
- 支持重新打开旧会话
- 支持消息中的图片/文件附件
- 避免 bytes 直接写 JSON 导致报错
"""

from __future__ import annotations

import json
import re
import shutil
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
HISTORY_FILE = DATA_DIR / "chat_history.json"
ATTACHMENT_DIR = DATA_DIR / "chat_attachments"

DATA_DIR.mkdir(parents=True, exist_ok=True)
ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 基础工具
# ============================================================

def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _new_chat_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _safe_filename(name: str) -> str:
    """
    去掉 Windows 文件名非法字符。
    """
    name = (name or "attachment").strip()
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    return name[:180] or "attachment"


def _read_records() -> list[dict]:
    if not HISTORY_FILE.exists():
        return []

    try:
        data = json.loads(
            HISTORY_FILE.read_text(encoding="utf-8")
        )
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_records(records: list[dict]) -> None:
    """
    原子写入，避免程序中断导致 JSON 损坏。
    """
    temp_file = HISTORY_FILE.with_suffix(".tmp")

    temp_file.write_text(
        json.dumps(
            records,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    temp_file.replace(HISTORY_FILE)


# ============================================================
# 会话标题
# ============================================================

def build_chat_title(messages: list[dict]) -> str:
    """
    使用第一条用户消息作为历史会话标题。
    """
    for message in messages:
        if message.get("role") != "user":
            continue

        text = str(
            message.get("content", "") or ""
        ).strip()

        if not text:
            continue

        text = re.sub(r"\s+", " ", text)

        if len(text) > 22:
            return text[:22] + "..."

        return text

    return "新会话"


# ============================================================
# 附件持久化
# ============================================================

def _serialize_messages(
    chat_id: str,
    messages: list[dict],
) -> list[dict]:
    """
    把 Streamlit session_state 中的消息转成可写 JSON 的结构。

    attachment["data"] 是 bytes，不能直接 JSON 序列化。
    因此这里把附件文件写到 data/chat_attachments/<chat_id>/，
    JSON 中只保存 attachment_path。
    """
    chat_folder = ATTACHMENT_DIR / chat_id
    chat_folder.mkdir(parents=True, exist_ok=True)

    output: list[dict] = []

    for message_index, message in enumerate(messages):
        saved_message = {
            key: deepcopy(value)
            for key, value in message.items()
            if key != "attachments"
        }

        saved_attachments = []

        for attachment_index, attachment in enumerate(
            message.get("attachments", []) or []
        ):
            item = {
                key: deepcopy(value)
                for key, value in attachment.items()
                if key != "data"
            }

            raw_data = attachment.get("data")
            old_path = attachment.get("attachment_path")

            # 当前消息中有原始二进制，写入磁盘
            if isinstance(raw_data, (bytes, bytearray)):
                filename = _safe_filename(
                    attachment.get("name", "attachment")
                )

                disk_name = (
                    f"{message_index:04d}_"
                    f"{attachment_index:03d}_"
                    f"{filename}"
                )

                file_path = chat_folder / disk_name

                try:
                    file_path.write_bytes(bytes(raw_data))
                    item["attachment_path"] = str(
                        file_path.relative_to(BASE_DIR)
                    ).replace("\\", "/")
                except Exception:
                    item["attachment_path"] = None

            # 已加载过的旧会话，沿用附件路径
            elif old_path:
                item["attachment_path"] = old_path

            saved_attachments.append(item)

        if saved_attachments:
            saved_message["attachments"] = saved_attachments

        output.append(saved_message)

    return output


def _deserialize_messages(
    messages: list[dict],
) -> list[dict]:
    """
    从 JSON 恢复消息，并重新读取附件 bytes，
    这样 render_chat() 仍然可以 st.image(attachment["data"])。
    """
    output: list[dict] = []

    for message in messages:
        restored = deepcopy(message)
        attachments = []

        for attachment in restored.get("attachments", []) or []:
            item = deepcopy(attachment)

            relative_path = item.get("attachment_path")

            if relative_path:
                file_path = BASE_DIR / relative_path

                if file_path.exists():
                    try:
                        item["data"] = file_path.read_bytes()
                    except Exception:
                        item["data"] = None

            attachments.append(item)

        if attachments:
            restored["attachments"] = attachments

        output.append(restored)

    return output


# ============================================================
# 保存会话
# ============================================================

def save_conversation(
    messages: list[dict],
    chat_id: str | None = None,
) -> str | None:
    """
    保存或更新一个会话。

    返回：
        chat_id

    如果没有任何用户消息，则不保存，返回 None。
    """
    has_user_message = any(
        item.get("role") == "user"
        for item in messages
    )

    if not has_user_message:
        return chat_id

    if not chat_id:
        chat_id = _new_chat_id()

    records = _read_records()

    serialized_messages = _serialize_messages(
        chat_id,
        messages,
    )

    record = {
        "id": chat_id,
        "title": build_chat_title(messages),
        "updated_at": _now_text(),
        "messages": serialized_messages,
    }

    found = False

    for index, item in enumerate(records):
        if item.get("id") == chat_id:
            records[index] = record
            found = True
            break

    if not found:
        records.insert(0, record)

    # 最近更新的排最前面
    records.sort(
        key=lambda x: x.get("updated_at", ""),
        reverse=True,
    )

    _write_records(records)

    return chat_id


# ============================================================
# 加载某一个会话
# ============================================================

def load_conversation(
    chat_id: str,
) -> list[dict] | None:
    records = _read_records()

    for item in records:
        if item.get("id") == chat_id:
            return _deserialize_messages(
                item.get("messages", []) or []
            )

    return None


# ============================================================
# 会话列表/搜索
# ============================================================

def list_conversations(
    search_text: str = "",
    limit: int = 30,
) -> list[dict]:
    records = _read_records()

    search_text = (
        search_text or ""
    ).strip().lower()

    if search_text:
        records = [
            item
            for item in records
            if search_text
            in str(
                item.get("title", "")
            ).lower()
        ]

    return [
        {
            "id": item.get("id"),
            "title": item.get("title", "新会话"),
            "updated_at": item.get("updated_at", ""),
        }
        for item in records[:limit]
    ]


# ============================================================
# 删除会话
# ============================================================

def delete_conversation(
    chat_id: str,
) -> None:
    records = [
        item
        for item in _read_records()
        if item.get("id") != chat_id
    ]

    _write_records(records)

    folder = ATTACHMENT_DIR / chat_id

    if folder.exists():
        shutil.rmtree(
            folder,
            ignore_errors=True,
        )
