# TIMretry

QQ 官方机器人增强插件，解决两大痛点：

1. **TIM 消息兼容** — 猴补丁 `QQOfficialMessageEvent.send()`，强制 `send_buffer.use_markdown_ = False`，使消息以纯文本（msg_type=0）而非 Markdown（msg_type=2）发送，彻底解决 TIM 显示 `[暂不支持该消息类型，请用手机QQ查看]`
2. **DNS 自动重试** — 捕获 `ClientConnectorDNSError` / `OSError` / `ConnectionError`，指数退避重试

## 为什么 TIM 不兼容？

QQ 官方适配器在 `qqofficial_message_event.py` 中发送消息时：

```python
use_md = getattr(self.send_buffer, "use_markdown_", None)
if use_md is False:
    payload = {"content": plain_text, "msg_type": 0}   # ← 纯文本，TIM 兼容
else:
    payload = {"markdown": MarkdownPayload(...), "msg_type": 2}  # ← Markdown，TIM 不支持！
```

默认 `use_markdown_` 为 `None`，走 Markdown 路径。TIM 客户端不支持 Markdown 渲染 → 显示错误。

本插件在 `QQOfficialMessageEvent.send()` 入口强制设置 `send_buffer.use_markdown_ = False`，确保消息始终以纯文本发送。

> 注意：之前的 `on_decorating_result` 方案在流式输出时被 AstrBot 跳过（"流式输出已启用，跳过结果装饰阶段"），因此改用猴补丁方案。

## 安装

放入 AstrBot `data/plugins/` 目录，重启即可。

## 配置

| 参数 | 说明 | 默认值 |
|---|---|---|
| `max_retries` | DNS 重试次数 | 5 |
| `base_delay` | 基础延迟（秒） | 2.0 |
| `max_delay` | 延迟上限（秒） | 30.0 |

## 许可证

MIT