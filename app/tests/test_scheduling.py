"""Shared-queue acceptance with controlled lane completion order.

The application scheduler and real BatchRecovery retry controller run here;
only encoding, media preflight and disk persistence are substituted. GPU
hardware speed and native Windows execution are not claimed by these tests.
"""
import collections
import importlib
import os
import sys
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from batch import BatchRecovery
from failures import Cancelled, EncoderError, StorageError
from resources import render_budget


class SchedulingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = tempfile.TemporaryDirectory(prefix='MusicPro scheduler ')
        with patch.dict(os.environ, {'MUSICPRO_DATA_DIR': cls.data.name}):
            cls.app = importlib.import_module('app')

    @classmethod
    def tearDownClass(cls):
        cls.data.cleanup()

    def run_queue(self, renderer, total=4, device='mixed', memory=32,
                  jobs=None, stop=None, gpu='h264_nvenc'):
        stop = stop if stop is not None else threading.Event()
        with tempfile.TemporaryDirectory() as tmp:
            c = {k: str(Path(tmp)/k) for k in ('clips', 'licenses', 'music', 'output')}
            c.update(total=total, device=device, resources='high', height=720, license_count=0)
            if jobs is None:
                # Persisted 1.4-style assignments must also enter the shared queue.
                jobs = [dict(id=i+1, status='pending', device='cpu' if i % 2 == 0 else 'gpu',
                             encoder='libx264' if i % 2 == 0 else 'h264_nvenc',
                             music=f'song_{i}', dest=str(Path(tmp)/str(i)), progress=0,
                             error='', plan={'music':{'name':f'song_{i}.wav'}}) for i in range(total)]
            state = dict(config=c, jobs=jobs, batch='scheduling_test', logs=[],
                         catalog={'clip': [], 'license': [], 'music': []}, summary={'gpu': gpu})
            with ExitStack() as stack:
                for name, value in [('STATE', state), ('STOP', stop), ('BUSY', True),
                                    ('LOCK', threading.RLock())]:
                    stack.enter_context(patch.object(self.app, name, value))
                stack.enter_context(patch.object(self.app, 'save'))
                stack.enter_context(patch.object(self.app, 'log', side_effect=state['logs'].append))
                stack.enter_context(patch.object(self.app, 'ResourceGovernor'))
                stack.enter_context(patch.object(self.app, 'render_isolated', side_effect=renderer))
                stack.enter_context(patch.object(self.app, 'render_budget',
                    side_effect=lambda conf, devices: render_budget(conf, devices, 16, memory)))
                stack.enter_context(patch.object(BatchRecovery, 'plan_current', return_value=True))
                stack.enter_context(patch.object(BatchRecovery, 'completed'))
                stack.enter_context(patch.object(BatchRecovery, 'save_issues'))
                self.app.run_batch()
                self.assertFalse(self.app.BUSY)
            return state

    def faster_lane(self, fast):
        slow_started = threading.Event(); fast_finished = threading.Event()
        calls = []; mutex = threading.Lock()
        def render(job, config, progress):
            device = job['device']
            with mutex: calls.append((job['id'], device, job['encoder']))
            if device == fast:
                if not slow_started.wait(3): raise AssertionError('Second lane did not start')
                with mutex:
                    if sum(d == fast for _, d, _ in calls) == 3: fast_finished.set()
            else:
                slow_started.set()
                if not fast_finished.wait(3): raise AssertionError('Fast lane could not take the third queued job')
            progress(1)
        state = self.run_queue(render)
        self.assertEqual(state['status'], 'completed', state)
        self.assertEqual(collections.Counter(d for _, d, _ in calls), {fast: 3, 'cpu' if fast == 'gpu' else 'gpu': 1})
        self.assertEqual(sorted(i for i, _, _ in calls), [1, 2, 3, 4])
        self.assertTrue(all(enc == ('libx264' if d == 'cpu' else 'h264_nvenc') for _, d, enc in calls))
        self.assertTrue(all(j['status'] == 'done' for j in state['jobs']))

    def test_gpu_takes_waiting_cpu_jobs_while_cpu_finishes_its_current_video(self):
        self.faster_lane('gpu')

    def test_cpu_can_also_take_waiting_gpu_jobs(self):
        self.faster_lane('cpu')

    def test_low_memory_uses_one_gpu_lane_without_stranded_work(self):
        calls = []
        state = self.run_queue(lambda j, c, p: calls.append(j['device']), memory=.2)
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(calls, ['gpu']*4)
        self.assertEqual(set(state['resource_budget']['lanes']), {'gpu'})

    def test_single_video_prefers_gpu_in_mixed_mode(self):
        calls = []
        state = self.run_queue(lambda j, c, p: calls.append(j['device']), total=1)
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(calls, ['gpu'])

    def test_explicit_cpu_gpu_and_unavailable_gpu_modes(self):
        for device, gpu, expected in [('cpu', 'h264_nvenc', 'cpu'),
                                      ('gpu', 'h264_nvenc', 'gpu'), ('mixed', None, 'cpu')]:
            with self.subTest(device=device, gpu=gpu):
                calls = []
                state = self.run_queue(lambda j, c, p: calls.append(j['device']), device=device, gpu=gpu)
                self.assertEqual(state['status'], 'completed')
                self.assertEqual(calls, [expected]*4)

    def test_gpu_failure_keeps_current_job_ownership_and_cpu_drains_queue(self):
        cpu_started = threading.Event(); fallback_started = threading.Event()
        calls = []; mutex = threading.Lock(); completed_ids = []
        def render(job, config, progress):
            with mutex: calls.append((job['id'], job['device']))
            if job['device'] == 'gpu':
                if not cpu_started.wait(3): raise AssertionError('CPU lane did not start')
                raise EncoderError('Controlled unavailable GPU')
            if job['attempt'] == 2:
                fallback_started.set()
            elif not cpu_started.is_set():
                cpu_started.set()
                if not fallback_started.wait(3): raise AssertionError('GPU fallback did not start')
            with mutex: completed_ids.append(job['id'])
        state = self.run_queue(render, total=6)
        self.assertEqual(state['status'], 'completed_issues', state)
        self.assertEqual(sorted(completed_ids), list(range(1, 7)))
        self.assertEqual(sum(d == 'gpu' for _, d in calls), 1)
        self.assertEqual(len(calls), 7)  # six completed jobs and one failed GPU attempt
        self.assertTrue(all(j['device'] == 'cpu' for j in state['jobs']))
        self.assertEqual(state['blocked'], {'clip': [], 'license': [], 'music': []})

    def test_gpu_only_failure_continues_remaining_jobs_on_cpu(self):
        calls = []
        def render(job, config, progress):
            calls.append((job['id'], job['device']))
            if job['device'] == 'gpu': raise EncoderError('GPU unavailable')
        state = self.run_queue(render, device='gpu')
        self.assertEqual(state['status'], 'completed_issues')
        self.assertEqual(calls, [(1, 'gpu'), (1, 'cpu'), (2, 'cpu'), (3, 'cpu'), (4, 'cpu')])

    def test_stop_and_resume_do_not_claim_or_repeat_extra_jobs(self):
        stop = threading.Event(); calls = []
        def interrupted(job, config, progress):
            calls.append(job['id']); stop.set(); raise Cancelled()
        state = self.run_queue(interrupted, device='cpu', stop=stop)
        self.assertEqual(state['status'], 'paused')
        self.assertEqual(calls, [1])
        self.assertTrue(all(j['status'] == 'pending' for j in state['jobs']))
        # A previously completed job stays untouched after reloading old assignments.
        state['jobs'][0].update(status='done', progress=1)
        calls.clear()
        resumed = self.run_queue(lambda j, c, p: calls.append(j['id']), jobs=state['jobs'])
        self.assertEqual(resumed['status'], 'completed')
        self.assertEqual(sorted(calls), [2, 3, 4])

    def test_unrecoverable_job_does_not_block_remaining_queue(self):
        calls = []
        def render(job, config, progress):
            calls.append(job['id'])
            if job['id'] == 1: raise StorageError('Controlled output write failure')
        state = self.run_queue(render, device='cpu')
        self.assertEqual(state['status'], 'error')
        self.assertEqual(calls, [1, 2, 3, 4])
        self.assertEqual([j['status'] for j in state['jobs']], ['error', 'done', 'done', 'done'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
