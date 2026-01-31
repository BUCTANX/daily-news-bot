import os
import json
import hashlib
import smtplib
import feedparser
import requests  # 引入 requests 用于更强的伪装
import time
from datetime import datetime
from openai import OpenAI
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr
from bs4 import BeautifulSoup

# ================= 1. 全局配置 =================

API_KEY = os.environ.get("API_KEY")
API_BASE_URL = "https://api.deepseek.com"
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")

HISTORY_FILE = "news_history.json"

# 🔥 修复后的 RSS 源列表 (使用 RSSHub 镜像或更稳定的源)
RSS_SOURCES = {
    "Tech & AI": [
        "https://news.ycombinator.com/rss",  # Hacker News (极少封锁)
        # 替换 HF 为 ArXiv (CS.AI)，这是论文的源头，不会 401
        "http://export.arxiv.org/rss/cs.AI",
        # OpenAI 通常没有官方 RSS，这里使用第三方聚合或官方 Blog 的 XML
        "https://openai.com/news/rss.xml",
        # 替换 Anthropic 为 TechCrunch AI 板块，更稳定
        "https://techcrunch.com/category/artificial-intelligence/feed/",
    ],
    "Global News": [
        # 使用路透社的 RSSHub 镜像 (如果原版被封) 或者直接使用 Yahoo News (路透社源)
        "https://www.yahoo.com/news/rss/world",
        "http://feeds.bbci.co.uk/news/world/rss.xml",  # BBC 依然是最稳定的
    ],
    "Science": [
        "https://www.sciencedaily.com/rss/top/science.xml",
        "https://www.nature.com/nature.rss"
    ]
}


# ================= 2. 工具函数 =================

def get_hash(text):
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_history(history):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def clean_html(html_content):
    if not html_content: return ""
    soup = BeautifulSoup(html_content, "html.parser")
    text = soup.get_text()
    # 去除多余空行
    return " ".join(text.split())[:300].strip() + "..."


def fetch_rss_data():
    """使用 Requests + User-Agent 伪装抓取"""
    print("🌍 开始抓取 (已启用反爬伪装)...")
    history = load_history()
    today_str = datetime.now().strftime("%Y-%m-%d")

    valid_history = {k: v for k, v in history.items()
                     if (datetime.now() - datetime.strptime(v, "%Y-%m-%d")).days < 5}

    collected_items = []

    # 🕵️‍♂️ 关键修改：伪装成 Chrome 浏览器
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
    }

    for category, urls in RSS_SOURCES.items():
        print(f"  👉 正在扫描: {category}...")
        for url in urls:
            try:
                # 1. 先用 requests 下载内容 (绕过简单的 User-Agent 屏蔽)
                response = requests.get(url, headers=headers, timeout=10)

                if response.status_code != 200:
                    print(f"    ⚠️ 跳过 {url} (Status: {response.status_code})")
                    continue

                # 2. 再把下载到的内容喂给 feedparser
                feed = feedparser.parse(response.content)

                for entry in feed.entries[:3]:
                    link = entry.link
                    uid = get_hash(link)

                    if uid in valid_history:
                        continue

                    valid_history[uid] = today_str

                    # 尝试多种字段获取摘要
                    raw_summary = getattr(entry, 'summary',
                                          getattr(entry, 'description', ''))

                    collected_items.append({
                        "category": category,
                        "title": entry.title,
                        "url": link,
                        "summary": clean_html(raw_summary),
                        "source_name": feed.feed.title if 'title' in feed.feed else "News"
                    })
            except Exception as e:
                print(f"    ❌ 抓取错误 {url}: {e}")

    return collected_items, valid_history


# ================= 3. AI 分析核心 =================

def ai_analyze_report(items):
    print(f"🧠 AI 正在分析 {len(items)} 条情报...")
    if not items: return None

    input_text = ""
    for i, item in enumerate(items, 1):
        input_text += f"""
        【{i}】[{item['category']}] {item['title']}
        Link: {item['url']}
        Summary: {item['summary']}
        -----------------------------------
        """

    client = OpenAI(api_key=API_KEY, base_url=API_BASE_URL)

    # 提示词
    prompt = f"""
    你是一个专业的新闻分析师。请从以下数据中筛选 7-8 条最有价值的全球新闻（侧重科技突破和国际大事）。

    【输出要求】
    1. 直接输出 HTML 代码。
    2. 每一条新闻使用下面的 HTML 模板，不要改变 class 名称：

    <div class="news-card">
        <div class="card-header">
            <span class="category-tag">类别</span>
            <span class="source-tag">来源</span>
        </div>
        <h3 class="news-title"><a href="原文链接" target="_blank">中文标题</a></h3>
        <div class="news-content">
            <p><strong>💡 核心事实：</strong> 简述发生了什么。</p>
            <p><strong>📢 影响分析：</strong> 这件事为什么重要？</p>
        </div>
    </div>

    【原始数据】
    {input_text}
    """

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=3000
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ AI 接口错误: {e}")
        return None


# ================= 4. 邮件发送 =================

def send_email(html_content):
    print("📧 正在发送邮件...")
    # CSS 样式保持不变，为了节省篇幅这里省略，可以直接用之前代码里的 CSS
    css = """
    <style>
        body { font-family: Helvetica, Arial, sans-serif; background: #f4f4f4; padding: 20px; }
        .container { max-width: 700px; margin: 0 auto; background: #fff; padding: 20px; border-radius: 8px; }
        .news-card { border-bottom: 1px solid #eee; margin-bottom: 20px; padding-bottom: 20px; }
        .news-title { font-size: 18px; margin: 10px 0; }
        .news-title a { color: #333; text-decoration: none; }
        .category-tag { background: #007bff; color: white; padding: 2px 5px; font-size: 12px; border-radius: 3px; }
        .footer { text-align: center; color: #888; font-size: 12px; margin-top: 20px; }
    </style>
    """

    html_body = f"""
    <html><head>{css}</head><body>
    <div class="container">
        <h2>🌍 Global Daily Briefing ({datetime.now().strftime('%Y-%m-%d')})</h2>
        {html_content}
        <div class="footer">Powered by DeepSeek AI</div>
    </div>
    </body></html>
    """

    msg = MIMEText(html_body, 'html', 'utf-8')
    msg['From'] = formataddr(("DailyBot", SENDER_EMAIL))
    msg['To'] = formataddr(("Reader", RECEIVER_EMAIL))
    msg['Subject'] = Header(f"每日简报 - {datetime.now().strftime('%m/%d')}", 'utf-8')

    try:
        server = smtplib.SMTP_SSL("smtp.qq.com", 465)
        server.login(SENDER_EMAIL, EMAIL_PASSWORD)
        server.sendmail(SENDER_EMAIL, [RECEIVER_EMAIL], msg.as_string())
        server.quit()
        print("✅ 邮件发送成功！")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")


if __name__ == "__main__":
    items, new_history = fetch_rss_data()
    if not items:
        print("😴 无新内容")
        exit(0)

    report = ai_analyze_report(items)
    if report:
        send_email(report)
        save_history(new_history)
