#!/usr/bin/env python3
"""
HotPush 热榜定时推送脚本
默认通过 Server酱 推送到微信
"""

import os
import sys
import json
import subprocess
import urllib.request
import urllib.parse
import re
from datetime import datetime, timezone, timedelta

# ============ 配置区域 ============
HOTPUSH_USERNAME = os.environ.get("HOTPUSH_USERNAME", "hotx")
HOTPUSH_PASSWORD = os.environ.get("HOTPUSH_PASSWORD", "123456")
HOTPUSH_BASE_URL = "https://hotpush.dawenzaist.de5.net"

# Server酱: https://sct.ftqq.com/
SERVERCHAN_SENDKEY = os.environ.get("SERVERCHAN_SENDKEY", "")

# 以下渠道函数保留备用，当前主流程只使用 Server酱
# 企业微信机器人: 在群设置 -> 添加机器人 -> 获取Webhook地址
WECOM_WEBHOOK = os.environ.get("WECOM_WEBHOOK", "")

# wxpusher: https://wxpusher.zjiecode.com/
WXPUSHER_APPTOKEN = os.environ.get("WXPUSHER_APPTOKEN", "")
WXPUSHER_UIDS = os.environ.get("WXPUSHER_UIDS", "")  # 多个用逗号分隔

# PushPlus: https://www.pushplus.plus/
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")

# 推送内容设置
MAX_ITEMS_PER_SOURCE = int(os.environ.get("MAX_ITEMS_PER_SOURCE", "10"))  # 每个平台最多显示几条
SELECTED_SOURCES = os.environ.get("SELECTED_SOURCES", "")  # 留空则全部，或用逗号指定如 "weibo,zhihu,v2ex"

# ==================================


DEFAULT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
STATE_FILE = ".github/hotpush_state.json"
SLOT_WINDOWS = [
    ("morning", 9 * 60, 15),
    ("noon", 12 * 60, 15),
    ("evening", 21 * 60, 15),
]


def http_request(url, method="GET", headers=None, data=None, timeout=30, no_proxy=False):
    """发送HTTP请求

    Args:
        no_proxy: 设为 True 时绕过系统代理，直连目标服务器
    """
    req = urllib.request.Request(url, method=method)
    # 默认添加浏览器 User-Agent，避免被反爬拦截
    req.add_header("User-Agent", DEFAULT_USER_AGENT)
    req.add_header("Accept", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    if data and isinstance(data, dict):
        req.add_header("Content-Type", "application/json")
        data = json.dumps(data).encode("utf-8")
    elif data and isinstance(data, str):
        data = data.encode("utf-8")

    # 绕过代理时，临时清除代理环境变量
    if no_proxy:
        saved_proxy = {}
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
            val = os.environ.pop(key, None)
            if val is not None:
                saved_proxy[key] = val

    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            result = json.loads(body)
        except:
            result = {"error": body, "status": e.code}
    except Exception as e:
        result = {"error": str(e)}

    # 恢复代理环境变量
    if no_proxy:
        for key, val in saved_proxy.items():
            os.environ[key] = val

    return result


def login_hotpush():
    """登录 HotPush 获取 Token"""
    url = f"{HOTPUSH_BASE_URL}/api/auth/login"
    result = http_request(url, method="POST", headers={
        "Origin": HOTPUSH_BASE_URL,
        "Referer": f"{HOTPUSH_BASE_URL}/"
    }, data={
        "username": HOTPUSH_USERNAME,
        "password": HOTPUSH_PASSWORD
    })
    if result.get("success"):
        return result["token"]
    raise Exception(f"登录失败: {result.get('message', result)}")


def fetch_hot_list(token):
    """获取热榜数据"""
    url = f"{HOTPUSH_BASE_URL}/api/hot"
    result = http_request(url, headers={"Authorization": f"Bearer {token}"})
    if "data" in result:
        return result["data"]
    raise Exception(f"获取热榜失败: {result}")


def format_beijing_time(include_time=True):
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    date_text = f"{now.month:02d}月{now.day:02d}日"
    if include_time:
        return f"{date_text} {now.hour:02d}:{now.minute:02d}"
    return date_text


def get_beijing_now():
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz)


def get_current_slot(now=None):
    now = now or get_beijing_now()
    minute_of_day = now.hour * 60 + now.minute
    for slot_name, start_minute, duration in SLOT_WINDOWS:
        if start_minute <= minute_of_day < start_minute + duration:
            return slot_name
    return None


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)
        file.write("\n")


def should_skip_for_slot():
    now = get_beijing_now()
    slot_name = get_current_slot(now)
    if not slot_name:
        return True, f"当前时间 {now.strftime('%H:%M')} 不在推送窗口内", None, None

    today = now.strftime("%Y-%m-%d")
    state = load_state()
    if state.get(slot_name) == today:
        return True, f"今日 {slot_name} 时段已推送，跳过重复发送", slot_name, state

    return False, "", slot_name, state


def mark_slot_sent(slot_name, state):
    today = get_beijing_now().strftime("%Y-%m-%d")
    state[slot_name] = today
    save_state(state)


def run_git_command(args):
    subprocess.run(args, check=True)


def persist_state_file():
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    try:
        run_git_command(["git", "config", "user.name", "github-actions[bot]"])
        run_git_command(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"])
        run_git_command(["git", "add", STATE_FILE])
        diff_result = subprocess.run(["git", "diff", "--cached", "--quiet"])
        if diff_result.returncode == 0:
            return
        run_git_command(["git", "commit", "-m", "chore: update hotpush schedule state"])
        run_git_command(["git", "push"])
    except Exception as e:
        print(f"      ⚠️ 状态文件回写失败: {e}")


def clean_text(value):
    """清理推送文本，避免换行或 Markdown 特殊字符破坏格式"""
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def markdown_link(title, url):
    """生成 Server 酱可识别的 Markdown 链接"""
    title = clean_text(title) or "无标题"
    url = clean_text(url)
    if not url:
        return title
    safe_title = title.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    safe_title = safe_title.replace("(", "\\(").replace(")", "\\)")
    return f"[{safe_title}]({url})"


def format_message(data):
    """格式化热榜内容为 Server 酱 Markdown（每条热搜独立一行）"""
    date_str = format_beijing_time()

    selected = [s.strip() for s in SELECTED_SOURCES.split(",") if s.strip()] if SELECTED_SOURCES else None

    parts = []

    parts.append(f"## 今日热榜 ({date_str})")
    parts.append("")

    for source_data in data:
        source_id = source_data.get("source", "")
        source_name = source_data.get("source_name", source_id)
        items = source_data.get("items", [])

        if selected and source_id not in selected:
            continue
        if not items:
            continue

        parts.append(f"### {clean_text(source_name)}")
        parts.append("")

        display_items = items[:MAX_ITEMS_PER_SOURCE]
        for i, item in enumerate(display_items, 1):
            line = markdown_link(item.get("title", "无标题"), item.get("url", ""))
            hot_score = item.get("hot_score")
            if hot_score:
                line = f"{line} ({clean_text(hot_score)})"
            parts.append(f"{i}. {line}")

        if len(items) > MAX_ITEMS_PER_SOURCE:
            parts.append(f"... 共 {len(items)} 条")

        parts.append("")

    parts.append("*数据来源: HotPush*")

    return "\n".join(parts)


def format_html_message(data):
    """格式化热榜内容为 HTML（用于支持 HTML 的推送渠道）"""
    date_str = format_beijing_time()

    selected = [s.strip() for s in SELECTED_SOURCES.split(",") if s.strip()] if SELECTED_SOURCES else None

    html_parts = [
        f"<h2>🔥 今日热榜 ({date_str})</h2>",
        "<hr>"
    ]

    for source_data in data:
        source_id = source_data.get("source", "")
        source_name = source_data.get("source_name", source_id)
        items = source_data.get("items", [])

        if selected and source_id not in selected:
            continue
        if not items:
            continue

        html_parts.append(f"<h3>📌 {source_name}</h3>")
        html_parts.append("<ol>")

        display_items = items[:MAX_ITEMS_PER_SOURCE]
        for item in display_items:
            title = item.get("title", "无标题")
            url = item.get("url", "")
            hot_score = item.get("hot_score")
            if url:
                link = f'<a href="{url}">{title}</a>'
            else:
                link = title
            if hot_score:
                html_parts.append(f"<li>{link} <span style='color:#999'>[{hot_score}]</span></li>")
            else:
                html_parts.append(f"<li>{link}</li>")

        html_parts.append("</ol>")

        if len(items) > MAX_ITEMS_PER_SOURCE:
            html_parts.append(f"<p style='color:#999'>... 共 {len(items)} 条</p>")

    html_parts.append("<hr>")
    html_parts.append("<p style='color:#999;font-size:12px'>数据来源: HotPush</p>")

    return "\n".join(html_parts)


# ============ 推送渠道 ============

def push_serverchan(title, content):
    """Server酱推送"""
    if not SERVERCHAN_SENDKEY:
        return False, "未配置 SERVERCHAN_SENDKEY"
    url = f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send"
    result = http_request(url, method="POST", data={
        "title": title,
        "desp": content
    }, no_proxy=True)
    if result.get("code") == 0 or result.get("data", {}).get("error") == "SUCCESS":
        return True, "Server酱推送成功"
    return False, f"Server酱推送失败: {result}"


def push_wecom(title, content):
    """企业微信机器人推送"""
    if not WECOM_WEBHOOK:
        return False, "未配置 WECOM_WEBHOOK"
    result = http_request(WECOM_WEBHOOK, method="POST", data={
        "msgtype": "text",
        "text": {
            "content": f"{title}\n\n{content}"
        }
    }, no_proxy=True)
    if result.get("errcode") == 0:
        return True, "企业微信推送成功"
    return False, f"企业微信推送失败: {result}"


def push_wxpusher(title, content):
    """wxpusher推送"""
    if not WXPUSHER_APPTOKEN or not WXPUSHER_UIDS:
        return False, "未配置 WXPUSHER_APPTOKEN 或 WXPUSHER_UIDS"
    uids = [u.strip() for u in WXPUSHER_UIDS.split(",") if u.strip()]
    result = http_request("https://wxpusher.zjiecode.com/api/send/message", method="POST", data={
        "appToken": WXPUSHER_APPTOKEN,
        "content": content,
        "summary": title,
        "contentType": 1,
        "uids": uids
    }, no_proxy=True)
    if result.get("success"):
        return True, "wxpusher推送成功"
    return False, f"wxpusher推送失败: {result}"


def push_pushplus(title, content):
    """PushPlus推送"""
    if not PUSHPLUS_TOKEN:
        return False, "未配置 PUSHPLUS_TOKEN"
    result = http_request("https://www.pushplus.plus/send", method="POST", data={
        "token": PUSHPLUS_TOKEN,
        "title": title,
        "content": content,
        "template": "txt"
    }, no_proxy=True)
    if result.get("code") == 200:
        return True, "PushPlus推送成功"
    return False, f"PushPlus推送失败: {result}"


def push_all(title, text_content, html_content=None):
    """推送到 Server 酱"""
    ok, msg = push_serverchan(title, text_content)
    if not ok:
        raise Exception(msg)
    return msg


# ============ 主流程 ============

def main():
    print("=" * 50)
    print("HotPush 热榜推送任务开始")
    print("=" * 50)

    skip, reason, slot_name, state = should_skip_for_slot()
    if skip:
        print(f"      ℹ️ {reason}")
        return

    # 1. 登录
    print("[1/4] 正在登录 HotPush...")
    try:
        token = login_hotpush()
        print("      ✅ 登录成功")
    except Exception as e:
        print(f"      ❌ 登录失败: {e}")
        sys.exit(1)

    # 2. 获取热榜
    print("[2/4] 正在获取热榜数据...")
    try:
        data = fetch_hot_list(token)
        print(f"      ✅ 获取成功，共 {len(data)} 个数据源")
    except Exception as e:
        print(f"      ❌ 获取失败: {e}")
        sys.exit(1)

    # 3. 格式化消息
    print("[3/4] 正在格式化消息...")
    date_str = format_beijing_time(include_time=False)
    title = f"🔥 今日热榜 ({date_str})"
    text_content = format_message(data)
    print("      ✅ 格式化完成")

    # 4. 推送
    print("[4/4] 正在推送消息...")
    try:
        result = push_all(title, text_content)
        print(f"      ✅ {result}")
        mark_slot_sent(slot_name, state)
        persist_state_file()
    except Exception as e:
        print(f"      ❌ 推送失败: {e}")
        sys.exit(1)

    print("=" * 50)
    print("任务结束")
    print("=" * 50)


if __name__ == "__main__":
    main()
