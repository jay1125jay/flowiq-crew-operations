#!/usr/bin/env python3
"""Rebase unrelated updates; fail rather than overwrite concurrent research state."""
import pathlib
import subprocess
import time

ROOT=pathlib.Path(__file__).resolve().parents[1]

def git(*args, check=True):
    return subprocess.run(['git',*args],cwd=ROOT,check=check,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)

def main():
    files=git('diff','--name-only','--cached').stdout.splitlines()
    if not files:
        print('NO DATA CHANGES');return
    if any(not f.startswith('btc-flow-monitor/') for f in files):
        raise RuntimeError('out-of-scope staged path')
    git('commit','-m','data: persist validated BTC PAPER competition')
    for attempt in range(3):
        git('fetch','origin','main')
        result=git('rebase','origin/main',check=False)
        if result.returncode:
            git('rebase','--abort',check=False)
            raise RuntimeError('Concurrent research conflict; refusing to overwrite. Next scheduled run recollects.')
        result=git('push','origin','HEAD:main',check=False)
        if result.returncode==0:
            print('PERSIST PASS');return
        time.sleep(2**attempt)
    raise RuntimeError('Push failed after 3 attempts; no force push performed')

if __name__=='__main__':main()
