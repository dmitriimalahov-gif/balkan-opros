"""Формирует читаемую PDF-карту процессов ERP2 из обезличенного канона."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).parent
SOURCE = ROOT / "exports" / "factory-map-ru.json"
OUTPUT = ROOT / "exports" / "karta-processov-balkan-erp2.pdf"
DATA = json.loads(SOURCE.read_text(encoding="utf-8"))
PAGE = landscape(A4)

NAVY = HexColor("#18344B")
BLUE = HexColor("#376985")
TEXT = HexColor("#26343E")
MUTED = HexColor("#64717B")
LINE = HexColor("#C7D0D7")
PALE = HexColor("#F2F5F7")
WHITE = colors.white

regular_font = os.environ.get("DAIMON_CJK_FONT_REGULAR")
bold_font = os.environ.get("DAIMON_CJK_FONT_BOLD")
if not regular_font or not bold_font:
    raise RuntimeError("Не найдены управляемые шрифты Daimon")
pdfmetrics.registerFont(TTFont("DaimonCJK", regular_font))
pdfmetrics.registerFont(TTFont("DaimonCJK-Bold", bold_font))
pdfmetrics.registerFontFamily(
    "DaimonCJK", normal="DaimonCJK", bold="DaimonCJK-Bold",
    italic="DaimonCJK", boldItalic="DaimonCJK-Bold",
)

styles = getSampleStyleSheet()
TITLE = ParagraphStyle(
    "TitleRu", parent=styles["Title"], fontName="DaimonCJK-Bold",
    fontSize=28, leading=35, textColor=NAVY, alignment=TA_LEFT, spaceAfter=8 * mm,
)
SUBTITLE = ParagraphStyle(
    "SubtitleRu", parent=styles["Normal"], fontName="DaimonCJK",
    fontSize=13, leading=20, textColor=MUTED,
)
H1 = ParagraphStyle(
    "H1Ru", parent=styles["Heading1"], fontName="DaimonCJK-Bold",
    fontSize=19, leading=24, textColor=NAVY, spaceAfter=3 * mm,
)
H2 = ParagraphStyle(
    "H2Ru", parent=styles["Heading2"], fontName="DaimonCJK-Bold",
    fontSize=15, leading=19, textColor=NAVY, spaceAfter=2 * mm,
)
BODY = ParagraphStyle(
    "BodyRu", parent=styles["BodyText"], fontName="DaimonCJK",
    fontSize=10.5, leading=16, textColor=TEXT,
)
SMALL = ParagraphStyle(
    "SmallRu", parent=BODY, fontSize=8.8, leading=12, textColor=MUTED,
)
TABLE_BODY = ParagraphStyle(
    "TableBodyRu", parent=BODY, fontSize=9.2, leading=12, spaceAfter=0,
)
TABLE_CODE = ParagraphStyle(
    "TableCodeRu", parent=TABLE_BODY, fontName="DaimonCJK-Bold", textColor=NAVY,
)
TABLE_HEAD = ParagraphStyle(
    "TableHeadRu", parent=TABLE_BODY, fontName="DaimonCJK-Bold", textColor=NAVY,
)
NODE = ParagraphStyle(
    "NodeRu", parent=BODY, fontSize=9.1, leading=11.5, alignment=TA_CENTER,
    textColor=TEXT,
)
NODE_MAIN = ParagraphStyle(
    "NodeMainRu", parent=NODE, fontName="DaimonCJK-Bold", textColor=NAVY,
)
NODE_SMALL = ParagraphStyle(
    "NodeSmallRu", parent=NODE, fontSize=7.8, leading=10,
)
GROUP = ParagraphStyle(
    "GroupRu", parent=BODY, fontName="DaimonCJK-Bold", fontSize=10,
    leading=13, alignment=TA_CENTER, textColor=NAVY,
)


def para(text: str, style: ParagraphStyle = BODY) -> Paragraph:
    """Экранирует текст канона и сохраняет явные переносы строк в схемах."""
    from xml.sax.saxutils import escape
    return Paragraph(escape(text or "—").replace("\n", "<br/>"), style)


class FunctionMap(Flowable):
    """Ветвистая карта: связи показывают состав, а не последовательность."""

    def __init__(self, width: float, height: float = 425):
        super().__init__()
        self.width = width
        self.height = height
        self.groups = [
            ("Спрос и управление", ["10", "09", "11", "14"]),
            ("Планирование и данные", ["01", "02", "12", "13"]),
            ("Материалы и качество", ["05", "08", "06", "20"]),
            ("Производство и доступ", ["03", "04", "07", "15"]),
        ]
        self.by_key = {f["key"]: f for f in DATA["functions"]}

    def _paragraph(self, text: str, style: ParagraphStyle, x: float, y: float, w: float, h: float):
        p = para(text, style)
        pw, ph = p.wrap(w, h)
        p.drawOn(self.canv, x + (w - pw) / 2, y + (h - ph) / 2)

    def draw(self):
        c = self.canv
        w, h = self.width, self.height
        gap = 10
        col_w = (w - 3 * gap) / 4
        root_w, root_h = 270, 44
        root_x, root_y = (w - root_w) / 2, h - root_h
        c.setStrokeColor(NAVY)
        c.setLineWidth(1.2)
        c.rect(root_x, root_y, root_w, root_h, fill=0, stroke=1)
        self._paragraph("Balkan Pharmaceuticals\n16 функций · 223 шага", NODE_MAIN, root_x + 6, root_y + 3, root_w - 12, root_h - 6)
        branch_y = root_y - 24
        centers = [i * (col_w + gap) + col_w / 2 for i in range(4)]
        c.setStrokeColor(LINE)
        c.setLineWidth(0.8)
        c.line(w / 2, root_y, w / 2, branch_y)
        c.line(centers[0], branch_y, centers[-1], branch_y)
        node_h, node_gap = 55, 12
        first_y = branch_y - 102
        for i, (group, keys) in enumerate(self.groups):
            x = i * (col_w + gap)
            cx = centers[i]
            c.line(cx, branch_y, cx, branch_y - 18)
            self._paragraph(group, GROUP, x, branch_y - 38, col_w, 20)
            c.line(cx, branch_y - 38, cx, first_y + node_h / 2)
            for j, key in enumerate(keys):
                f = self.by_key[key]
                y = first_y - j * (node_h + node_gap)
                c.setStrokeColor(LINE)
                c.rect(x, y, col_w, node_h, fill=0, stroke=1)
                c.setFillColor(NAVY)
                c.rect(x, y, 3, node_h, fill=1, stroke=0)
                self._paragraph(
                    f"{key} · {f['step_count']} шагов\n{f['title']}", NODE,
                    x + 8, y + 4, col_w - 16, node_h - 8,
                )
                if j < len(keys) - 1:
                    c.setStrokeColor(LINE)
                    c.line(cx, y, cx, y - node_gap)


class ProcessFlow(Flowable):
    """Сквозной маршрут и основные поддерживающие связи."""

    def __init__(self, width: float, height: float = 420):
        super().__init__()
        self.width = width
        self.height = height
        self.by_key = {f["key"]: f for f in DATA["functions"]}

    def _node(self, key: str, x: float, y: float, w: float, h: float, main: bool = True):
        f = self.by_key[key]
        c = self.canv
        c.setStrokeColor(BLUE if main else LINE)
        c.setLineWidth(1.1 if main else 0.8)
        c.rect(x, y, w, h, fill=0, stroke=1)
        p = para(f"{key}\n{f['title']}", NODE_MAIN if main else NODE_SMALL)
        pw, ph = p.wrap(w - 8, h - 8)
        p.drawOn(c, x + (w - pw) / 2, y + (h - ph) / 2)
        return (x + w / 2, y + h / 2)

    def _arrow(self, x1: float, y1: float, x2: float, y2: float, support: bool = False):
        c = self.canv
        c.setStrokeColor(MUTED if support else BLUE)
        c.setFillColor(MUTED if support else BLUE)
        c.setLineWidth(0.8 if support else 1.1)
        c.setDash(3, 3) if support else c.setDash()
        c.line(x1, y1, x2, y2)
        from math import atan2, cos, sin, pi
        angle = atan2(y2 - y1, x2 - x1)
        size = 5
        p = c.beginPath()
        p.moveTo(x2, y2)
        p.lineTo(x2 - size * cos(angle - pi / 6), y2 - size * sin(angle - pi / 6))
        p.lineTo(x2 - size * cos(angle + pi / 6), y2 - size * sin(angle + pi / 6))
        p.close()
        c.drawPath(p, fill=1, stroke=0)
        c.setDash()

    def draw(self):
        c = self.canv
        w = self.width
        main_keys = ["10", "09", "02", "01", "03", "04", "07"]
        gap = 12
        node_w = (w - gap * 6) / 7
        node_h, main_y = 64, self.height - 100
        centers = {}
        for i, key in enumerate(main_keys):
            x = i * (node_w + gap)
            centers[key] = self._node(key, x, main_y, node_w, node_h, True)
            if i:
                self._arrow(x - gap + 2, main_y + node_h / 2, x - 2, main_y + node_h / 2)
        # Возврат отгруженной продукции в коммерческий контур.
        x07, y07 = centers["07"]
        x09, y09 = centers["09"]
        loop_y = main_y + node_h + 22
        c.setStrokeColor(BLUE)
        c.setLineWidth(1)
        c.line(x07, main_y + node_h, x07, loop_y)
        c.line(x07, loop_y, x09, loop_y)
        self._arrow(x09, loop_y, x09, main_y + node_h + 2)
        c.setFont("DaimonCJK", 8.5)
        c.setFillColor(MUTED)
        c.drawCentredString((x07 + x09) / 2, loop_y + 5, "отгрузка, расчёты и сопровождение клиента")

        support = [
            ("05", "НСИ для плана и участка", "02"),
            ("08", "Поставка материалов", "02"),
            ("06", "Комплект для запуска", "03"),
            ("20", "Допуск сырья и серий", "07"),
            ("12", "Проверенные данные", "01"),
            ("13", "Лимиты и расчёты", "09"),
            ("14", "Решения по исключениям", "01"),
            ("15", "Доступ и интеграции", "01"),
        ]
        s_gap = 8
        s_w = (w - s_gap * 7) / 8
        s_h, s_y = 58, 92
        for i, (key, caption, target) in enumerate(support):
            x = i * (s_w + s_gap)
            sx, sy = self._node(key, x, s_y, s_w, s_h, False)
            tx, ty = centers[target]
            self._arrow(sx, s_y + s_h + 3, tx, main_y - 4, True)
            p = para(caption, NODE_SMALL)
            pw, ph = p.wrap(s_w, 30)
            p.drawOn(c, x + (s_w - pw) / 2, s_y - ph - 7)

        c.setStrokeColor(LINE)
        c.line(0, 35, w, 35)
        c.setFont("DaimonCJK", 8.8)
        c.setFillColor(TEXT)
        c.drawString(0, 20, "Сплошные стрелки — основной поток. Пунктир — данные, контроль, обеспечение и управляющие решения.")
        c.drawString(0, 6, "Обратные связи: качество → пересчёт плана; склады и продажи → DWH; руководитель → владельцы функций.")


def page_decor(canvas, doc):
    canvas.saveState()
    w, h = PAGE
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(12 * mm, h - 11 * mm, w - 12 * mm, h - 11 * mm)
    canvas.setFont("DaimonCJK", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(12 * mm, h - 8.5 * mm, "Balkan Pharmaceuticals · Карта процессов ERP2")
    canvas.drawRightString(w - 12 * mm, 7 * mm, f"Страница {doc.page}")
    canvas.restoreState()


def cover(canvas, doc):
    canvas.saveState()
    w, h = PAGE
    canvas.setFillColor(NAVY)
    canvas.rect(0, h - 9 * mm, w, 9 * mm, fill=1, stroke=0)
    canvas.setStrokeColor(BLUE)
    canvas.setLineWidth(1.5)
    canvas.line(18 * mm, 22 * mm, 70 * mm, 22 * mm)
    canvas.setFont("DaimonCJK", 8.5)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(w - 18 * mm, 18 * mm, "Внутренний регламент · без персональных данных")
    canvas.restoreState()


def function_table(function: dict, width: float, selected_steps: list[dict] | None = None) -> LongTable:
    rows = [[
        para("Код", TABLE_HEAD), para("Действие", TABLE_HEAD),
        para("Результат / подтверждение", TABLE_HEAD), para("Переход и связи", TABLE_HEAD),
    ]]
    steps = selected_steps if selected_steps is not None else [
        step for stage in function["stages"] for step in stage["steps"]
    ]
    for step in steps:
        rows.append([
            para(step["canon_id"], TABLE_CODE),
            para(step["action_ru"], TABLE_BODY),
            para(step["confirms_ru"], TABLE_BODY),
            para(step["next_text"], TABLE_BODY),
        ])
    table = LongTable(rows, colWidths=[45, width * 0.36, width * 0.29, width - 45 - width * 0.65], repeatRows=1, splitByRow=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "DaimonCJK"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEABOVE", (0, 0), (-1, 0), 1.1, NAVY),
        ("LINEBELOW", (0, 0), (-1, 0), 0.65, NAVY),
        ("LINEBELOW", (0, 1), (-1, -2), 0.25, LINE),
        ("LINEBELOW", (0, -1), (-1, -1), 1.1, NAVY),
    ]))
    return table


def build() -> Path:
    functions = DATA["functions"]
    steps = [s for f in functions for st in f["stages"] for s in st["steps"]]
    assert len(functions) == 16
    assert len(steps) == DATA["totals"]["steps"] == 223
    assert all(s["action_ru"] and s["next_text"] for s in steps)

    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=PAGE,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=17 * mm, bottomMargin=12 * mm,
        title="Карта процессов Balkan Pharmaceuticals — ERP2",
        author="Balkan Pharmaceuticals",
        subject="Функции, сквозной маршрут, связи и 223 шага процессного канона ERP2",
    )
    width = PAGE[0] - doc.leftMargin - doc.rightMargin
    story = [Spacer(1, 20 * mm)]
    story.append(para("Карта процессов завода", TITLE))
    story.append(para("Balkan Pharmaceuticals · процессный канон ERP2", SUBTITLE))
    story.append(Spacer(1, 10 * mm))
    stats = [
        [para("16", H1), para("223", H1), para("4", H1)],
        [para("функций", BODY), para("шагов", BODY), para("контура управления", BODY)],
    ]
    stats_table = Table(stats, colWidths=[width / 3] * 3)
    stats_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(stats_table)
    story.append(Spacer(1, 9 * mm))
    story.append(para("Как читать документ", H2))
    story.append(para("1. Общая карта показывает состав функций. 2. Отдельная схема показывает сквозной путь и межролевые связи. 3. Подробные таблицы раскрывают действие, результат и переход каждого шага.", BODY))
    story.append(Spacer(1, 5 * mm))
    story.append(para(f"Сформировано {date.today().strftime('%d.%m.%Y')} по актуальному канону ERP2. Ответы сотрудников и персональные данные не включены.", SMALL))
    story.append(PageBreak())

    story.append(para("1. Общая карта функций", H1))
    story.append(para("Ветви объединяют функции по смыслу. Они не означают последовательность: рабочие переходы показаны на следующей странице.", BODY))
    story.append(Spacer(1, 3 * mm))
    story.append(FunctionMap(width))
    story.append(PageBreak())

    story.append(para("2. Сквозной путь и связи", H1))
    story.append(para("Основной поток: от спроса и планирования до выпуска, отгрузки и сопровождения. Поддерживающие функции подключаются в точках принятия решений и контроля.", BODY))
    story.append(Spacer(1, 3 * mm))
    story.append(ProcessFlow(width))
    story.append(PageBreak())

    story.append(para("3. Состав функций", H1))
    story.append(para("Нажмите на название функции, чтобы перейти к её подробной таблице. Коды шагов сохранены как в каноне ERP2.", BODY))
    story.append(Spacer(1, 5 * mm))
    cells = []
    for f in functions:
        link = f'<link href="#function-{f["key"]}" color="#18344B"><b>{f["key"]} · {f["title"]}</b></link><br/><font size="9" color="#64717B">{f["step_count"]} шагов · роль {f["erp2_role"]}</font>'
        cells.append(Paragraph(link, BODY))
    rows = []
    for i in range(0, len(cells), 2):
        rows.append([cells[i], cells[i + 1] if i + 1 < len(cells) else ""])
    toc = Table(rows, colWidths=[width / 2 - 5 * mm, width / 2 - 5 * mm], hAlign="LEFT")
    toc.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, LINE),
    ]))
    story.append(toc)

    for f in functions:
        # Ровно две сбалансированные страницы на каждую должность, без сжатия текста.
        function_steps = [step for stage in f["stages"] for step in stage["steps"]]
        midpoint = (len(function_steps) + 1) // 2
        chunks = [function_steps[:midpoint], function_steps[midpoint:]]
        for page_index, chunk in enumerate(chunks):
            story.append(PageBreak())
            heading = ParagraphStyle(
                f"Function{f['key']}-{page_index}", parent=H1,
                fontSize=19, leading=24, spaceAfter=3 * mm, keepWithNext=True,
            )
            function_note = ParagraphStyle(
                f"FunctionNote{f['key']}-{page_index}", parent=SMALL,
                fontSize=8.8, leading=12, keepWithNext=True,
            )
            if page_index == 0:
                story.append(Paragraph(f'<a name="function-{f["key"]}"/>{f["key"]} · {f["title"]}', heading))
                note = f"Страница 1 из 2 · роль ERP2: {f['erp2_role']} · {len(chunk)} шагов. Действие → подтверждение → следующий шаг или связанная функция."
            else:
                story.append(Paragraph(f'{f["key"]} · {f["title"]} — продолжение', heading))
                note = f"Страница 2 из 2 · {len(chunk)} шагов. Действие → подтверждение → следующий шаг или связанная функция."
            story.append(para(note, function_note))
            story.append(Spacer(1, 2 * mm))
            story.append(function_table(f, width, chunk))
            if f["key"] == "01" and page_index == len(chunks) - 1:
                story.append(Spacer(1, 2 * mm))
                story.append(para("Примечание: в исходном каноне код 01-18 используется для двух разных записей. Обе сохранены без объединения.", SMALL))

    doc.build(story, onFirstPage=cover, onLaterPages=page_decor)
    return OUTPUT


if __name__ == "__main__":
    result = build()
    print(f"PDF создан: {result}")
