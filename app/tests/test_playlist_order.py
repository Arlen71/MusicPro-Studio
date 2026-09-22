"""1.7 ordering, naming collisions, legacy migration and recovery regressions."""
import copy
import random
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from engine import UserError, music_choices, validate, validate_plan
from failures import SourceError
from output_names import MARKER, prepare_output, safe_title, video_filename
from playlist import ORDER_KEYS, order_slots, select_tracks, text_from_plan
from test_engine import asset
import test_playlist as playlist_tests
from test_playlist import playlist_plan


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.pool = [asset(f'/music/Song {i}.wav', i+5) for i in range(8)]

    def test_each_subset_of_first_three_slots_and_random_remaining(self):
        for mask in range(8):
            slots = {i:self.pool[i]['path'] for i in range(3) if mask & (1<<i)}
            orders = []
            for seed in range(20):
                selected, missing = select_tracks(self.pool,5,random.Random(seed),slots)
                paths = [a['path'] for a in selected]
                self.assertEqual(len(set(paths)),5)
                self.assertFalse(missing)
                for index,path in slots.items():self.assertEqual(paths[index],path)
                orders.append(tuple(paths))
            self.assertGreater(len(set(orders)),1)

    def test_disabled_panel_ignores_saved_selections_and_small_counts(self):
        c = dict(music_mode='playlist',playlist_count=5,playlist_order_enabled=False,
                 playlist_first='/music/Song 0.wav',playlist_second='/music/Song 1.wav')
        self.assertEqual(order_slots(c),{})
        c['playlist_order_enabled']=True;c['playlist_count']=1
        self.assertEqual(order_slots(c),{0:'/music/Song 0.wav'})
        c['music_mode']='single'
        self.assertEqual(order_slots(c),{})

    def test_preserve_healthy_positions_without_stealing_a_later_fixed_song(self):
        preferred=[{'asset':a} for a in self.pool[:5]]
        slots={1:self.pool[0]['path'],2:self.pool[7]['path']}
        selected,_=select_tracks(self.pool,5,random.Random(1),slots,preferred)
        self.assertEqual(selected[1],self.pool[0])
        self.assertEqual(selected[2],self.pool[7])
        self.assertEqual(selected[3:],self.pool[3:5])
        self.assertEqual(len({a['path'] for a in selected}),5)

    def test_fixed_invalid_song_replaced_but_other_positions_stay(self):
        preferred=[{'asset':a} for a in self.pool[:4]]
        slots={0:self.pool[0]['path'],1:self.pool[1]['path'],2:self.pool[2]['path']}
        selected,missing=select_tracks(self.pool[1:],4,random.Random(4),slots,preferred)
        self.assertEqual(missing,{'0':self.pool[0]['path']})
        self.assertEqual(selected[1:],self.pool[1:4])
        self.assertNotIn(selected[0],self.pool[:4])

    def test_config_migration_and_active_duplicate_path_validation(self):
        raw=dict(clips='c',licenses='l',music='m',output='o')
        c=validate(raw)
        self.assertFalse(c['playlist_order_enabled'])
        self.assertTrue(all(c[key]=='' for key in ORDER_KEYS))
        song=str(Path('m/song.wav').resolve())
        for enabled in (True,'1','on','true'):
            with self.assertRaisesRegex(UserError,'ikki o‘ringa'):
                validate({**raw,'music_mode':'playlist','playlist_order_enabled':enabled,
                          'playlist_first':song,'playlist_second':song})
        c=validate({**raw,'music_mode':'playlist','playlist_order_enabled':False,
                    'playlist_first':song,'playlist_second':song})
        self.assertEqual(c['playlist_first'],song)
        with self.assertRaisesRegex(UserError,'joriy Musikalar'):
            validate({**raw,'music_mode':'playlist','playlist_order_enabled':True,
                      'playlist_first':str(Path('elsewhere/song.wav').resolve())})

    def test_music_list_is_local_sorted_nonrecursive_and_preserves_unicode(self):
        with tempfile.TemporaryDirectory() as temp:
            # macOS hands out /var/... for a /private/var temp dir; the app resolves.
            root=Path(temp).resolve()
            for name in ('Z.wav','a.MP3','Qo‘shiq – Ўзбек.flac','notes.txt'):(root/name).write_bytes(b'not probed here')
            (root/'nested').mkdir();(root/'nested/deep.wav').write_bytes(b'')
            result=music_choices(str(root))
            self.assertEqual([a['name'] for a in result['files']],['a.MP3','Qo‘shiq – Ўзбек.flac','Z.wav'])
            self.assertTrue(all(Path(a['path']).parent==root for a in result['files']))


class NamingTests(unittest.TestCase):
    def test_safe_windows_names_reserved_unicode_and_trailing_dots(self):
        self.assertEqual(safe_title('Artist – Ўзбек qo‘shiq'), 'Artist – Ўзбек qo‘shiq')
        self.assertEqual(safe_title('CON'), '_CON')
        self.assertEqual(safe_title('LPT1.song'), '_LPT1.song')
        self.assertEqual(safe_title('A: B? / C*. '),'A_ B_ _ C_')
        self.assertEqual(safe_title('... '),'Musiqa')
        self.assertLessEqual(len(safe_title('🎵'*100).encode('utf-16-le')),160)
        with self.assertRaises(UserError):video_filename({'video_filename':'../escape.mp4'})
        self.assertEqual(video_filename({}),'video.mp4')  # legacy direct-render compatibility

    def test_named_output_case_insensitive_collisions_and_existing_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'SONG').mkdir();(root/'SONG/user.txt').write_text('keep')
            (root/'Song (2)').write_text('keep as file')
            plan={'music':asset('Song.mp3',10)}
            j=dict(id=1)
            dest=prepare_output(j,plan,{'output':temp},'batch')
            self.assertEqual(dest.name,'Song (3)')
            self.assertEqual(plan['video_filename'],'Song (3).mp4')
            self.assertEqual((root/'SONG/user.txt').read_text(),'keep')
            self.assertEqual((root/'Song (2)').read_text(),'keep as file')
            self.assertEqual(prepare_output(j,plan,{'output':temp},'batch'),dest)

    def test_concurrent_jobs_reserve_unique_folders(self):
        with tempfile.TemporaryDirectory() as temp:
            def create(i):
                j={'id':i};p={'music':asset('Same song.mp3',10)}
                return prepare_output(j,p,{'output':temp},'batch')
            with ThreadPoolExecutor(max_workers=6) as pool:
                paths=list(pool.map(create,range(1,21)))
            self.assertEqual(len(set(paths)),20)
            self.assertTrue(all((p/MARKER).is_file() for p in paths))

    def test_first_song_replacement_renames_and_preserves_own_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp:
            job={'id':1};plan={'music':asset('Bad.mp3',10)}
            previous=prepare_output(job,plan,{'output':temp},'batch')
            (previous/'render_diagnostics.txt').write_text('decode failed',encoding='utf-8')
            changed={'music':asset('Virtual Playlist',20),'tracks':[{'asset':asset('Healthy.flac',20)}]}
            final=prepare_output(job,changed,{'output':temp},'batch')
            self.assertEqual(final.name,'Healthy')
            self.assertEqual(changed['video_filename'],'Healthy.mp4')
            self.assertFalse(previous.exists())
            self.assertEqual((final/'render_diagnostics.txt').read_text(),'decode failed')

    def test_unexpected_files_and_other_jobs_are_never_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            job={'id':1};plan={'music':asset('First.mp3',10)}
            previous=prepare_output(job,plan,{'output':temp},'batch')
            (previous/'user.mp4').write_bytes(b'user data')
            prepare_output(job,{'music':asset('Second.mp3',10)},{'output':temp},'batch')
            self.assertEqual((previous/'user.mp4').read_bytes(),b'user data')
            other={'id':2,'dest':str(previous),'name_base':'First'}
            p={'music':asset('First.mp3',10)}
            self.assertNotEqual(prepare_output(other,p,{'output':temp},'batch'),previous)


class OrderedRecoveryTests(unittest.TestCase):
    def fixture(self, root, **kw):
        return playlist_tests.PlaylistRecoveryTests().fixture(root, **kw)

    def test_all_jobs_keep_selected_slots_and_name_from_first_music(self):
        with tempfile.TemporaryDirectory() as temp:
            c,state,r,analyze=self.fixture(Path(temp),total=4)
            paths=[a['path'] for a in r.catalog['music']]
            c.update(playlist_order_enabled=True,playlist_first=paths[1],
                     playlist_second=paths[3],playlist_third=paths[0])
            with patch('batch.analyze_playlist_music',side_effect=analyze):
                for j in state['jobs']:r.prepare(j)
            self.assertEqual([Path(j['dest']).name for j in state['jobs']],
                             ['good1','good1 (2)','good1 (3)','good1 (4)'])
            for j in state['jobs']:
                self.assertEqual([t['asset']['path'] for t in j['plan']['tracks']],[paths[1],paths[3],paths[0]])
                self.assertEqual(j['video_filename'],Path(j['dest']).name+'.mp4')
                validate_plan(j['plan'],c)

    def test_fixed_first_source_decode_failure_updates_name_and_reports_automatically(self):
        with tempfile.TemporaryDirectory() as temp:
            c,state,r,analyze=self.fixture(Path(temp))
            original=r.catalog['music'][:3]
            c.update(playlist_order_enabled=True,**dict(zip(ORDER_KEYS,[a['path'] for a in original])))
            j=state['jobs'][0];attempts=[]
            def render(job,config):
                attempts.append(copy.deepcopy(job))
                if job['plan']['tracks'][0]['asset']['path']==original[0]['path']:
                    (Path(job['dest'])/'render_diagnostics.txt').write_text('source error')
                    raise SourceError(original[0],'music','Damaged after planning')
            with patch('batch.analyze_playlist_music',side_effect=analyze):r.run_job(j,render,c)
            self.assertEqual(len(attempts),2)
            self.assertEqual(Path(j['dest']).name,'replacement')
            self.assertEqual(j['video_filename'],'replacement.mp4')
            self.assertEqual([t['asset'] for t in j['plan']['tracks'][1:]],original[1:])
            self.assertFalse(Path(attempts[0]['dest']).exists())
            self.assertIn('0:00 replacement',text_from_plan(j['plan']))
            self.assertNotIn('0:00 bad',text_from_plan(j['plan']))
            self.assertTrue(any('1-o‘rin' in issue['action'] for issue in state['issues']))
            validate_plan(j['plan'],c)

    def test_recovery_cannot_silently_reorder_healthy_fixed_slots(self):
        with tempfile.TemporaryDirectory() as temp:
            c,state,r,analyze=self.fixture(Path(temp))
            original=r.catalog['music'][:3]
            c.update(playlist_order_enabled=True,playlist_second=original[1]['path'])
            p=playlist_plan(original,c,clips=r.catalog['clip'],licenses=r.catalog['license'])
            p['tracks'][1]['asset'],p['tracks'][0]['asset']=p['tracks'][0]['asset'],p['tracks'][1]['asset']
            with self.assertRaises(UserError):validate_plan(p,c)


if __name__=='__main__':unittest.main(verbosity=2)
