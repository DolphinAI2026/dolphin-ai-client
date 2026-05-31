"""
对话上下文压缩模块

借鉴 Claude Code 的三层压缩策略，为 aPaaS Builder AI 实现简化版：
1. 微压缩：去掉旧 AI 回复中的代码块，只保留摘要文本
2. 摘要压缩：超过阈值时用 LLM 生成旧对话摘要，替换原始消息
3. 工具结果清理：清除中间态的搜索/读取结果

用法：
    compactor = ContextCompactor(llm_cfg)
    messages = compactor.compact(raw_messages, mode="chat")
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.llm_client import LLMClient

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────────────
MAX_HISTORY_CHARS = 30_000          # 历史消息总字符上限
COMPACT_TRIGGER_ROUNDS = 8         # 超过 N 轮对话触发摘要压缩
KEEP_RECENT_ROUNDS = 4             # 压缩时保留最近 N 轮不动
MAX_ASSISTANT_CHARS = 500           # AI 回复截断长度
SUMMARY_MARKER = "[对话摘要]"       # 摘要消息标记
COMPACT_SUMMARY_PROMPT = """\
请将以下多轮对话压缩为一段简明摘要，用于后续对话的上下文背景。

要求：
- 保留关键信息：用户的需求要点、已做出的技术决策、重要的代码文件路径
- 去掉具体代码内容（只说"生成了xx文件"即可）
- 去掉重复的问答和修正过程，只保留最终结论
- 用第三人称描述（"用户要求..."、"已完成..."）
- 控制在 300 字以内

对话内容：
"""


class ContextCompactor:
    """对话上下文压缩器"""

    def __init__(self, llm_cfg: Optional[Dict[str, Any]] = None):
        """
        llm_cfg: {"api_key": str, "base_url": str, "model": str, "max_tokens": int}
                 如果为 None，跳过 LLM 摘要，只做本地压缩
        """
        self.llm_cfg = llm_cfg

    # ── 主入口 ──────────────────────────────────────────────────────

    def compact(
        self,
        messages: List[Dict[str, str]],
        mode: str = "chat",
        existing_summary: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """
        同步压缩消息列表（不调用 LLM，纯本地处理）。

        mode:
          - "chat": 基础聊天，按字符上限截断
          - "coding": 代码生成，去掉代码块只留摘要
          - "coding_with_workspace": 有工作区的代码生成，更激进地压缩

        existing_summary: 之前已生成的摘要（如果有），会插入到最前面
        """
        if not messages:
            return []

        result = []

        # 如果有之前的摘要，作为第一条消息
        if existing_summary:
            result.append({
                "role": "user",
                "content": f"{SUMMARY_MARKER}\n{existing_summary}",
            })

        if mode == "chat":
            result.extend(self._compact_chat(messages))
        elif mode in ("coding", "coding_with_workspace"):
            has_ws = mode == "coding_with_workspace"
            result.extend(self._compact_coding(messages, has_workspace=has_ws))
        else:
            result.extend(messages)

        return result

    async def compact_with_summary(
        self,
        messages: List[Dict[str, str]],
        mode: str = "chat",
        existing_summary: Optional[str] = None,
    ) -> tuple[List[Dict[str, str]], Optional[str]]:
        """
        异步压缩：如果对话轮次超过阈值，先用 LLM 生成摘要，再做本地压缩。
        返回 (压缩后的消息列表, 新摘要文本)。

        新摘要应该存到 DB，下次对话时传入 existing_summary。
        """
        rounds = self._count_rounds(messages)
        new_summary = existing_summary

        if rounds > COMPACT_TRIGGER_ROUNDS and self.llm_cfg:
            # 把需要压缩的旧消息（不含最近 KEEP_RECENT_ROUNDS 轮）做摘要
            old_msgs, recent_msgs = self._split_by_rounds(
                messages, keep_recent=KEEP_RECENT_ROUNDS
            )
            if old_msgs:
                summary_text = await self._generate_summary(old_msgs, existing_summary)
                if summary_text:
                    new_summary = summary_text
                    # 用摘要 + 最近几轮重建消息
                    result = [{
                        "role": "user",
                        "content": f"{SUMMARY_MARKER}\n{new_summary}",
                    }]
                    if mode in ("coding", "coding_with_workspace"):
                        has_ws = mode == "coding_with_workspace"
                        result.extend(self._compact_coding(recent_msgs, has_workspace=has_ws))
                    else:
                        result.extend(self._compact_chat(recent_msgs))
                    return result, new_summary

        # 不需要摘要，走普通压缩
        compacted = self.compact(messages, mode=mode, existing_summary=existing_summary)
        return compacted, new_summary

    # ── Chat 模式压缩 ───────────────────────────────────────────────

    def _compact_chat(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """基础聊天压缩：按字符上限从新到旧截断"""
        truncated = []
        total_chars = 0
        for msg in reversed(messages):
            msg_len = len(msg.get("content") or "")
            if total_chars + msg_len > MAX_HISTORY_CHARS and truncated:
                break
            truncated.insert(0, msg)
            total_chars += msg_len
        return truncated

    # ── Coding 模式压缩 ─────────────────────────────────────────────

    def _compact_coding(
        self,
        messages: List[Dict[str, str]],
        has_workspace: bool = False,
        max_rounds: int = 6,
    ) -> List[Dict[str, str]]:
        """
        代码生成压缩：
        - 有工作区：去掉 AI 回复中的代码块，只保留摘要
        - 无工作区：保留最近 max_rounds 轮
        """
        if not messages:
            return []

        if has_workspace:
            rounds = self._pair_rounds(messages)
            recent = rounds[-max_rounds:]
            result = []
            for round_msgs in recent:
                for msg in round_msgs:
                    if msg["role"] == "assistant":
                        content = msg["content"] or ""
                        summary = re.sub(r'```[\s\S]*?```', '[代码已省略]', content)
                        if len(summary) > MAX_ASSISTANT_CHARS:
                            summary = summary[:MAX_ASSISTANT_CHARS] + "...[截断]"
                        result.append({"role": "assistant", "content": summary})
                    else:
                        result.append(msg)
            return result
        else:
            return messages[-(max_rounds * 2):]

    # ── 工具结果清理 ────────────────────────────────────────────────

    @staticmethod
    def clean_tool_results(
        messages: List[Dict[str, Any]],
        keep_recent: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        清理 tool role 消息中的大段结果。
        保留最近 keep_recent 条 tool 结果完整，其余压缩到 200 字。
        """
        # 找出所有 tool 消息的索引
        tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
        if len(tool_indices) <= keep_recent:
            return messages

        # 需要压缩的 tool 消息
        to_compress = set(tool_indices[:-keep_recent])
        result = []
        for i, msg in enumerate(messages):
            if i in to_compress:
                content = msg.get("content") or ""
                if len(content) > 200:
                    compressed = content[:200] + f"\n... [已压缩，原始 {len(content)} 字符]"
                    result.append({**msg, "content": compressed})
                else:
                    result.append(msg)
            else:
                result.append(msg)
        return result

    # ── LLM 摘要生成 ────────────────────────────────────────────────

    async def _generate_summary(
        self,
        messages: List[Dict[str, str]],
        existing_summary: Optional[str] = None,
    ) -> Optional[str]:
        """调用 LLM 生成对话摘要"""
        if not self.llm_cfg:
            return None

        # 构造要压缩的对话文本
        dialogue = ""
        if existing_summary:
            dialogue += f"[之前的摘要] {existing_summary}\n\n"
        for msg in messages:
            role = "用户" if msg["role"] == "user" else "AI"
            content = msg.get("content") or ""
            # 去掉代码块减少 token
            content = re.sub(r'```[\s\S]*?```', '[代码块]', content)
            if len(content) > 500:
                content = content[:500] + "..."
            dialogue += f"{role}: {content}\n\n"

        prompt = COMPACT_SUMMARY_PROMPT + dialogue

        try:
            client = LLMClient(
                api_key=self.llm_cfg["api_key"],
                base_url=self.llm_cfg["base_url"],
                model=self.llm_cfg["model"],
            )
            data = await client.chat_completion(
                [{"role": "user", "content": prompt}],
                max_tokens=1024,
                temperature=0.3,
                timeout=30.0,
            )
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.warning(f"对话摘要生成失败: {e}")
            return None

    # ── 辅助方法 ────────────────────────────────────────────────────

    @staticmethod
    def _count_rounds(messages: List[Dict[str, str]]) -> int:
        """计算对话轮次（一轮 = user + assistant）"""
        return sum(1 for m in messages if m.get("role") == "assistant")

    @staticmethod
    def _pair_rounds(messages: List[Dict[str, str]]) -> List[List[Dict[str, str]]]:
        """按轮次配对消息"""
        rounds = []
        current = []
        for msg in messages:
            current.append(msg)
            if msg["role"] == "assistant":
                rounds.append(current)
                current = []
        if current:
            rounds.append(current)
        return rounds

    @staticmethod
    def _split_by_rounds(
        messages: List[Dict[str, str]],
        keep_recent: int = 4,
    ) -> tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        """
        按轮次分割消息：返回 (要压缩的旧消息, 要保留的近期消息)
        """
        rounds = []
        current = []
        for msg in messages:
            current.append(msg)
            if msg["role"] == "assistant":
                rounds.append(current)
                current = []
        if current:
            rounds.append(current)

        if len(rounds) <= keep_recent:
            return [], messages

        old_rounds = rounds[:-keep_recent]
        recent_rounds = rounds[-keep_recent:]
        old_msgs = [m for r in old_rounds for m in r]
        recent_msgs = [m for r in recent_rounds for m in r]
        return old_msgs, recent_msgs
