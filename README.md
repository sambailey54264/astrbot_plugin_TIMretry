# TIMretry

QQ 官方机器人增强插件，解决三大痛点：

1. **TIM 消息兼容** — 猴补丁 `QQOfficialMessageEvent._post_send()`，强制纯文本模式（msg_type=0）发送，彻底解决 TIM 显示 `[暂不支持该消息类型，请用手机QQ查看]`
2. **Markdown 格式清洗** — 可选开关，自动去除消息中的 Markdown 格式符号（粗体、标题、列表、链接等）
3. **DNS 自动重试** — 捕获 `ClientConnectorDNSError` / `OSError` / `ConnectionError`，指数退避重试

## 为什么 TIM 不兼容？

QQ 官方适配器在 `qqofficial_message_event.py` 中发送消息时：

```python
use_md = getattr(self.send_buffer, "use_markdown_", None)
if use_md is False:
    payload = {"content": plain_text, "msg_type": 0}   # ← 纯文本，TIM 兼容
else:
    payload = {"markdown": MarkdownPayload(...), "msg_type": 2}  # ← Markdown，TIM 不支持！
```

本插件在 `_post_send()` 入口强制设置 `use_markdown_ = False`。`_post_send()` 是 `send()` 和 `send_streaming()` 的共同出口，覆盖流式和非流式。

## 安装

放入 AstrBot `data/plugins/` 目录，重启即可。

或通过 WebUI → 插件管理 → 手动安装，填入仓库地址：

```
https://github.com/sambailey54264/astrbot_plugin_TIMretry
```

## 配置

| 参数 | 说明 | 默认值 |
|---|---|---|
| `strip_markdown` | 清洗 Markdown 格式符号 | 开启 |
| `max_retries` | DNS 重试次数 | 5 |
| `base_delay` | 基础延迟（秒） | 2.0 |
| `max_delay` | 延迟上限（秒） | 30.0 |

### Markdown 清洗范围

| 格式 | 示例 | 清洗后 |
|---|---|---|
| 粗体 | `**你好**` | 你好 |
| 斜体 | `*你好*` | 你好 |
| 删除线 | `~~错误~~` | 错误 |
| 行内代码 | `` `code` `` | code |
| 标题 | `## 标题` | 标题 |
| 列表 | `- 项目` / `1. 项目` | 项目 |
| 引用 | `> 引用` | 引用 |
| 链接 | `[文字](url)` | 文字 |
| 图片 | `![alt](url)` | alt |

## 相关链接

- AstrBot 主仓库：https://github.com/AstrBotDevs/AstrBot
- 相关 Issue：#7623 QQ官方机器人 DNS/连接重试

## 许可证

MIT