
from __future__ import annotations

from dataclasses import dataclass
from openai import OpenAI

from prompts.system_prompt import SYSTEM_PROMPT
from rag.retriever import Retriever
from agents.hitl import should_handoff, log_handoff


@dataclass
class AgentAnswer:
    answer: str
    sources: list[dict]
    handoff: bool
    handoff_reason: str


class PolicyAgent:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        retriever: Retriever,
        min_score: float,
        hitl_log_path,
    ):
        if not api_key:
            raise RuntimeError("未配置 DASHSCOPE_API_KEY。")

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )

        self.model = model
        self.retriever = retriever
        self.min_score = min_score
        self.hitl_log_path = hitl_log_path

    def ask(
        self,
        question: str,
        history: list[dict] | None = None,
    ) -> AgentAnswer:

        results = self.retriever.retrieve(question)
        top_score = results[0]["score"] if results else 0.0

        handoff, reason = should_handoff(
            question,
            top_score,
            self.min_score,
        )

        if handoff:
            log_handoff(
                self.hitl_log_path,
                question,
                reason,
            )

        # 整理 RAG 上下文
        context_parts: list[str] = []

        for i, item in enumerate(results, start=1):
            heading = item.get("heading") or "未标注章节"
            page = item.get("page")
            page_text = f"；页码 {page}" if page else ""

            context_parts.append(
                f"[S{i}] 文件：{item['source']}；"
                f"章节：{heading}{page_text}\n"
                f"{item['text']}"
            )

        context = (
            "\n\n".join(context_parts)
            if context_parts
            else "没有检索到相关制度内容。"
        )

        # 最近几轮对话
        recent_history = ""
        if history:
            for msg in history[-6:]:
                role = "用户" if msg.get("role") == "user" else "助手"
                recent_history += (
                    f"{role}：{msg.get('content', '')}\n"
                )

        prompt = f"""
员工问题：
{question}

最近对话：
{recent_history or "无"}

以下内容是系统后台提供的内部参考资料，只用于帮助你形成答案。
不要向员工提及“检索结果、知识库、来源编号、S1/S2、RAG”等后台信息。

内部参考资料：
{context}

人工介入判断：
{
    "需要人工确认，原因：" + reason
    if handoff
    else "当前无需强制转人工。"
}

请直接以企业人事行政服务助手的身份回答员工问题。
""".strip()

        messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ]

        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.2,
        )

        answer = (
            resp.choices[0].message.content
            or "模型没有返回有效内容。"
        ).strip()

        if handoff:
            # 员工端不暴露 RAG、相似度等后台技术细节。
            if reason.startswith("RAG检索置信度较低"):
                employee_reason = "当前可用的公司资料依据不足"
            else:
                employee_reason = reason
            answer += (
                "\n\n⚠️ **人工确认建议**："
                + employee_reason
                + "。建议由 HR 对最终处理结论进行确认。"
            )

        return AgentAnswer(
            answer=answer,
            sources=results,
            handoff=handoff,
            handoff_reason=reason,
        )
