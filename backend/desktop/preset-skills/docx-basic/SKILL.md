---
name: docx-basic
description: 基础Word导出——把内容生成一个带标题/小节的 .docx 文档
---
## 怎么做
1. 把用户内容整理成「标题 + 若干小节（小标题 + 段落）」。
2. 编辑 `skill_docx-basic/helper.py` 的 `TITLE` 和 `SECTIONS`。
3. run_python 执行 helper.py（python-docx 生成 `output.docx`）。
4. save_binary_artifact 登记 `output.docx`（中文名）。
