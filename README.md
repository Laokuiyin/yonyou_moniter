# 用友网络港股上市监控

Python + GitHub Actions 自动化监控用友网络（Yonyou）赴港上市关键节点。

## 功能特性

- **A 股公告监控**：东方财富网 H 股相关公告
- **智能过滤**：只捕捉关键上市事件，自动过滤噪音
- **持久化去重**：GitHub Actions 无状态环境下的公告去重
- **多平台推送**：支持 Telegram、飞书，可同时使用或二选一
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

### 方案一：使用飞书推送（推荐）

#### 1. 准备飞书机器人

```bash
# 1. 在飞书中创建一个群聊（可以只有你自己）
# 2. 进入群聊，点击右上角 "..." → 群机器人
# 3. 点击 "添加机器人" → 选择 "自定义机器人"
# 4. 设置机器人名称和描述，点击 "添加"
# 5. 复制生成的 Webhook URL（格式：https://open.feishu.cn/open-apis/bot/v2/hook/xxx）
```

#### 2. 配置 GitHub Secrets

在 GitHub 仓库设置中添加以下 Secret：

| Secret 名称 | 值 |
|------------|---|
| `FEISHU_WEBHOOK_URL` | 飞书机器人的 Webhook URL |

### 方案二：使用 Telegram 推送

#### 1. 准备 Telegram Bot

```bash
# 1. 在 Telegram 中搜索 @BotFather
# 2. 发送 /newbot 创建 Bot，获取 Token
# 3. 给你的 Bot 发送任意消息（如：start）
# 4. 访问以下链接获取 Chat ID
curl https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
```

#### 2. 配置 GitHub Secrets

在 GitHub 仓库设置中添加以下 Secrets：

| Secret 名称 | 值 |
|------------|---|
| `TELEGRAM_BOT_TOKEN` | 你的 Bot Token（格式：`123456789:ABC...`） |
| `TELEGRAM_CHAT_ID` | 你的 Chat ID（纯数字） |

> **提示**：你可以同时配置 Telegram 和飞书，系统会向两个平台都发送通知。

### 3. 测试推送功能

1. 进入仓库 **Actions** 页面
2. 点击 **"Yonyou HK Listing Monitor"**
3. 点击 **"Run workflow"**
4. **勾选** "Test mode" ✅
5. 点击 **"Run workflow"**

如果配置正确，你会在飞书/Telegram 收到测试消息。

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
来源：EASTMONEY
链接：https://...
重要性：HIGH
```

## 技术说明

### 数据源

- **东方财富网 API**：用于获取A股公告（用友网络 600588）
  - 稳定可靠，无需额外认证
  - 只需股票代码即可查询
  - 支持查询最近N天的公告（默认7天）

- **港交所披露易（已禁用）**：需要申请 API key 后方可启用
  - 访问 https://www.hkexnews.hk/ 申请
  - 在 `src/monitor.py` 中取消注释 `HKEXMonitor` 相关代码

### 测试API连接

项目提供了测试脚本验证API功能：

```bash
# 测试东方财富API
python test_eastmoney_api.py
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

## 故障排查

| 问题 | 解决方法 |
|------|----------|
| 收不到飞书消息 | 检查 Webhook URL 是否正确，确认机器人没有被移除 |
| 收不到 Telegram 消息 | 检查 Token 和 Chat ID 是否正确，确认给 Bot 发送过消息 |
| Actions 运行失败 | 查看 Actions 日志中的错误信息 |
| 没有新公告 | 正常情况，只有在检测到关键事件时才会推送 |

## 许可证

MIT License
