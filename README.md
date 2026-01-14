# 用友网络港股上市监控

Python + GitHub Actions 自动化监控用友网络（Yonyou）赴港上市关键节点。

## 功能特性

- **A 股公告监控**：巨潮资讯 H 股相关公告
- **智能过滤**：只捕捉关键上市事件，自动过滤噪音
- **持久化去重**：GitHub Actions 无状态环境下的公告去重
- **Telegram 推送**：实时消息推送
- **测试模式**：支持手动测试推送功能

> **注意**：港交所披露易（HKEXnews）监控已禁用，需要申请 API key 后方可启用。

## 监控的关键事件

| 事件类型 | 说明 |
|---------|------|
| Prospectus | 正式招股说明书 |
| Global Offering | 全球发售 |
| Price Range | 价格区间 |
| Allocation Results | 配售结果 |
| H股发行详情 | 发行数量、占总股本比例、价格 |

## 快速开始

### 1. 准备 Telegram Bot

```bash
# 1. 在 Telegram 中搜索 @BotFather
# 2. 发送 /newbot 创建 Bot，获取 Token
# 3. 给你的 Bot 发送任意消息（如：start）
# 4. 访问以下链接获取 Chat ID
curl https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
```

### 2. 配置 GitHub Secrets

在 GitHub 仓库设置中添加以下 Secrets：

| Secret 名称 | 值 |
|------------|---|
| `TELEGRAM_BOT_TOKEN` | 你的 Bot Token（格式：`123456789:ABC...`） |
| `TELEGRAM_CHAT_ID` | 你的 Chat ID（纯数字） |

### 3. 测试 Telegram 推送

1. 进入仓库 **Actions** 页面
2. 点击 **"Yonyou HK Listing Monitor"**
3. 点击 **"Run workflow"**
4. **勾选** "Test mode" ✅
5. 点击 **"Run workflow"**

如果配置正确，你会收到测试消息。

### 4. 启用自动监控

测试成功后，GitHub Actions 会按计划自动运行：
- **执行时间**：北京时间 08:00 - 22:00，每 2 小时一次
- **晚上不执行**：22:00 - 次日 08:00 休息

## 执行时间表

| 北京时间 | 执行 |
|----------|------|
| 08:00 | ✅ |
| 10:00 | ✅ |
| 12:00 | ✅ |
| 14:00 | ✅ |
| 16:00 | ✅ |
| 18:00 | ✅ |
| 20:00 | ✅ |
| 22:00 - 08:00 | ❌ 休息 |

## 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入你的配置

# 正常运行
python src/monitor.py

# 测试模式（发送测试消息）
TEST_MODE=true python src/monitor.py
```

## 项目结构

```
yonyou_hk_monitor/
├── .github/
│   └── workflows/
│       └── monitor.yml      # GitHub Actions 工作流
├── src/
│   └── monitor.py           # 主监控脚本
├── data/
│   └── seen_hashes.json     # 去重数据（自动生成）
├── requirements.txt         # Python 依赖
├── .env.example             # 环境变量模板
└── README.md
```

## 推送消息格式

```
【用友港股上市 · 关键进展】
事件：正式招股说明书（Prospectus）
日期：2026-XX-XX
来源：CNINFO
链接：https://...
重要性：HIGH
```

## 高级配置

### 修改执行频率

编辑 `.github/workflows/monitor.yml` 中的 `schedule` 部分：

```yaml
schedule:
  - cron: '0 0 * * *'   # UTC 00:00 = 北京时间 08:00
  - cron: '0 2 * * *'   # UTC 02:00 = 北京时间 10:00
  # ... 添加更多时间点
```

**注意**：GitHub Actions 使用 UTC 时区，北京时间 = UTC + 8

### 启用港交所监控

如需启用港交所披露易监控：

1. 访问 https://www.hkexnews.hk/ 申请 API key
2. 将 key 添加到 GitHub Secrets
3. 修改 `src/monitor.py` 中的 `HKEXMonitor` 类

## 故障排查

| 问题 | 解决方法 |
|------|----------|
| 收不到消息 | 检查 Telegram Token 和 Chat ID 是否正确 |
| Actions 运行失败 | 查看 Actions 日志中的错误信息 |
| 没有新公告 | 正常情况，只有在检测到关键事件时才会推送 |

## 许可证

MIT License
