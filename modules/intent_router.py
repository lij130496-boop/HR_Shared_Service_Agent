from __future__ import annotations

INTENT_KEYWORDS = {
    "leave_request": ["请假条", "请假申请", "请假单", "我要请假"],
    "overtime_request": ["加班申请", "加班单", "我要加班"],
    "interview_invitation": ["面试邀请", "面试通知", "邀请面试"],
    "onboarding_notice": ["入职通知", "报到通知", "录用入职"],
    "employment_certificate": ["在职证明", "工作证明"],
    "training_notice": ["培训通知", "培训安排"],
    "meeting_minutes": ["会议纪要", "会议总结", "整理会议"],
    "hr_monthly_report": ["HR月报", "人事月报", "运营报告", "AI运营报告", "月度报告"],
}

DISPLAY_NAMES = {
    "leave_request": "请假申请",
    "overtime_request": "加班申请",
    "interview_invitation": "面试邀请",
    "onboarding_notice": "入职通知",
    "employment_certificate": "在职证明",
    "training_notice": "培训通知",
    "meeting_minutes": "会议纪要",
    "hr_monthly_report": "HR月度运营报告",
}


def detect_office_intent(text: str) -> str | None:
    text = (text or "").strip()
    if not text:
        return None

    for intent, keywords in INTENT_KEYWORDS.items():
        if any(k in text for k in keywords):
            return intent

    return None
