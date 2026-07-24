"""
CSDN article → formatted markdown note with local images.
Cascade: trafilatura → requests → Playwright+stealth

Usage:
    python csdn_to_md.py "https://blog.csdn.net/xxx/article/details/xxx"
    python csdn_to_md.py "https://blog.csdn.net/xxx/article/details/xxx" --article-slug "my-notes"
"""
import sys, re, json, os, hashlib, argparse
from pathlib import Path
from datetime import date
from urllib.parse import urlparse

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


# ── HTML fetching cascade ─────────────────────────────────────────────

def try_trafilatura(url):
    import trafilatura
    print("[1/3] trafilatura...")
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        print("       no response")
        return None
    print("       ok")
    return downloaded


def try_requests(url):
    import requests
    print("[2/3] requests + browser headers...")
    headers = {
        'User-Agent': UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Referer': 'https://blog.csdn.net/',
    }
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        print("       ok")
        return resp.text
    except Exception as e:
        print(f"       failed: {e}")
        return None


def try_playwright(url):
    from playwright.sync_api import sync_playwright
    from playwright_stealth import stealth_sync
    print("[3/3] Playwright + stealth...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent=UA,
                locale='zh-CN',
            )
            page = context.new_page()
            stealth_sync(page)
            page.goto(url, wait_until='domcontentloaded', timeout=30000)
            page.wait_for_timeout(3000)
            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            page.wait_for_timeout(2000)
            page.evaluate('window.scrollTo(0, 0)')
            page.wait_for_timeout(1000)
            html = page.content()
            browser.close()
            print("       ok")
            return html
    except Exception as e:
        print(f"       failed: {e}")
        return None


def fetch_html(url):
    print(f"Fetching: {url}")
    for strategy in [try_trafilatura, try_requests, try_playwright]:
        html = strategy(url)
        if html and len(html) > 500:
            return html
    raise RuntimeError("All fetch strategies exhausted.")


# ── Content extraction ────────────────────────────────────────────────

def extract_content(html, url):
    """Extract content as ordered elements: block-level HTML walk, images in place."""
    from bs4 import BeautifulSoup, Tag

    soup = BeautifulSoup(html, 'html.parser')

    # ── Step 1: flatten KaTeX into plain inline text ───────────────────
    # ── Step 1: extract LaTeX source from KaTeX MathML ───────────────
    # CSDN's KaTeX puts the original LaTeX as the last line inside
    # .katex-mathml. Simple formulas (t, [0,1]) → inline backtick.
    # Complex formulas (\begin{array}, \frac, \begin{cases}) → $$ block.
    def _extract_latex(katex_el):
        ml = katex_el.select_one('.katex-mathml')
        if not ml:
            return None
        lines = [l.strip() for l in ml.get_text().split('\n') if l.strip()]
        if not lines:
            return None
        for line in reversed(lines):
            if '\\' in line:
                return line
        return lines[-1]

    def _is_display(latex):
        triggers = ['\\begin{', '\\frac', '\\sum', '\\prod', '\\int', '\\\\']
        return any(t in latex for t in triggers)

    for katex in soup.select('.katex'):
        latex = _extract_latex(katex)
        if latex:
            if _is_display(latex):
                katex.replace_with(f'\n$$\n{latex}\n$$\n')
            else:
                katex.replace_with(f'`{latex}`')

    # ── Step 1b: preserve links, font colors & strong/em ───────────────
    # Convert <a> to markdown links before extraction (get_text strips tags).
    for tag in soup.find_all('a'):
        href = tag.get('href', '')
        text = tag.get_text(strip=True)
        if not text:
            tag.decompose()
        elif href and not href.startswith('#'):
            tag.replace_with(f'[{text}]({href})')
        else:
            tag.unwrap()  # remove the <a> but keep the text

    for tag in soup.find_all(['strong', 'b']):
        tag.replace_with(f"**{tag.get_text()}**")
    for tag in soup.find_all(['em', 'i']):
        tag.replace_with(f"*{tag.get_text()}*")
    for tag in soup.find_all('font'):
        color = tag.get('color', '')
        text = tag.get_text()
        if color:
            tag.replace_with(f'<font color="{color}">{text}</font>')
        else:
            tag.unwrap()
    for tag in soup.find_all('center'):
        # Images inside <center> need to survive — convert them to markdown first
        for img in tag.find_all('img'):
            src = img.get('src') or img.get('data-src') or ''
            alt = img.get('alt', '') or ''
            if src and not src.startswith('data:'):
                img.replace_with(f'![{alt}]({src})')
        text = tag.get_text(strip=True)
        tag.replace_with(f'\n<center>{text}</center>\n')

    # ── Step 2: Title ──────────────────────────────────────────────────
    title = ''
    title_tag = soup.select_one('.title-article') or soup.select_one('h1.title') or soup.find('h1')
    if title_tag:
        title = title_tag.get_text(strip=True)
    if not title:
        og_title = soup.find('meta', property='og:title')
        if og_title:
            title = og_title.get('content', '')

    # ── Step 3: Article body ───────────────────────────────────────────
    article = (soup.select_one('#content_views') or
               soup.select_one('article') or
               soup.select_one('.article-content') or
               soup)

    # Remove unwanted CSDN UI elements
    for tag in article.select('.hide-article-box, .recommend-box, .slider, .look-more, '
                               '.article_copyright, .more-toolbox, .toolbox, '
                               'script, style, iframe, .blog-tags, .up-time, '
                               '.toc, #article_directory, .article_directory, '
                               '.catalog, .directory, nav, .csdn-side-toolbar, '
                               '.recommend-list-box, .article-info-box, .praise-box, '
                               '.reward-box, .recommend-item-box, .insert-baidu-box'):
        tag.decompose()

    # ── Step 4: walk block-level elements in document order ────────────
    BLOCK_TAGS = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                  'p', 'pre', 'img', 'ul', 'ol', 'table', 'blockquote'}
    all_blocks = article.find_all(list(BLOCK_TAGS))

    elements = []
    seen_img_urls = set()

    def has_block_parent(el, stop_at):
        """Check if el is nested inside another block element."""
        p = el.parent
        while p and p != stop_at:
            if hasattr(p, 'name') and p.name in BLOCK_TAGS:
                return True
            p = p.parent
        return False

    def extract_img(img):
        """Return image dict or None if filtered."""
        src = img.get('src') or img.get('data-src') or ''
        if not src or src.startswith('data:'):
            return None
        if any(x in src.lower() for x in ['avatar', 'icon', 'logo', '1x1', 'beacon',
                                            'csdnimg.cn/medal', 'csdnimg.cn/avatar',
                                            'blog.csdn.net/img/']):
            return None
        return {'type': 'image', 'src': src, 'alt': img.get('alt', '') or ''}

    for el in all_blocks:
        if has_block_parent(el, article):
            continue   # handled by a parent block element

        tag = el.name

        # ── Headings ────────────────────────────────────────────────
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            text = el.get_text(strip=True)
            if text and len(text) > 1:
                elements.append({'type': 'heading', 'level': int(tag[1]), 'text': text})

        # ── Paragraph ───────────────────────────────────────────────
        elif tag == 'p':
            # Walk children in document order — text and images interleaved
            from bs4 import NavigableString
            parts = []
            for child in el.children:
                if isinstance(child, NavigableString):
                    parts.append(('text', child.strip()))
                elif hasattr(child, 'name'):
                    if child.name == 'img':
                        img_data = extract_img(child)
                        if img_data and img_data['src'] not in seen_img_urls:
                            seen_img_urls.add(img_data['src'])
                            parts.append(('img', img_data))
                    elif child.name == 'br':
                        parts.append(('br', None))
                    else:
                        # Inline tags — extract images inside, then text
                        for sub_img in child.find_all('img'):
                            img_data = extract_img(sub_img)
                            if img_data and img_data['src'] not in seen_img_urls:
                                seen_img_urls.add(img_data['src'])
                                parts.append(('img', img_data))
                        t = child.get_text(strip=True)
                        if t:
                            parts.append(('text', t))

            # Emit interleaved: group consecutive text, emit images in place
            text_buf = []
            for kind, data in parts:
                if kind == 'text' and data:
                    text_buf.append(data)
                elif kind == 'img':
                    if text_buf:
                        merged = ' '.join(text_buf)
                        if len(merged) > 2:
                            elements.append({'type': 'paragraph', 'text': merged})
                        text_buf = []
                    elements.append(data)
                elif kind == 'br':
                    pass  # line break = text split; already handled by segment grouping

            # Flush remaining text
            if text_buf:
                merged = ' '.join(text_buf)
                if len(merged) > 2:
                    elements.append({'type': 'paragraph', 'text': merged})

        # ── Standalone image ────────────────────────────────────────
        elif tag == 'img':
            img_data = extract_img(el)
            if img_data and img_data['src'] not in seen_img_urls:
                seen_img_urls.add(img_data['src'])
                elements.append(img_data)

        # ── Code block ──────────────────────────────────────────────
        elif tag == 'pre':
            code_tag = el.find('code')
            code_text = code_tag.get_text() if code_tag else el.get_text()
            lang = ''
            if code_tag and code_tag.get('class'):
                for cls in code_tag.get('class', []):
                    if cls.startswith('language-'):
                        lang = cls.replace('language-', '')
            if code_text.strip():
                elements.append({'type': 'code', 'language': lang, 'text': code_text.strip()})

        # ── Table ───────────────────────────────────────────────────
        elif tag == 'table':
            rows = []
            for tr in el.find_all('tr'):
                cells = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
                if cells:
                    rows.append(cells)
            if rows:
                elements.append({'type': 'table', 'rows': rows})

        # ── List ────────────────────────────────────────────────────
        elif tag in ('ul', 'ol'):
            items = []
            for li in el.find_all('li', recursive=False):
                text = li.get_text(strip=True)
                if text and len(text) > 1:
                    items.append(text)
            if items:
                elements.append({'type': 'list', 'ordered': tag == 'ol', 'items': items})

        # ── Blockquote ──────────────────────────────────────────────
        elif tag == 'blockquote':
            text = el.get_text(strip=True)
            if text and len(text) > 2:
                elements.append({'type': 'blockquote', 'text': text})

    img_count = sum(1 for e in elements if e['type'] == 'image')
    print(f"[extract] title='{title[:40]}...', {len(elements)} elements, {img_count} images")
    return {'title': title, 'elements': elements, 'url': url}


# ── Image download ─────────────────────────────────────────────────────

def download_images(elements, img_dir):
    """Download images with retry, return updated elements with local paths."""
    import time
    import requests
    img_dir = Path(img_dir)
    img_dir.mkdir(parents=True, exist_ok=True)

    img_count = 0
    for elem in elements:
        if elem['type'] != 'image':
            continue

        src = elem['src']
        ext = src.rsplit('?', 1)[0].rsplit('.', 1)[-1] if '.' in src.rsplit('?', 1)[0] else 'png'
        ext = ext[:5].lower()
        if ext not in ('png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'):
            ext = 'png'

        url_hash = hashlib.md5(src.encode()).hexdigest()[:8]
        filename = f"{img_count:02d}_{url_hash}.{ext}"
        filepath = img_dir / filename

        if not filepath.exists():
            success = False
            last_error = None
            for attempt in range(3):
                try:
                    headers = {'User-Agent': UA, 'Referer': 'https://blog.csdn.net/'}
                    resp = requests.get(src, headers=headers, timeout=15)
                    resp.raise_for_status()
                    filepath.write_bytes(resp.content)
                    print(f"[img {img_count:02d}] {filename} ({len(resp.content)} bytes)")
                    success = True
                    break
                except Exception as e:
                    last_error = e
                    if attempt < 2:
                        delay = 2 ** (attempt + 1)  # 2s, 4s
                        print(f"[img {img_count:02d}] retry {attempt+1} in {delay}s...")
                        time.sleep(delay)
            if not success:
                print(f"[img {img_count:02d}] FAILED after 3 retries: {src[:80]} — {last_error}")
                img_count += 1
                continue
        else:
            print(f"[img {img_count:02d}] {filename} (cached)")

        elem['local_filename'] = filename
        img_count += 1

    print(f"[download] {img_count} images → {img_dir}/")
    return elements


# ── Markdown generation ────────────────────────────────────────────────

def elements_to_markdown(elements, img_dir_name):
    """Convert ordered elements to markdown string."""
    lines = []
    for elem in elements:
        t = elem['type']

        if t == 'heading':
            prefix = '#' * elem['level']
            lines.append(f"\n{prefix} {elem['text']}\n")

        elif t == 'paragraph':
            lines.append(f"\n{elem['text']}\n")

        elif t == 'image':
            alt = elem.get('alt', '')
            local = elem.get('local_filename', '')
            if local:
                lines.append(f"\n![{alt}]({img_dir_name}/{local})\n")
            else:
                lines.append(f"\n![{alt}]({elem['src']})\n")

        elif t == 'code':
            lang = elem.get('language', '')
            lines.append(f"\n```{lang}\n{elem['text']}\n```\n")

        elif t == 'table':
            rows = elem['rows']
            if not rows:
                continue
            header = rows[0]
            lines.append('\n| ' + ' | '.join(header) + ' |')
            lines.append('|' + '|'.join(['------' for _ in header]) + '|')
            for row in rows[1:]:
                padded = row + [''] * (len(header) - len(row))
                lines.append('| ' + ' | '.join(padded[:len(header)]) + ' |')
            lines.append('')

        elif t == 'list':
            for item in elem['items']:
                prefix = '1. ' if elem.get('ordered') else '- '
                lines.append(f"{prefix}{item}")
            lines.append('')

        elif t == 'blockquote':
            lines.append(f"\n> {elem['text']}\n")

    return '\n'.join(lines)


def generate_markdown(title, elements, source_url, img_dir_name):
    """Generate final markdown: header + body from elements + footer."""
    today = date.today().isoformat()
    body = elements_to_markdown(elements, img_dir_name)
    return f"""# {title}

> **来源**：[CSDN]({source_url})
> **笔记时间**：{today}

---

{body}

---

> 📁 图片目录：`{img_dir_name}/`
> 🔗 原文链接：{source_url}
"""


# ── Main ───────────────────────────────────────────────────────────────

def csdn_to_markdown(url, output_dir='.', article_slug=None):
    """Full pipeline: fetch → extract → download images → write markdown."""
    html = fetch_html(url)
    article = extract_content(html, url)

    title = article['title']
    if not article_slug:
        slug = re.sub(r'[^\w一-鿿-]', '', title.replace(' ', '-'))
        slug = re.sub(r'-+', '-', slug).strip('-')
        article_slug = slug[:60] if slug else 'csdn-article'

    img_dir_name = f"{article_slug}-images"
    img_dir = Path(output_dir) / img_dir_name

    print(f"\nTitle: {title}")
    print(f"Slug:  {article_slug}")
    print(f"Images dir: {img_dir}\n")

    # Download images, update elements with local paths
    elements = download_images(article['elements'], img_dir)

    # Generate markdown from ordered elements
    md_content = generate_markdown(title, elements, url, img_dir_name)

    # Write
    md_path = Path(output_dir) / f"{article_slug}.md"
    md_path.write_text(md_content, encoding='utf-8')

    print(f"\nMarkdown: {md_path}")
    print(f"Images:   {img_dir}/")
    print("Done.")
    return str(md_path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='CSDN article → markdown note')
    parser.add_argument('url', help='CSDN article URL')
    parser.add_argument('--output-dir', '-o', default='.', help='Output directory (default: .)')
    parser.add_argument('--article-slug', '-s', default=None, help='Article slug for filenames')
    args = parser.parse_args()

    csdn_to_markdown(args.url, args.output_dir, args.article_slug)
