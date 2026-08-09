"""Render a markdown document to a print-ready PDF.

    python3 tools/docs/md2pdf.py docs/planning/next-week-task-pool.md out.pdf

markdown -> HTML -> headless Chrome. No new dependencies: the `markdown` module is
already available and Chrome ships on every machine here, so this needs no
`brew install` of poppler, pandoc or wkhtmltopdf.

WHY A SCRIPT RATHER THAN A COMMITTED PDF. A binary checked in beside its own source
goes stale silently -- the same "two descriptions that can disagree" problem the task
pool itself flags in P-09. Rendered PDFs under docs/ are gitignored; regenerate in one
command.

Layout choices that matter for a document people are handed around:

  - every top-level heading starts a NEW PAGE, so one lane's section can be handed to
    one person without printing the rest;
  - `break-inside: avoid` on paragraphs and tables, so a ticket never splits across a
    page boundary mid-sentence.
"""
import html as _html
import re
import subprocess
import sys
from pathlib import Path

import markdown

src = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
text = src.read_text(encoding="utf-8")

body = markdown.markdown(
    text,
    extensions=["tables", "fenced_code", "sane_lists", "attr_list"],
    output_format="html5",
)

CSS = """
@page { size: A4; margin: 16mm 15mm 18mm 15mm; }
@page { @bottom-center { content: counter(page); } }

html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body {
  font: 10.5pt/1.5 -apple-system, "Helvetica Neue", Helvetica, Arial, sans-serif;
  color: #16191d; margin: 0;
}

h1 {
  font-size: 15pt; font-weight: 700; letter-spacing: -.2px;
  margin: 0 0 10pt; padding-bottom: 5pt;
  border-bottom: 2.5pt solid #1f2937;
  break-after: avoid;
}
/* Each lane starts on a fresh page: the point is handing a section to one person. */
h1 + * { break-before: avoid; }
body > h1:not(:first-of-type) { break-before: page; }

h2 {
  font-size: 12pt; font-weight: 700; margin: 16pt 0 7pt;
  color: #111827; break-after: avoid;
}
h3 { font-size: 10.5pt; font-weight: 700; margin: 12pt 0 5pt; break-after: avoid; }

p { margin: 0 0 7pt; orphans: 3; widows: 3; }
/* A ticket is one paragraph; never split one across a page. */
p:has(strong) { break-inside: avoid; }

em { color: #4b5563; }
strong { color: #0b1220; }

code {
  font: 9pt/1.4 ui-monospace, "SF Mono", Menlo, monospace;
  background: #f3f4f6; padding: .5pt 3pt; border-radius: 2.5pt;
  color: #b3005e; white-space: nowrap;
}

hr { border: none; border-top: .75pt solid #d1d5db; margin: 14pt 0; }

table {
  border-collapse: collapse; width: 100%; margin: 8pt 0 12pt;
  font-size: 9.5pt; break-inside: avoid;
}
th {
  text-align: left; background: #1f2937; color: #fff;
  padding: 4.5pt 7pt; font-weight: 600;
}
td { padding: 4pt 7pt; border-bottom: .5pt solid #e5e7eb; vertical-align: top; }
tr:nth-child(even) td { background: #f9fafb; }
td code { background: transparent; padding: 0; }

ul { margin: 0 0 8pt; padding-left: 16pt; }
li { margin-bottom: 3pt; break-inside: avoid; }

blockquote {
  margin: 8pt 0; padding: 6pt 10pt; background: #f9fafb;
  border-left: 2.5pt solid #9ca3af; color: #374151;
}
"""

doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{_html.escape(src.stem)}</title>
<style>{CSS}</style></head>
<body>{body}</body></html>"""

tmp_html = out.with_suffix(".render.html")
tmp_html.write_text(doc, encoding="utf-8")

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
subprocess.run(
    [CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
     f"--print-to-pdf={out}", tmp_html.as_uri()],
    check=True, capture_output=True, timeout=180,
)
tmp_html.unlink()
print(f"wrote {out} ({out.stat().st_size:,} bytes)")
