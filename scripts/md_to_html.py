#!/usr/bin/env python3
"""
Markdown → HTML 변환기
- 사이드바 목차 (TOC)
- 다크/라이트 테마 선택
- Mermaid 다이어그램 지원
- 코드 하이라이트
- 반응형 (모바일 사이드바 토글)

Usage:
  python3 scripts/md_to_html.py <input.md> <output.html>
"""
import markdown
import re
import sys
import os
from datetime import datetime


def extract_toc(html_body):
    """HTML에서 h2, h3, h4 태그를 추출하여 TOC 생성"""
    toc_items = []
    pattern = re.compile(r'<h([234])[^>]*id="([^"]*)"[^>]*>(.*?)</h[234]>', re.DOTALL)
    for match in pattern.finditer(html_body):
        level = int(match.group(1))
        anchor = match.group(2)
        text = re.sub(r'<[^>]+>', '', match.group(3)).strip()
        toc_items.append((level, anchor, text))
    return toc_items


def build_toc_html(toc_items):
    """TOC 아이템을 HTML 리스트로 변환"""
    if not toc_items:
        return ''

    html = '<nav class="toc">\n<ul>\n'
    for level, anchor, text in toc_items:
        indent = '  ' * (level - 2)
        css_class = f'toc-h{level}'
        html += f'{indent}<li class="{css_class}"><a href="#{anchor}">{text}</a></li>\n'
    html += '</ul>\n</nav>'
    return html


PALETTE = [
    '#4f8fea', '#6c5ce7', '#00b894', '#e17055', '#fdcb6e',
    '#00cec9', '#e84393', '#0984e3', '#55efc4', '#fab1a0',
    '#74b9ff', '#a29bfe', '#ffeaa7', '#81ecec', '#fd79a8',
]


def inject_mermaid_styles(code):
    """mermaid 코드에 subgraph/노드 자동 색상 style 삽입"""
    lines = code.strip().split('\n')

    # subgraph 이름 수집
    subgraphs = []
    for line in lines:
        m = re.match(r'\s*subgraph\s+(\w+)', line)
        if m:
            subgraphs.append(m.group(1))

    if not subgraphs:
        return code

    # subgraph별 style 라인 추가
    style_lines = []
    for i, sg in enumerate(subgraphs):
        color = PALETTE[i % len(PALETTE)]
        # 밝은 배경 + 테두리
        style_lines.append(f'    style {sg} fill:{color}22,stroke:{color},stroke-width:2px,color:#e6edf3')

    return code.strip() + '\n' + '\n'.join(style_lines) + '\n'


def protect_mermaid(md_text):
    """마크다운 변환 전에 mermaid 블록을 플레이스홀더로 교체 (codehilite 방지)"""
    mermaid_blocks = []
    def replacer(match):
        idx = len(mermaid_blocks)
        code = inject_mermaid_styles(match.group(1))
        mermaid_blocks.append(code)
        return f'<div class="mermaid">\n%%MERMAID_PLACEHOLDER_{idx}%%\n</div>'
    protected = re.sub(r'```mermaid\n(.*?)```', replacer, md_text, flags=re.DOTALL)
    return protected, mermaid_blocks


def restore_mermaid(html_body, mermaid_blocks):
    """플레이스홀더를 원래 mermaid 코드로 복원"""
    for idx, code in enumerate(mermaid_blocks):
        html_body = html_body.replace(f'%%MERMAID_PLACEHOLDER_{idx}%%', code.strip())
    return html_body


def convert(input_path, output_path):
    with open(input_path, 'r', encoding='utf-8') as f:
        md_text = f.read()

    title = md_text.split('\n')[0].lstrip('# ').strip()

    # mermaid 블록을 보호 (codehilite가 손대지 못하게)
    md_text, mermaid_blocks = protect_mermaid(md_text)

    extensions = ['tables', 'fenced_code', 'codehilite', 'toc', 'attr_list']
    extension_configs = {
        'toc': {
            'permalink': False,
            'toc_depth': '2-4',
            'slugify': lambda value, separator: re.sub(r'[^\w\s-]', '', value).strip().lower().replace(' ', separator),
        }
    }

    md = markdown.Markdown(extensions=extensions, extension_configs=extension_configs)
    html_body = md.convert(md_text)

    # mermaid 복원
    html_body = restore_mermaid(html_body, mermaid_blocks)

    toc_items = extract_toc(html_body)
    toc_html = build_toc_html(toc_items)

    today = datetime.now().strftime('%Y-%m-%d')

    full_html = f'''<!DOCTYPE html>
<html lang="ko" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<style>
  /* ── 테마 변수 ── */
  :root[data-theme="dark"] {{
    --bg: #0d1117;
    --bg-sidebar: #161b22;
    --fg: #e6edf3;
    --fg-muted: #8b949e;
    --border: #30363d;
    --accent: #58a6ff;
    --accent-hover: #79c0ff;
    --code-bg: #1e293b;
    --code-fg: #e2e8f0;
    --table-header: #161b22;
    --table-even: #0d1117;
    --table-odd: #161b22;
    --blockquote-bg: #161b22;
    --blockquote-border: #3b82f6;
    --link: #58a6ff;
    --strong: #79c0ff;
    --card-bg: #21262d;
  }}
  :root[data-theme="light"] {{
    --bg: #ffffff;
    --bg-sidebar: #f6f8fa;
    --fg: #1f2937;
    --fg-muted: #6b7280;
    --border: #e5e7eb;
    --accent: #2563eb;
    --accent-hover: #1d4ed8;
    --code-bg: #f3f4f6;
    --code-fg: #1e293b;
    --table-header: #f8fafc;
    --table-even: #ffffff;
    --table-odd: #f9fafb;
    --blockquote-bg: #eff6ff;
    --blockquote-border: #3b82f6;
    --link: #2563eb;
    --strong: #1e40af;
    --card-bg: #f3f4f6;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: var(--bg);
    color: var(--fg);
    line-height: 1.75;
    display: flex;
    min-height: 100vh;
  }}

  /* ── 사이드바 ── */
  .sidebar {{
    position: fixed;
    top: 0;
    left: 0;
    width: 280px;
    height: 100vh;
    background: var(--bg-sidebar);
    border-right: 1px solid var(--border);
    overflow-y: auto;
    padding: 20px 0;
    z-index: 100;
    transition: transform 0.3s ease;
  }}

  .sidebar-header {{
    padding: 0 20px 16px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 12px;
  }}

  .sidebar-title {{
    font-size: 0.95rem;
    font-weight: 700;
    color: var(--fg);
    line-height: 1.3;
  }}

  .sidebar-controls {{
    display: flex;
    gap: 8px;
    margin-top: 12px;
  }}

  .theme-btn {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    color: var(--fg-muted);
    padding: 4px 10px;
    border-radius: 6px;
    font-size: 0.7rem;
    cursor: pointer;
    transition: all 0.2s;
  }}
  .theme-btn:hover {{
    border-color: var(--accent);
    color: var(--accent);
  }}
  .theme-btn.active {{
    background: var(--accent);
    color: #fff;
    border-color: var(--accent);
  }}

  .back-link {{
    display: block;
    margin-top: 10px;
    font-size: 0.75rem;
    color: var(--fg-muted);
    text-decoration: none;
  }}
  .back-link:hover {{
    color: var(--accent);
  }}

  /* ── TOC ── */
  .toc {{
    padding: 0 12px;
  }}
  .toc ul {{
    list-style: none;
    padding: 0;
  }}
  .toc li {{
    margin: 0;
  }}
  .toc a {{
    display: block;
    padding: 4px 8px;
    color: var(--fg-muted);
    text-decoration: none;
    font-size: 0.78rem;
    border-radius: 4px;
    border-left: 2px solid transparent;
    transition: all 0.15s;
    line-height: 1.4;
  }}
  .toc a:hover {{
    color: var(--accent);
    background: var(--card-bg);
    border-left-color: var(--accent);
  }}
  .toc a.active {{
    color: var(--accent);
    border-left-color: var(--accent);
    font-weight: 600;
  }}
  .toc-h3 a {{ padding-left: 20px; font-size: 0.75rem; }}
  .toc-h4 a {{ padding-left: 32px; font-size: 0.72rem; }}

  /* ── 본문 ── */
  .content {{
    margin-left: 280px;
    flex: 1;
    max-width: 860px;
    padding: 40px 48px 80px;
  }}

  /* ── 모바일 ── */
  .menu-toggle {{
    display: none;
    position: fixed;
    top: 12px;
    left: 12px;
    z-index: 200;
    background: var(--bg-sidebar);
    border: 1px solid var(--border);
    color: var(--fg);
    padding: 8px 12px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 1.1rem;
  }}

  @media (max-width: 900px) {{
    .sidebar {{
      transform: translateX(-100%);
    }}
    .sidebar.open {{
      transform: translateX(0);
    }}
    .content {{
      margin-left: 0;
      padding: 60px 20px 60px;
    }}
    .menu-toggle {{
      display: block;
    }}
  }}

  /* ── 타이포그래피 ── */
  h1 {{ font-size: 1.9rem; margin: 2rem 0 1rem; padding-bottom: 0.5rem; border-bottom: 2px solid var(--accent); }}
  h2 {{ font-size: 1.45rem; margin: 2.5rem 0 0.8rem; padding-bottom: 0.3rem; border-bottom: 1px solid var(--border); color: var(--accent); }}
  h3 {{ font-size: 1.15rem; margin: 1.8rem 0 0.5rem; }}
  h4 {{ font-size: 1rem; margin: 1.3rem 0 0.4rem; color: var(--fg-muted); }}
  p {{ margin: 0.6rem 0; }}
  hr {{ border: none; border-top: 1px solid var(--border); margin: 2rem 0; }}
  strong {{ color: var(--strong); }}
  a {{ color: var(--link); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  ul, ol {{ margin: 0.5rem 0 0.5rem 1.5rem; }}
  li {{ margin: 0.25rem 0; }}

  /* ── 테이블 ── */
  table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: 0.85rem; }}
  th, td {{ border: 1px solid var(--border); padding: 0.5rem 0.75rem; text-align: left; }}
  th {{ background: var(--table-header); font-weight: 600; }}
  tr:nth-child(even) {{ background: var(--table-even); }}
  tr:nth-child(odd) {{ background: var(--table-odd); }}

  /* ── 코드 ── */
  code {{
    background: var(--code-bg);
    color: var(--code-fg);
    padding: 0.15rem 0.4rem;
    border-radius: 4px;
    font-size: 0.82em;
    font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
  }}
  pre {{
    background: var(--code-bg);
    color: var(--code-fg);
    padding: 1rem 1.2rem;
    border-radius: 8px;
    overflow-x: auto;
    margin: 1rem 0;
    border: 1px solid var(--border);
  }}
  pre code {{
    background: none;
    padding: 0;
    font-size: 0.82rem;
    line-height: 1.5;
  }}

  /* ── 인용 ── */
  blockquote {{
    border-left: 4px solid var(--blockquote-border);
    padding: 0.6rem 1rem;
    margin: 1rem 0;
    background: var(--blockquote-bg);
    border-radius: 0 6px 6px 0;
  }}
  blockquote p {{ margin: 0.3rem 0; }}

  /* ── Mermaid ── */
  .mermaid {{
    margin: 1.5rem 0;
    text-align: center;
    background: var(--card-bg);
    padding: 1rem;
    border-radius: 8px;
    border: 1px solid var(--border);
  }}
  .mermaid svg {{ max-width: 100%; }}

  /* ── Footer ── */
  footer {{
    margin-top: 3rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
    color: var(--fg-muted);
    font-size: 0.8rem;
  }}
</style>
</head>
<body>

<button class="menu-toggle" onclick="document.querySelector('.sidebar').classList.toggle('open')">☰</button>

<aside class="sidebar">
  <div class="sidebar-header">
    <div class="sidebar-title">{title}</div>
    <div class="sidebar-controls">
      <button class="theme-btn" onclick="setTheme('dark')" id="btn-dark">🌙 Dark</button>
      <button class="theme-btn" onclick="setTheme('light')" id="btn-light">☀️ Light</button>
    </div>
    <a class="back-link" href="index.html">← 문서 목록으로</a>
  </div>
  {toc_html}
</aside>

<main class="content">
{html_body}
</main>

<script>
  // 테마 전환
  function setTheme(theme) {{
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('doc-theme', theme);
    document.getElementById('btn-dark').classList.toggle('active', theme === 'dark');
    document.getElementById('btn-light').classList.toggle('active', theme === 'light');
    // Mermaid 재렌더링
    if (typeof mermaid !== 'undefined') {{
      mermaid.initialize({{ startOnLoad: false, theme: 'base', securityLevel: 'loose', themeVariables: getMermaidTheme(theme) }});
      document.querySelectorAll('.mermaid').forEach(el => {{
        el.removeAttribute('data-processed');
        el.innerHTML = el.textContent;
      }});
      mermaid.run();
    }}
  }}

  // 저장된 테마 로드
  const savedTheme = localStorage.getItem('doc-theme') || 'dark';
  setTheme(savedTheme);

  // Mermaid 초기화
  function getMermaidTheme(theme) {{
    const dark = {{
      primaryColor: '#3d7be0',
      primaryTextColor: '#ffffff',
      primaryBorderColor: '#5a9cf0',
      secondaryColor: '#7c5cbf',
      secondaryTextColor: '#ffffff',
      secondaryBorderColor: '#a29bfe',
      tertiaryColor: '#00997a',
      tertiaryTextColor: '#ffffff',
      tertiaryBorderColor: '#55efc4',
      noteTextColor: '#f0f0f0',
      noteBkgColor: '#2d3436',
      noteBorderColor: '#636e72',
      lineColor: '#8b949e',
      textColor: '#e6edf3',
      mainBkg: '#1e3050',
      nodeBorder: '#5a9cf0',
      clusterBkg: '#1a1e2e',
      clusterBorder: '#4a5568',
      titleColor: '#79c0ff',
      edgeLabelBackground: '#21262d',
      actorBkg: '#3d7be0',
      actorTextColor: '#ffffff',
      actorBorder: '#5a9cf0',
      signalColor: '#8b949e',
      labelBoxBkgColor: '#21262d',
      labelBoxBorderColor: '#4a5568',
      labelTextColor: '#e6edf3',
      loopTextColor: '#e6edf3',
      activationBorderColor: '#5a9cf0',
      activationBkgColor: '#1e3050',
      sequenceNumberColor: '#ffffff',
      pie1: '#4f8fea', pie2: '#6c5ce7', pie3: '#00b894', pie4: '#e17055',
      pie5: '#fdcb6e', pie6: '#00cec9', pie7: '#e84393', pie8: '#0984e3'
    }};
    const light = {{
      primaryColor: '#4f8fea',
      primaryTextColor: '#1a1a2e',
      primaryBorderColor: '#3a7bd5',
      secondaryColor: '#a29bfe',
      secondaryTextColor: '#1a1a2e',
      secondaryBorderColor: '#6c5ce7',
      tertiaryColor: '#55efc4',
      tertiaryTextColor: '#1a1a2e',
      tertiaryBorderColor: '#00b894',
      noteTextColor: '#2d3436',
      noteBkgColor: '#ffeaa7',
      noteBorderColor: '#fdcb6e',
      lineColor: '#636e72',
      textColor: '#2d3436',
      mainBkg: '#dfe6e9',
      nodeBorder: '#3a7bd5',
      clusterBkg: '#f0f3f5',
      clusterBorder: '#b2bec3',
      titleColor: '#2d3436',
      edgeLabelBackground: '#ffffff',
      actorBkg: '#4f8fea',
      actorTextColor: '#ffffff',
      actorBorder: '#3a7bd5',
      signalColor: '#636e72',
      labelBoxBkgColor: '#ffffff',
      labelBoxBorderColor: '#b2bec3',
      labelTextColor: '#2d3436',
      loopTextColor: '#2d3436',
      activationBorderColor: '#3a7bd5',
      activationBkgColor: '#dfe6e9',
      sequenceNumberColor: '#ffffff',
      pie1: '#4f8fea', pie2: '#6c5ce7', pie3: '#00b894', pie4: '#e17055',
      pie5: '#fdcb6e', pie6: '#00cec9', pie7: '#e84393', pie8: '#0984e3'
    }};
    return theme === 'dark' ? dark : light;
  }}

  mermaid.initialize({{ startOnLoad: true, theme: 'base', securityLevel: 'loose', themeVariables: getMermaidTheme(savedTheme) }});

  // TOC 현재 위치 하이라이트
  const tocLinks = document.querySelectorAll('.toc a');
  const headings = [];
  tocLinks.forEach(link => {{
    const id = link.getAttribute('href').slice(1);
    const el = document.getElementById(id);
    if (el) headings.push({{ el, link }});
  }});

  function updateActiveToc() {{
    let current = null;
    for (const h of headings) {{
      if (h.el.getBoundingClientRect().top <= 100) current = h;
    }}
    tocLinks.forEach(l => l.classList.remove('active'));
    if (current) current.link.classList.add('active');
  }}

  window.addEventListener('scroll', updateActiveToc, {{ passive: true }});
  updateActiveToc();

  // 모바일: 링크 클릭 시 사이드바 닫기
  tocLinks.forEach(link => {{
    link.addEventListener('click', () => {{
      if (window.innerWidth <= 900) {{
        document.querySelector('.sidebar').classList.remove('open');
      }}
    }});
  }});
</script>

</body>
</html>'''

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(full_html)
    print(f"Generated: {output_path} ({os.path.getsize(output_path)//1024}KB)")


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python3 scripts/md_to_html.py <input.md> <output.html>")
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
