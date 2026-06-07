#!/usr/bin/env python3
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None


INDEXES = [
    {"name": "上证指数", "symbol": "s_sh000001", "source": "sina_cn"},
    {"name": "沪深300", "symbol": "s_sh000300", "source": "sina_cn"},
    {"name": "创业板指", "symbol": "s_sz399006", "source": "sina_cn"},
    {"name": "纳斯达克综合指数", "symbol": "gb_ixic", "source": "sina_global"},
    {"name": "标普500", "symbol": "gb_inx", "source": "sina_global"},
]

DEFAULT_THRESHOLD = 1.0
DEFAULT_STATE_FILE = os.path.join(os.path.dirname(__file__), ".index_alert_state.json")


def env(name, default=None):
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        return default


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2, sort_keys=True)


def http_text(url, timeout=15):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 index-alert/1.0",
            "Accept": "text/javascript, text/plain, */*",
            "Referer": "https://finance.sina.com.cn",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("gbk", errors="replace")


def format_market_time(timestamp, timezone_name):
    if not timestamp:
        return "未知"
    if ZoneInfo and timezone_name:
        try:
            dt = datetime.fromtimestamp(timestamp, ZoneInfo(timezone_name))
            return dt.strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception:
            pass
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def market_date(timestamp, timezone_name):
    if not timestamp:
        return datetime.now().strftime("%Y-%m-%d")
    if ZoneInfo and timezone_name:
        try:
            return datetime.fromtimestamp(timestamp, ZoneInfo(timezone_name)).strftime("%Y-%m-%d")
        except Exception:
            pass
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")


def now_in_timezone(timezone_name):
    if ZoneInfo:
        try:
            return datetime.now(ZoneInfo(timezone_name))
        except Exception:
            pass
    return datetime.now()


def parse_sina_line(text, symbol):
    prefix = f"var hq_str_{symbol}=\""
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].split("\";", 1)[0].split(",")
    raise RuntimeError(f"行情返回中找不到 {symbol}")


def fetch_sina_cn_index(index):
    url = f"https://hq.sinajs.cn/list={index['symbol']}"
    fields = parse_sina_line(http_text(url), index["symbol"])
    if len(fields) < 4 or not fields[1]:
        raise RuntimeError(f"{index['name']} 行情字段不完整")

    current = float(fields[1])
    change = float(fields[2])
    percent = float(fields[3])
    previous_close = current - change
    dt = now_in_timezone("Asia/Shanghai")

    return {
        "name": index["name"],
        "symbol": index["symbol"],
        "current": current,
        "previous_close": previous_close,
        "percent": percent,
        "direction": "UP" if percent >= 0 else "DOWN",
        "market_time": dt.strftime("%Y-%m-%d %H:%M:%S CST"),
        "market_date": dt.strftime("%Y-%m-%d"),
    }


def fetch_sina_global_index(index):
    url = f"https://hq.sinajs.cn/list={index['symbol']}"
    fields = parse_sina_line(http_text(url), index["symbol"])
    if len(fields) < 5 or not fields[1]:
        raise RuntimeError(f"{index['name']} 行情字段不完整")

    current = float(fields[1])
    percent = float(fields[2])
    change = float(fields[4])
    previous_close = current - change
    market_time_text = fields[3]
    if not market_time_text and len(fields) > 25:
        market_time_text = fields[25]
    market_date_text = market_time_text[:10] if len(market_time_text) >= 10 else datetime.now().strftime("%Y-%m-%d")

    return {
        "name": index["name"],
        "symbol": index["symbol"],
        "current": current,
        "previous_close": previous_close,
        "percent": percent,
        "direction": "UP" if percent >= 0 else "DOWN",
        "market_time": market_time_text,
        "market_date": market_date_text,
    }


def fetch_index(index):
    if index["source"] == "sina_cn":
        return fetch_sina_cn_index(index)
    if index["source"] == "sina_global":
        return fetch_sina_global_index(index)
    raise RuntimeError(f"未知行情源: {index['source']}")


def dingtalk_signed_url(webhook, secret):
    timestamp = str(int(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), string_to_sign, hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(digest).decode("utf-8"))
    separator = "&" if "?" in webhook else "?"
    return f"{webhook}{separator}timestamp={timestamp}&sign={sign}"


def send_dingtalk(webhook, secret, content):
    url = dingtalk_signed_url(webhook, secret) if secret else webhook
    payload = json.dumps(
        {"msgtype": "text", "text": {"content": content}},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read().decode("utf-8")
    data = json.loads(body)
    if data.get("errcode") != 0:
        raise RuntimeError(f"钉钉发送失败: {body}")


def build_message(triggered, threshold, test=False):
    title = "指数提醒测试" if test else "指数波动提醒"
    lines = [
        f"{title}：以下指数涨跌幅已达到 {threshold:.2f}%。",
        "",
    ]
    for item in triggered:
        sign = "+" if item["percent"] >= 0 else ""
        lines.extend(
            [
                f"触发指数：{item['name']} ({item['symbol']})",
                f"当前点位：{item['current']:.2f}",
                f"涨跌幅：{sign}{item['percent']:.2f}%",
                f"上一交易日收盘价：{item['previous_close']:.2f}",
                f"行情时间：{item['market_time']}",
                "",
            ]
        )
    if test:
        lines.append("这是一条测试消息，不代表真实行情。")
    return "\n".join(lines).strip()


def should_notify(state, item):
    date_state = state.setdefault(item["market_date"], {})
    symbol_state = date_state.setdefault(item["symbol"], {})
    return not symbol_state.get(item["direction"])


def mark_notified(state, item):
    date_state = state.setdefault(item["market_date"], {})
    symbol_state = date_state.setdefault(item["symbol"], {})
    symbol_state[item["direction"]] = True


def main():
    webhook = env("DINGTALK_WEBHOOK")
    secret = env("DINGTALK_SECRET")
    threshold = float(env("INDEX_ALERT_THRESHOLD", str(DEFAULT_THRESHOLD)))
    state_file = env("INDEX_ALERT_STATE_FILE", DEFAULT_STATE_FILE)
    test_mode = env("INDEX_ALERT_TEST", "0") == "1"
    dry_run = env("INDEX_ALERT_DRY_RUN", "0") == "1"

    if not webhook and not dry_run:
        print("缺少环境变量 DINGTALK_WEBHOOK", file=sys.stderr)
        return 2

    if test_mode:
        triggered = [
            {
                "name": "测试指数",
                "symbol": "TEST",
                "current": 1012.30,
                "previous_close": 1000.00,
                "percent": 1.23,
                "direction": "UP",
                "market_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "market_date": datetime.now().strftime("%Y-%m-%d"),
            }
        ]
    else:
        state = read_json(state_file, {})
        triggered = []
        for index in INDEXES:
            item = fetch_index(index)
            print(
                f"{item['name']} {item['current']:.2f} "
                f"({item['percent']:+.2f}%) @ {item['market_time']}"
            )
            if abs(item["percent"]) >= threshold and should_notify(state, item):
                triggered.append(item)

        if not triggered:
            print("没有指数达到提醒阈值。")
            return 0

    message = build_message(triggered, threshold, test=test_mode)
    if dry_run:
        print(message)
        return 0

    send_dingtalk(webhook, secret, message)
    if not test_mode:
        state = read_json(state_file, {})
        for item in triggered:
            mark_notified(state, item)
        write_json(state_file, state)
    print("钉钉通知已发送。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
