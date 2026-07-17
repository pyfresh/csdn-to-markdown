# CSDN to Markdown

CSDN 博客文章 → 格式化 Markdown 笔记，图片下载到本地。

## 功能

- 三级抓取级联：trafilatura → requests → Playwright+stealth
- KaTeX 公式自动扁平化为纯文本
- 颜色、粗体、居中等样式保留（MPE 渲染）
- 图片按原文位置穿插，下载到本地目录
- 文章目录/侧边栏自动过滤

## 依赖

```bash
pip install trafilatura beautifulsoup4 requests
pip install playwright playwright-stealth    # 备选，trafilatura 通常就够了
python -m playwright install chromium         # 仅 Playwright 备选需要
```

## 用法

```bash
python csdn_to_md.py "https://blog.csdn.net/xxx/article/details/xxx"
```

可选参数：

```bash
python csdn_to_md.py "url" --article-slug "my-slug" --output-dir "./notes"
```

输出：
- `{slug}.md` — 格式化笔记
- `{slug}-images/` — 本地图片

## Claude Code Skill

同时提供 SKILL.md，作为 Claude Code 的 Skill 使用。安装：

```bash
cp -r csdn-to-markdown ~/.claude/skills/
```
