import os
import json
import hashlib
import smtplib
import feedparser
import time
from datetime import datetime
from openai import OpenAI
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr
from bs4 import BeautifulSoup

# ================= 1. 全局配置 =================

# API 和 邮件配置
API_KEY = os.environ.get("API_KEY")
API_BASE_URL = "https://api.deepseek.com"
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")

HISTORY_FILE = "news_history.json"

# 🔥 升级后的高质量、无审查、全球化信源
RSS_SOURCES = {
    # 1. 核心前沿科技 (硬核、一手)
    "Hardcore Tech": [
        "https://news.ycombinator.com/rss",  # Hacker News (硅谷风向标)
        "https://huggingface.co/papers/rss",  # Hugging Face Papers (最新 AI 论文)
        "https://openai.com/news/rss.xml",  # OpenAI Blog
        "https://www.anthropic.com/rss",  # Anthropic Blog
    ],
    # 2. 深度科技新闻 (行业分析)
    "Tech News": [
        "https://www.theverge.com/rss/index.xml",  # The Verge (高质量科技评论)
        "https://techcrunch.com/feed/",  # TechCrunch (创投)
    ],
    # 3. 全球局势 (客观、中立、权威)
    "World News": [
        "http://feeds.bbci.co.uk/news/world/rss.xml",  # BBC World
        "https://www.reutersagency.com/feed/?best-topics=politics&post_type=best",  # 路透社 (事实核查标准极高)
    ],
    # 4. 金融与市场
    "Finance": [
        "https://feeds.bloomberg.com/markets/news.rss",  # Bloomberg Markets
    ],
    # 5. 前沿科学
    "Science": [
        "https://www.sciencedaily.com/rss/top/science.xml",  # Science Daily
        "https://www.nature.com/nature.rss"  # Nature Journal
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
    """简单的 HTML 清洗，去除标签只留文字"""
    if not html_content: return ""
    soup = BeautifulSoup(html_content, "html.parser")
    return soup.get_text()[:300].strip() + "..."  # 限制长度，节省 Token


def fetch_rss_data():
    """抓取所有 RSS 源"""
    print("🌍 开始全球数据抓取...")
    history = load_history()
    today_str = datetime.now().strftime("%Y-%m-%d")

    # 清理 5 天前的历史记录 (保持文件精简)
    valid_history = {k: v for k, v in history.items()
                     if (datetime.now() - datetime.strptime(v, "%Y-%m-%d")).days < 5}

    collected_items = []

    # 设置请求头，防止部分网站反爬
    feedparser.USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

    for category, urls in RSS_SOURCES.items():
        print(f"  👉 正在扫描: {category}...")
        for url in urls:
            try:
                # 增加超时设置
                feed = feedparser.parse(url)

                # 如果抓取失败（状态码非200）
                if hasattr(feed, 'status') and feed.status != 200:
                    print(f"    ⚠️ 跳过 {url} (Status: {feed.status})")
                    continue

                # 每个源只取前 3 条最新的
                for entry in feed.entries[:3]:
                    link = entry.link
                    uid = get_hash(link)

                    if uid in valid_history:
                        continue

                    valid_history[uid] = today_str

                    # 智能获取摘要 (summary -> description -> content)
                    raw_summary = getattr(entry, 'summary',
                                          getattr(entry, 'description',
                                                  getattr(entry, 'content', [{'value': ''}])[0]['value']))

                    summary_text = clean_html(raw_summary)
                    if not summary_text: summary_text = "No summary available."

                    title_text = entry.title
                    source_name = feed.feed.title if 'title' in feed.feed else "Unknown Source"

                    collected_items.append({
                        "category": category,
                        "title": title_text,
                        "url": link,
                        "summary": summary_text,
                        "source_name": source_name
                    })
            except Exception as e:
                print(f"    ❌ 解析错误 {url}: {e}")

    return collected_items, valid_history


# ================= 3. AI 分析核心 (修复报错) =================

def ai_analyze_report(items):
    """DeepSeek 聚合分析"""
    print(f"🧠 AI 正在分析 {len(items)} 条全球情报...")
    if not items: return None

    # 构建输入给 AI 的文本
    input_text = ""
    for i, item in enumerate(items, 1):
        input_text += f"""
        【{i}】类别: {item['category']} | 来源: {item['source_name']}
        标题: {item['title']}
        链接: {item['url']}
        摘要: {item['summary']}
        -----------------------------------
        """

    client = OpenAI(api_key=API_KEY, base_url=API_BASE_URL)

    # 🎯 修复点：移除了 f-string 中的 HTML 示例变量，改用 {{}} 转义或纯文本描述
    prompt = f"""
    你是一位具有全球视野的【高级情报分析师】。请阅读以下未经筛选的原始新闻数据。

    【原始数据】
    {input_text}

    【任务目标】
    1. 剔除无关紧要、重复或低质量的软文。
    2. 筛选出 **最重要、最具洞察力** 的 7-9 条新闻。
    3. 重点关注：颠覆性的 AI 技术、重大的地缘政治变动（客观视角）、关键的全球金融趋势、前沿科学突破。
    4. 将内容翻译并总结为中文。

    【输出格式要求】
    请直接返回 HTML 代码（不要使用 Markdown 代码块标记）。
    每条新闻请严格按照以下 HTML 结构模板生成（请将模板中的说明文字替换为实际内容）：

    <div class="news-card">
        <div class="card-header">
            <span class="category-tag">这里填新闻类别(如: Hardcore Tech)</span>
            <span class="source-tag">这里填来源媒体(如: Reuters)</span>
        </div>
        <h3 class="news-title"><a href="这里填原文URL" target="_blank">这里填中文标题</a></h3>
        <div class="news-content">
            <p><strong>🧐 深度解读：</strong> 用通俗、客观的语言解释该事件的核心逻辑。如果是科技新闻，解释技术原理；如果是时政，解释背景和影响。</p>
            <p><strong>🚀 关键点：</strong> 提炼 1-2 个最值得关注的数据或事实。</p>
        </div>
    </div>

    请确保 HTML 语法正确，不要包含 ```html ... ```。
    """

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=4000  # 保证输出够长
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ AI 接口调用失败: {e}")
        return None


# ================= 4. 邮件发送 =================

def send_email(html_content):
    print("📧 正在构建并发送邮件...")

    # 极简主义 CSS 风格
    css = """
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #f4f4f4; padding: 20px; color: #333; }
        .container { max-width: 680px; margin: 0 auto; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
        .header { background: #000; color: #fff; padding: 30px 20px; text-align: center; }
        .header h1 { margin: 0; font-size: 24px; font-weight: 700; letter-spacing: 1px; }
        .header p { margin: 8px 0 0; font-size: 14px; color: #888; text-transform: uppercase; }
        .content { padding: 25px; }

        .news-card { margin-bottom: 30px; border-bottom: 1px solid #eaeaea; padding-bottom: 20px; }
        .news-card:last-child { border-bottom: none; margin-bottom: 0; }

        .card-header { font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; color: #666; }
        .category-tag { font-weight: bold; color: #007bff; margin-right: 8px; }
        .source-tag { color: #999; }

        .news-title { margin: 0 0 12px; font-size: 20px; line-height: 1.4; font-weight: 600; }
        .news-title a { color: #111; text-decoration: none; border-bottom: 2px solid transparent; transition: border-color 0.2s; }
        .news-title a:hover { border-color: #007bff; }

        .news-content p { margin: 8px 0; font-size: 15px; line-height: 1.7; color: #444; text-align: justify; }
        strong { color: #000; font-weight: 600; }

        .footer { background: #f9f9f9; padding: 20px; text-align: center; font-size: 12px; color: #aaa; border-top: 1px solid #eee; }
    </style>
    """

    html_body = f"""
    <html>
    <head>{css}</head>
    <body>
        <div class="container">
            <div class="header">
                <h1>GLOBAL INSIGHTS</h1>
                <p>{datetime.now().strftime('%Y.%m.%d')} | TECH & WORLD</p>
            </div>
            <div class="content">
                {html_content}
            </div>
            <div class="footer">
                Served by DeepSeek AI & GitHub Actions
            </div>
        </div>
    </body>
    </html>
    """

    msg = MIMEText(html_body, 'html', 'utf-8')
    msg['From'] = formataddr(("TechBot Pro", SENDER_EMAIL))
    msg['To'] = formataddr(("Master", RECEIVER_EMAIL))
    msg['Subject'] = Header(f"🌍 全球情报: {datetime.now().strftime('%m-%d')} 核心简报", 'utf-8')

    try:
        server = smtplib.SMTP_SSL("smtp.qq.com", 465)
        server.login(SENDER_EMAIL, EMAIL_PASSWORD)
        server.sendmail(SENDER_EMAIL, [RECEIVER_EMAIL], msg.as_string())
        server.quit()
        print("✅ 邮件发送成功！")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")


if __name__ == "__main__":
    # 1. 抓取
    items, new_history = fetch_rss_data()

    if not items:
        print("😴 无新内容 (All caught up)")
        exit(0)

    print(f"📊 收集到 {len(items)} 条原始数据，准备分析...")

    # 2. AI 分析
    report = ai_analyze_report(items)

    if report:
        # 3. 发送
        send_email(report)
        # 4. 保存状态
        save_history(new_history)
