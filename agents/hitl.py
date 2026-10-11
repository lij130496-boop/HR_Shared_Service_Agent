from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


HIGH_RISK_KEYWORDS = {
    "工资", "薪资", "扣工资", "赔偿", "辞退", "开除", "解除劳动合同",
    "劳动仲裁", "仲裁", "违法", "法律", "隐私", "身份证", "处分申诉",
    "社保争议", "工伤",
}


def should_handoff(question: str, top_score: float, min_score: float) -> tuple[bool, str]:
    matched = [k for k in HIGH_RISK_KEYWORDS if k in question]
    if matched:
        return True, f"涉及高风险人事事项：{', '.join(matched[:3])}"
    if top_score < min_score:
        return True, f"RAG检索置信度较低（最高相似度 {top_score:.3f}）"
    return False, ""


def log_handoff(path: Path, question: str, reason: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "question": question,
        "reason": reason,
        "status": "待HR确认",
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
