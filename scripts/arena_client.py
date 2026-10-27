#!/usr/bin/env python3
"""TavernArena connector. Your policy runs locally; nothing is uploaded except actions.

Example: python arena_client.py --url http://127.0.0.1:8860 --mode practice --example
Custom:  python arena_client.py --url https://YOUR_ARENA --policy my_agent:act --mode arena
Credentials are read from ARENA_API_KEY (never put a key on the command line).
"""
import argparse
import base64
import hashlib
import http.client
import importlib
import importlib.util
import json
import numbers
import os
import ssl
import sys
import time
import threading
from urllib.parse import urlsplit
import uuid

class ArenaClient:
    def __init__(self,url,key):
        parsed=urlsplit(url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
            raise ValueError('Use an arena origin URL without credentials, path, query, or fragment')
        if parsed.scheme not in ('http','https') or not parsed.hostname:
            raise ValueError('An HTTP(S) arena origin is required')
        if parsed.scheme=='http' and parsed.hostname not in ('127.0.0.1','localhost','::1'):
            raise ValueError('Remote arenas require HTTPS')
        self.parsed,self.key,self.connection=parsed,key,None

    def close(self):
        if self.connection:
            self.connection.close()
        self.connection=None

    def request(self,method,path,body=None,authenticated=True):
        encoded=json.dumps(body,separators=(',',':')).encode() if body is not None else None
        for attempt in range(3):
            try:
                if self.connection is None:
                    cls=http.client.HTTPSConnection if self.parsed.scheme=='https' else http.client.HTTPConnection
                    kwargs={'timeout':30}
                    if cls is http.client.HTTPSConnection:kwargs['context']=ssl.create_default_context()
                    self.connection=cls(self.parsed.hostname,self.parsed.port,**kwargs)
                headers={'Accept':'application/json','User-Agent':'TavernArena-Connector/1'}
                if authenticated:headers['Authorization']='Bearer '+self.key
                if encoded is not None:headers['Content-Type']='application/json'
                self.connection.request(method,path,encoded,headers)
                response=self.connection.getresponse()
                data=response.read(2**22+1)
                if len(data)>2**22:raise ValueError('Arena response exceeds the client safety limit')
                parsed=json.loads(data)
                if response.status>=400:
                    if response.status in (429,503) and attempt<2:
                        time.sleep(1+attempt)
                        continue
                    return {'client_error':True,'status':response.status,**parsed}
                return parsed
            except (OSError,http.client.HTTPException):
                self.close()
                if attempt==2:raise ConnectionError('Arena connection interrupted; verify state before retrying') from None
                time.sleep(.5*(attempt+1))
        raise ConnectionError('Arena request failed')

    @staticmethod
    def validate(manifest,expected_ruleset=None,expected_catalog=None,custom_policy=False):
        observation=manifest['observation']
        if manifest.get('protocol_version')!='2' or [observation[k]['length'] for k in ('features','cards','action_mask')]!=[4017,447,245]:
            raise ValueError('Unsupported protocol or observation layout')
        canonical=lambda x:json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
        if hashlib.sha256(canonical(observation)).hexdigest()!=manifest['observation_sha256']:
            raise ValueError('Observation schema checksum failed')
        if hashlib.sha256(canonical(manifest['actions'])).hexdigest()!=manifest['action_layout_sha256']:
            raise ValueError('Action schema checksum failed')
        if expected_ruleset and expected_ruleset!=manifest['ruleset_id']:
            raise ValueError('Ruleset differs from the explicitly approved ruleset')
        if expected_catalog and expected_catalog!=manifest['catalog_sha256']:
            raise ValueError('Card vocabulary differs from the training vocabulary')
        if importlib.util.find_spec('taverngym'):
            import taverngym
            if taverngym.build_info()['source_hash']!=manifest['environment']['engine_source_hash']:
                raise ValueError('Installed TavernGym engine differs from the arena engine')
            if dict(taverngym.layout())!=observation['layout']:
                raise ValueError('Installed TavernGym observation/action layout differs')
            vocabulary=[{'index':i,'id':c[0],'name':c[1],'name_zh':c[2],'tier':c[3]}
                        for i in range(1,taverngym.N_CARDS) for c in (taverngym.card_info(i),)]
            catalog={'empty_index':0,'cards':vocabulary,'details':json.loads(taverngym.catalog_json())}
            if hashlib.sha256(canonical(catalog)).hexdigest()!=manifest['catalog_sha256']:
                raise ValueError('Installed TavernGym card vocabulary differs')
        elif custom_policy and not expected_catalog:
            raise ValueError('For a custom model install the matching public TavernGym, or pass --catalog-sha256 from your verified training vocabulary')

    @staticmethod
    def decode(state):
        import numpy as np
        raw=state['observation']
        def decode(name,dtype,count):
            binary=base64.b64decode(raw[name],validate=True)
            values=np.frombuffer(binary,dtype=dtype)
            if values.size!=count:raise ValueError('Observation size mismatch')
            return values
        version=raw.get('version',1)
        if version not in (1,2):raise ValueError('Unsupported observation version')
        features=decode('features_b64','<f4',4017 if version==2 else 3227)
        cards=decode('cards_b64','<i4',447 if version==2 else 124)
        mask=decode('action_mask_b64','u1',245)
        if not np.isfinite(features).all() or not np.isin(mask,[0,1]).all():
            raise ValueError('Invalid observation values')
        return {'features':features,'cards':cards,'action_mask':mask.astype(bool)}

    heartbeat_seconds=10

    def run(self,policy,mode='practice',continuous=False,expected_ruleset=None,expected_catalog=None,custom_policy=False,wait_for_human=False,*,
            min_players=None,preferred_players=8,max_wait_seconds=None,timeout_action='start',model_version='',room_code=None,games=1):
        if wait_for_human and mode!='arena':raise ValueError('--wait-for-human requires --mode arena')
        if not 1<=games<=10000:raise ValueError('--games must be between 1 and 10000')
        if mode=='custom' and not room_code:raise ValueError('--mode custom requires --room-code')
        options=dict(min_players=min_players,preferred_players=preferred_players,max_wait_seconds=max_wait_seconds,
                     timeout_action=timeout_action,model_version=model_version,room_code=room_code,games=games)
        stop=threading.Event()
        def beat():
            connection=ArenaClient(self.parsed.geturl(),self.key)
            try:
                while not stop.wait(self.heartbeat_seconds):
                    try:
                        result=connection.request('POST','/api/v1/agent/heartbeat',{})
                        if result.get('status') in (401,403):return
                    except ConnectionError:
                        pass
            finally:
                connection.close()
        thread=threading.Thread(target=beat,name='arena-heartbeat',daemon=True)
        thread.start()
        try:
            return self._run(policy,mode,continuous,expected_ruleset,expected_catalog,custom_policy,wait_for_human,options)
        finally:
            stop.set()
            thread.join(timeout=2)
            # Cancelling a queue is safe; an active game remains resumable and is
            # never silently abandoned via a different API.
            try:self.request('DELETE','/api/v1/queue')
            except (ConnectionError,ValueError):pass

    def _run(self,policy,mode='practice',continuous=False,expected_ruleset=None,expected_catalog=None,custom_policy=False,wait_for_human=False,options=None):
        options=options or {};completed=0;last_queue=None
        manifest=self.request('GET','/api/v1/manifest',authenticated=False)
        if manifest.get('client_error'):raise RuntimeError('Cannot read arena manifest')
        self.validate(manifest,expected_ruleset,expected_catalog,custom_policy)
        while True:
            queue_options={k:v for k,v in options.items() if k!='games' and v is not None}
            joined=self.request('POST','/api/v1/queue',{'mode':mode,'ruleset_id':manifest['ruleset_id'],'wait_for_human':wait_for_human,**queue_options})
            if joined.get('client_error') and joined.get('error')!='already_playing':
                raise RuntimeError(joined.get('message',joined.get('error','queue failed')))
            print('Resuming existing match' if joined.get('error')=='already_playing' else 'Queued: '+mode,file=sys.stderr,flush=True)
            cursor=None
            policy_state={}
            decision=None
            while True:
                path='/api/v1/agent/state'+('?wait=15&after='+cursor if cursor else '')
                state=self.request('GET',path)
                if state.get('client_error'):raise RuntimeError(state.get('message','authentication or state failure'))
                cursor=state.get('cursor')
                if state['type']=='match_finished':
                    print(json.dumps(state,ensure_ascii=False),flush=True)
                    break
                if state['type']=='queue_cancelled':
                    print('Queue ended: '+state.get('reason','cancelled'),file=sys.stderr,flush=True)
                    print(json.dumps(state,ensure_ascii=False),flush=True)
                    return state
                if state['type']=='idle':raise RuntimeError('No active queue or match; the queue may have expired or the server restarted')
                if state['type']=='queue_status':
                    summary=(state.get('owners_waiting'),state.get('reason'),int(state.get('countdown_seconds',0)//10))
                    if summary!=last_queue:
                        print('Queue: accounts={}/{} preferred={} countdown={}s reason={}'.format(
                            state.get('owners_waiting'),state.get('minimum_accounts'),state.get('preferred_players',8),
                            state.get('countdown_seconds',0),state.get('reason','waiting')),file=sys.stderr,flush=True)
                        last_queue=summary
                if state['type']!='decision':continue
                if state['decision_id']==decision:continue
                observation=self.decode(state)
                context={k:state[k] for k in ('match_id','seat','turn','phase','remaining_ms','actions_used','action_limit','player_view')}
                context['state']=policy_state
                action=policy(observation,context)
                if isinstance(action,bool) or not isinstance(action,numbers.Integral) or not 0<=action<245 or not observation['action_mask'][action]:
                    raise ValueError('Policy must return a legal integer action')
                payload={k:state[k] for k in ('match_id','seat','seat_revision','decision_id')}
                payload.update(action=int(action),request_id=uuid.uuid4().hex)
                result=self.request('POST','/api/v1/agent/actions',payload)
                if result.get('client_error'):
                    if result.get('error') in ('stale','expired','illegal','forbidden','match_void','action_limit'):
                        cursor=None
                        continue
                    raise RuntimeError(result.get('message','action failed'))
                decision=state['decision_id']
                cursor=None
            completed+=1
            if not continuous and completed>=options.get('games',1):return state


def example(observation,context):
    # Connectivity example: resolve a choice, otherwise finish the turn promptly.
    mask=observation['action_mask']
    if mask[0]:return 0
    return next(i for i,allowed in enumerate(mask) if allowed)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True)
    parser.add_argument('--mode',choices=('practice','arena','standard','custom'),default='practice')
    parser.add_argument('--policy',help='A LOCAL module:function taking (observation, context)')
    parser.add_argument('--example',action='store_true')
    parser.add_argument('--continuous',action='store_true')
    parser.add_argument('--games',type=int,default=1,help='Run N games serially, then stop (1..10000)')
    parser.add_argument('--min-players',type=int,choices=range(1,9))
    parser.add_argument('--preferred-players',type=int,choices=range(1,9),default=8)
    parser.add_argument('--max-wait-seconds',type=int,help='Personal wait cap, 0..900 seconds')
    parser.add_argument('--timeout-action',choices=('start','wait','cancel'),default='start')
    parser.add_argument('--model-version',default='',help='Optional public label only; never a path or secret')
    parser.add_argument('--room-code',help='Invitation code for an unrated custom room; not your Agent Key')
    parser.add_argument('--check',action='store_true',help='Validate the public simulator contract without entering a queue')
    parser.add_argument('--wait-for-human',action='store_true',help='arena: wait for at least one other account; keep rule bot fill')
    parser.add_argument('--expected-ruleset')
    parser.add_argument('--catalog-sha256')
    args=parser.parse_args()
    if args.wait_for_human and args.mode!='arena':parser.error('--wait-for-human requires --mode arena')
    if args.min_players and args.min_players>args.preferred_players:parser.error('--min-players cannot exceed --preferred-players')
    if args.max_wait_seconds is not None and not 0<=args.max_wait_seconds<=900:parser.error('--max-wait-seconds must be 0..900')
    if args.continuous and args.games!=1:parser.error('Use --games or --continuous, not both')
    if not 1<=args.games<=10000:parser.error('--games must be 1..10000')
    key=os.getenv('ARENA_API_KEY','')
    if not key and not args.check:parser.error('Set ARENA_API_KEY locally; do not put a secret on the command line')
    if not args.check and bool(args.policy)==args.example:parser.error('Choose exactly one of --policy or --example')
    policy=example
    if args.policy:
        module,separator,name=args.policy.partition(':')
        if not separator:parser.error('--policy must use module:function')
        policy=getattr(importlib.import_module(module),name)
    client=ArenaClient(args.url,key)
    try:
        if args.check:
            manifest=client.request('GET','/api/v1/manifest',authenticated=False)
            client.validate(manifest,args.expected_ruleset,args.catalog_sha256,bool(args.policy))
            print(json.dumps({'compatible':True,'ruleset_id':manifest['ruleset_id'],'observation_version':2,'queued':False}))
        else:
            client.run(policy,args.mode,args.continuous,args.expected_ruleset,args.catalog_sha256,bool(args.policy),args.wait_for_human,
                min_players=args.min_players,preferred_players=args.preferred_players,max_wait_seconds=args.max_wait_seconds,
                timeout_action=args.timeout_action,model_version=args.model_version,room_code=args.room_code,games=args.games)
    except KeyboardInterrupt:
        print('Stopped. Any waiting ticket was cancelled; an active game can be resumed within its reconnect grace.',file=sys.stderr)
        raise SystemExit(130)
    except (ValueError,RuntimeError,ConnectionError) as exc:
        print(str(exc),file=sys.stderr)
        raise SystemExit(1)
    finally:
        client.close()

if __name__=='__main__':main()
