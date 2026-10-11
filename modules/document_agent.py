from __future__ import annotations

from datetime import date
import streamlit as st

from modules.document_templates import generate_document
from modules.intent_router import DISPLAY_NAMES


def _download(doc_type: str, data: dict):
    docx_bytes, filename = generate_document(doc_type, data)
    st.success("✅ 文档已生成")
    st.download_button(
        "📄 下载 Word 文档",
        data=docx_bytes,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        width="stretch",
    )


def render_document_task(intent: str | None):
    if not intent or intent == "hr_monthly_report":
        return

    st.markdown(f"### 🧠 智能办公 · {DISPLAY_NAMES.get(intent, intent)}")
    st.caption("填写必要信息后，小冲AI会直接生成可下载的 Word 文档。")

    if intent == "leave_request":
        name = st.text_input("姓名 *", key="doc_leave_name")
        department = st.text_input("部门 *", key="doc_leave_department")
        leave_type = st.selectbox("请假类型", ["事假", "病假", "年假", "婚假", "其他"], key="doc_leave_type")
        c1, c2 = st.columns(2)
        with c1:
            start_date = st.date_input("开始日期", value=date.today(), key="doc_leave_start")
        with c2:
            end_date = st.date_input("结束日期", value=date.today(), key="doc_leave_end")
        reason = st.text_area("请假原因 *", key="doc_leave_reason")
        if st.button("生成请假申请", type="primary", width="stretch"):
            if not name.strip() or not department.strip() or not reason.strip():
                st.warning("请填写姓名、部门和请假原因。")
            else:
                _download(intent, {
                    "name": name.strip(), "department": department.strip(), "leave_type": leave_type,
                    "start_date": start_date.isoformat(), "end_date": end_date.isoformat(), "reason": reason.strip()
                })

    elif intent == "overtime_request":
        name = st.text_input("姓名 *", key="doc_ot_name")
        department = st.text_input("部门 *", key="doc_ot_department")
        work_date = st.date_input("加班日期", value=date.today(), key="doc_ot_date")
        hours = st.number_input("预计时长（小时）", 0.5, 24.0, 2.0, 0.5, key="doc_ot_hours")
        reason = st.text_area("加班原因 *", key="doc_ot_reason")
        if st.button("生成加班申请", type="primary", width="stretch"):
            if not name.strip() or not department.strip() or not reason.strip():
                st.warning("请填写姓名、部门和加班原因。")
            else:
                _download(intent, {
                    "name": name.strip(), "department": department.strip(),
                    "work_date": work_date.isoformat(), "hours": f"{hours:g}小时", "reason": reason.strip()
                })

    elif intent == "interview_invitation":
        candidate = st.text_input("候选人姓名 *", key="doc_iv_candidate")
        position = st.text_input("应聘岗位 *", key="doc_iv_position")
        interview_time = st.text_input("面试时间 *", placeholder="例如：2026-10-15 14:00", key="doc_iv_time")
        location = st.text_input("面试地点 *", key="doc_iv_location")
        contact = st.text_input("联系人", key="doc_iv_contact")
        phone = st.text_input("联系电话", key="doc_iv_phone")
        if st.button("生成面试邀请", type="primary", width="stretch"):
            if not candidate.strip() or not position.strip() or not interview_time.strip() or not location.strip():
                st.warning("请填写候选人、岗位、面试时间和地点。")
            else:
                _download(intent, {
                    "candidate": candidate.strip(), "position": position.strip(), "interview_time": interview_time.strip(),
                    "location": location.strip(), "contact": contact.strip(), "phone": phone.strip()
                })

    elif intent == "onboarding_notice":
        name = st.text_input("姓名 *", key="doc_on_name")
        department = st.text_input("部门 *", key="doc_on_department")
        position = st.text_input("岗位 *", key="doc_on_position")
        report_time = st.text_input("报到时间 *", key="doc_on_time")
        location = st.text_input("报到地点 *", key="doc_on_location")
        materials = st.text_area("需携带资料", key="doc_on_materials")
        contact = st.text_input("联系人", key="doc_on_contact")
        if st.button("生成入职通知", type="primary", width="stretch"):
            if not name.strip() or not position.strip() or not report_time.strip() or not location.strip():
                st.warning("请填写姓名、岗位、报到时间和地点。")
            else:
                _download(intent, {
                    "name": name.strip(), "department": department.strip(), "position": position.strip(),
                    "report_time": report_time.strip(), "location": location.strip(),
                    "materials": materials.strip(), "contact": contact.strip()
                })

    elif intent == "employment_certificate":
        name = st.text_input("姓名 *", key="doc_ec_name")
        department = st.text_input("部门 *", key="doc_ec_department")
        position = st.text_input("岗位 *", key="doc_ec_position")
        start_date = st.date_input("入职日期", value=date.today(), key="doc_ec_start")
        purpose = st.text_input("证明用途", key="doc_ec_purpose")
        if st.button("生成在职证明", type="primary", width="stretch"):
            if not name.strip() or not department.strip() or not position.strip():
                st.warning("请填写姓名、部门和岗位。")
            else:
                _download(intent, {
                    "name": name.strip(), "department": department.strip(), "position": position.strip(),
                    "start_date": start_date.isoformat(), "purpose": purpose.strip()
                })

    elif intent == "training_notice":
        topic = st.text_input("培训主题 *", key="doc_tr_topic")
        training_time = st.text_input("培训时间 *", key="doc_tr_time")
        location = st.text_input("培训地点 *", key="doc_tr_location")
        audience = st.text_input("培训对象", key="doc_tr_audience")
        lecturer = st.text_input("讲师", key="doc_tr_lecturer")
        notes = st.text_area("注意事项", key="doc_tr_notes")
        if st.button("生成培训通知", type="primary", width="stretch"):
            if not topic.strip() or not training_time.strip() or not location.strip():
                st.warning("请填写培训主题、时间和地点。")
            else:
                _download(intent, {
                    "topic": topic.strip(), "training_time": training_time.strip(), "location": location.strip(),
                    "audience": audience.strip(), "lecturer": lecturer.strip(), "notes": notes.strip()
                })

    elif intent == "meeting_minutes":
        topic = st.text_input("会议主题 *", key="doc_mm_topic")
        meeting_time = st.text_input("会议时间", key="doc_mm_time")
        participants = st.text_input("参会人员", key="doc_mm_people")
        discussion = st.text_area("会议主要内容 *", height=140, key="doc_mm_discussion")
        decisions = st.text_area("会议决定", height=100, key="doc_mm_decisions")
        actions = st.text_area("任务分工 / 待办", height=100, key="doc_mm_actions")
        if st.button("生成会议纪要", type="primary", width="stretch"):
            if not topic.strip() or not discussion.strip():
                st.warning("请填写会议主题和主要内容。")
            else:
                _download(intent, {
                    "topic": topic.strip(), "meeting_time": meeting_time.strip(), "participants": participants.strip(),
                    "discussion": discussion.strip(), "decisions": decisions.strip(), "actions": actions.strip()
                })
