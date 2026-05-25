"""
astrbot_plugin_TIMretry — QQ官方机器人 TIM 兼容 + DNS 自动重试

功能：
1. TIM 兼容：猴补丁 QQOfficialMessageEvent._post_send()，强制纯文本模式
   （msg_type=0），可选清洗 Markdown 格式符号。
2. DNS 自动重试：捕获 ClientConnectorDNSError / OSError / ConnectionError
   并执行指数退避重试。
"""

from __future__ import annotations

import asyncio
import functools
import re
import traceback

from astrbot.api import logger, star
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.all import Context, AstrBotConfig
from astrbot.core.message.components import Plain

try:
    from aiohttp import ClientConnectorDNSError
except ImportError:
    ClientConnectorDNSError = None  # type: ignore[assignment]


# ──────────────────────────────────────────────
# Markdown 清洗
# ──────────────────────────────────────────────

# 匹配模式按顺序应用，避免互相干扰
_MD_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # 图片 ![alt](url) → alt
    (re.compile(r"!\[([^\]]*)\]\([^)]+\)"), r"\1"),
    # 链接 [text](url) → text
    (re.compile(r"\[([^\]]*)\]\([^)]+\)"), r"\1"),
    # 粗体+斜体 ***text*** → text
    (re.compile(r"\*\*\*(.+?)\*\*\*"), r"\1"),
    # 粗体 **text** 或 __text__
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),
    (re.compile(r"__(.+?)__"), r"\1"),
    # 斜体 *text* 或 _text_（注意不匹配 **）
    (re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)"), r"\1"),
    (re.compile(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)"), r"\1"),
    # 删除线 ~~text~~
    (re.compile(r"~~(.+?)~~"), r"\1"),
    # 行内代码 `code`
    (re.compile(r"`([^`]+)`"), r"\1"),
    # ATX 标题 # ~ ######
    (re.compile(r"^#{1,6}\s+", re.MULTILINE), ""),
    # 无序列表标记 - 或 *
    (re.compile(r"^[\-\*]\s+", re.MULTILINE), ""),
    # 有序列表标记 1. 2. 等
    (re.compile(r"^\d+\.\s+", re.MULTILINE), ""),
    # 引用 >
    (re.compile(r"^>\s?", re.MULTILINE), ""),
    # 水平分割线 --- / *** / ___（单独一行）
    (re.compile(r"^[\-\*\_]{3,}\s*$", re.MULTILINE), ""),
]


def strip_markdown(text: str) -> str:
    """清洗 Markdown 格式符号，保留纯文本内容。

    处理: 粗体、斜体、删除线、代码、标题、列表、引用、分割线、链接、图片。
    """
    result = text
    for pattern, replacement in _MD_PATTERNS:
        result = pattern.sub(replacement, result)
    # 清理多余的空白行
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


# ──────────────────────────────────────────────
# 插件主类
# ──────────────────────────────────────────────


class TIMretryPlugin(star.Star):
    """QQ 官方机器人增强插件。"""

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self._patched_originals: dict[str, object] = {}
        self._patched_platform_ids: set[str] = set()
        self._qq_post_send_original = None

    # ── 生命周期 ──────────────────────────────

    async def initialize(self) -> None:
        await self._patch_qq_official_retry()
        await self._patch_tim_markdown_fix()

    async def terminate(self) -> None:
        platforms = self.context.platform_manager.get_insts()
        for plat in platforms:
            pid = plat.meta().id
            if pid in self._patched_originals:
                plat.send_by_session = self._patched_originals[pid]
                logger.info(f"[TIMretry] 已恢复平台 {pid} 的 send_by_session")
        self._patched_originals.clear()
        self._patched_platform_ids.clear()

        if self._qq_post_send_original is not None:
            from astrbot.core.platform.sources.qqofficial.qqofficial_message_event import (
                QQOfficialMessageEvent,
            )
            QQOfficialMessageEvent._post_send = self._qq_post_send_original
            logger.info("[TIMretry] 已恢复 _post_send")
            self._qq_post_send_original = None

        logger.info("[TIMretry] 插件已卸载")

    # ── TIM 兼容补丁 ───────────────────────────

    async def _patch_tim_markdown_fix(self) -> None:
        """猴补丁 _post_send()：强制纯文本 + 可选 Markdown 清洗。"""
        if self._qq_post_send_original is not None:
            return

        try:
            from astrbot.core.platform.sources.qqofficial.qqofficial_message_event import (
                QQOfficialMessageEvent,
            )
        except ImportError:
            logger.warning("[TIMretry] 无法导入 QQOfficialMessageEvent，跳过 TIM 补丁")
            return

        self._qq_post_send_original = QQOfficialMessageEvent._post_send

        # 捕获 self 引用（闭包内访问 config）
        plugin_self = self

        @functools.wraps(self._qq_post_send_original)
        async def post_send_with_plain_text(self_event, stream=None):
            buf = self_event.send_buffer
            if buf is not None:
                # ① 强制纯文本模式（msg_type=0）
                if getattr(buf, "use_markdown_", None) is not False:
                    buf.use_markdown_ = False

                # ② 可选：清洗 Markdown 格式符号
                if plugin_self.config.get("strip_markdown", True):
                    for comp in buf.chain:
                        if isinstance(comp, Plain):
                            original = comp.text
                            cleaned = strip_markdown(original)
                            if cleaned != original:
                                comp.text = cleaned
                                logger.debug(
                                    f"[TIMretry] Markdown 已清洗 "
                                    f"({len(original)} → {len(cleaned)} 字符)"
                                )

            return await self._qq_post_send_original(self_event, stream)

        QQOfficialMessageEvent._post_send = post_send_with_plain_text
        logger.info("[TIMretry] TIM 兼容补丁已启用 (强制纯文本 + Markdown清洗)")

    # ── DNS 重试补丁 ───────────────────────────

    async def _patch_qq_official_retry(self) -> None:
        if self._patched_platform_ids:
            return

        platforms = self.context.platform_manager.get_insts()
        for plat in platforms:
            meta = plat.meta()
            if getattr(meta, "type", "") != "qq_official":
                continue
            pid = meta.id
            if pid in self._patched_platform_ids:
                continue

            original_send = plat.send_by_session

            @functools.wraps(original_send)
            async def send_with_retry(session, chain, _orig=original_send):
                max_retries: int = self.config.get("max_retries", 5)
                base_delay: float = self.config.get("base_delay", 2.0)
                max_delay: float = self.config.get("max_delay", 30.0)
                last_exc: Exception | None = None

                for attempt in range(max_retries + 1):
                    try:
                        return await _orig(session, chain)
                    except Exception as exc:
                        last_exc = exc
                        if not _is_retryable(exc):
                            raise
                        if attempt >= max_retries:
                            break
                        delay = min(base_delay * (2**attempt), max_delay)
                        logger.warning(
                            f"[TIMretry] {type(exc).__name__} "
                            f"(第{attempt + 1}/{max_retries + 1}次)，"
                            f"{delay:.1f}s后重试: {exc}"
                        )
                        await asyncio.sleep(delay)

                logger.error(f"[TIMretry] 重试{max_retries}次后仍失败: {last_exc}")
                assert last_exc is not None
                raise last_exc

            self._patched_originals[pid] = original_send
            plat.send_by_session = send_with_retry
            self._patched_platform_ids.add(pid)
            logger.info(f"[TIMretry] 平台 {pid} 已启用 DNS/连接重试")

    # ── 钩子 ───────────────────────────────────

    @filter.after_message_sent()
    async def on_after_sent(self, event: AstrMessageEvent) -> None:
        pass  # 占位，供未来扩展


# ──────────────────────────────────────────────
# 辅助
# ──────────────────────────────────────────────


def _is_retryable(exc: Exception) -> bool:
    if ClientConnectorDNSError is not None and isinstance(exc, ClientConnectorDNSError):
        return True
    exc_type = type(exc).__name__
    if "DNS" in exc_type.upper() or "GAERROR" in exc_type.upper():
        return True
    if isinstance(exc, (OSError, ConnectionError)):
        return True
    try:
        from aiohttp import ClientError
        if isinstance(exc, ClientError):
            return True
    except ImportError:
        pass
    return False