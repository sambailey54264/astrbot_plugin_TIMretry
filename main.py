"""
astrbot_plugin_TIMretry — QQ官方机器人 TIM 兼容 + DNS 自动重试

功能：
1. TIM 兼容：猴补丁 QQOfficialMessageEvent.send()，纯文本消息直接以
   msg_type=0（content 模式）调用 QQ API，彻底解决 TIM 不兼容。
   富媒体消息走原始流程。
2. Markdown 清洗：可选开关，发送前清洗消息中的 Markdown 格式符号。
3. DNS 自动重试：捕获 ClientConnectorDNSError / OSError / ConnectionError
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

_MD_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"!\[([^\]]*)\]\([^)]+\)"), r"\1"),
    (re.compile(r"\[([^\]]*)\]\([^)]+\)"), r"\1"),
    (re.compile(r"\*\*\*(.+?)\*\*\*"), r"\1"),
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),
    (re.compile(r"__(.+?)__"), r"\1"),
    (re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)"), r"\1"),
    (re.compile(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)"), r"\1"),
    (re.compile(r"~~(.+?)~~"), r"\1"),
    (re.compile(r"`([^`]+)`"), r"\1"),
    (re.compile(r"^#{1,6}\s+", re.MULTILINE), ""),
    (re.compile(r"^[\-\*]\s+", re.MULTILINE), ""),
    (re.compile(r"^\d+\.\s+", re.MULTILINE), ""),
    (re.compile(r"^>\s?", re.MULTILINE), ""),
    (re.compile(r"^[\-\*\_]{3,}\s*$", re.MULTILINE), ""),
]


def strip_markdown(text: str) -> str:
    result = text
    for pattern, replacement in _MD_PATTERNS:
        result = pattern.sub(replacement, result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def _extract_plain_text(chain) -> str:
    texts: list[str] = []
    for comp in chain:
        if isinstance(comp, Plain):
            texts.append(comp.text)
        else:
            t = getattr(comp, "text", None)
            if t and isinstance(t, str):
                texts.append(t)
    return "".join(texts)


def _has_rich_media(chain) -> bool:
    for comp in chain:
        name = type(comp).__name__
        if name in ("Image", "Record", "Video", "File"):
            return True
    return False


# ──────────────────────────────────────────────
# 插件主类
# ──────────────────────────────────────────────


class TIMretryPlugin(star.Star):

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self._patched_originals: dict[str, object] = {}
        self._patched_platform_ids: set[str] = set()
        self._qq_send_original = None

    async def initialize(self) -> None:
        await self._patch_qq_official_retry()
        await self._patch_tim_send_fix()

    async def terminate(self) -> None:
        platforms = self.context.platform_manager.get_insts()
        for plat in platforms:
            pid = plat.meta().id
            if pid in self._patched_originals:
                plat.send_by_session = self._patched_originals[pid]
                logger.info(f"[TIMretry] 已恢复平台 {pid} 的 send_by_session")
        self._patched_originals.clear()
        self._patched_platform_ids.clear()
        if self._qq_send_original is not None:
            from astrbot.core.platform.sources.qqofficial.qqofficial_message_event import (
                QQOfficialMessageEvent,
            )
            QQOfficialMessageEvent.send = self._qq_send_original
            logger.info("[TIMretry] 已恢复 QQOfficialMessageEvent.send")
            self._qq_send_original = None
        logger.info("[TIMretry] 插件已卸载")

    async def _patch_tim_send_fix(self) -> None:
        if self._qq_send_original is not None:
            return
        try:
            from astrbot.core.platform.sources.qqofficial.qqofficial_message_event import (
                QQOfficialMessageEvent,
            )
        except ImportError:
            logger.warning("[TIMretry] 无法导入 QQOfficialMessageEvent，跳过 TIM 补丁")
            return
        self._qq_send_original = QQOfficialMessageEvent.send
        _plugin = self

        @functools.wraps(self._qq_send_original)
        async def send_with_tim_fix(self_event, chain):
            if _plugin.config.get("strip_markdown", True):
                for comp in chain.chain:
                    if isinstance(comp, Plain):
                        original = comp.text
                        cleaned = strip_markdown(original)
                        if cleaned != original:
                            comp.text = cleaned

            if not _has_rich_media(chain):
                plain_text = _extract_plain_text(chain)
                if plain_text:
                    try:
                        source = self_event.message_obj.raw_message
                        import botpy.message
                        if isinstance(source, botpy.message.GroupMessage):
                            await self_event.bot.api.post_group_message(
                                group_openid=source.group_openid,
                                content=plain_text,
                                msg_type=0,
                                msg_id=self_event.message_obj.message_id,
                                msg_seq=hash(plain_text) % 10000 + 1,
                            )
                            return
                        elif isinstance(source, botpy.message.C2CMessage):
                            await QQOfficialMessageEvent.post_c2c_message(
                                self_event.bot,
                                openid=source.author.user_openid,
                                content=plain_text,
                                msg_type=0,
                                msg_id=self_event.message_obj.message_id,
                                msg_seq=hash(plain_text) % 10000 + 1,
                            )
                            return
                        elif isinstance(source, botpy.message.Message | botpy.message.DirectMessage):
                            await self_event.bot.api.post_message(
                                channel_id=source.channel_id,
                                content=plain_text,
                                msg_type=0,
                                msg_id=self_event.message_obj.message_id,
                            )
                            return
                    except Exception as e:
                        logger.warning(f"[TIMretry] 纯文本直发失败，回退原始流程: {e}")

            self_event.send_buffer = chain
            return await self._qq_send_original(self_event, chain)

        QQOfficialMessageEvent.send = send_with_tim_fix
        logger.info("[TIMretry] TIM 兼容补丁已启用 (钩 send()，纯文本直发 msg_type=0)")

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

    @filter.after_message_sent()
    async def on_after_sent(self, event: AstrMessageEvent) -> None:
        pass


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