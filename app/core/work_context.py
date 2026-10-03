"""The editor, chat, creation and cover share one versioned work buffer."""
from dataclasses import dataclass, field
import re
from app.core.files import digest
from app.storage.project import ConflictError,new_id

@dataclass
class CurrentWork:
    store: object
    document_id: str
    revision: str
    text: str
    config: dict
    selection: tuple = (0,0)
    epoch: int = 0
    dirty: bool = False
    draft: bool = False
    buffer_id: str = field(default_factory=new_id)
    @classmethod
    def load(cls,store,did,config):
        d=store.document(did)
        return cls(store,did,d['head'],d['text'],config)
    def edit(self,text):
        if text!=self.text:
            self.text=text; self.epoch+=1; self.dirty=True
    def save(self,reason='手动编辑'):
        if self.dirty:
            self.revision=self.store.save_document(self.document_id,self.revision,self.text,reason)
            self.dirty=False
            self.invalidate_memory()
        return self.revision
    def invalidate_memory(self):
        """Derived records are versioned; later chapters are never silently rewritten."""
        memories=self.store.setting('v2_memories',{})
        memories.pop(self.document_id,None)
        self.store.set_setting('v2_memories',memories)
        plan=self.store.setting('v2_plan',{})
        if plan.get('source_document_id')==self.document_id and plan.get('source_revision')!=self.revision:
            plan['source_stale']=True; self.store.set_setting('v2_plan',plan)
        docs=[d for d in self.store.documents() if d['kind']!='reference']
        after=False
        for doc in docs:
            if doc['id']==self.document_id: after=True
            elif after: self.store.set_setting('v2_stale:'+doc['id'],True)
    def freeze(self):
        return dict(project_id=self.store.metadata()['id'],document_id=self.document_id,
                    revision=self.revision,text=self.text,hash=digest(self.text),epoch=self.epoch,selection=list(self.selection),buffer_id=self.buffer_id)
    def apply(self,frozen,replacement,start=0,end=None,reason='AI修改'):
        if frozen['project_id']!=self.store.metadata()['id'] or frozen['document_id']!=self.document_id:
            raise ConflictError('修改不属于当前作品')
        end=len(frozen['text']) if end is None else end
        old=frozen['text'][start:end]
        if self.text!=frozen['text']:
            # Merge only an unchanged unique target; full rewrites cannot merge.
            if not old or self.text.count(old)!=1 or start==0 and end==len(frozen['text']):
                raise ConflictError('正文在处理期间发生了变化，请选择要保留的内容')
            start=self.text.index(old); end=start+len(old)
        before=self.text; base=self.revision
        candidate=before[:start]+replacement+before[end:]
        self.store.save_document(self.document_id,base,candidate,reason)
        self.revision=self.store.document(self.document_id)['head']; self.text=candidate
        self.dirty=False; self.epoch+=1; self.draft=False; self.invalidate_memory()
        return before

def locate(text,instruction,selected=(0,0)):
    if selected[1]>selected[0]: return selected
    nums={'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
    wanted=re.search(r'第([\d一二三四五六七八九十]+)[场幕]',instruction)
    if not wanted:
        # Vague deictic targets should not become a full rewrite.
        if any(v in instruction for v in ('那段','这段','这一句','那一句','只改这里','仅改这里')):
            raise ValueError('没有找到你指定的段落，请选中要修改的内容')
        return (0,len(text))
    val=wanted[1]; number=int(val) if val.isdigit() else nums.get(val)
    body_start=text.find('第二部分｜完整剧本')
    body_end=text.find('第三部分｜完整人物台词')
    lo=body_start if body_start>=0 else 0; hi=body_end if body_end>=0 else len(text)
    headers=list(re.finditer(r'(?m)^\s*(?:#{1,4}\s*)?(?:第[\d一二三四五六七八九十]+场|场[次景]?\s*\d+|S\d+)\s*[^\n]*',text[lo:hi]))
    if not number or number>len(headers): raise ValueError('没有找到你指定的段落，请选中要修改的内容')
    return (lo+headers[number-1].start(),lo+headers[number].start() if number<len(headers) else hi)

def intent(instruction):
    # Explicit non-writing requests take priority over mentions of editing words.
    if re.search(r'只检查|仅检查|只复核|仅复核|(?:不|不要|别)(?:改稿|改写|修改正文|改正文)|仅讨论|只讨论',instruction) and not re.search(r'检查(?:并|后)修改|复核(?:并|后)修改',instruction):
        return 'inspect' if re.search(r'检查|复核',instruction) else 'discuss'
    if re.search(r'解释|讲解|讲讲|聊聊|讨论|(?:怎么|如何|什么).*(?:改写|修改|写|拓展|扩展)|(?:改写|修改|优化|拓展|扩展).{0,8}建议',instruction) and not re.search(r'(?:直接|请|帮我|帮忙).{0,8}(?:改写|修改|重写|拓展|扩展|延长)|检查(?:并|后)修改',instruction): return 'discuss'
    if any(v in instruction for v in ('不要续写','不续写','别续写','不要写下一章')) and any(v in instruction for v in ('只检查','检查','复核')): return 'inspect'
    if '续写' in instruction or '下一章' in instruction: return 'next'
    if not any(v in instruction for v in ('不要改设定','保留设定','保留大纲','不要改大纲','只改第')) and re.search(r'(?:修改|调整|重写|改变|增加|改|加强|把).{0,20}(?:大纲|规划|设定)|(?:大纲|规划|设定).{0,20}(?:修改|调整|重写|改变|增加|加强)',instruction): return 'planning'
    if re.search(r'(?:只|仅)(?:改|修改)|改成|改得|改紧|改强|检查(?:并|后)修改',instruction): return 'modify'
    if any(v in instruction for v in ('不要修改','不要改','只检查','检查','复核','讲了什么','聊聊','怎么写','建议')) and not any(v in instruction for v in ('只改动作','只改台词','检查并修改','检查后修改')):
        return 'inspect'
    if any(v in instruction for v in ('修改','改写','只改','改一下','改一改','改第','改为','改成','改得','改紧','改强','重写','加强','增强','替换','缩短','缩写','润色','更悲伤','更强','更狠','狠一点','更紧凑','优化','扩写')) or re.search(r'把.{1,60}(?:改|换|写成|变成)',instruction): return 'modify'
    if re.search(r'拓展|扩展|延长(?:到|至)|(?:拓|扩)写(?:到|至)|(?:台词|对白|动作|画面|描写|节奏|情绪).{0,8}(?:太少|不够|增加|丰富|详细|更强|太慢|太快)',instruction): return 'modify'
    return 'discuss'
