from pathlib import Path

readme = """# 小冲AI

小冲AI 是一个面向企业员工与 HR 的智能办公助手，基于 **Streamlit + Qwen + RAG + 多模态分析** 开发。

系统主要用于企业制度问答、图片与文件分析、办公文档生成、新员工培训、历史会话以及 HR 管理。

---

## 主要功能

### 1. 企业制度智能问答
员工可以直接询问：

- 考勤
- 请假
- 加班
- 调休
- 培训
- 考核
- 奖惩
- 入职、离职等公司制度问题

系统会结合企业知识库检索相关制度，再生成回答。

---

### 2. 图片与文件分析
聊天框支持上传：

- JPG / PNG / WEBP 图片
- PDF
- Word
- TXT
- Markdown

可以进行：

- 图片内容识别
- 图片文字提取
- 截图分析
- 文档内容提取
- 文档总结
- 图片内容与公司制度联合分析

---

### 3. 智能办公文档
系统可以识别用户的办公需求，并辅助生成：

- 请假申请
- 加班申请
- 面试邀请
- 入职通知
- 在职证明
- 培训通知
- 会议纪要

---

### 4. 新员工培训
新员工培训模块包括：

- 员工基本信息
- 岗位主要工作分析
- 公司办公地图与位置
- 考勤制度培训
- 培训完成记录
- 新员工培训 Word 文档导出

---

### 5. 历史会话
支持：

- 新建会话
- 自动保存聊天记录
- 搜索历史会话
- 打开并继续历史会话
- 保存聊天中的图片和附件

---

### 6. 员工反馈
员工可以对 AI 回答进行：

- 👍 正确评价
- 👎 错误评价

系统会记录员工问题和反馈，供 HR 后续优化知识库。

---

### 7. HR 管理中心
HR 管理员登录后可以使用：

- HR 制度智能问答
- 查看回答的知识库来源
- 查看知识文件和知识切块
- 查看新员工培训记录
- 配置公司办公地图
- 查看人工审核记录
- 查看员工反馈与 AI 运营数据

---

## 系统组成

```text
员工 / HR
    ↓
Streamlit 界面
    ↓
Smart Router 意图识别
    ↓
┌─────────────┬─────────────┐
│             │             │
RAG知识库    多模态分析    办公文档
│             │             │
Qwen          Qwen-VL       Word生成
│             │             │
└─────────────┴─────────────┘
              ↓
        小冲AI最终回答
```

---

## 主要技术

- Python
- Streamlit
- 阿里云百炼 Qwen
- Qwen-VL
- RAG
- Embedding
- 本地向量库
- python-docx
- PyPDF
- OpenAI Compatible API

---

## 项目主要目录

```text
HR_Shared_Service_Agent_V3_NewHire/
│
├─ app.py
├─ config.py
├─ requirements.txt
├─ README.md
│
├─ agents/
│  ├─ policy_agent.py
│  └─ smart_router.py
│
├─ modules/
│  ├─ chat_history.py
│  ├─ document_agent.py
│  ├─ document_templates.py
│  └─ intent_router.py
│
├─ rag/
│  ├─ embeddings.py
│  ├─ retriever.py
│  ├─ vector_store.py
│  └─ indexer.py
│
├─ onboarding/
│  ├─ exporter.py
│  ├─ storage.py
│  └─ company.py
│
├─ knowledge_base/
├─ assets/
└─ data/
```

---

## 运行方式

安装依赖：

```bash
pip install -r requirements.txt
```

运行项目：

```bash
streamlit run app.py
```

浏览器访问：

```text
http://localhost:8501
```

---

## 项目定位

**小冲AI = 企业制度问答 + 多模态分析 + 智能办公 + 新员工培训 + HR 管理**

目标是让员工可以直接通过自然语言完成企业内部常见的人事与办公任务。
"""

out = Path("/mnt/data/README_小冲AI_系统版.md")
out.write_text(readme, encoding="utf-8")

print(f"已生成：{out}")
