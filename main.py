import os
import json
import hashlib
import smtplib
import requests
import feedparser
from datetime import datetime
from openai import OpenAI
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr
from bs4 import BeautifulSoup

# ================= 1. 配置区域 =================

API_KEY = os.environ.get("API_KEY")
API_BASE_URL = "https://api.deepseek.com"

SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
# 多个收件人支持
RECEIVER_EMAILS = os.environ.get("RECEIVER_EMAIL", "").split(",")

HISTORY_FILE = "news_history.json"

# 🔥 优化后的信源：移除 404，加入巨头动向
RSS_SOURCES = {
    # 1. 硬核 AI (Paper & Big Tech)
    "HARDCORE_AI": [
        "http://export.arxiv.org/rss/cs.AI",  # ArXiv AI
        "https://openai.com/news/rss.xml",  # OpenAI
        "https://research.google/blog/rss",  # Google DeepMind/Research (替代 PyTorch)
        "https://www.microsoft.com/en-us/research/feed/",  # Microsoft Research
        "https://huggingface.co/blog/feed.xml",  # Hugging Face
    ],
    # 2. 社区热议 (Reddit = 最佳的 Twitter 平替)
    "COMMUNITY_BUZZ": [
        "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day",  # 最硬核的大模型社区
        "https://www.reddit.com/r/MachineLearning/top/.rss?t=day",
        "https://news.ycombinator.com/rss",  # Hacker News
    ],
    # 3. 深度回顾
    "TECH_INSIGHTS": [
        "https://www.theverge.com/rss/index.xml",
    ]
}


# ================= 2. 爬虫工具 =================

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


def clean_text(html_content):
    if not html_content: return ""
    soup = BeautifulSoup(html_content, "html.parser")
    # 去除代码块等干扰，只留文本
    text = soup.get_text(separator=' ', strip=True)
    return text[:600] + "..."  # 稍微增加长度给 AI 分析


def fetch_data():
    print("🕷️ 正在抓取全球情报...")
    history = load_history()
    today_str = datetime.now().strftime("%Y-%m-%d")

    # 历史记录保留 3 天
    valid_history = {k: v for k, v in history.items()
                     if (datetime.now() - datetime.strptime(v, "%Y-%m-%d")).days < 3}

    collected = []

    # 伪装 Chrome
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    for category, urls in RSS_SOURCES.items():
        print(f"  👉 扫描: {category}...")
        for url in urls:
            try:
                resp = requests.get(url, headers=headers, timeout=20)
                if resp.status_code != 200:
                    continue  # 静默跳过错误源

                feed = feedparser.parse(resp.content)

                # 限制条数：AI类多取一点，其他少取一点
                limit = 3 if category == "HARDCORE_AI" else 2

                for entry in feed.entries[:limit]:
                    link = entry.link
                    uid = get_hash(link)

                    if uid in valid_history: continue
                    valid_history[uid] = today_str

                    content_raw = ""
                    if hasattr(entry, 'content'):
                        content_raw = entry.content[0].value
                    elif hasattr(entry, 'summary'):
                        content_raw = entry.summary
                    elif hasattr(entry, 'description'):
                        content_raw = entry.description

                    collected.append({
                        "category": category,
                        "title": entry.title,
                        "url": link,
                        "summary": clean_text(content_raw),
                        "source": feed.feed.title if hasattr(feed.feed, 'title') else "Web"
                    })
            except Exception as e:
                print(f"    ❌ Err: {url} -> {e}")

    return collected, valid_history


# ================= 3. AI 核心逻辑 (修复杂质) =================

def generate_newsletter(items):
    print(f"🧠 AI 正在深度分析 {len(items)} 条情报...")
    if not items: return None

    data_str = ""
    for i, item in enumerate(items, 1):
        data_str += f"[{i}] <{item['category']}> {item['title']}\n来源: {item['source']}\n内容: {item['summary']}\n链接: {item['url']}\n\n"

    client = OpenAI(api_key=API_KEY, base_url=API_BASE_URL)

    # 🚀 Prompt 重点修改：禁止输出任何非 HTML 内容
    prompt = f"""
    你是一个不仅懂技术，还懂传播学的科技主编。请根据素材编写今天的日报。

    【绝对指令】
    1. **只输出 HTML 代码**。不要输出 "好的，这是日报" 或者 "第一部分" 这种废话。
    2. 不要输出 markdown 标记（如 ```html）。

    【内容结构要求】
    请按照以下顺序生成三个 `div` 板块：

    **板块一：TL;DR (摘要)**
    - HTML结构: `<div class="section-tldr">...</div>`
    - 内容：用 `<ul><li>` 列表列出今天最重要的 3 个核心看点（用 Emoji 开头）。

    **板块二：Hardcore AI (硬核技术)**
    - HTML结构: `<div class="section-news"><h2>🧠 硬核 AI & 前沿</h2> ...具体新闻... </div>`
    - 内容：挑选最硬核的论文、开源模型、大厂动态。
    - 每条新闻用 `<div class="news-item">...</div>` 包裹。

    **板块三：Community Buzz (社区热议)**
    - HTML结构: `<div class="section-news"><h2>🔥 社区热议 (Twitter/Reddit 风向)</h2> ...具体新闻... </div>`
    - 内容：挑选最有争议、最有趣的社区讨论。语气要像推特大V点评一样犀利。

    【单条新闻 HTML 模板】
    <div class="news-item">
        <h3 class="title"><a href="URL" target="_blank">中文标题</a></h3>
        <div class="meta">
            <span class="source">来源媒体</span>
            <span class="read-time">预计阅读 2min</span>
        </div>
        <p class="summary">
           这里是内容摘要。如果是技术文章，请解释它牛在哪里；如果是讨论，请概括正反方观点。
        </p>
    </div>

    【素材】
    {data_str}
    """

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=4000
        )
        content = response.choices[0].message.content
        # 二次清洗，防止 AI 不听话
        content = content.replace("```html", "").replace("```", "").strip()
        # 如果 AI 还是输出了 "板块一" 这种字，强制去掉（通常 DeepSeek 很听话，不用正则也行）
        return content
    except Exception as e:
        print(f"AI Error: {e}")
        return None


# ================= 4. 邮件视觉升级 (高对比度) =================

def send_email(html_body):
    print("📧 正在发送...")

    # 🎨 CSS 视觉大改版：高对比度、纯黑文字
    css = """
    <style>
        /* 全局重置 */
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #f6f8fa; color: #1a1a1a; margin: 0; padding: 20px; line-height: 1.6; }
        .container { max-width: 680px; margin: 0 auto; background: #ffffff; border-radius: 12px; padding: 30px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }

        /* 头部 */
        .header { text-align: center; border-bottom: 2px solid #000; padding-bottom: 20px; margin-bottom: 30px; }
        .header h1 { font-size: 26px; font-weight: 900; letter-spacing: -0.5px; margin: 0; text-transform: uppercase; }
        .header p { color: #555; font-size: 14px; margin-top: 5px; }

        /* TL;DR 板块 (黄色背景高亮) */
        .section-tldr { background-color: #fff8c5; border: 1px solid #e1d68d; border-radius: 8px; padding: 15px 20px; margin-bottom: 30px; }
        .section-tldr ul { margin: 0; padding-left: 20px; }
        .section-tldr li { margin-bottom: 8px; font-weight: 600; color: #24292f; }

        /* 新闻板块标题 */
        h2 { font-size: 20px; font-weight: 800; border-left: 5px solid #0366d6; padding-left: 10px; margin-top: 40px; margin-bottom: 20px; color: #000; }

        /* 单条新闻卡片 */
        .news-item { margin-bottom: 25px; padding-bottom: 20px; border-bottom: 1px solid #eaeaea; }
        .news-item:last-child { border-bottom: none; }

        /* 标题链接 (强制纯黑，点击后不变色) */
        .title { margin: 0 0 8px 0; font-size: 18px; line-height: 1.4; font-weight: 700; }
        .title a { color: #000000 !important; text-decoration: none; border-bottom: 1px solid #ddd; transition: all 0.2s; }
        .title a:hover { color: #0366d6 !important; border-bottom: 2px solid #0366d6; }
        .title a:visited { color: #000000 !important; } 

        /* 元数据 */
        .meta { font-size: 12px; color: #666; margin-bottom: 8px; display: flex; gap: 10px; }
        .source { background: #f1f3f5; padding: 2px 6px; border-radius: 4px; font-weight: 500; }

        /* 摘要 (加深颜色) */
        .summary { color: #333333 !important; font-size: 15px; margin: 0; text-align: justify; }

        .footer { text-align: center; font-size: 12px; color: #999; margin-top: 40px; border-top: 1px solid #eee; padding-top: 20px; }
    </style>
    """

    full_html = f"""
    <html><head>{css}</head><body>
        <div class="container">
            <div class="header">
                <h1>AI Insider Daily</h1>
                <p>{datetime.now().strftime('%Y.%m.%d')} | Hardcore Tech & Community Buzz</p>
            </div>

            <!-- AI 生成的内容直接嵌入这里 -->
            {html_body}

            <div class="footer">
                Served by DeepSeek • GitHub Actions
            </div>
        </div>
    </body></html>
    """

    for receiver in RECEIVER_EMAILS:
        r = receiver.strip()
        if not r: continue
        try:
            msg = MIMEText(full_html, 'html', 'utf-8')
            msg['From'] = formataddr(("AI Insider", SENDER_EMAIL))
            msg['To'] = formataddr(("Reader", r))
            msg['Subject'] = Header(f"🔥 今日AI: {datetime.now().strftime('%m/%d')} 重点情报", 'utf-8')

            server = smtplib.SMTP_SSL("smtp.qq.com", 465)
            server.login(SENDER_EMAIL, EMAIL_PASSWORD)
            server.sendmail(SENDER_EMAIL, [r], msg.as_string())
            server.quit()
            print(f"✅ 发送给: {r}")
        except Exception as e:
            print(f"❌ 发送失败 ({r}): {e}")


if __name__ == "__main__":
    items, new_history = fetch_data()
    if items:
        report = generate_newsletter(items)
        if report:
            send_email(report)
            save_history(new_history)
    else:
        print("😴 无新内容")
