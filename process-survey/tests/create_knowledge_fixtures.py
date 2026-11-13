#!/usr/bin/env python3
"""Создаёт небольшие документы для браузерной проверки базы знаний."""
from pathlib import Path
import docx
import openpyxl

ROOT = Path(__file__).resolve().parents[1] / 'tests' / 'fixtures'
ROOT.mkdir(parents=True, exist_ok=True)
workbook = openpyxl.Workbook()
sheet = workbook.active
sheet.title = 'Проверка серии'
sheet.append(['Артикул', 'Количество', 'Ответственный', 'Статус'])
sheet.append(['BAL-001', 120, 'Иван', 'Готов'])
sheet.append(['BAL-002', 80, 'Мария', 'Проверка'])
sheet['E2'] = '=B2*2'
workbook.save(ROOT / 'process-template.xlsx')

document = docx.Document()
document.add_paragraph('Инструкция по проверке серии Balkan.')
document.add_paragraph('Мастер проверяет номер серии и подписывает журнал. QA утверждает результат.')
table = document.add_table(rows=2, cols=2)
table.rows[0].cells[0].text = 'Этап'
table.rows[0].cells[1].text = 'Ответственный'
table.rows[1].cells[0].text = 'Утверждение'
table.rows[1].cells[1].text = 'QA'
document.save(ROOT / 'batch-instruction.docx')
print(ROOT)
