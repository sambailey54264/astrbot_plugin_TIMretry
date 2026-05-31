# TIMretry

QQ 官方机器人增强插件，解决三大痛点：

1. **TIM 消息兼容** — 钩 `QQOfficialMessageEvent.send()`，纯文本消息直接以 `msg_type=0` 调 QQ API，彻底解决 TIM 显示 `[暂不支持该消息类型，请用手机QQ查看]`
2. **Markdown 格式清洗** — 可选开关，自动去除 Markdown 格式符号（粗体、标题、列表、链接等）
3. **DNS 自动重试** — 捕获 `ClientConnectorDNSError` / `OSError` / `ConnectionError`，指数退避重试

## 安装

放入 AstrBot `data/plugins/` 目录，重启即可。或 WebUI 手动安装填入：

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

## 更新日志

### v1.1.0
- 修复 `MessageChain` 不可迭代导致 `TypeError`
- 修复 `post_c2c_message` 的 `SimpleNamespace` 包装问题
- 修复直发后缺少 `_has_send_oper` 标记导致消息被 LLM 二次处理

### v1.0.0
- 初始版本：TIM 纯文本兼容 + Markdown 清洗 + DNS 重试

## 许可证

MIT
