---
name: 基础PPT导出
description: 把要点/大纲生成一个简洁 .pptx；适合通用汇报/宣传
---
## 怎么做
1. 阅读用户给的内容，整理成「封面 + 若干内容页（标题+要点）」。
2. 编辑工作目录里的 `skill_基础PPT导出/helper.py`，把 `SLIDES` 改成实际内容（第一项为封面）。
3. 用 run_python 执行该 helper.py（它用 python-pptx 生成 `output.pptx` 到工作目录）。
4. 用 save_binary_artifact 登记 `output.pptx`（filename 用有意义的中文名，如 `XX汇报.pptx`）。
