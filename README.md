# 用友网络港股上市监控

Python + GitHub Actions 自动化监控用友网络（Yonyou）赴港上市关键节点。

## 功能特性

- **双源监控**：港交所披露易（HKEXnews）+ A股公告（巨潮资讯）
- **智能过滤**：只捕捉关键上市事件，自动过滤噪音
- **持久化去重**：GitHub Actions 无状态环境下的公告去重
- **Telegram 推送**：结构化消息推送

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
# 1. 找 @BotFather 创建 Bot，获取 Token
# 2. 发送消息给你的 Bot
# 3. 访问以下链接获取 Chat ID
curl https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
```

### 2. 配置 GitHub Secrets

在 GitHub 仓库设置中添加以下 Secrets：

| Secret 名称 | 值 |
|------------|---|
| `TELEGRAM_BOT_TOKEN` | 你的 Bot Token |
| `TELEGRAM_CHAT_ID` | 你的 Chat ID |

### 3. 推送代码到 GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/yonyou-hk-monitor.git
git push -u origin main
```

### 4. 启用 GitHub Actions

推送代码后，GitHub Actions 会自动开始运行：
- **定时执行**：每 2 小时检查一次
- **手动触发**：在 Actions 页面点击 "Run workflow"

## 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入你的配置

# 运行监控
python src/monitor.py
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
来源：HKEXnews
链接：https://...
重要性：HIGH

附加信息：
  • 稀释风险偏高
```

## 许可证

MIT License
