"""Render the authored algorithm report Markdown to a linked, bookmarked PDF.

Run: python tools/build_algorithm_report.py
Optional publication dependencies are listed in requirements-report.txt.
"""

import html
import io
from pathlib import Path
import re

import matplotlib
matplotlib.use('Agg')
from matplotlib import mathtext
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether,
                               PageBreak, PageTemplate, Paragraph, Spacer,
                               Table, TableStyle, XPreformatted)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/multiphase-report/report.md'
OUTPUT = SOURCE.parent / 'rapport-bobinages-multiphases.pdf'
PAGE_W, PAGE_H = A4
MARGIN = 51
WIDTH = PAGE_W - 2*MARGIN
INK = colors.HexColor('#172334')
ACCENT = colors.HexColor('#245e89')


def register_fonts():
    font_root = Path(matplotlib.get_data_path()) / 'fonts/ttf'
    for name, filename in (('Report', 'DejaVuSans.ttf'),
                           ('Report-Bold', 'DejaVuSans-Bold.ttf'),
                           ('Report-Italic', 'DejaVuSans-Oblique.ttf'),
                           ('Report-BoldItalic', 'DejaVuSans-BoldOblique.ttf'),
                           ('Code', 'DejaVuSansMono.ttf')):
        pdfmetrics.registerFont(TTFont(name, str(font_root / filename)))
    pdfmetrics.registerFontFamily('Report', normal='Report', bold='Report-Bold',
                                 italic='Report-Italic', boldItalic='Report-BoldItalic')


def inline(text):
    text = html.escape(text, quote=False)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)',
                  lambda m: f'<link href="{html.escape(m[2], quote=True)}" color="#245e89">{m[1]}</link>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'`([^`]+)`', r'<font name="Code" size="8.1">\1</font>', text)
    return text


class ReportDocument(BaseDocTemplate):
    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name in ('Heading1', 'Heading2'):
            level = 0 if flowable.style.name == 'Heading1' else 1
            name = f'heading-{self.seq.nextf("heading")}'
            self.canv.bookmarkPage(name)
            self.canv.addOutlineEntry(flowable.getPlainText(), name, level, False)


def page_decoration(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(INK)
    canvas.rect(0, PAGE_H-11, PAGE_W, 11, fill=1, stroke=0)
    canvas.setFont('Report', 8)
    canvas.setFillColor(colors.HexColor('#586573'))
    canvas.drawString(MARGIN, PAGE_H-33, 'BOBINAGES MULTIPHASÉS / ANALYSE DU CHAMP MAGNÉTIQUE')
    canvas.setStrokeColor(colors.HexColor('#d5dde3'))
    canvas.line(MARGIN, 43, PAGE_W-MARGIN, 43)
    canvas.setFont('Report', 8)
    canvas.drawString(MARGIN, 29, 'LAGHA Khalil Ellah  |  14 novembre 2026')
    canvas.drawRightString(PAGE_W-MARGIN, 29, str(doc.page))
    canvas.restoreState()


def make_styles():
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = 'Report'
        style.textColor = INK
    styles['BodyText'].fontSize = 9.55
    styles['BodyText'].leading = 14.1
    styles['BodyText'].spaceAfter = 7
    styles['Heading1'].fontSize = 20
    styles['Heading1'].leading = 25
    styles['Heading1'].spaceAfter = 14
    styles['Heading2'].fontSize = 12.3
    styles['Heading2'].leading = 17
    styles['Heading2'].textColor = ACCENT
    styles['Heading2'].spaceBefore = 10
    styles['Heading2'].spaceAfter = 6
    styles['Heading3'].fontSize = 10.4
    styles['Heading3'].leading = 15
    styles['Heading3'].spaceBefore = 7
    styles['Heading3'].spaceAfter = 4
    styles.add(ParagraphStyle('BulletReport', parent=styles['BodyText'], leftIndent=11,
                              firstLineIndent=-9, spaceAfter=4))
    styles.add(ParagraphStyle('CaptionReport', parent=styles['BodyText'], fontSize=8.2,
                              leading=11.5, textColor=colors.HexColor('#53616d'), spaceAfter=9))
    styles.add(ParagraphStyle('CoverTitle', parent=styles['Heading1'], fontSize=29,
                              leading=36, spaceBefore=27, spaceAfter=20))
    styles.add(ParagraphStyle('CoverLead', parent=styles['BodyText'], fontSize=15,
                              leading=23, spaceAfter=18))
    styles.add(ParagraphStyle('CodeReport', fontName='Code', fontSize=7.35,
                              leading=10.5, textColor=INK, backColor=colors.HexColor('#f1f5f8'),
                              borderPadding=9, spaceBefore=7, spaceAfter=11))
    return styles


def equation(latex):
    buffer = io.BytesIO()
    latex = latex.replace(r'\bmod', r'\ \mathrm{mod}\ ')
    mathtext.math_to_image('$'+latex+'$', buffer, dpi=190, format='png', color='#172334')
    buffer.seek(0)
    im = PILImage.open(buffer)
    width, height = im.size
    draw_width = min(WIDTH-20, width*72/190)
    return Image(buffer, draw_width, height*draw_width/width, hAlign='CENTER')


def build():
    register_fonts()
    styles = make_styles()
    lines = SOURCE.read_text(encoding='utf-8').splitlines()
    story = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line == '<!-- pagebreak -->':
            story.append(PageBreak())
            i += 1
            continue
        if line.startswith('<!--'):
            i += 1
            continue
        if line.startswith('```'):
            mode = line[3:]
            block = []
            i += 1
            while i < len(lines) and not lines[i].startswith('```'):
                block.append(lines[i])
                i += 1
            if mode == 'math':
                story.extend((Spacer(1, 5), equation(' '.join(block)), Spacer(1, 9)))
            else:
                story.append(XPreformatted(html.escape('\n'.join(block)), styles['CodeReport']))
            i += 1
            continue
        if line.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                row = [cell.strip() for cell in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r'[:\- ]+', cell or '-') for cell in row):
                    rows.append(row)
                i += 1
            columns = len(rows[0])
            cell_style = ParagraphStyle('Cell', parent=styles['BodyText'], fontSize=8.15,
                                        leading=11.4, spaceAfter=0)
            table = Table([[Paragraph(inline(cell), cell_style) for cell in row] for row in rows],
                          colWidths=[WIDTH/columns]*columns, hAlign='LEFT', repeatRows=1)
            table.setStyle(TableStyle([
                ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e6eef4')),
                ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f6f8fa')]),
                ('VALIGN',(0,0),(-1,-1),'TOP'),
                ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
                ('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),
                ('LINEBELOW',(0,0),(-1,0),0.65,colors.HexColor('#c5d3de')),
                ('LINEBELOW',(0,-1),(-1,-1),0.4,colors.HexColor('#d9e1e8'))]))
            story.extend((table, Spacer(1, 9)))
            continue
        match = re.fullmatch(r'!\[([^\]]*)\]\(([^)]+)\)', line)
        if match:
            path = SOURCE.parent / match[2]
            with PILImage.open(path) as im:
                width, height = im.size
            draw_width = WIDTH
            draw_height = height*draw_width/width
            if draw_height > 414:
                draw_width *= 414/draw_height
                draw_height = 414
            story.append(Image(str(path), draw_width, draw_height))
            story.append(Paragraph(inline(match[1]), styles['CaptionReport']))
            i += 1
            continue
        if line.startswith('# '):
            story.append(Paragraph(inline(line[2:]), styles['CoverTitle'] if not story else styles['Heading1']))
            i += 1
            continue
        if line.startswith('## '):
            story.append(Paragraph(inline(line[3:]), styles['Heading2']))
            i += 1
            continue
        if line.startswith('### '):
            story.append(Paragraph(inline(line[4:]), styles['Heading3']))
            i += 1
            continue
        if line.startswith('> '):
            story.append(Paragraph(inline(line[2:]), styles['CoverLead'] if not any(isinstance(s,PageBreak) for s in story) else styles['CaptionReport']))
            i += 1
            continue
        if line.startswith('- '):
            story.append(Paragraph('• '+inline(line[2:]), styles['BulletReport']))
            i += 1
            continue
        paragraph = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].lstrip().startswith(('#','|','!','```','<!--','- ','> ')):
            paragraph.append(lines[i].strip())
            i += 1
        story.append(Paragraph(inline(' '.join(paragraph)), styles['BodyText']))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = ReportDocument(str(OUTPUT), pagesize=A4, title='Génération des bobinages multiphasés et analyse du champ magnétique',
                         author='LAGHA Khalil Ellah', subject='Algorithmes, force magnétomotrice, induction et harmoniques spatiaux',
                         leftMargin=MARGIN, rightMargin=MARGIN, topMargin=54, bottomMargin=59)
    doc.addPageTemplates(PageTemplate(id='report', frames=[Frame(MARGIN,59,WIDTH,PAGE_H-113,
                                                                leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)],
                                     onPage=page_decoration))
    doc.build(story)
    # Retain previously shared PDF URLs with the same revised French document.
    (SOURCE.parent / 'winding-dolomites-multiphase-report.pdf').write_bytes(OUTPUT.read_bytes())
    print(OUTPUT)


if __name__ == '__main__':
    build()
