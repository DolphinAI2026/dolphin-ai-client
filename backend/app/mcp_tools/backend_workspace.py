"""aPaaS backend self-development workspace MCP tools."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from app import runtime
from app.config import settings


_re_lint = re
_registered_tools_by_mcp: dict[int, dict[str, object]] = {}


def _scan_java_files(ws_path) -> list:
    """收集 workspace 里所有 .java 文件路径（相对 workspace root）。"""
    out = []
    for path in ws_path.rglob("*.java"):
        rel = path.relative_to(ws_path)
        parts = rel.parts
        if any(p in ("target", "build", "node_modules", ".git") for p in parts):
            continue
        out.append((str(rel), path))
    return out


def _lint_one_java(rel_path: str, content: str) -> list[dict]:
    """对单个 Java 文件查坑。返回 [{line, severity, pit, message, hint}]。"""
    findings = []
    lines = content.split("\n")
    in_main = rel_path.startswith("src/main/")

    for i, ln in enumerate(lines, start=1):
        if in_main and "@SpringBootApplication" in ln:
            findings.append({
                "line": i, "severity": "fatal", "pit": "P7",
                "message": "@SpringBootApplication 出现在 src/main/java 下",
                "hint": "移到 src/test/java/...Application.java；否则 aPaaS 发布卡在「上线中」无报错",
            })

        if _re_lint.search(r"\.doQuery\s*\(\s*(?:Map|HashMap|LinkedHashMap|TreeMap)\.class\s*\)", ln):
            findings.append({
                "line": i, "severity": "fatal", "pit": "P9",
                "message": "doQuery 传了 Map.class / HashMap.class",
                "hint": "用无参 doQuery() / doQueryFirst() 返回 List<Map> — Java 17 JPMS 拒绝反射 java.util 内部字段",
            })

        if _re_lint.search(r"\.setVar\s*\(", ln) and ".setVariable(" not in ln:
            findings.append({
                "line": i, "severity": "warn", "pit": "P10",
                "message": "用了 setVar（会自动加 va_ 前缀，导致 SQL 占位符 :xxx 匹配不上）",
                "hint": "改用 setOriginVar(name, value)，除非 SQL 占位符本身就写的 :va_xxx",
            })

        if _re_lint.search(r"WHERE\s+(parent_id|main_id|master_id|f_main_id)\b", ln, _re_lint.IGNORECASE):
            findings.append({
                "line": i, "severity": "warn", "pit": "P11",
                "message": "用了 parent_id / main_id 之类做子表关联查询",
                "hint": "aPaaS 子表关联主表用 tab_doc_id（值 = 主表 document_id），不是 parent_id / main_id",
            })

        if _re_lint.search(r"INSERT\s+INTO", ln, _re_lint.IGNORECASE):
            tail = "\n".join(lines[i-1:i+3])
            if ".doUpdate(" in tail:
                findings.append({
                    "line": i, "severity": "fatal", "pit": "P14",
                    "message": "INSERT 用了 doUpdate() — 抛 SW-180227 (update 必须带 WHERE)",
                    "hint": "INSERT 应造 POJO + doInsert(entity)，不是 .sql(INSERT) + doUpdate()",
                })
            elif ".doInsert(" in tail and _re_lint.search(r"\.doInsert\s*\(\s*\)", tail):
                findings.append({
                    "line": i, "severity": "fatal", "pit": "P15",
                    "message": "原生 INSERT SQL + doInsert() 无 POJO — 抛 SW-180228",
                    "hint": "造 Entity 类继承 BasePojo 后调 doInsert(entity)",
                })

        if _re_lint.search(r"\.setOriginVar\s*\([^,]+,\s*null\s*\)", ln):
            findings.append({
                "line": i, "severity": "fatal", "pit": "P13",
                "message": "setOriginVar 第二参传了字面 null — 必崩",
                "hint": "改成 v == null ? \"\" : v；想入 SQL NULL 用 NULLIF 或原生 Sql2o addParameter",
            })

        if _re_lint.search(r"=\s*'[a-z][a-z_]+_g\d+'", ln):
            findings.append({
                "line": i, "severity": "warn", "pit": "P1",
                "message": "可能拿下拉/单选字段做 = 'code' 比较 — apaas 下拉字段存的是 JSON 数组",
                "hint": "改用 JSON_UNQUOTE(JSON_EXTRACT(f,'$[0]')) = 'code' 或 LIKE '%code%'",
            })

    if in_main and _re_lint.search(r"class\s+\w+\s+extends\s+MpaasBasePojo\b", content):
        for i, ln in enumerate(lines, start=1):
            m = _re_lint.search(r"class\s+(\w+)\s+extends\s+MpaasBasePojo\b", ln)
            if m:
                class_name = m.group(1)
                if class_name == "BasePojo":
                    break
                findings.append({
                    "line": i, "severity": "warn", "pit": "P16",
                    "message": f"{class_name} 直接继承 MpaasBasePojo — 缺 documentId/status/tenantId/formId 字段",
                    "hint": "改继承 BasePojo（项目内的封装基类）；INSERT 前调 initInsertIdentity()，否则 aPaaS 详情页空白",
                })
                break

    return findings


def _doctor_check_mvn() -> dict:
    """检查 mvn 是否在 PATH + 拿版本。"""
    mvn = shutil.which("mvn")
    if not mvn:
        return {
            "ok": False, "severity": "fatal", "check": "mvn",
            "message": "mvn 不在 PATH",
            "hint": "装 Maven 或者把 mvn 加到 PATH。Mac 用 brew install maven。",
        }
    try:
        result = subprocess.run(
            [mvn, "-v"],
            capture_output=True,
            text=True,
            timeout=10,
            **runtime.subprocess_window_kwargs(),
        )
        ver_line = (result.stdout or result.stderr).split("\n")[0]
        return {
            "ok": True, "severity": "info", "check": "mvn",
            "message": f"mvn 可用：{ver_line.strip()}",
            "mvn_path": mvn,
        }
    except Exception as e:
        return {
            "ok": False, "severity": "warn", "check": "mvn",
            "message": f"mvn 找到但执行失败：{e}",
        }


def _doctor_check_java() -> dict:
    """检查 java -version 拿 JDK 主版本，并按环境级配置校验。"""
    expected_jdk = str(getattr(settings, "apaas_backend_jdk_version", "17") or "17").strip().lower()
    if expected_jdk in ("1.8", "jdk8", "java8"):
        expected_jdk = "8"
    elif expected_jdk in ("jdk17", "java17"):
        expected_jdk = "17"
    elif expected_jdk not in ("8", "17", "auto"):
        expected_jdk = "17"

    java = shutil.which("java")
    if not java:
        return {
            "ok": False, "severity": "fatal", "check": "java",
            "message": "java 不在 PATH",
            "hint": f"安装 JDK {expected_jdk if expected_jdk != 'auto' else '8/17'}，或配置 JAVA_HOME。",
        }
    try:
        result = subprocess.run(
            [java, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            **runtime.subprocess_window_kwargs(),
        )
        ver_str = result.stderr or result.stdout
        m = re.search(r'version\s+"([\d._]+)"', ver_str)
        if not m:
            return {
                "ok": False, "severity": "warn", "check": "java",
                "message": f"无法解析 java 版本：{ver_str[:200]}",
            }
        v = m.group(1)
        major = v.split(".")[0]
        if major == "1":
            major = v.split(".")[1]
        major_int = int(major)
        if expected_jdk == "auto":
            return {
                "ok": True, "severity": "info", "check": "java",
                "message": f"Java {major_int} ({v})；APAAS_BACKEND_JDK_VERSION=auto，由 mvn wrapper 按 pom.xml 选择",
            }
        expected_int = int(expected_jdk)
        if major_int == expected_int:
            return {
                "ok": True, "severity": "info", "check": "java",
                "message": f"Java {major_int} ✓ ({v})；匹配 APAAS_BACKEND_JDK_VERSION={expected_jdk}",
            }
        if major_int <= 17:
            return {
                "ok": True, "severity": "warn", "check": "java",
                "message": f"Java {major_int} ({v}) — 环境配置要求 JDK {expected_jdk}",
                "hint": f"将 JAVA_HOME 切到 JDK {expected_jdk}，或调整 APAAS_BACKEND_JDK_VERSION。",
            }
        return {
            "ok": False, "severity": "fatal", "check": "java",
            "message": f"Java {major_int} ({v}) — 当前只支持 JDK 8/17 打包配置",
            "hint": f"将 JAVA_HOME 切到 JDK {expected_jdk}，或调整 APAAS_BACKEND_JDK_VERSION。",
        }
    except Exception as e:
        return {
            "ok": False, "severity": "warn", "check": "java",
            "message": f"java 找到但执行失败：{e}",
        }


def _doctor_check_settings_xml() -> dict:
    """检查 ~/.m2/settings.xml 是否配 dcloud-public 认证。"""
    settings_xml = Path.home() / ".m2" / "settings.xml"
    if not settings_xml.exists():
        return {
            "ok": False, "severity": "fatal", "check": "settings.xml",
            "message": "~/.m2/settings.xml 不存在",
            "hint": (
                "建文件加上 dcloud-public server 认证 + mirror。模版见 "
                "docs/skills/ai-coding/backend-dev.md 或 aPaaS-后端自开发模版包打包规范.md 第五节"
            ),
        }
    try:
        content = settings_xml.read_text(encoding="utf-8")
    except Exception as e:
        return {
            "ok": False, "severity": "warn", "check": "settings.xml",
            "message": f"~/.m2/settings.xml 存在但读不了：{e}",
        }

    has_server = "dcloud-public" in content
    has_mirror = "registry.dfy.definesys.cn" in content
    if not has_server:
        return {
            "ok": False, "severity": "fatal", "check": "settings.xml",
            "message": "~/.m2/settings.xml 里没找到 dcloud-public server 配置",
            "hint": (
                "<servers><server><id>dcloud-public</id>"
                "<username>dcloud-public</username><password>dcloud-public</password>"
                "</server></servers>"
            ),
        }
    if not has_mirror:
        return {
            "ok": True, "severity": "warn", "check": "settings.xml",
            "message": "有 dcloud-public server，但没找到 mirrorOf 配置（可能依赖 pom 里的 <repositories>）",
            "hint": (
                "推荐加 <mirror><id>dcloud-public</id><mirrorOf>*,!central</mirrorOf>"
                "<url>https://registry.dfy.definesys.cn/repository/maven-public/</url></mirror>"
            ),
        }
    return {
        "ok": True, "severity": "info", "check": "settings.xml",
        "message": "~/.m2/settings.xml 配 dcloud-public server + mirror ✓",
    }


def _doctor_check_pom(ws_path) -> dict:
    """检查 pom.xml 关键字段：repositories / lib profile / papaas.version / motor-spring-boot-starter。"""
    pom = ws_path / "pom.xml"
    if not pom.exists():
        return {
            "ok": False, "severity": "fatal", "check": "pom.xml",
            "message": "workspace 下没有 pom.xml",
            "hint": "调 init_apaas_backend_workspace 生成标准 pom",
        }
    try:
        content = pom.read_text(encoding="utf-8")
    except Exception as e:
        return {
            "ok": False, "severity": "fatal", "check": "pom.xml",
            "message": f"pom.xml 读不了：{e}",
        }

    issues = []
    if "registry.dfy.definesys.cn" not in content:
        issues.append({
            "severity": "warn", "field": "<repositories>",
            "message": "pom 没配 <repositories> 指向 dcloud-public Nexus；如果 settings.xml 里有 mirror 也能拿到，否则会失败",
        })
    if "<id>lib</id>" not in content:
        issues.append({
            "severity": "fatal", "field": "lib profile",
            "message": "pom 缺 lib profile — `mvn -P lib` 必报 The requested profile \"lib\" could not be activated",
            "hint": "调 init_apaas_backend_workspace 重写 pom",
        })
    if "<papaas.version>" not in content:
        issues.append({
            "severity": "warn", "field": "papaas.version",
            "message": "pom 没定义 <papaas.version> property",
        })
    elif "4.1.1-rc" not in content and "<papaas.version>" in content:
        issues.append({
            "severity": "warn", "field": "papaas.version",
            "message": "papaas 版本不是 4.1.1-rc — 旧版本 (3.2.x) 上传后 404",
            "hint": "改 <papaas.version>4.1.1-rc</papaas.version>",
        })
    if "motor-spring-boot-starter" not in content:
        issues.append({
            "severity": "fatal", "field": "motor-spring-boot-starter",
            "message": "pom 缺 motor-spring-boot-starter — 4.1.1-rc 模版包必备",
        })

    if not issues:
        return {
            "ok": True, "severity": "info", "check": "pom.xml",
            "message": "pom.xml 关键字段齐全 ✓ (repositories / lib profile / papaas 4.1.1-rc / motor)",
        }

    fatal_issues = [i for i in issues if i["severity"] == "fatal"]
    return {
        "ok": len(fatal_issues) == 0,
        "severity": "fatal" if fatal_issues else "warn",
        "check": "pom.xml",
        "message": f"pom.xml {len(issues)} 个问题（{len(fatal_issues)} fatal）",
        "issues": issues,
    }


def _doctor_check_app_class_location(ws_path) -> dict:
    """检查 @SpringBootApplication 是否误放 src/main（坑 7 死亡坑）。"""
    main_dir = ws_path / "src" / "main" / "java"
    if not main_dir.exists():
        return {
            "ok": True, "severity": "info", "check": "app_class_location",
            "message": "src/main/java 不存在 — 跳过此检查",
        }
    offenders = []
    for path in main_dir.rglob("*.java"):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if "@SpringBootApplication" in text:
            offenders.append(str(path.relative_to(ws_path)))
    if offenders:
        return {
            "ok": False, "severity": "fatal", "check": "app_class_location",
            "message": f"src/main/java 下有 {len(offenders)} 个 @SpringBootApplication（坑 7）",
            "offenders": offenders,
            "hint": "移到 src/test/java，否则 aPaaS 发布卡死「上线中」无报错",
        }
    return {
        "ok": True, "severity": "info", "check": "app_class_location",
        "message": "启动类位置 ✓ (src/main 下无 @SpringBootApplication)",
    }


def register(
    mcp,
    resolve_identity: Callable[[int | None, int | None], tuple[int, int]],
    resolve_workspace_path: Callable[[str, int, int], tuple[Path | None, dict | None]],
) -> dict[str, object]:
    """Register backend workspace tools and return tool objects needed by mcp_server."""
    marker = id(mcp)
    if marker in _registered_tools_by_mcp:
        return _registered_tools_by_mcp[marker]

    @mcp.tool()
    async def init_apaas_backend_workspace(
        ws_id: str,
        project_name: str,
        apaas_tenant_id: str = "",
        apaas_app_id: str = "",
        sample_form_id: str = "",
        overwrite: bool = False,
        tenant_id: int = 0,
        user_id: int = 0,
    ) -> dict:
        """给 AI Coding workspace 写入 aPaaS 后端自开发模版包标准骨架（10 个文件）。

        一次性写入：pom.xml + BasePojo + BaseDao + URL 白名单 + 示例 Service /
        Controller / Entity + 启动类（test 路径下）+ application.properties + README。

        直接绕过 5 大死亡坑：
          - 坑 5/6: 启动配置缺 autoconfigure exclude
          - 坑 7: @SpringBootApplication 误放 src/main 让 aPaaS 发布卡死
          - 坑 15: INSERT 必须 POJO + doInsert (示例 Service 内已演示)
          - 坑 16: BasePojo + initInsertIdentity (避免详情页空白)

        入参：
          ws_id        AI Coding workspace ID（不能是 vibe oc_ 前缀）
          project_name 项目名（kebab-case，会用作 Java 包名 + URL 前缀 +
                       artifactId，例如 'leave-passport'）
          apaas_tenant_id / apaas_app_id / sample_form_id
                       application.properties 占位值（可空，agent 后续手填）
          overwrite    是否覆盖已存在的文件（默认 false — 已有任一目标文件就拒绝，
                       防止误覆盖 agent 手写的代码）

        返回：{ok, files_written, files_skipped, files_conflict}
        """
        if ws_id.startswith("oc_"):
            return {
                "ok": False, "error_code": "WRONG_WS_TYPE",
                "message": "init_apaas_backend_workspace 只支持 AI Coding workspace；"
                           "Vibe Coding (oc_ 前缀) 是纯全栈代码，跟 aPaaS 后端自开发模版包无关",
            }
        if not project_name.strip():
            return {"ok": False, "error_code": "INVALID_PARAMS",
                    "message": "project_name 必填（kebab-case，如 leave-passport）"}

        if not re.match(r"^[a-z][a-z0-9\-]*[a-z0-9]$", project_name.strip()):
            return {
                "ok": False, "error_code": "INVALID_PROJECT_NAME",
                "message": (f"project_name '{project_name}' 不合法：必须全小写字母 / 数字 / -，"
                            f"首尾不能是 - 或数字开头"),
            }

        tid, uid = resolve_identity(tenant_id, user_id)
        ws_path, err = resolve_workspace_path(ws_id, tid, uid)
        if err:
            return err

        from app.apaas_backend_templates import render_all_templates
        files = render_all_templates(
            project_pkg=project_name.strip(),
            tenant_id=apaas_tenant_id.strip(),
            app_id=apaas_app_id.strip(),
            form_id=sample_form_id.strip(),
        )

        conflicts = []
        for rel_path in files.keys():
            target = ws_path / rel_path
            if target.exists():
                conflicts.append(rel_path)
        if conflicts and not overwrite:
            return {
                "ok": False, "error_code": "FILES_CONFLICT",
                "message": (f"{len(conflicts)} 个目标文件已存在，拒绝覆盖；"
                            f"想强制覆盖请传 overwrite=true"),
                "conflicts": conflicts,
            }

        from app.coding.tools import _write_file
        written = []
        failed = []
        for rel_path, content in files.items():
            text = await _write_file({"file_path": rel_path, "content": content}, ws_path)
            if isinstance(text, str) and text.startswith("Error:"):
                failed.append({"file_path": rel_path, "error": text})
            else:
                written.append(rel_path)

        return {
            "ok": len(failed) == 0,
            "ws_id": ws_id,
            "project_name": project_name.strip(),
            "files_written": written,
            "files_failed": failed,
            "files_count": len(files),
            "overwrote_existing": len(conflicts) if overwrite else 0,
            "next_step": (
                "1. 编辑 src/main/java/.../sample/* 把示例 Service/Controller "
                "改成你的业务；2. 改 application.properties 里的 tenantId/appId/formId；"
                "3. 调 lint_apaas_backend_workspace 自查；4. publish_dev_workspace 上传"
            ),
        }

    @mcp.tool()
    async def lint_apaas_backend_workspace(
        ws_id: str,
        tenant_id: int = 0,
        user_id: int = 0,
    ) -> dict:
        """静态扫描 workspace 里的 Java 代码，找 16 坑里能 grep 出来的写法。

        检测能力（覆盖 16 坑里的 P1/P7/P9/P10/P11/P13/P14/P15/P16）：
          P7  @SpringBootApplication 在 src/main → 发布卡死（fatal）
          P9  doQuery(Map.class)              → JPMS 反射拒绝（fatal）
          P10 setVar(...)                     → va_ 前缀坑（warn）
          P11 WHERE parent_id / main_id        → 子表应用 tab_doc_id（warn）
          P13 setOriginVar(_, null)           → 必崩（fatal）
          P14 INSERT INTO + doUpdate()         → SW-180227（fatal）
          P15 INSERT SQL + doInsert() 无 POJO  → SW-180228（fatal）
          P16 extends MpaasBasePojo            → 应继承 BasePojo（warn）
          P1  field = 'xxx_gN'                 → 下拉字段是 JSON 数组（warn）

        不能静态检测的（需要 publish 后跑或者 review）：
          P2/3 数据字典 / 用户 ID 翻译、P5/6 application.yml 配置、P8 历史脏数据、
          P12 业务字段列名运行时检测

        返回：{ok, files_scanned, findings_count, fatal_count, findings:[...]}
        """
        if ws_id.startswith("oc_"):
            return {"ok": False, "error_code": "WRONG_WS_TYPE",
                    "message": "lint_apaas_backend_workspace 只用于 AI Coding workspace；"
                               "oc_ 旧工作区走 run_workspace_command 自己跑 lint"}

        tid, uid = resolve_identity(tenant_id, user_id)
        ws_path, err = resolve_workspace_path(ws_id, tid, uid)
        if err:
            return err

        java_files = _scan_java_files(ws_path)
        if not java_files:
            return {
                "ok": True, "ws_id": ws_id, "files_scanned": 0,
                "findings_count": 0, "fatal_count": 0, "findings": [],
                "hint": "workspace 里没找到 .java 文件 — 调 init_apaas_backend_workspace 先建骨架",
            }

        all_findings = []
        for rel, abs_path in java_files:
            try:
                content = abs_path.read_text(encoding="utf-8")
            except Exception as e:
                all_findings.append({
                    "file": rel, "line": 0, "severity": "warn", "pit": "lint",
                    "message": f"读文件失败: {e}",
                })
                continue
            for f in _lint_one_java(rel, content):
                f["file"] = rel
                all_findings.append(f)

        fatal = [f for f in all_findings if f.get("severity") == "fatal"]
        return {
            "ok": True,
            "ws_id": ws_id,
            "files_scanned": len(java_files),
            "findings_count": len(all_findings),
            "fatal_count": len(fatal),
            "findings": all_findings[:200],
            "passed": len(fatal) == 0,
            "next_step": (
                "全部通过 — 可以 publish_dev_workspace"
                if len(fatal) == 0
                else f"有 {len(fatal)} 个 fatal 问题必须修；其他 warn 看情况"
            ),
        }

    @mcp.tool()
    async def doctor_apaas_backend_workspace(
        ws_id: str,
        tenant_id: int = 0,
        user_id: int = 0,
    ) -> dict:
        """打包前置体检 — 不实际跑 mvn，3 秒内出结果。

        治"我同事打包不成功"系列问题。一次性检查 5 项：
          1. mvn 在不在 PATH（mvn）
          2. java 版本是否匹配 APAAS_BACKEND_JDK_VERSION
          3. ~/.m2/settings.xml 是否配 dcloud-public Nexus 认证
          4. pom.xml 关键字段（repositories / lib profile / papaas 4.1.1-rc / motor）
          5. @SpringBootApplication 没误放 src/main（防坑 7 发布卡死）

        返回 {ok, fatal_count, warn_count, checks: [...]}
        - ok=true 才能安全打包；fatal_count>0 必修
        - 每条 check 含 hint，告诉怎么修
        """
        if ws_id.startswith("oc_"):
            return {"ok": False, "error_code": "WRONG_WS_TYPE",
                    "message": "doctor_apaas_backend_workspace 只用于 AI Coding workspace"}

        tid, uid = resolve_identity(tenant_id, user_id)
        ws_path, err = resolve_workspace_path(ws_id, tid, uid)
        if err:
            return err

        checks = [
            _doctor_check_mvn(),
            _doctor_check_java(),
            _doctor_check_settings_xml(),
            _doctor_check_pom(ws_path),
            _doctor_check_app_class_location(ws_path),
        ]

        fatal = [c for c in checks if c.get("severity") == "fatal"]
        warn = [c for c in checks if c.get("severity") == "warn"]

        return {
            "ok": len(fatal) == 0,
            "ws_id": ws_id,
            "fatal_count": len(fatal),
            "warn_count": len(warn),
            "info_count": sum(1 for c in checks if c.get("severity") == "info"),
            "checks": checks,
            "next_step": (
                "✓ 全 fatal 检查通过，可以 publish_dev_workspace"
                if len(fatal) == 0
                else f"先修 {len(fatal)} 个 fatal 问题（看每个 check 的 hint）"
            ),
        }

    tools = {
        "init_apaas_backend_workspace": init_apaas_backend_workspace,
        "lint_apaas_backend_workspace": lint_apaas_backend_workspace,
        "doctor_apaas_backend_workspace": doctor_apaas_backend_workspace,
    }
    _registered_tools_by_mcp[marker] = tools
    return tools
