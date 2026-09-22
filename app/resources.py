"""Bounded render concurrency and Windows aggregate CPU rate control.

The job contains the server and all subsequently created workers/FFmpeg children.
No GPU power limit is changed. GPU load is controlled through encoder concurrency.
Windows restrictions are reported; thread budgeting remains a usable fallback.
"""
from __future__ import annotations
import ctypes
import math
import os
import re
import subprocess
import sys
import threading

PROFILES = {'auto': .40, 'medium': .60, 'high': .85}
_JOB = None


def macos_available_gb():
    """macOS has no SC_AVPHYS_PAGES; count the pages the kernel can reclaim."""
    page = os.sysconf('SC_PAGE_SIZE')
    try:
        out = subprocess.run(['/usr/bin/vm_stat'], capture_output=True, text=True, timeout=10).stdout
        counts = {k.strip(): int(v) for k, v in re.findall(r'^(.+?):\s+(\d+)\.\s*$', out, re.M)}
        pages = sum(counts.get(k, 0) for k in ('Pages free', 'Pages inactive', 'Pages speculative', 'Pages purgeable'))
        if pages > 0:
            return pages * page / 1024**3
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    # A warm page cache still leaves roughly half of physical memory reclaimable.
    return os.sysconf('SC_PHYS_PAGES') * page / 1024**3 * .5


def available_memory_gb():
    try:
        if sys.platform == 'darwin':
            return macos_available_gb()
        if os.name == 'nt':
            class Memory(ctypes.Structure):
                _fields_ = [('length', ctypes.c_uint32), ('load', ctypes.c_uint32)] + [
                    (n, ctypes.c_uint64) for n in ('total', 'available', 'page_total', 'page_available', 'virtual_total', 'virtual_available', 'extended')]
            state = Memory(); state.length = ctypes.sizeof(state)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
                raise OSError('GlobalMemoryStatusEx')
            return state.available / 1024**3
        return os.sysconf('SC_AVPHYS_PAGES') * os.sysconf('SC_PAGE_SIZE') / 1024**3
    except (AttributeError, OSError, ValueError):
        return 4.0


def render_budget(config, devices, cores=None, memory_gb=None):
    """Total concurrent segments are bounded across CPU and GPU lanes."""
    profile = config.get('resources', 'auto')
    cores = max(1, int(cores or os.cpu_count() or 4))
    memory_gb = available_memory_gb() if memory_gb is None else memory_gb
    devices = sorted(set(devices))
    # Includes decode, filter, encoder and frame queues, with headroom for the OS.
    per_segment = 1.0 if config['height'] == 1080 else .6
    slots = max(1, min(8, int(max(0, memory_gb) * .65 / per_segment)))
    cpu_want = {'auto': 1, 'medium': 2, 'high': 4}[profile]
    gpu_want = {'auto': 1, 'medium': 2, 'high': 3}[profile]
    wants = {d: min(cpu_want, max(1, cores//4)) if d == 'cpu' else min(gpu_want, max(1, cores//2)) for d in devices}
    counts = {d: 1 for d in devices}
    # A low-memory mixed batch uses one lane at a time.
    parallel_lanes = slots >= len(devices)
    capacity = slots if parallel_lanes else 1
    if parallel_lanes:
        while sum(counts.values()) < capacity:
            changed = False
            for d in devices:
                if counts[d] < wants[d] and sum(counts.values()) < capacity:
                    counts[d] += 1; changed = True
            if not changed: break
    active = sum(counts.values()) if parallel_lanes else 1
    share = max(1, math.ceil(cores * PROFILES[profile] / max(1, active)))
    return dict(profile=profile, cores=cores, memory_gb=round(memory_gb,1), parallel_lanes=parallel_lanes,
                lanes={d: dict(segment_workers=counts[d], encoder_threads=min(32,share),
                               filter_threads=max(1,min(4,share//3)), decode_threads=max(1,min(4,share//3))) for d in devices})


class WindowsCpuJob:
    """Windows 8+ Job Object hard cap, shared by every descendant process."""
    def __init__(self):
        from ctypes import wintypes as w
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        self.k.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        self.k.CreateJobObjectW.restype = w.HANDLE
        self.k.GetCurrentProcess.restype = w.HANDLE
        self.k.AssignProcessToJobObject.argtypes = [w.HANDLE,w.HANDLE]
        self.k.AssignProcessToJobObject.restype = w.BOOL
        self.k.SetInformationJobObject.argtypes = [w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
        self.k.SetInformationJobObject.restype = w.BOOL
        self.k.QueryInformationJobObject.argtypes = [w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD,ctypes.c_void_p]
        self.k.QueryInformationJobObject.restype = w.BOOL
        self.k.GetSystemTimes.argtypes = [ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p]
        self.k.GetSystemTimes.restype = w.BOOL
        self.k.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.k.CreateJobObjectW(None,None)
        if not self.handle: raise ctypes.WinError(ctypes.get_last_error())
        if not self.k.AssignProcessToJobObject(self.handle,self.k.GetCurrentProcess()):
            error = ctypes.get_last_error(); self.k.CloseHandle(self.handle)
            raise ctypes.WinError(error)

    def cap(self, percent=None):
        class Rate(ctypes.Structure):
            _fields_ = [('flags',ctypes.c_uint32),('rate',ctypes.c_uint32)]
        info = Rate(5 if percent is not None else 0, round(percent*100) if percent is not None else 0)
        if not self.k.SetInformationJobObject(self.handle,15,ctypes.byref(info),ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())

    def sample(self):
        class Accounting(ctypes.Structure):
            _fields_ = [(n,ctypes.c_int64) for n in ('user','kernel','period_user','period_kernel')] + [
                (n,ctypes.c_uint32) for n in ('faults','processes','active','terminated')]
        idle = ctypes.c_uint64(); kernel = ctypes.c_uint64(); user = ctypes.c_uint64(); job = Accounting()
        if not self.k.GetSystemTimes(ctypes.byref(idle),ctypes.byref(kernel),ctypes.byref(user)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not self.k.QueryInformationJobObject(self.handle,1,ctypes.byref(job),ctypes.sizeof(job),None):
            raise ctypes.WinError(ctypes.get_last_error())
        return idle.value, kernel.value+user.value, job.user+job.kernel


def automatic_cap(previous, current):
    idle, total, own = (b-a for a,b in zip(previous,current))
    if total <= 0: return 40
    external = max(0, min(100, 100*(total-idle-own)/total))
    return max(15, min(60, round(80-external)))


class ResourceGovernor:
    def __init__(self, profile, report):
        self.profile = profile; self.report = report
        self.stop = threading.Event(); self.thread = None; self.job = None

    def start(self):
        global _JOB
        if os.name != 'nt':
            self.report(('macOS qattiq CPU foiz limitini bermaydi; ' if sys.platform == 'darwin' else
                         'CPU foiz limiti Windowsda ishlaydi; ') +
                        'oqimlar, parallel segmentlar va past jarayon ustuvorligi orqali boshqariladi.')
            return
        try:
            if _JOB is None: _JOB = WindowsCpuJob()
            self.job = _JOB
            target = {'auto':40,'medium':60,'high':85}[self.profile]
            self.job.cap(target)
            self.report(f'CPU umumiy limiti: {target}%' + (' · avtomatik moslashadi (15–60%).' if self.profile=='auto' else '.'))
            if self.profile == 'auto':
                self.thread = threading.Thread(target=self._adapt,daemon=True); self.thread.start()
        except (OSError,AttributeError) as e:
            self.report(f'Windows CPU foiz limitini qo‘llamadi ({e}). Oqimlar va parallel segmentlar bo‘yicha resurs rejimi ishlaydi.')

    def _adapt(self):
        try:
            previous = self.job.sample()
            while not self.stop.wait(2):
                current = self.job.sample(); self.job.cap(automatic_cap(previous,current)); previous = current
        except OSError as e:
            self.report(f'Avtomatik CPU nazorati to‘xtadi, oxirgi limit saqlandi: {e}')

    def close(self):
        self.stop.set()
        if self.thread: self.thread.join(3)
        if self.job:
            try: self.job.cap(None)
            except OSError as e: self.report(f'CPU limitini olib tashlab bo‘lmadi: {e}. MusicPro qayta ochilganda tiklanadi.')
