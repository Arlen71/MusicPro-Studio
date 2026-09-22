import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reports import *
from worker import publish_progress

def cells(payload):
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        xml=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        return [[ ''.join(c.itertext()) for c in row.findall(tag('c'))] for row in xml.find(tag('sheetData'))]

class ReportTests(unittest.TestCase):
    def test_exact_rounding_boundaries_and_hour(self):
        p=dict(fps=30,segments=[dict(kind='license',start=60*30,frames=330,asset={'name':'CS00652 (17).mp4'}),
                                dict(kind='clip',start=0,frames=1800,asset={'name':'clip.mp4'}),
                                dict(kind='license',start=59*30+29,frames=62,asset={'name':'CS02.MP4'}),
                                dict(kind='license',start=3600*30,frames=90,asset={'name':'CS03.mp4'})])
        rows=rows_from_plan(p)
        self.assertEqual(rows[0],[PLACEHOLDER,'CS00652 (17)','01:01','01:11'])
        self.assertEqual(rows[1][2:],['01:00','01:02'])
        self.assertEqual(rows[2][2:],['60:01','60:03'])
        url='https://www.youtube.com/watch?v=sample&list=ONE'
        self.assertTrue(all(r[0]==url for r in rows_from_plan(p,url)))

    def test_xlsx_literal_cells_and_only_four_columns(self):
        rows=[[PLACEHOLDER,'=HYPERLINK("bad")','00:01','00:12'],[PLACEHOLDER,'CS & <α> (1)','01:00','01:20']]
        blob=workbook_bytes(rows)
        self.assertEqual(cells(blob),[HEADERS,*rows])
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            doc=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
            self.assertEqual(len(doc.findall('.//'+tag('f'))),0)
            self.assertEqual(len(doc.findall('.//'+tag('row'))),3)
        self.assertEqual(cells(workbook_bytes([])),[HEADERS])

    def test_legacy_musicpro_no_clip_rows(self):
        txt='LITSEN VIDEOLAR:\nCS00652 (17).mp4 | 00:01:12.933 → 00:01:21.499 | detail\nBARCHA KADRLAR:\n00:00:00.000 → 00:00:10.000 | clip | video.mp4'
        self.assertEqual(rows_from_text(txt),[[PLACEHOLDER,'CS00652 (17)','01:13','01:21']])

    def test_legacy_prompt_format(self):
        txt=' 1. CS00209 (334).mp4\n  Oraliq: 00:01:48.799 → 00:02:05.066 (davomiyligi 16.3s)'
        self.assertEqual(rows_from_text(txt)[0][1:],['CS00209 (334)','01:49','02:05'])
        with self.assertRaises(ValueError):rows_from_text('no licensed intervals')

    def test_progress_file_permission_error_does_not_abort(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'worker.progress'
            with patch('worker.os.replace',side_effect=PermissionError('sharing violation')):
                publish_progress(p,.2)  # Must not propagate into the render loop.
            publish_progress(p,.3)
            self.assertEqual(float(p.read_text()),.3)

    def test_saved_workbook_reopens(self):
        with tempfile.TemporaryDirectory() as temp:
            p=dict(fps=25,segments=[dict(kind='license',start=1700,frames=250,asset={'name':'CS01.mp4'})])
            dest=write_report(p,temp)
            self.assertEqual(cells(dest.read_bytes())[1],[PLACEHOLDER,'CS01','01:09','01:18'])

if __name__=='__main__':unittest.main(verbosity=2)
