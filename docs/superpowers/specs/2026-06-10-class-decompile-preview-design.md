# .class 文件预览反编译 — 设计

日期: 2026-06-10
状态: 用户已确认(对话中逐段确认)

## 背景

IDE 工作区(原生代码工作区 CodeViewer)点 `.class` 文件只显示「二进制文件,不支持预览」+ 下载按钮。
用户要求能直接看到内容。`.class` 是 JVM 字节码,要可读必须反编译。

现状链路:
- 前端 `frontend/src/views/coding/CodeViewer.vue` 的 `BINARY_EXT` 白名单含 `class`,命中直接短路到下载面板,不发请求。
- 后端 `GET /workspace/{ws_id}/file`(`backend/app/routes/coding.py` `read_workspace_file`)→ `workspace_mgr.read_file` 按 utf-8 读文本,读二进制必抛解码错。

环境结论(已核实):
- 本机有 Temurin 11 JDK(`javap`/`java` 在 PATH)。
- 部署镜像本来就打了 JDK8 + JDK17 + Maven(`deploy/docker/Dockerfile:62-64,125-138`,`JAVA_HOME=/opt/jdk17`),无需改镜像。

## 方案(用户选定: CFR 完整反编译 + javap 兜底)

### 后端

1. 新模块 `backend/app/coding/class_decompiler.py`:
   - `decompile_class_file(class_path: Path) -> DecompileResult`(含 `text` 与 `tool` 字段, tool = `cfr` | `javap`)。
   - 优先 `java -jar <CFR_JAR> <file>`,失败/不可用退 `javap -p -c -constants <file>`,都失败抛友好错误。
   - 子进程 20s 超时;java 可执行文件按 `JAVA_HOME/bin/java` → PATH `java` 查找。
   - CFR jar 路径: env `CFR_JAR_PATH` 覆盖,默认 `backend/vendor/cfr-0.152.jar`。
2. CFR jar(~2MB, MIT)从 Maven Central(org.benf:cfr:0.152)下载,提交进仓库 `backend/vendor/`。
3. 路由 `read_workspace_file`: `file_path` 以 `.class` 结尾(不区分大小写)时走反编译,返回
   `{path, content, decompiled: true, decompiler: "cfr"|"javap"}`;其他文件行为完全不变。
   路径安全(escape 检查)复用 workspace_mgr 现有逻辑。

### 前端(CodeViewer.vue)

1. `BINARY_EXT` 移除 `class`(`jar` 等仍走下载面板)。
2. 正常走 `readWorkspaceFile`;响应 `decompiled: true` 时头部显示「反编译视图」小徽标。
3. `.class` 内容按 Java 高亮(shikiHighlight 语言映射加 class → java)。
4. 反编译失败(后端 4xx/5xx)时仍落现有二进制下载面板,不出红色报错。

### 测试

- `backend/tests/test_class_decompiler.py`:
  - 用 `javac` 现场编译小 fixture → CFR 反编译 → 断言含类名/方法名(机器无 javac/java 则 skip)。
  - CFR jar 路径不存在时 → javap 兜底路径生效。
  - 非法/损坏 class → 抛友好错误。
- 端到端: preview 中打开真实工作区 `1_57418e77` 的 `target/classes/com/xdap/legacyquery/config/LegacyQueryAllowUrlConfig.class`,确认渲染出反编译 Java。

## 明确不做(YAGNI)

- 不缓存反编译结果(单文件 <1s)。
- 不支持浏览 jar 包内部条目。
- 不隐藏 `target/` 构建目录(用户明确要能看产物)。
- agent 侧 read_file 工具不动,只改人看的预览链路。
