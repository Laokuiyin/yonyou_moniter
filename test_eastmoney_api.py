#!/usr/bin/env python3
"""
测试东方财富API集成
"""

import sys
import os
from datetime import datetime, timedelta

# 添加src目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from monitor import AShareMonitor, DedupManager, EventAnalyzer
from pathlib import Path

def test_eastmoney_api():
    """测试东方财富API"""

    print("=" * 60)
    print("Testing Eastmoney API for Yonyou (600588)")
    print("=" * 60)

    # 创建临时去重管理器
    temp_dir = Path("./data/test")
    temp_dir.mkdir(parents=True, exist_ok=True)
    dedup = DedupManager(temp_dir / "test_hashes.json")

    # 初始化监控器（查询最近30天）
    monitor = AShareMonitor(dedup, days_back=30)

    print(f"\nStock: {monitor.STOCK_CODE}")
    print(f"API URL: {monitor.API_URL}")

    # 测试1: 最近30天的公告
    print("\n" + "=" * 60)
    print("Test 1: Last 30 days (full monitor_announcements)")
    print("=" * 60)

    results = monitor.monitor_announcements()

    print(f"\n{'=' * 60}")
    print(f"Results: {len(results)} H-share critical events found")
    print(f"{'=' * 60}")

    if results:
        for i, event in enumerate(results, 1):
            print(f"\n{i}. {event['title']}")
            print(f"   Date: {event['date']}")
            print(f"   Source: {event['source']}")
            print(f"   Event Type: {event['event_type']}")
            print(f"   URL: {event['url']}")
    else:
        print("\nNo H-share critical events found in the last 30 days.")
        print("This is normal if there are no recent H股 announcements.")

    # 测试2: 直接调用API查看所有公告
    print("\n" + "=" * 60)
    print("Test 2: Raw API call (all announcements)")
    print("=" * 60)

    params = {
        "sr": "-1",
        "page_size": "20",
        "page_index": "1",
        "ann_type": "A",
        "client_source": "web",
        "stock_list": monitor.STOCK_CODE,
        "f_node": "0",
        "s_node": "0"
    }

    response = monitor._call_api(params)
    if response and "data" in response:
        announcements = response["data"]["list"]
        print(f"\n✓ Found {len(announcements)} recent announcements")

        # 检查H股相关
        h_share_anns = [ann for ann in announcements if monitor._is_h_share_related(ann.get("title", ""))]
        print(f"H股相关公告: {len(h_share_anns)} 条")

        if h_share_anns:
            print("\nH股公告列表:")
            for i, ann in enumerate(h_share_anns, 1):
                title = ann.get("title", "")
                date = ann.get("notice_date", "").split()[0]
                print(f"  {i}. [{date}] {title}")
    else:
        print("❌ No response from API")

    return results

if __name__ == "__main__":
    try:
        test_eastmoney_api()
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
