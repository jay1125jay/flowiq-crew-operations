"""Local-only live preparation settings and read-only Binance verification.
No order placement, withdrawal, or remote control endpoints.
"""
import ctypes
from ctypes import wintypes
import hashlib
import hmac
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULTS = dict(budget_krw=5000000, leverage=3, compound=False,
    capital_cap_krw=5000000, daily_loss_krw=100000, max_gap_pct=.3,
    allocation='equal', enabled_wallets=[])


def validate(data):
    if not isinstance(data,dict) or set(data)-set(DEFAULTS):
        raise ValueError('Unknown settings')
    result=dict(DEFAULTS,**data)
    for key,low,high in [('budget_krw',10000,1000000000),('capital_cap_krw',10000,1000000000),
                         ('daily_loss_krw',1,1000000000),('max_gap_pct',0,5),('leverage',1,20)]:
        value=result[key]
        if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or not low<=value<=high:
            raise ValueError('Invalid '+key)
    if int(result['leverage'])!=result['leverage']: raise ValueError('Integer leverage required')
    if result['daily_loss_krw']>result['budget_krw']: raise ValueError('Daily loss exceeds budget')
    if result['capital_cap_krw']<result['budget_krw']: raise ValueError('Capital cap below budget')
    if type(result['compound']) is not bool or result['allocation']!='equal': raise ValueError('Invalid allocation')
    wallets=result['enabled_wallets']
    if not isinstance(wallets,list) or len(wallets)>5 or any(not isinstance(w,str) or not re.fullmatch('0x[0-9a-fA-F]{40}',w) for w in wallets) or len(set(w.lower() for w in wallets))!=len(wallets):
        raise ValueError('Select up to five unique wallets')
    result['enabled_wallets']=[w.lower() for w in wallets]
    return result


def atomic(path,data):
    temp=path.with_suffix('.tmp')
    with temp.open('wb') as f:
        f.write(data);f.flush();os.fsync(f.fileno())
    os.replace(temp,path)


def protect(data, decrypt=False):
    """Windows DPAPI, bound to the current Windows user. Never fall back to plaintext."""
    if os.name!='nt': raise ValueError('Encrypted credential storage requires Windows')
    class Blob(ctypes.Structure):
        _fields_=[('cbData',wintypes.DWORD),('pbData',ctypes.POINTER(ctypes.c_ubyte))]
    buf=ctypes.create_string_buffer(data)
    source=Blob(len(data),ctypes.cast(buf,ctypes.POINTER(ctypes.c_ubyte)))
    target=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
    fn=crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    fn.restype=wintypes.BOOL
    if not fn(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target)):
        raise ValueError('Windows credential encryption failed')
    try: return ctypes.string_at(target.pbData,target.cbData)
    finally: kernel.LocalFree(target.pbData)


class BinanceReadOnly:
    ALLOWED={('https://api.binance.com','/api/v3/time'),
             ('https://api.binance.com','/sapi/v1/account/apiRestrictions'),
             ('https://fapi.binance.com','/fapi/v1/time'),
             ('https://fapi.binance.com','/fapi/v3/account')}
    def __init__(self,key,secret):
        if not all(isinstance(v,str) and re.fullmatch('[A-Za-z0-9]{16,256}',v) for v in (key,secret)):
            raise ValueError('Use a Binance HMAC API key and secret')
        self.key,self.secret=key,secret
    def get(self,host,path,params=None):
        if (host,path) not in self.ALLOWED: raise ValueError('Read-only endpoint required')
        headers={};url=host+path
        if params is not None:
            query=urllib.parse.urlencode(params)
            signature=hmac.new(self.secret.encode(),query.encode(),hashlib.sha256).hexdigest()
            url+='?'+query+'&signature='+signature;headers['X-MBX-APIKEY']=self.key
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs): return None
        try:
            req=urllib.request.Request(url,headers=headers,method='GET')
            with urllib.request.build_opener(NoRedirect).open(req,timeout=10) as r:
                return json.loads(r.read(2_000_000))
        except urllib.error.HTTPError as e:
            raise ValueError('Binance HTTP '+str(e.code)+': check permissions, IP restrictions and account availability') from None
        except (OSError,ValueError): raise ValueError('Binance connection failed; check network and API configuration') from None
    def check(self):
        host='https://api.binance.com'
        stamp=self.get(host,'/api/v3/time')['serverTime']
        permissions=self.get(host,'/sapi/v1/account/apiRestrictions',dict(timestamp=stamp,recvWindow=5000))
        if permissions.get('enableWithdrawals') is not False: raise ValueError('Disable withdrawal permission first')
        host='https://fapi.binance.com'
        stamp=self.get(host,'/fapi/v1/time')['serverTime']
        account=self.get(host,'/fapi/v3/account',dict(timestamp=stamp,recvWindow=5000))
        return dict(checked_at_ms=int(time.time()*1000),reading=True,
                    futures=permissions.get('enableFutures') is True,
                    ip_restricted=permissions.get('ipRestrict') is True,withdrawals=False,
                    available_usdt=account.get('availableBalance'),
                    wallet_balance_usdt=account.get('totalWalletBalance'),
                    unrealized_usdt=account.get('totalUnrealizedProfit'),
                    can_trade=account.get('canTrade') is True)


class SettingsStore:
    def __init__(self,directory):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.path=self.directory/'live-preparation.json'
        self.vault=self.directory/'binance-credentials.dpapi'
        self.lock=threading.RLock();self.last_test=None;self.last_attempt=0
    def read(self):
        with self.lock:
            values=validate(json.loads(self.path.read_text())) if self.path.exists() else dict(DEFAULTS)
            return dict(settings=values,credentials_saved=self.vault.exists(),connection=self.last_test,
                        live_enabled=False,settings_applied=False,mode='PREPARATION_ONLY')
    def save(self,data):
        values=validate(data)
        with self.lock: atomic(self.path,json.dumps(values,allow_nan=False).encode())
        return self.read()
    def check(self,data):
        with self.lock:
            now=time.monotonic()
            if self.last_attempt and now-self.last_attempt<10: raise ValueError('Wait ten seconds before testing again')
            self.last_attempt=now;self.last_test=None
            supplied=bool(data.get('api_key') or data.get('secret_key'))
            if supplied:
                key,secret=data.get('api_key'),data.get('secret_key')
            else:
                if not self.vault.exists(): raise ValueError('Enter API key and secret')
                values=json.loads(protect(self.vault.read_bytes(),decrypt=True));key,secret=values['key'],values['secret']
            result=BinanceReadOnly(key,secret).check()
            # Validate online first, then encrypt. Never write rejected keys.
            if supplied and data.get('save') is True:
                encrypted=protect(json.dumps(dict(key=key,secret=secret)).encode())
                atomic(self.vault,encrypted)
            self.last_test=result
            return self.read()
    def disconnect(self):
        with self.lock:
            self.vault.unlink(missing_ok=True);self.last_test=None
        return self.read()
