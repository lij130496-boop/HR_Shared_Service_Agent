from __future__ import annotations

from io import BytesIO
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt


def _add_multiline_text(doc: Document, text: str) -> None:
    text = (text or "").strip()
    if not text:
        doc.add_paragraph("暂无可用内容。")
        return
    for line in text.splitlines():
        line = line.strip()
        if line:
            doc.add_paragraph(line)


def build_onboarding_docx(
    state: dict,
    company_map_path: Path | None = None,
    company_locations: list[dict[str, str]] | None = None,
) -> bytes:
    """生成更贴近实际的新员工培训完成记录。"""
    doc = Document()
    doc.styles["Normal"].font.name = "Microsoft YaHei"
    doc.styles["Normal"].font.size = Pt(10.5)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("新员工培训与入职引导记录")
    run.bold = True
    run.font.size = Pt(20)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.add_run("人事行政共享服务助手自动生成")

    doc.add_heading("一、员工基本信息", level=1)
    info = state.get("basic", {})
    table = doc.add_table(rows=4, cols=2)
    table.style = "Table Grid"
    rows = [
        ("员工姓名", info.get("name", "")),
        ("所属部门", info.get("department", "")),
        ("岗位", info.get("position", "")),
        ("入职日期", info.get("start_date", "")),
    ]
    for row, (key, value) in zip(table.rows, rows):
        row.cells[0].text = key
        row.cells[1].text = str(value)

    doc.add_heading("二、主要工作分析", level=1)
    work = state.get("work_analysis", {})
    _add_multiline_text(doc, work.get("summary", ""))
    doc.add_paragraph(
        "学习确认：" + ("已了解" if work.get("confirmed") else "未确认")
    )

    doc.add_heading("三、公司办公地图和位置", level=1)
    if company_map_path and Path(company_map_path).exists():
        try:
            doc.add_picture(str(company_map_path), width=Inches(6.2))
            last = doc.paragraphs[-1]
            last.alignment = WD_ALIGN_PARAGRAPH.CENTER
        except Exception:
            doc.add_paragraph("公司办公地图已配置，但未能嵌入本次文档。")
    else:
        doc.add_paragraph("公司办公地图暂未配置，请以 HR 发布的实际办公地图为准。")

    locations = company_locations or []
    if locations:
        loc_table = doc.add_table(rows=1, cols=2)
        loc_table.style = "Table Grid"
        loc_table.rows[0].cells[0].text = "位置"
        loc_table.rows[0].cells[1].text = "说明"
        for item in locations:
            row = loc_table.add_row()
            row.cells[0].text = str(item.get("name", ""))
            row.cells[1].text = str(item.get("description", ""))
    else:
        doc.add_paragraph("暂无办公位置说明。")

    office = state.get("office_map", {})
    doc.add_paragraph(
        "学习确认：" + ("已了解" if office.get("confirmed") else "未确认")
    )

    doc.add_heading("四、考勤管理制度", level=1)
    attendance = state.get("attendance", {})
    _add_multiline_text(doc, attendance.get("summary", ""))
    doc.add_paragraph(
        "学习确认：" + ("已了解" if attendance.get("confirmed") else "未确认")
    )

    doc.add_heading("五、培训完成情况", level=1)
    checklist = [
        ("主要工作分析", bool(work.get("confirmed"))),
        ("公司办公地图和位置", bool(office.get("confirmed"))),
        ("考勤管理制度", bool(attendance.get("confirmed"))),
    ]
    for label, done in checklist:
        status = "已完成" if done else "未完成"
        doc.add_paragraph(f"[{status}] {label}")

    doc.add_paragraph("当前状态：新员工培训与入职引导已完成")
    doc.add_paragraph(
        "说明：岗位职责、办公位置和考勤要求均应以公司当前正式资料及 HR 最新通知为准。"
    )

    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
