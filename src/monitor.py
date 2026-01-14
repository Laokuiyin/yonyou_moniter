#!/usr/bin/env python3
"""
用友网络港股上市监控脚本
监控港交所披露易(HKEXnews)和A股公告，捕捉关键上市节点事件
"""

import os
import json
import hashlib
import logging
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
    # 使用港交所披露易搜索API
    SEARCH_API = f"{BASE_URL}/hkex/web/special-news-api"
    # RSS订阅源（备用）
    RSS_URL = f"{BASE_URL}/di/rss/rss.asp"

    def __init__(self, dedup: DedupManager):
        self.dedup = dedup

    def monitor_new_listings(self) -> List[Dict]:
        """监控新上市文件"""
        results = []

        # 方案1: 使用RSS订阅源（更稳定）
        try:
            logger.info("Trying RSS feed...")
            results = self._fetch_rss_feed()
            if results:
                return results
        except Exception as e:
            logger.debug(f"RSS feed failed: {e}")

        # 方案2: 使用搜索API（POST请求）
        try:
            logger.info("Trying search API...")
            results = self._fetch_search_api()
        except Exception as e:
            logger.error(f"HKEX monitoring error: {e}")

        return results

    def _fetch_rss_feed(self) -> List[Dict]:
        """使用RSS订阅源获取最新公告"""
        # RSS URL: 搜索包含"Yonyou"的公司公告
        url = f"{self.BASE_URL}/di/rss/rss.asp?alertId=1&companyName=Yonyou&documentType=NEW_LISTING"

        response = Fetcher.get(url, headers={"Accept": "application/rss+xml, text/xml"})
        if not response:
            return []

        return self._parse_rss(response.text)

    def _fetch_search_api(self) -> List[Dict]:
        """使用港交所搜索API"""
        url = self.SEARCH_API

        # 构造搜索参数
        params = {
            "lang": "EN",
            "searchType": "ALL",
            "companyName": "Yonyou",
            "documentType": "NEW_LISTING",
            "pageSize": 50
        }

        response = Fetcher.get(url, headers={"Accept": "application/json"})
        if not response:
            return []

        return self._parse_json_response(response.json())

    def _parse_rss(self, rss_content: str) -> List[Dict]:
        """解析RSS内容"""
        results = []
        soup = BeautifulSoup(rss_content, "xml") or BeautifulSoup(rss_content, "html.parser")

        for item in soup.find_all("item")[:50]:  # 限制50条
            title = item.find("title")
            link = item.find("link")
            pub_date = item.find("pubDate")

            if not title or not link:
                continue

            title_text = title.get_text(strip=True)
            link_text = link.get_text(strip=True)
            date_text = pub_date.get_text(strip=True) if pub_date else datetime.now().strftime("%Y-%m-%d")

            parsed = self._process_item({
                "title": title_text,
                "url": link_text,
                "date": date_text
            })

            if parsed:
                results.append(parsed)

        return results

    def _parse_json_response(self, data: dict) -> List[Dict]:
        """解析JSON响应"""
        results = []
        # 根据实际API结构调整
        for item in data.get("results", []):
            parsed = self._process_item(item)
            if parsed:
                results.append(parsed)
        return results

    def _parse_html_response(self, html: str) -> List[Dict]:
        """解析HTML响应"""
        results = []
        soup = BeautifulSoup(html, "html.parser")

        # 根据实际HTML结构调整选择器
        for row in soup.select("tr.search-item, .news-item, .listing-item"):
            title_elem = row.select_one("a[title], .title, .news-title")
            date_elem = row.select_one(".date, .news-date, time")
            link_elem = row.select_one("a[href]")

            if not title_elem or not link_elem:
                continue

            title = title_elem.get_text(strip=True) or title_elem.get("title", "").strip()
            date_str = date_elem.get_text(strip=True) if date_elem else datetime.now().strftime("%Y-%m-%d")
            link = link_elem.get("href", "")

            if link.startswith("/"):
                link = f"{self.BASE_URL}{link}"

            item = {"title": title, "date": date_str, "url": link}
            parsed = self._process_item(item)
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
            self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
            logger.info(f"Alert sent: {event['title'][:50]}")
        except TelegramError as e:
            logger.error(f"Telegram error: {e}")

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

    # 初始化去重管理器
    dedup = DedupManager(SEEN_HASHES_FILE)
    logger.info(f"Loaded {len(dedup.seen_hashes)} seen hashes")

    # 监控港交所
    logger.info("Monitoring HKEXnews...")
    hkex_monitor = HKEXMonitor(dedup)
    hkex_events = hkex_monitor.monitor_new_listings()
    logger.info(f"HKEXnews: {len(hkex_events)} new critical events")

    # 监控A股公告
    logger.info("Monitoring A-share announcements...")
    ashare_monitor = AShareMonitor(dedup)
    ashare_events = ashare_monitor.monitor_announcements()
    logger.info(f"A-share: {len(ashare_events)} new critical events")

    # 汇总事件
    all_events = hkex_events + ashare_events

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
