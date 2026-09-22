"""Per-output Top 5/10 selection, random gaps, persistence and recovery."""
import copy
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import UserError, validate, validate_plan
from failures import SourceError
from playlist import order_slots, select_tracks, text_from_plan
from test_engine import asset
import test_playlist as pt


class PerVideoSelectionTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path('music').resolve()
        self.pool = [asset(str(self.folder/f'Song {i}.wav'), i+5) for i in range(14)]
        self.paths = [a['path'] for a in self.pool]
        self.raw = dict(clips='clips', licenses='licenses', music=str(self.folder),
                        output='output', total=3, music_mode='playlist', playlist_count=10)

    def test_independent_top_ten_and_sparse_slots_without_repeats(self):
        mapping = {'1':dict(enabled=True, tracks=self.paths[:10]),
                   '2':dict(enabled=True, tracks=self.paths[1:11][::-1]),
                   '3':dict(enabled=True, tracks=['',self.paths[2],'','',self.paths[8],
                                                  '','','','',self.paths[12]])}
        c = validate({**self.raw, 'playlist_per_video':mapping})
        random_orders = set()
        for seed in range(20):
            for job_id in range(1,4):
                slots = order_slots(c,job_id)
                selected,missing = select_tracks(self.pool,10,random.Random(seed),slots)
                paths = [a['path'] for a in selected]
                self.assertEqual(len(set(paths)),10)
                self.assertFalse(missing)
                for index,path in slots.items():self.assertEqual(paths[index],path)
                if job_id==3:random_orders.add(tuple(paths))
        self.assertGreater(len(random_orders),1)

    def test_absent_disabled_empty_and_single_mode_are_random(self):
        c = validate({**self.raw,'playlist_order_enabled':True,'playlist_first':self.paths[0],
                      'playlist_per_video':{'1':dict(enabled=False,tracks=self.paths[:10]),
                                            '2':dict(enabled=True,tracks=['']*10)}})
        for job_id in range(1,4):self.assertEqual(order_slots(c,job_id),{})
        self.assertEqual(c['playlist_per_video']['1']['tracks'],self.paths[:10])
        orders={tuple(a['path'] for a in select_tracks(self.pool,10,random.Random(seed),order_slots(c,3))[0])
                for seed in range(10)}
        self.assertGreater(len(orders),1)
        c['playlist_per_video']['1']['enabled']=True;c['music_mode']='single'
        self.assertEqual(order_slots(c,1),{})
        legacy=validate({**self.raw,'playlist_order_enabled':True,'playlist_first':self.paths[0]})
        self.assertEqual(order_slots(legacy,1),{0:self.paths[0]})

    def test_duplicate_rejection_is_local_to_each_video(self):
        mapping={str(i):dict(enabled=True,tracks=self.paths[:10]) for i in (1,2)}
        c=validate({**self.raw,'playlist_per_video':mapping})
        self.assertEqual(order_slots(c,1),order_slots(c,2))
        mapping['2']['tracks']=[self.paths[0],self.paths[0]]
        with self.assertRaisesRegex(UserError,'2-video.*ikki o‘ringa'):
            validate({**self.raw,'playlist_per_video':mapping})
        with self.assertRaisesRegex(UserError,'joriy Musikalar'):
            validate({**self.raw,'playlist_per_video':{'1':dict(enabled=True,tracks=['outside.wav'])}})

    def test_settings_roundtrip_and_smaller_counts_keep_inactive_choices(self):
        mapping={'1':dict(enabled=True,tracks=self.paths[:10]),
                 '3':dict(enabled=True,tracks=self.paths[:10][::-1])}
        c=validate({**self.raw,'playlist_per_video':mapping})
        c=validate(json.loads(json.dumps(c)))
        smaller=validate({**c,'total':1,'playlist_count':5})
        self.assertEqual(len(order_slots(smaller,1)),5)
        self.assertEqual(smaller['playlist_per_video'],c['playlist_per_video'])
        restored=validate({**smaller,'total':3,'playlist_count':10})
        self.assertEqual(order_slots(restored,3),dict(enumerate(self.paths[:10][::-1])))

    def test_invalid_editor_payloads_are_rejected(self):
        for mapping in ([],{'0':{}},{'01':{}},{'10001':{}},{'1':None},
                        {'1':dict(enabled='on')},{'1':dict(tracks='song.wav')},
                        {'1':dict(tracks=['']*1001)},{'1':dict(tracks=[None])}):
            with self.subTest(mapping=str(mapping)[:80]),self.assertRaises(UserError):
                validate({**self.raw,'playlist_per_video':mapping})


class PerVideoRecoveryTests(unittest.TestCase):
    def test_jobs_keep_separate_orders_and_reject_wrong_job_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            c,state,r,analyze=pt.PlaylistRecoveryTests().fixture(Path(temp),total=3)
            paths=[a['path'] for a in r.catalog['music']]
            c.update(total=3,playlist_per_video={'1':dict(enabled=True,tracks=paths[:3]),
                                               '2':dict(enabled=True,tracks=paths[:3][::-1])})
            with patch('batch.analyze_playlist_music',side_effect=analyze):
                for job in state['jobs']:r.prepare(job)
            for i,job in enumerate(state['jobs'],1):
                self.assertEqual(job['plan']['playlist_job_id'],i)
                self.assertTrue(r.plan_current(job))
                validate_plan(job['plan'],c)
            self.assertEqual([t['asset']['path'] for t in state['jobs'][0]['plan']['tracks']],paths[:3])
            self.assertEqual([t['asset']['path'] for t in state['jobs'][1]['plan']['tracks']],paths[:3][::-1])
            foreign={**state['jobs'][1],'plan':copy.deepcopy(state['jobs'][0]['plan'])}
            self.assertFalse(r.plan_current(foreign))
            wrong=copy.deepcopy(state['jobs'][0]['plan']);wrong['playlist_job_id']=2
            with self.assertRaises(UserError):validate_plan(wrong,c)
            wrong.pop('playlist_job_id')
            with self.assertRaises(UserError):validate_plan(wrong,c)

    def test_bad_selected_music_replaced_only_in_its_slot_without_changing_other_job(self):
        with tempfile.TemporaryDirectory() as temp:
            c,state,r,analyze=pt.PlaylistRecoveryTests().fixture(Path(temp),total=2)
            tracks=r.catalog['music'];paths=[a['path'] for a in tracks]
            c.update(total=2,playlist_per_video={'1':dict(enabled=True,tracks=paths[:3]),
                                               '2':dict(enabled=True,tracks=paths[1:][::-1])})
            attempts=[]
            def render(job,config):
                attempts.append(job['id'])
                if tracks[0]['path'] in [t['asset']['path'] for t in job['plan']['tracks']]:
                    raise SourceError(tracks[0],'music','Damaged source')
            with patch('batch.analyze_playlist_music',side_effect=analyze):
                for job in state['jobs']:r.run_job(job,render,c)
            self.assertEqual(attempts,[1,1,2])
            actual=[[t['asset']['path'] for t in job['plan']['tracks']] for job in state['jobs']]
            self.assertEqual(actual,[[paths[3],paths[1],paths[2]],paths[1:][::-1]])
            self.assertTrue(state['issues'])
            for job in state['jobs']:
                validate_plan(job['plan'],c)
                self.assertTrue(Path(job['dest']).name.startswith('replacement'))
                self.assertIn('0:00 replacement',text_from_plan(job['plan']))


if __name__=='__main__':unittest.main(verbosity=2)
