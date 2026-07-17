---
name: csdn-to-markdown
description: Use when the user gives a CSDN blog URL (blog.csdn.net) and wants a formatted markdown note file with all article images downloaded locally. Covers scraping article content, extracting text+images, and generating structured markdown matching a clean note-taking style.
---

# CSDN to Markdown

Take a CSDN blog URL and produce a well-formatted markdown note file with all images downloaded locally.

## Workflow

1. **Fetch HTML** — cascade: `trafilatura` → `requests` → `Playwright+stealth`
2. **Extract content** — title, headings, paragraphs, images, code blocks from `#content_views`
3. **Download images** — to `{article_slug}-images/` directory, numbered sequentially
4. **Generate markdown** — write the `.md` file with local image references

## Fetch Cascade

CSDN's WAF blocks bare `curl`/`requests`. Use the cascade in `csdn_to_md.py`:

```
trafilatura.fetch_url(url)          # Strategy 1: proper browser fingerprint — works ~90%
requests + browser headers          # Strategy 2: fallback
Playwright + playwright-stealth     # Strategy 3: full browser for JS-heavy pages
```

`trafilatura` alone handles most CSDN articles. Only fall back to Playwright if trafilatura returns empty or 403.

## Image Handling

- Extract `src` (prefer `data-src` for lazy-loaded images)
- Filter out: avatars, icons, logos, 1x1 pixels, beacon trackers
- Download to `{article_slug}-images/` with names `{index:02d}_{hash}.{ext}`
- Reference in markdown as `![alt]({article_slug}-images/{filename})`
- Deduplicate by URL — CSDN sometimes repeats images

## Markdown Output Format

Match this style (from `图解Transformer笔记.md`):

```markdown
# {Article Title}

> **来源**：{source attribution}
> **笔记时间**：{today's date}

---

## {Section heading from article}

### {Subsection if present}

![{image alt}]({local image path})

- Key point preservation with bullet lists
- Important concepts in **bold**

> Key insight blockquote for crucial takeaways
```

Principles:
- Preserve the article's heading hierarchy
- Every content image gets a `![alt](path)` line with alt text
- Use blockquotes for key insights and source attribution
- Use tables for comparison data if present in original
- Bold key terms on first mention
- Add a "关键数字速记" summary table if the article contains scattered parameters

## Usage

```bash
python csdn_to_md.py "<csdn_url>" [--output-dir <dir>] [--article-slug <slug>]
```

Produces:
- `{output_dir}/{article_slug}.md` — the formatted note
- `{output_dir}/{article_slug}-images/` — downloaded images

If `--article-slug` is omitted, derive it from the article title (Chinese/English, hyphenated).

## Dependencies

```
pip install trafilatura beautifulsoup4 requests
pip install playwright playwright-stealth  # fallback only
python -m playwright install chromium       # one-time, 183MB
```
