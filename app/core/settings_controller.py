"""Thin TT settings adapter over this product's existing stores and providers.

Layout/callback contract: TT-YingXu 8f80b197, ModelSettingsPage and controller.
No legacy product configuration, secrets, activation, or production modules imported.
"""
import copy,hashlib,json,shutil,time
from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import urlparse
from app.providers.contracts import Connection,CancelToken,PRESETS
from app.providers.image_contracts import ImageConnection
from app.providers.http_text import HttpTextProvider
from app.providers.codex_text import CodexTextProvider,command_prefix
from app.core.files import write_json
from app.storage.project import now

MODEL_CHANNEL_KEYS=['volcengine_ark','deepseek_official','aliyun_bailian','gpt_relay','codex_local']
MODEL_CHANNEL_LABELS={'volcengine_ark':'火山方舟','deepseek_official':'DeepSeek 官方','aliyun_bailian':'千问','gpt_relay':'中转站','codex_local':'Codex 本地'}
PROVIDERS=dict(volcengine_ark='ark',deepseek_official='deepseek',aliyun_bailian='qwen',gpt_relay='custom',codex_local='codex')
MODEL_DEFAULT_BASE={k:PRESETS[v][1] for k,v in PROVIDERS.items()}
MODEL_KEY_URLS={'volcengine_ark':'https://console.volcengine.com/ark/apiKey','deepseek_official':'https://platform.deepseek.com/api_keys','aliyun_bailian':'https://bailian.console.aliyun.com/cn-beijing/?tab=app#/api-key'}
# Models are obtained from the current provider or entered by the user.
MODEL_PRESETS={k:[] for k in MODEL_CHANNEL_KEYS}
def site_id(protocol,base): return hashlib.sha256((protocol+'\n'+base.strip().rstrip('/')).encode()).hexdigest()[:24]

class SettingsController:
    def __init__(self,owner): self.owner=owner; self.codex=SimpleNamespace(command_prefix=lambda:command_prefix(self.codex_local_settings()['commandPath'])); self.reload()
    def reload(self):
        self.channel_configs={}
        for key,provider in PROVIDERS.items():
            rows=[c for c in self.owner.connections.all() if c.provider==provider]; current=next((c for c in rows if c.id==self.owner.options.get('default_connection')),rows[0] if rows else None)
            self.channel_configs[key]=current or Connection('tt_'+key,MODEL_CHANNEL_LABELS[key],provider,'',base_url=MODEL_DEFAULT_BASE[key],timeout=300,max_output=8192,context_limit=65536,output_mode='auto')
        current=self.owner.options.get('default_connection'); self.active_provider=next((k for k,c in self.channel_configs.items() if c.id==current),'')
    def saved(self,c,image=False): return next((old for old in (self.owner.image_connections if image else self.owner.connections).all() if old.id==c.id),None)
    def model_key_status(self,key):
        c=self.channel_configs[key]; saved=bool(c.credential_version and self.owner.connections.vault.path.is_file() and key not in self.owner.options.get('cleared_model_keys',[])); return dict(saved=saved,masked='••••••••' if saved else '')
    def save_model_channel(self,key,value):
        old=self.channel_configs[key]; model=value.model.strip(); base=value.base_url.strip().rstrip('/')
        c=replace(old,model=model,base_url=base,cli_path=self.codex_local_settings()['commandPath'] if key=='codex_local' else old.cli_path,
                  max_output=getattr(value,'max_output',old.max_output),output_mode=getattr(value,'output_mode',old.output_mode),json_mode=getattr(value,'json_mode',old.json_mode),format_mode=getattr(value,'format_mode',old.format_mode))
        from app.core.output_budget import output_plan
        output_plan(c,{},'discuss')
        c.validate(); entered=getattr(value,'api_key','').strip(); self.owner.connections.save(c,entered or None)
        if entered:
            self.owner.options['cleared_model_keys']=[k for k in self.owner.options.get('cleared_model_keys',[]) if k!=key]; self.owner.save_options()
        self.reload(); return dict(active=key==self.active_provider)
    def activate_model_channel(self,key):
        c=self.channel_configs[key]
        if key=='codex_local':
            detected=self.cached_codex_status() or self.detect_codex()
            if not detected.get('available') or not detected.get('authenticated'): raise ValueError('Codex 尚未就绪，请重新检测本机状态；未自动登录。')
            # Like TT's CLI bridge, following the local default needs no API form.
            if not self.saved(c):
                c=replace(c,cli_path=self.codex_local_settings()['commandPath']); self.owner.connections.save(c)
        elif not self.saved(c): raise ValueError('请先保存当前接口设置，再启用该模型。')
        c.validate(); self.owner.options['default_connection']=c.id; self.owner.save_options(); self.reload(); self.owner.assistant.refresh_models()
    def model_capabilities(self,key):
        c=self.channel_configs[key]; v=c.verification
        def declared(value): return dict(status='用户声明，未实测' if value else '未知',value=value if value else None)
        return dict(identity=dict(provider=c.provider,base_url=c.base_url,model=c.model or 'Codex 默认',credential_version=c.credential_version,cli_path=c.cli_path),stream=declared(c.stream),structured_output=declared(c.json_mode),tool_call=declared(c.tool_call),tool_stream=declared(c.tool_stream),reasoning=declared(c.reasoning_levels),limits=dict(context=c.context_limit,output=c.max_output,source='本地配置上限，不代表平台保证'),verification=copy.deepcopy(v),tool_route='原生函数工具' if c.tool_call and c.provider!='codex' else '受限 JSON 工具桥',price=copy.deepcopy(c.pricing) or dict(status='暂无法估算'))
    def delete_model_key(self,key):
        c=self.channel_configs[key]
        if self.saved(c): self.owner.connections.save(c,'')
        self.reload()
        # Credential versions stay append-only, while presence is public metadata.
        self.owner.options.setdefault('cleared_model_keys',[])
        if key not in self.owner.options['cleared_model_keys']: self.owner.options['cleared_model_keys'].append(key)
        self.owner.save_options()
    def clear_all_keys(self):
        # This vault is shared by this product's text/image stores only.
        self.owner.connections.vault.clear(); self.reload()
        state=self._sites()
        for value in state['sites'].values(): value['keyStatus']=dict(saved=False)
        write_json(self.owner.preferences.parent/'image_sites.json',state)
        self.owner.options['cleared_model_keys']=list(MODEL_CHANNEL_KEYS); self.owner.save_options()
    def request_secret(self,c,entered=''):
        if entered: return entered
        old=self.saved(c)
        if old is None: raise ValueError('请填写接口密钥，或先保存当前接口设置')
        if old.base_url.rstrip('/')!=c.base_url.rstrip('/'): raise ValueError('接口地址已变化，请填写该站点的密钥')
        return self.owner.connections.secret_snapshot(old)
    def list_models(self,value):
        old=self.channel_configs[value.provider]; c=replace(old,base_url=value.base_url,model=value.model); return HttpTextProvider().list_models(c,self.request_secret(c,value.api_key))
    def test_model_connection(self,value):
        old=self.channel_configs[value.provider]; c=replace(old,base_url=value.base_url,model=value.model,max_output=128,timeout=90); return HttpTextProvider().generate(c,self.request_secret(c,value.api_key),[dict(role='user',content='请回复连接成功')],CancelToken())
    def codex_local_settings(self): return dict(commandPath=self.owner.options.get('codex_command_path',''))
    def save_codex_command_path(self,path):
        if path: command_prefix(path)
        if path!=self.owner.options.get('codex_command_path',''):
            for store,provider in [(self.owner.connections,'codex'),(self.owner.image_connections,'image_codex')]:
                for c in store.all():
                    if c.provider==provider: store.save(replace(c,cli_path=path,verification={},capability_status='未验证'))
        self.owner.options['codex_command_path']=path; self.owner.save_options(); self.reload(); return self.codex_local_settings()
    def detect_codex(self):
        path=self.codex_local_settings()['commandPath']; result=CodexTextProvider(self.owner.preferences.parent).detect(path,login=True)
        return dict(available=True,authenticated=result['logged_in'],version=result['version'],command=__import__('subprocess').list2cmdline(result['prefix']),source='manual_override' if path else 'merged_path',features=result['features'])
    def cached_codex_status(self):
        from app.core.codex_state import status
        return status(self.owner.preferences.parent,self.codex_local_settings()['commandPath'])
    def codex_image_capability(self,detected):
        c=next((c for c in self.owner.image_connections.all() if c.provider=='image_codex' and c.cli_path==self.codex_local_settings()['commandPath']),None); record=c.verification.get('image_generation',{}) if c else {}; success=record.get('status')=='已实测'; dimensions=record.get('dimensions',[])
        return dict(available=bool(detected.get('available')),authenticated=bool(detected.get('authenticated')),skillPresent='image_generation' in detected.get('features',[]),ready=bool(detected.get('available') and detected.get('authenticated') and 'image_generation' in detected.get('features',[])),lastSuccessAt=1 if success else 0,lastActualSize=' × '.join(map(str,dimensions[0])) if success and dimensions else '')
    def image_provider_settings(self):
        default=self.owner.options.get('default_image'); c=next((c for c in self.owner.image_connections.all() if c.id==default),None); return dict(activeImageProvider='codex_image' if c and c.provider=='image_codex' else 'openai_compatible' if c else '')
    def set_active_image_provider(self,provider):
        if provider=='codex_image':
            text=self.channel_configs['codex_local']; c=next((c for c in self.owner.image_connections.all() if c.provider=='image_codex'),None)
            if not c: c=ImageConnection('tt_codex_image','Codex Image','image_codex',text.model,cli_path=self.codex_local_settings()['commandPath'],sizes=('1024x1024','1024x1536','1536x1024')); self.owner.image_connections.save(c)
        else:
            value=self.openai_image_settings(); c=self.owner.image_connections.get('image_site_'+site_id(value['protocol'],value['baseUrl']))
        self.owner.options['default_image']=c.id; self.owner.save_options()
    def _sites(self):
        path=self.owner.preferences.parent/'image_sites.json'; return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else dict(version=1,sites={})
    def openai_image_settings(self):
        defaults=dict(protocol='openai_images_v1',baseUrl='',modelId='',modelCatalog=[],modelCatalogUpdatedAt=0,sizeStrategy='exact_pixels',defaultSizeTier='1K',manualSize='',supportedRatios=['3:4'],quality='model_default',modelSettings={},modelCapabilities={},pricingEnabled=False,pricingSource='manual',unitPrices={},currency='CNY')
        sid=self.owner.options.get('settings_image_site'); record=self._sites()['sites'].get(sid,{})
        if not record:
            old=next((c for c in self.owner.image_connections.all() if c.id==self.owner.options.get('default_image') and c.provider=='image_http'),None)
            if old: record=dict(baseUrl=old.base_url,modelId=old.model,manualSize=old.sizes[0] if old.sizes else '',quality=old.qualities[0] if old.qualities else 'model_default')
        return dict(defaults,**copy.deepcopy(record))
    def list_openai_image_sites(self): return list(self._sites()['sites'].values())
    def openai_image_site(self,sid): return copy.deepcopy(self._sites()['sites'].get(sid,{}))
    def activate_openai_image_site(self,sid):
        value=self.openai_image_site(sid)
        if not value: raise ValueError('保存的网站记录不存在')
        self.owner.options['settings_image_site']=sid; self.owner.save_options(); self.set_active_image_provider('openai_compatible'); return value
    def save_openai_image_settings(self,values,api_key=''):
        value=copy.deepcopy(values); self.check_openai_image_settings(value); sid=site_id(value['protocol'],value['baseUrl']); cid='image_site_'+sid; old=next((c for c in self.owner.image_connections.all() if c.id==cid),None)
        sizes=tuple([value['manualSize']]) if value.get('manualSize') else self.image_sizes(value); quality=value.get('quality'); quality=() if quality in {'','model_default'} else (quality,)
        c=replace(old,model=value['modelId'],sizes=sizes,qualities=quality) if old else ImageConnection(cid,value['baseUrl'],'image_http',value['modelId'],base_url=value['baseUrl'],sizes=sizes,qualities=quality)
        prices=value.get('unitPrices',{}); price=prices.get(value.get('defaultSizeTier')) if value.get('pricingEnabled') else None
        pricing=dict(currency='CNY',per_image=price,version=now(),source=value.get('pricingSource','manual')) if isinstance(price,(int,float)) and price>0 else {}
        c=replace(c,pricing=pricing); self.owner.image_connections.save(c,api_key.strip() or None); value.update(siteId=sid,keyStatus=dict(saved=bool(api_key or old and self.openai_image_key_status(value['protocol'],value['baseUrl'])['saved']))); state=self._sites(); state['sites'][sid]=value; write_json(self.owner.preferences.parent/'image_sites.json',state); self.owner.options['settings_image_site']=sid; self.owner.save_options(); return value
    @staticmethod
    def image_sizes(v):
        tier={'1K':1024,'2K':2048,'4K':4096}.get(v.get('defaultSizeTier'),1024); result=[]
        for ratio in v.get('supportedRatios') or ['1:1']:
            a,b=map(int,ratio.split(':')); width=tier if a>=b else round(tier*a/b/64)*64; height=tier if b>=a else round(tier*b/a/64)*64; result.append(f'{width}x{height}')
        return tuple(result)
    def check_openai_image_settings(self,v=None,api_key=''):
        v=v or self.openai_image_settings()
        if v['protocol']!='openai_images_v1': raise ValueError('该专用协议尚未接入，不可启用')
        c=ImageConnection('validation','通用图片API','image_http',v['modelId'],base_url=v['baseUrl'],sizes=tuple([v['manualSize']]) if v.get('manualSize') else self.image_sizes(v)); c.validate(); return dict(ok=True)
    def openai_image_key_status(self,protocol='',base_url=''):
        v=self.openai_image_settings(); sid=site_id(protocol or v['protocol'],base_url or v['baseUrl']); value=self._sites()['sites'].get(sid,{}).get('keyStatus',dict(saved=False)); return dict(saved=bool(value.get('saved') and self.owner.image_connections.vault.path.is_file()))
    def delete_openai_image_key(self,protocol,base):
        sid=site_id(protocol,base); cid='image_site_'+sid; c=self.owner.image_connections.get(cid); self.owner.image_connections.save(c,''); state=self._sites(); state['sites'][sid]['keyStatus']=dict(saved=False); write_json(self.owner.preferences.parent/'image_sites.json',state)
    def image_metadata(self,v,key=''):
        self.check_openai_image_settings(v); cid='image_site_'+site_id(v['protocol'],v['baseUrl']); old=next((c for c in self.owner.image_connections.all() if c.id==cid),None)
        secret=key or (self.owner.image_connections.secret_snapshot(old) if old else '')
        if not secret: raise ValueError('请填写或保存当前网站的密钥')
        c=Connection(cid,'图片站点模型信息','custom',v['modelId'],base_url=v['baseUrl']); rows=HttpTextProvider().list_models(c,secret); return rows
    def list_openai_image_models(self,v,key=''): return [r.get('id','') if isinstance(r,dict) else str(r) for r in self.image_metadata(v,key)]
    def inspect_openai_image_model(self,v,key=''):
        rows=self.image_metadata(v,key); row=next((r for r in rows if isinstance(r,dict) and r.get('id')==v['modelId']),{}); return dict(currency=row.get('currency',''),unitPrices=row.get('unit_prices',{}),source='provider_metadata')
