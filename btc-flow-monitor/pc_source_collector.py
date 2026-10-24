#!/usr/bin/env python3
"""Resilient PC source collector for slower Windows/home-network environments."""
import json
import shutil
import subprocess
import sys
import time

import realtime_runtime as base

SCRIPTS = [
    'trader-discovery/leaderboard_expand.py',
    'scripts/whale_ranker.py',
    'trader-discovery/trader_discovery.py',
    'collect_adaptive_market.py',
    'trader-discovery/current_positions.py',
]
COLLECTION_DEADLINE_SECONDS = 240
RETRY_DELAY_SECONDS = 5
TARGET_REFRESH_SECONDS = 60


def _short_error(exc):
    text = str(exc).strip().replace('\n', ' ')
    return f'{type(exc).__name__}: {text[:180]}' if text else type(exc).__name__


def collect_sources(directory, shared, stop):
    """Collect public sources without marking freshly completed slow cycles as stale."""
    work = directory / 'collector'
    if not work.exists():
        shutil.copytree(base.ROOT, work, ignore=shutil.ignore_patterns('__pycache__', 'browser-evidence', '*.sqlite*'))
    else:
        for source in base.ROOT.rglob('*.py'):
            destination = work / source.relative_to(base.ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    while not stop.is_set():
        cycle_started = time.time()
        failed = False
        try:
            for script in SCRIPTS:
                remaining = COLLECTION_DEADLINE_SECONDS - (time.time() - cycle_started)
                if remaining <= 0 or stop.is_set():
                    raise TimeoutError(f'collection deadline before {script}')
                proc = subprocess.Popen(
                    [sys.executable, str(work / script)],
                    cwd=work,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                try:
                    end = time.monotonic() + remaining
                    while proc.poll() is None:
                        if stop.wait(.25):
                            proc.kill()
                            proc.wait()
                            raise TimeoutError(f'collection stopped during {script}')
                        if time.monotonic() >= end:
                            proc.kill()
                            proc.wait()
                            raise TimeoutError(f'collection timed out during {script}')
                    stderr = (proc.stderr.read() if proc.stderr else '').strip()
                    if proc.returncode:
                        tail = stderr[-220:] if stderr else f'exit {proc.returncode}'
                        raise RuntimeError(f'{script}: {tail}')
                finally:
                    if proc.stderr:
                        proc.stderr.close()

            def read(path):
                return json.loads((work / path).read_text(encoding='utf-8'))

            # Freshness starts when a complete, internally consistent bundle is ready.
            completed_at = time.time()
            bundle = dict(
                started_at=completed_at,
                collection_started_at=cycle_started,
                collection_seconds=round(completed_at - cycle_started, 3),
                cohorts=read('trader-discovery/latest.json'),
                positions=read('trader-discovery/current-positions.json'),
                market=read('data/adaptive-market.json'),
                ranking=read('data/whale-ranking.json'),
            )
            base.engine.validate_inputs(
                bundle['cohorts'], bundle['positions'], bundle['market'], bundle['ranking'], base.iso(completed_at)
            )
            shared.set(bundle, None)
        except Exception as exc:
            failed = True
            shared.set(None, _short_error(exc))

        elapsed = time.time() - cycle_started
        if failed:
            stop.wait(RETRY_DELAY_SECONDS)
        else:
            stop.wait(max(1, TARGET_REFRESH_SECONDS - elapsed))
