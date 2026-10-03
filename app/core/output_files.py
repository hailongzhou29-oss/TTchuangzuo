"""Human-readable, flat outputs; SQLite and provider assets stay authoritative."""
import os,re
from pathlib import Path
from app.core.files import digest
from app.core.writing_views import chapter_documents,is_long

CATEGORIES=('剧本','小说','图片')

def safe_name(value):
    name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',str(value)).strip(' .')[:80].rstrip(' .') or '未命名作品'
    if re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',name): name='_'+name
    return name

class OutputFiles:
    def __init__(self,root): self.root=Path(root).expanduser().resolve()
    def folder(self,category):
        if category not in CATEGORIES: raise ValueError('未知输出分类')
        path=self.root/category
        if not path.resolve().is_relative_to(self.root): raise ValueError('分类目录指向作品总目录之外')
        path.mkdir(parents=True,exist_ok=True); return path
    def paths(self): return {name:self.root/name for name in CATEGORIES}
    @staticmethod
    def available(folder,stem,extension,cover=False):
        extension=extension.lower().lstrip('.')
        if extension not in {'md','txt','png'}: raise ValueError('不支持的输出格式')
        stem=safe_name(stem); number=1
        while True:
            suffix=f'_{number:02d}' if cover else f'_v{number:03d}'
            path=Path(folder)/(stem+suffix+'.'+extension)
            if not path.exists(): return path
            number+=1
    def write(self,category,stem,data,extension='md',cover=False):
        return self.write_to(self.folder(category),stem,data,extension,cover)
    @classmethod
    def write_to(cls,folder,stem,data,extension='md',cover=False):
        folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
        while True:
            path=cls.available(folder,stem,extension,cover)
            created=False
            try:
                with path.open('xb') as handle:
                    created=True
                    handle.write(data); handle.flush(); os.fsync(handle.fileno())
                return path
            except FileExistsError: continue
            except OSError:
                # Only remove this request's incomplete newly-created file.
                if created and path.exists(): path.unlink()
                raise

def work_output(work,whole_book=False):
    store=work.store; title=safe_name(store.metadata()['name']); category='剧本' if work.config.get('output')=='script' else '小说'
    document=store.document(work.document_id)
    if document['kind']=='outline': return category,title+'_大纲',work.text
    chapters=chapter_documents(store)
    if whole_book:
        if category!='小说': raise ValueError('整本导出仅适用于小说')
        text='\n\n'.join(store.document(d['id'])['text'] for d in chapters)
        return category,title+'_整本小说',text
    if category=='小说' and (is_long(work.config) or len(chapters)>1):
        index=next((i+1 for i,d in enumerate(chapters) if d['id']==work.document_id),1)
        chapter=re.sub(r'^第[\d一二三四五六七八九十百]+章[\s·:：-]*','',document['title']).strip()
        stem=title+f'_第{index:03d}章_'+safe_name(chapter or '正文')
    else: stem=title+'_'+category
    return category,stem,work.text

def publish_work(output,work):
    if not work.text.strip() or work.dirty or work.draft or work.store.setting('v2_generation_draft'): return None
    if work.store.setting('v2_third_unsynced:'+work.document_id,False): return None
    category,stem,text=work_output(work); fingerprint=digest(text)
    receipts=work.store.setting('v2_output_receipts',[])
    for receipt in reversed(receipts):
        if receipt.get('document_id')==work.document_id and receipt.get('root')==str(output.root) and receipt.get('stem')==stem:
            if receipt.get('hash')==fingerprint and Path(receipt['path']).is_file(): return Path(receipt['path'])
            break
    path=output.write(category,stem,text.encode('utf-8'))
    receipts.append(dict(document_id=work.document_id,revision=work.revision,root=str(output.root),stem=stem,path=str(path),hash=fingerprint))
    work.store.set_setting('v2_output_receipts',receipts); return path
