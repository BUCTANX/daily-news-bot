import os
import requests
import feedparser
import smtplib
import markdown2  # 用于将 Markdown 转为漂亮的 HTML
from bs4 import BeautifulSoup
from openai import OpenAI
from datetime import datetime
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr

# ================= 1. 配置区域 =================
# 敏感信息全部从环境变量获取，保障安全性
# 在 PyCharm 测试时，请在 "Edit Configurations" -> "Environment variables" 中设置这些值
# 格式: KEY=VALUE;KEY2=VALUE2

# AI 配置
API_KEY = os.environ.get("API_KEY")
API_BASE_URL = "https://api.deepseek.com"

# 邮件配置
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")  # 发件人邮箱 (如: 123456@qq.com)
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")  # 邮箱授权码 (不是QQ密码！)
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")  # 收件人邮箱 (可以是同一个)


# ==============================================

def get_hacker_news(limit=5):
    """获取 Hacker News 热门科技新闻"""
    print("正在抓取 Hacker News...")
    try:
        top_ids = requests.get("https://hacker-news.firebaseio.com/v0/topstories.json").json()
        content = []
        for pid in top_ids[:limit]:
            item = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{pid}.json").json()
            if 'url' in item:
                content.append(f"Title: {item['title']}\nURL: {item['url']}")
        return "\n\n".join(content)
    except Exception as e:
        print(f"HN 抓取失败: {e}")
        return ""


def get_huggingface_papers(limit=5):
    """获取 Hugging Face 每日 AI 论文"""
    print("正在抓取 Hugging Face Papers...")
    try:
        feed = feedparser.parse("https://huggingface.co/papers/rss")
        content = []
        for entry in feed.entries[:limit]:
            content.append(f"Paper: {entry.title}\nLink: {entry.link}\nSummary: {entry.summary[:150]}...")
        return "\n\n".join(content)
    except Exception as e:
        print(f"HF Papers 抓取失败: {e}")
        return ""


def get_github_trending():
    """爬取 GitHub Trending"""
    print("正在抓取 GitHub Trending...")
    try:
        url = "https://github.com/trending?since=daily"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers)
        soup = BeautifulSoup(resp.text, 'html.parser')
        content = []
        for row in soup.select('article.Box-row')[:5]:
            name = row.select_one('h2 a').text.strip().replace('\n', '').replace(' ', '')
            link = "https://github.com" + row.select_one('h2 a')['href']
            desc_tag = row.select_one('p.col-9')
            desc = desc_tag.text.strip() if desc_tag else "无描述"
            content.append(f"Repo: {name}\nDesc: {desc}\nLink: {link}")
        return "\n\n".join(content)
    except Exception as e:
        print(f"GitHub Trending 抓取失败: {e}")
        return ""


def ai_summary(text_data):
    """调用 DeepSeek 进行总结"""
    print("正在调用 DeepSeek 进行分析...")
    if not API_KEY:
        return "错误：未配置 API_KEY"

    client = OpenAI(api_key=API_KEY, base_url=API_BASE_URL)

    prompt = f"""
    你是一个专业的技术情报分析师。请阅读以下从 Hacker News, Hugging Face, GitHub 获取的原始数据：

    {text_data}

    任务：
    1. 挑选出最值得关注的 6-8 条内容。
    2. 用中文进行总结。
    3. 格式要求：Markdown。
       - 每条新闻使用 `###` 标题。
       - 标题下方必须紧跟一行 `**核心价值**：xxx` 的点评。
       - 最后附上 `[点击查看原文](URL)` 的链接。
    4. 语气要专业、简洁。
    """

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"AI 调用出错: {e}")
        return None


def send_email(markdown_content):
    """通过 SMTP 发送 HTML 格式邮件"""
    print("正在构建邮件...")
    if not SENDER_EMAIL or not EMAIL_PASSWORD:
        print("错误：未配置邮箱信息，无法发送。")
        return

    # 1. 将 Markdown 转换为 HTML
    # extras=['target-blank-links'] 可以让链接在新标签页打开
    html_body = markdown2.markdown(markdown_content, extras=['target-blank-links'])

    # 2. 加上一些简单的 CSS 样式，让邮件更像一份报纸
    full_html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; }}
            h3 {{ color: #2c3e50; border-bottom: 1px solid #eaeaea; padding-bottom: 5px; margin-top: 20px; }}
            a {{ color: #0366d6; text-decoration: none; }}
            strong {{ color: #d73a49; }}
            .footer {{ margin-top: 30px; font-size: 12px; color: #999; text-align: center; }}
        </style>
    </head>
    <body>
        <h2>🚀 每日科技情报 ({datetime.now().strftime('%Y-%m-%d')})</h2>
        {html_body}
        <div class="footer">Powered by DeepSeek & GitHub Actions</div>
    </body>
    </html>
    """

    # 3. 构建邮件对象
    message = MIMEText(full_html, 'html', 'utf-8')
    message['From'] = formataddr(("TechBot", SENDER_EMAIL))
    message['To'] = formataddr(("Master", RECEIVER_EMAIL))
    message['Subject'] = Header(f"每日科技情报 - {datetime.now().strftime('%m-%d')}", 'utf-8')

    try:
        # 4. 连接 QQ 邮箱 SMTP 服务器
        server = smtplib.SMTP_SSL("smtp.qq.com", 465)
        server.login(SENDER_EMAIL, EMAIL_PASSWORD)
        server.sendmail(SENDER_EMAIL, [RECEIVER_EMAIL], message.as_string())
        server.quit()
        print("✅ 邮件发送成功！")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")


if __name__ == "__main__":
    # 1. 抓取数据
    data_sources = []

    hn_data = get_hacker_news()
    if hn_data: data_sources.append(f"【Hacker News】\n{hn_data}")

    hf_data = get_huggingface_papers()
    if hf_data: data_sources.append(f"【Hugging Face Papers】\n{hf_data}")

    gh_data = get_github_trending()
    if gh_data: data_sources.append(f"【GitHub Trending】\n{gh_data}")

    # 2. AI 处理
    if data_sources:
        all_text = "\n\n".join(data_sources)
        report = ai_summary(all_text)

        if report:
            # 3. 发送邮件
            send_email(report)
    else:
        print("今日未抓取到数据，跳过执行。")