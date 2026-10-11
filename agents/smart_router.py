# -*- coding: utf-8 -*-

import json
import re

from openai import OpenAI

from config import settings


# ============================================================
# 小冲AI智能路由器
#
# 作用：
# 不再只靠关键词判断用户意图
# 而是让Qwen理解用户真正想做什么
# ============================================================


SUPPORTED_INTENTS = [

    "policy_qa",

    "leave_request",

    "overtime_request",

    "interview_invitation",

    "onboarding_notice",

    "employment_certificate",

    "training_notice",

    "meeting_minutes",

    "hr_monthly_report",

    "image_analysis",

    "document_analysis",

    "general_chat"
]


# ============================================================
# 意图对应工具
# ============================================================

TOOL_MAPPING = {

    "policy_qa":
        "search_policy",

    "leave_request":
        "generate_leave_document",

    "overtime_request":
        "generate_overtime_document",

    "interview_invitation":
        "generate_interview_invitation",

    "onboarding_notice":
        "generate_onboarding_notice",

    "employment_certificate":
        "generate_employment_certificate",

    "training_notice":
        "generate_training_notice",

    "meeting_minutes":
        "generate_meeting_minutes",

    "hr_monthly_report":
        "generate_hr_report",

    "image_analysis":
        "analyze_image",

    "document_analysis":
        "analyze_document",

    "general_chat":
        "chat"
}


# ============================================================
# 清理模型返回的JSON
# ============================================================

def _clean_json_text(text: str) -> str:

    if not text:

        return "{}"


    text = text.strip()


    # 去掉 ```json
    text = re.sub(
        r"^```json\s*",
        "",
        text,
        flags=re.IGNORECASE
    )


    # 去掉 ```
    text = re.sub(
        r"^```\s*",
        "",
        text
    )


    text = re.sub(
        r"\s*```$",
        "",
        text
    )


    # 如果模型前后说了别的话
    # 尝试只提取JSON主体

    start = text.find("{")

    end = text.rfind("}")


    if (
        start >= 0
        and end > start
    ):

        text = text[
            start:end + 1
        ]


    return text


# ============================================================
# 主路由函数
# ============================================================

def route_request(
    question: str,
    history=None,
    current_intent=None,
    has_image=False,
    has_file=False
):

    history = history or []


    # ========================================================
    # 图片、文件优先
    # ========================================================

    if has_image:

        return {
            "intent":
                "image_analysis",

            "confidence":
                1.0,

            "tool":
                "analyze_image",

            "fields":
                {},

            "missing_fields":
                [],

            "reason":
                "用户上传了图片"
        }


    if has_file:

        return {
            "intent":
                "document_analysis",

            "confidence":
                1.0,

            "tool":
                "analyze_document",

            "fields":
                {},

            "missing_fields":
                [],

            "reason":
                "用户上传了文档"
        }


    # ========================================================
    # 最近聊天
    # ========================================================

    history_text = ""


    for item in history[-8:]:

        role = item.get(
            "role",
            ""
        )

        content = item.get(
            "content",
            ""
        )


        history_text += (
            f"{role}: {content}\n"
        )


    # ========================================================
    # Prompt
    # ========================================================

    prompt = f"""
你是“小冲AI”的智能任务路由器。

你的任务不是回答用户问题。

你的任务是判断：

1. 用户真正想做什么
2. 应该调用哪个业务能力
3. 用户已经提供了哪些信息
4. 还缺少哪些必要信息


当前正在进行的任务：

{current_intent or "无"}


最近聊天记录：

{history_text or "无"}


用户最新消息：

{question}


支持的意图只有：

policy_qa
leave_request
overtime_request
interview_invitation
onboarding_notice
employment_certificate
training_notice
meeting_minutes
hr_monthly_report
image_analysis
document_analysis
general_chat


意图说明：

policy_qa：
询问公司考勤、请假、加班、薪资、奖惩、培训、
合同、报销等公司制度。

leave_request：
用户想请假、生成请假申请、办理请假。

overtime_request：
用户想申请加班或生成加班申请。

interview_invitation：
生成面试邀请或面试通知。

onboarding_notice：
生成入职通知、报到通知。

employment_certificate：
生成在职证明、工作证明。

training_notice：
生成培训通知。

meeting_minutes：
整理会议记录、生成会议纪要。

hr_monthly_report：
生成人事月报、HR运营报告。

general_chat：
普通聊天，或者不属于以上业务。


特别注意：

不要只靠关键词。

例如：

“我老婆明天做手术，我想休三天”
应该判断为：

leave_request


“昨天开会说了一堆事情，我发给你帮我整理”
应该判断为：

meeting_minutes


“公司迟到10分钟怎么算”
应该判断为：

policy_qa


如果用户正在继续上一轮任务，例如：

上一轮是 leave_request

用户这次只说：

“改成三天”

仍然应该判断为：

leave_request


对于 leave_request，
尽量从用户话里提取：

name
department
leave_type
start_date
end_date
duration
reason


对于 overtime_request，
尽量提取：

name
department
date
start_time
end_time
reason


必须只返回JSON。

格式：

{{
    "intent": "leave_request",
    "confidence": 0.95,
    "tool": "generate_leave_document",

    "fields": {{
        "name": "",
        "department": "",
        "leave_type": "",
        "start_date": "",
        "end_date": "",
        "duration": "",
        "reason": ""
    }},

    "missing_fields": [],

    "reason": "简短说明为什么这样判断"
}}

不要返回Markdown。
不要解释。
只返回JSON。
""".strip()


    # ========================================================
    # 调用Qwen
    # ========================================================

    try:

        client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url
        )


        response = (
            client.chat.completions.create(

                model=settings.chat_model,

                messages=[
                    {
                        "role":
                            "system",

                        "content":
                            "你是企业AI助手的任务路由器，只负责意图识别和信息提取。"
                    },

                    {
                        "role":
                            "user",

                        "content":
                            prompt
                    }
                ],

                temperature=0
            )
        )


        content = (
            response
            .choices[0]
            .message
            .content
            or "{}"
        )


        content = _clean_json_text(
            content
        )


        result = json.loads(
            content
        )


    except Exception as e:

        print(
            "SmartRouter失败：",
            e
        )


        return {
            "intent":
                "general_chat",

            "confidence":
                0.0,

            "tool":
                "chat",

            "fields":
                {},

            "missing_fields":
                [],

            "reason":
                "路由识别失败，进入普通聊天"
        }


    # ========================================================
    # 安全校验
    # ========================================================

    intent = result.get(
        "intent",
        "general_chat"
    )


    if (
        intent
        not in SUPPORTED_INTENTS
    ):

        intent = "general_chat"


    result["intent"] = intent


    result["tool"] = (
        TOOL_MAPPING.get(
            intent,
            "chat"
        )
    )


    if not isinstance(
        result.get("fields"),
        dict
    ):

        result["fields"] = {}


    if not isinstance(
        result.get(
            "missing_fields"
        ),
        list
    ):

        result[
            "missing_fields"
        ] = []


    return result