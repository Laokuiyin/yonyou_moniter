#!/usr/bin/env python3
"""
用友网络港股上市监控脚本
监控港交所披露易(HKEXnews)和A股公告，捕捉关键上市节点事件
"""

import os
import json
import hashlib
import logging
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List, Set
import re

import requests
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.error import TelegramError

# =============================================================================
# Configuration
# =============================================================================

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Data persistence paths (GitHub Actions compatible)
DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
SEEN_HASHES_FILE = DATA_DIR / "seen_hashes.json"

# Request timeouts
REQUEST_TIMEOUT = 30
RETRY_ATTEMPTS = 3
RETRY_DELAY = 2

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


# =============================================================================
# Critical Event Keywords (必须捕捉的关键事件)
# =============================================================================

CRITICAL_KEYWORDS = {
    # 港交所相关
    "prospectus": ["PROSPECTUS", "招股说明书", "招股書"],
    "global_offering": ["GLOBAL OFFERING", "全球发售", "配售"],
    "price_range": ["PRICE RANGE", "价格区间", "发售区间", "发行价"],
    "allocation": ["ALLOCATION RESULT", "配售结果", "中签结果", "发售结果"],
    "h_share_details": ["H股", "H SHARE", "境外上市", "发行数量", "占总股本", "股份"],
}

# 排除关键词 (反噪音)
EXCLUDE_KEYWORDS = [
    "APPLICATION PROOF",
    "APPLICATION",
    "申请表格",
    "补递",
    "更正",
    "延期",
    "季度报告",
    "年度报告",
    "中期报告",
]

# 目标公司名称
TARGET_COMPANIES = ["用友", "YONYOU", "Yonyou"]


# =============================================================================
# Persistence Layer (持久化去重)
# =============================================================================

class DedupManager:
    """管理已处理公告的哈希去重系统"""

    def __init__(self, hash_file: Path):
        self.hash_file = hash_file
        self.seen_hashes: Set[str] = self._load_hashes()

    def _load_hashes(self) -> Set[str]:
        """从文件加载已处理的哈希"""
        if self.hash_file.exists():
            try:
                data = json.loads(self.hash_file.read_text(encoding="utf-8"))
                return set(data.get("hashes", []))
            except Exception as e:
                logger.warning(f"Failed to load hashes: {e}")
                return set()
        return set()

    def _save_hashes(self):
        """保存哈希到文件"""
        try:
            self.hash_file.parent.mkdir(parents=True, exist_ok=True)
            self.hash_file.write_text(
                json.dumps({"hashes": list(self.seen_hashes), "last_updated": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False),
                encoding="utf-8"
            )
            logger.debug(f"Saved {len(self.seen_hashes)} hashes")
        except Exception as e:
            logger.error(f"Failed to save hashes: {e}")

    def is_seen(self, item_id: str) -> bool:
        """检查是否已处理"""
        return item_id in self.seen_hashes

    def mark_seen(self, item_id: str):
        """标记为已处理"""
        self.seen_hashes.add(item_id)
        self._save_hashes()

    def generate_hash(self, title: str, date: str, url: str) -> str:
        """生成公告唯一标识"""
        content = f"{title}|{date}|{url}".encode("utf-8")
        return hashlib.sha256(content).hexdigest()[:16]


# =============================================================================
# HTTP Client with Retry
# =============================================================================

class Fetcher:
    """带重试和超时的HTTP请求器"""

    @staticmethod
    def get(url: str, headers: Optional[Dict] = None) -> Optional[requests.Response]:
        """GET请求with重试"""
        for attempt in range(RETRY_ATTEMPTS):
            try:
                response = requests.get(
                    url,
                    headers=headers or {},
                    timeout=REQUEST_TIMEOUT
                )
                response.raise_for_status()
                return response
            except requests.RequestException as e:
                logger.warning(f"Request failed (attempt {attempt + 1}/{RETRY_ATTEMPTS}): {e}")
                if attempt == RETRY_ATTEMPTS - 1:
                    logger.error(f"Failed to fetch {url}")
                    return None
        return None


# =============================================================================
# Event Analyzer
# =============================================================================

class EventAnalyzer:
    """分析公告是否为关键事件"""

    @staticmethod
    def contains_exclude_keywords(text: str) -> bool:
        """检查是否包含排除关键词"""
        text_upper = text.upper()
        for keyword in EXCLUDE_KEYWORDS:
            if keyword.upper() in text_upper:
                return True
        return False

    @staticmethod
    def identify_event_type(title: str, description: str = "") -> Optional[str]:
        """识别事件类型"""
        content = f"{title} {description}".upper()

        for event_type, keywords in CRITICAL_KEYWORDS.items():
            for keyword in keywords:
                if keyword.upper() in content:
                    return event_type

        return None

    @staticmethod
    def extract_advanced_info(text: str) -> Dict[str, str]:
        """提取高级信息（H股比例、价格等）"""
        info = {}

        # 提取百分比（H股发行比例）
        percentage_match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
        if percentage_match:
            info["percentage"] = percentage_match.group(1)
            try:
                if float(percentage_match.group(1)) >= 15:
                    info["dilution_warning"] = "稀释风险偏高"
            except ValueError:
                pass

        # 检测价格区间
        if any(keyword in text.upper() for keyword in ["PRICE RANGE", "价格区间", "发售区间"]):
            info["valuation_anchor"] = "估值锚已出现"

        return info


# =============================================================================
# HKEXnews Monitor
# =============================================================================

class HKEXMonitor:
    """港交所披露易监控"""

    BASE_URL = "https://www.hkexnews.hk"
    # 港交所搜索API v2
    SEARCH_API = f"{BASE_URL}/hkex_api/data/get/search"
    # 新上市页面
    NEW_LISTINGS_URL = f"{BASE_URL}/new-listing"

    def __init__(self, dedup: DedupManager):
        self.dedup = dedup

    def monitor_new_listings(self) -> List[Dict]:
        """监控新上市文件"""
        results = []

        # 方案1: 使用港交所搜索API
        try:
            logger.info("Trying HKEX search API v2...")
            results = self._fetch_search_api()
            if results:
                return results
        except Exception as e:
            logger.debug(f"Search API failed: {e}")

        # 方案2: 解析新上市页面HTML
        try:
            logger.info("Trying to parse new listings page...")
            results = self._fetch_new_listings_page()
        except Exception as e:
            logger.error(f"HKEX monitoring error: {e}")

        return results

    def _fetch_search_api(self) -> List[Dict]:
        """使用港交所搜索API v2"""
        url = self.SEARCH_API

        # 港交所搜索参数
        params = {
            "lang": "EN",
            "searchType": "ALL",
            "companyName": "Yonyou",
            "documentType": ["NEW_LISTING", "PROSPECTUS"],
            "size": 50
        }

        response = Fetcher.get(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )
        if not response:
            return []

        try:
            data = response.json()
            return self._parse_search_results(data)
        except Exception as e:
            logger.debug(f"Failed to parse JSON: {e}")
            return []

    def _fetch_new_listings_page(self) -> List[Dict]:
        """解析新上市页面"""
        url = self.NEW_LISTINGS_URL

        response = Fetcher.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            }
        )
        if not response:
            return []

        return self._parse_new_listings_html(response.text)

    def _parse_search_results(self, data: dict) -> List[Dict]:
        """解析搜索API结果"""
        results = []

        # 港交所API可能返回不同的结构
        if "hits" in data:
            items = data["hits"]
        elif "results" in data:
            items = data["results"]
        elif "data" in data:
            items = data["data"]
        else:
            items = []

        for item in items:
            if isinstance(item, dict):
                # 处理不同的字段名
                title = item.get("title") or item.get("docTitle") or item.get("header", "")
                date_str = item.get("date") or item.get("publishDate") or item.get("dateTime", "")
                url = item.get("url") or item.get("docLink") or item.get("link", "")

                if title and url:
                    parsed = self._process_item({
                        "title": title,
                        "date": date_str,
                        "url": url
                    })
                    if parsed:
                        results.append(parsed)

        return results

    def _parse_new_listings_html(self, html: str) -> List[Dict]:
        """解析新上市页面HTML"""
        results = []
        soup = BeautifulSoup(html, "html.parser")

        # 港交所新上市页面的选择器（需要根据实际页面调整）
        for row in soup.select("tr, .news-item, .listing-item, [class*='listing'], [class*='news']"):
            title_elem = row.select_one("a[href]")
            if not title_elem:
                continue

            title = title_elem.get_text(strip=True)
            link = title_elem.get("href", "")

            if not link:
                continue

            if link.startswith("/"):
                link = f"{self.BASE_URL}{link}"

            # 查找日期
            date_elem = row.select_one(".date, time, [class*='date'], [class*='time']")
            date_str = date_elem.get_text(strip=True) if date_elem else datetime.now().strftime("%Y-%m-%d")

            parsed = self._process_item({
                "title": title,
                "date": date_str,
                "url": link
            })

            if parsed:
                results.append(parsed)

        return results

    def _process_item(self, item: Dict) -> Optional[Dict]:
        """处理单个公告项"""
        title = item.get("title", "")
        date_str = item.get("date", "")
        url = item.get("url", "")

        # 检查公司名称匹配
        if not any(company.lower() in title.lower() for company in TARGET_COMPANIES):
            return None

        # 排除噪音
        if EventAnalyzer.contains_exclude_keywords(title):
            logger.debug(f"Excluded by keywords: {title}")
            return None

        # 去重
        item_hash = self.dedup.generate_hash(title, date_str, url)
        if self.dedup.is_seen(item_hash):
            logger.debug(f"Already seen: {title}")
            return None

        # 识别事件类型
        event_type = EventAnalyzer.identify_event_type(title)
        if not event_type:
            logger.debug(f"No critical event matched: {title}")
            return None

        self.dedup.mark_seen(item_hash)

        return {
            "source": "HKEXnews",
            "title": title,
            "date": date_str,
            "url": url,
            "event_type": event_type,
            "importance": "HIGH"
        }


# =============================================================================
# A-Share Announcement Monitor
# =============================================================================

class AShareMonitor:
    """A股公告监控（上交所/巨潮资讯）"""

    def __init__(self, dedup: DedupManager):
        self.dedup = dedup

    def monitor_announcements(self) -> List[Dict]:
        """监控H股相关公告"""
        results = []

        # 巨潮资讯搜索URL
        search_urls = [
            "http://www.cninfo.com.cn/new/fulltextSearch?notautosubmit=&keyword=Yonyou",
            "http://www.cninfo.com.cn/new/fulltextSearch?notautosubmit=&keyword=用友网络",
        ]

        for url in search_urls:
            try:
                response = Fetcher.get(url, headers={"Accept-Language": "zh-CN,zh;q=0.9"})
                if not response:
                    continue

                items = self._parse_cninfo(response.text)
                results.extend(items)

            except Exception as e:
                logger.error(f"A-share monitoring error for {url}: {e}")

        return results

    def _parse_cninfo(self, html: str) -> List[Dict]:
        """解析巨潮资讯响应"""
        results = []
        soup = BeautifulSoup(html, "html.parser")

        for item in soup.select(".result-item, .news-item, tr"):
            title_elem = item.select_one("a[title], .title")
            date_elem = item.select_one(".date, time")
            link_elem = item.select_one("a[href]")

            if not title_elem or not link_elem:
                continue

            title = title_elem.get_text(strip=True) or title_elem.get("title", "").strip()
            date_str = date_elem.get_text(strip=True) if date_elem else datetime.now().strftime("%Y-%m-%d")
            link = link_elem.get("href", "")

            # 只处理H股相关公告
            if not any(kw in title.upper() for kw in ["H股", "H SHARE", "境外上市", "香港"]):
                continue

            # 排除噪音
            if EventAnalyzer.contains_exclude_keywords(title):
                continue

            # 去重
            item_hash = self.dedup.generate_hash(title, date_str, link)
            if self.dedup.is_seen(item_hash):
                continue

            # 识别事件类型
            event_type = EventAnalyzer.identify_event_type(title)
            if not event_type:
                continue

            self.dedup.mark_seen(item_hash)

            results.append({
                "source": "CNINFO",
                "title": title,
                "date": date_str,
                "url": link,
                "event_type": event_type,
                "importance": "HIGH"
            })

        return results


# =============================================================================
# Telegram Notifier
# =============================================================================

class TelegramNotifier:
    """Telegram推送通知"""

    def __init__(self):
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")

        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
        self.chat_id = TELEGRAM_CHAT_ID

    def send_alert(self, event: Dict):
        """发送事件提醒"""
        message = self._format_message(event)

        try:
            # 使用 asyncio 运行异步方法
            asyncio.run(self._send_message_async(message))
            logger.info(f"Alert sent: {event['title'][:50]}")
        except Exception as e:
            logger.error(f"Telegram error: {e}")

    async def _send_message_async(self, message: str):
        """异步发送消息"""
        await self.bot.send_message(
            chat_id=self.chat_id,
            text=message,
            parse_mode=None,  # 使用纯文本，避免 Markdown 解析错误
            disable_web_page_preview=True
        )

    def _format_message(self, event: Dict) -> str:
        """格式化推送消息"""
        event_type_names = {
            "prospectus": "正式招股说明书（Prospectus）",
            "global_offering": "全球发售 / Global Offering",
            "price_range": "价格区间 / Price Range",
            "allocation": "配售结果 / Allocation Results",
            "h_share_details": "H股发行详情",
        }

        event_name = event_type_names.get(event["event_type"], event["event_type"])

        message = f"""【用友港股上市 · 关键进展】
事件：{event_name}
日期：{event['date']}
来源：{event['source']}
链接：{event['url']}
重要性：{event['importance']}"""

        # 添加高级信息
        advanced_info = EventAnalyzer.extract_advanced_info(event["title"])
        if advanced_info:
            message += "\n\n附加信息："
            for key, value in advanced_info.items():
                message += f"\n  • {value}"

        return message


# =============================================================================
# Main Orchestrator
# =============================================================================

def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("Yonyou HK Listing Monitor Started")
    logger.info("=" * 60)

    # 检查是否为测试模式
    test_mode = os.getenv("TEST_MODE", "false").lower() == "true"

    if test_mode:
        logger.info("Running in TEST MODE - sending test notification...")
        try:
            notifier = TelegramNotifier()
            test_event = {
                "source": "TEST",
                "title": "【测试】用友港股上市监控系统",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "url": "https://github.com/Laokuiyin/yonyou_moniter",
                "event_type": "prospectus",
                "importance": "TEST"
            }
            notifier.send_alert(test_event)
            logger.info("Test notification sent successfully!")
        except Exception as e:
            logger.error(f"Test notification failed: {e}")
        logger.info("Test completed")
        return

    # 初始化去重管理器
    dedup = DedupManager(SEEN_HASHES_FILE)
    logger.info(f"Loaded {len(dedup.seen_hashes)} seen hashes")

    all_events = []

    # 港交所监控已禁用（需要申请 API key）
    logger.info("HKEXnews monitoring: DISABLED (requires API key registration)")
    logger.info("To enable HKEX monitoring, register at: https://www.hkexnews.hk/")

    # 监控A股公告
    logger.info("Monitoring A-share announcements...")
    ashare_monitor = AShareMonitor(dedup)
    ashare_events = ashare_monitor.monitor_announcements()
    logger.info(f"A-share: {len(ashare_events)} new critical events")
    all_events.extend(ashare_events)

    if not all_events:
        logger.info("No new critical events found")
        return

    # 发送通知
    logger.info(f"Sending {len(all_events)} notifications...")
    try:
        notifier = TelegramNotifier()
        for event in all_events:
            notifier.send_alert(event)
    except Exception as e:
        logger.error(f"Notification failed: {e}")

    logger.info("Monitoring completed")


if __name__ == "__main__":
    main()
