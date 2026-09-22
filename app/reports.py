"""Four-column licensing reports; populate the bundled formatted XLSX template.

The Windows runtime only needs the Python standard library. Worksheet cells are
stored as literal strings, including MM:SS and file codes (never as formulas).
"""
from __future__ import annotations
import io
import os
import re
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

HEADERS = ['video_url', 'clip_code_and_title', 'start', 'end']
PLACEHOLDER = "VIDEO LINKI NI QO'YING"
REPORT_NAME = 'Litsen_video_malumot.xlsx'
TEMPLATE = Path(__file__).resolve().parent / 'assets' / 'report_template.xlsx'
NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
ET.register_namespace('', NS)

def tag(name):
    return '{' + NS + '}' + name

def mmss(seconds):
    return f'{seconds // 60:02d}:{seconds % 60:02d}'

def link_value(value):
    if value is None or not str(value).strip():
        return PLACEHOLDER
    value = str(value)
    if len(value) > 4000 or any(ord(c) < 32 for c in value):
        raise ValueError('YouTube havolasida noto‘g‘ri belgi bor yoki u juda uzun.')
    return value  # Preserve exactly what was provided.

def clip_code(name):
    return re.sub(r'\.mp4$', '', str(name), flags=re.I)

def rows_from_plan(plan, video_url=''):
    fps = int(plan['fps'])
    return [[link_value(video_url), clip_code(s['asset']['name']),
             mmss(int(s['start']) // fps + 1),
             mmss((int(s['start']) + int(s['frames'])) // fps)]
            for s in plan['segments'] if s['kind'] == 'license']

def rows_from_text(text, video_url=''):
    # Legacy MusicPro report: only the dedicated license block is converted.
    if 'LITSEN VIDEOLAR' in text:
        text = text.split('LITSEN VIDEOLAR', 1)[1].split('BARCHA KADRLAR', 1)[0]
    clock = r'(\d+):(\d{2}):(\d{2})(?:[.,]\d+)?'
    lines = re.findall(r'^\s*(.+?\.mp4)\s*\|\s*' + clock + r'\s*→\s*' + clock,
                       text, re.M | re.I)
    if not lines:
        lines = re.findall(r'^\s*\d+\.\s*(.+?\.mp4)\s*\r?\n\s*Oraliq:\s*' +
                           clock + r'\s*→\s*' + clock, text, re.M | re.I)
    if not lines:
        raise ValueError('TXT faylida litsen videolar oraliqlari topilmadi.')
    result = []
    for name, h1, m1, s1, h2, m2, s2 in lines:
        if max(int(m1), int(m2), int(s1), int(s2)) > 59:
            raise ValueError('TXT faylida noto‘g‘ri vaqt bor.')
        start = int(h1)*3600 + int(m1)*60 + int(s1)
        end = int(h2)*3600 + int(m2)*60 + int(s2)
        result.append([link_value(video_url), clip_code(name.strip()), mmss(start+1), mmss(end)])
    return result

def workbook_bytes(rows):
    """Fill data in a pre-authored XLSX asset without adding a runtime dependency."""
    with zipfile.ZipFile(TEMPLATE) as template:
        worksheet = ET.fromstring(template.read('xl/worksheets/sheet1.xml'))
        old = worksheet.find(tag('sheetData'))
        row_nodes = old.findall(tag('row'))
        styles = [[c.get('s', '0') for c in row.findall(tag('c'))] for row in row_nodes[:2]]
        data = ET.Element(tag('sheetData'))
        for number, values in enumerate([HEADERS, *rows], 1):
            row = ET.SubElement(data, tag('row'), {'r':str(number), 'ht': '22' if number == 1 else '20', 'customHeight':'1'})
            for col, value in enumerate(values):
                style = styles[0 if number == 1 else 1][col]
                cell = ET.SubElement(row, tag('c'), {'r':f'{chr(65+col)}{number}', 's':style, 't':'inlineStr'})
                node = ET.SubElement(ET.SubElement(cell, tag('is')), tag('t'), {'{http://www.w3.org/XML/1998/namespace}space':'preserve'})
                # Excel cannot store control characters in XML 1.0 text.
                node.text = ''.join(c for c in str(value) if ord(c) >= 32 or c in '\t\n\r')
        index = list(worksheet).index(old); worksheet.remove(old); worksheet.insert(index, data)
        dimension = worksheet.find(tag('dimension'))
        if dimension is not None: dimension.set('ref', f'A1:D{len(rows)+1}')
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as result:
            for item in template.infolist():
                payload = ET.tostring(worksheet, encoding='utf-8', xml_declaration=True) if item.filename == 'xl/worksheets/sheet1.xml' else template.read(item.filename)
                result.writestr(item, payload)
        return out.getvalue()

def write_report(plan, dest, video_url=''):
    dest = Path(dest); dest.mkdir(parents=True, exist_ok=True)
    target = dest / REPORT_NAME
    payload = workbook_bytes(rows_from_plan(plan, video_url))
    with tempfile.NamedTemporaryFile(prefix='report_', suffix='.tmp', dir=dest, delete=False) as f:
        temp = Path(f.name); f.write(payload)
    try:
        os.replace(temp, target)
    except PermissionError as e:
        raise ValueError('Excel hisoboti boshqa dasturda ochiq. Uni yoping va hisobotni qayta saqlang.') from e
    finally:
        temp.unlink(missing_ok=True)
    return target
