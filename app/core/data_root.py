"""One movable application data folder; the launcher keeps only its location."""
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import closing
from pathlib import Path

from app.core.files import write_json
from app.core.test_isolation import guard_test_write


def validate_root(path):
    unresolved=Path(path).expanduser()
    if unresolved.is_symlink() or getattr(unresolved,'is_junction',lambda:False)():
        raise ValueError('作品总目录不能使用目录链接')
    root=unresolved.resolve()
    if root==Path(root.anchor) or (os.name=='nt' and root.drive.casefold()=='c:'):
        raise ValueError('作品总目录请选择 C 盘以外的独立文件夹')
    if root.is_symlink() or getattr(root,'is_junction',lambda:False)():
        raise ValueError('作品总目录不能使用目录链接')
    return root


def startup_paths(source_root,data_root=None,preferences=None):
    source_root=Path(source_root).resolve(); locator=source_root/'local.runtime.json'
    runtime=json.loads(locator.read_text(encoding='utf-8-sig')) if locator.is_file() else {}
    root=validate_root(data_root or (Path(preferences).parent if preferences else runtime.get('data_root') or source_root.parent/'TT写作数据'))
    prefs=Path(preferences).resolve() if preferences else root/'preferences.json'
    if prefs.parent!=root: raise ValueError('设置文件必须直接保存在作品总目录内')
    return root,prefs,locator if data_root is None and preferences is None else None


def set_runtime_data_root(root):
    root=validate_root(root); cache=root/'cache'; guard_test_write(cache); cache.mkdir(parents=True,exist_ok=True)
    # All application scratch files and inherited child-process temp files stay here.
    tempfile.tempdir=str(cache); os.environ['TMP']=str(cache); os.environ['TEMP']=str(cache)


def save_locator(path,root):
    if path is None: return
    path=Path(path); value=json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else {}
    value['data_root']=str(validate_root(root)); write_json(path,value)


def relocate(value,source,target):
    if isinstance(value,dict): return {k:relocate(v,source,target) for k,v in value.items()}
    if isinstance(value,list): return [relocate(v,source,target) for v in value]
    if isinstance(value,str):
        # Match only whole path boundaries, never ordinary text or a sibling prefix.
        old=str(source); normalized=value.replace('\\','/'); prefix=old.replace('\\','/')
        if normalized.casefold()==prefix.casefold(): return str(target)
        if normalized.casefold().startswith(prefix.casefold()+'/'):
            return str(target/Path(normalized[len(prefix)+1:]))
    return value


class DataMigration:
    def __init__(self,source,target):
        self.source=validate_root(source); self.target=validate_root(target)
        if self.source==self.target or self.source.is_relative_to(self.target) or self.target.is_relative_to(self.source):
            raise ValueError('新目录必须与当前作品总目录独立，不能互相包含')
        if not self.source.is_dir(): raise ValueError('当前作品总目录不存在')
        if self.target.exists() and (not self.target.is_dir() or any(self.target.iterdir())):
            raise ValueError('请选择新的空文件夹，避免覆盖其他文件')
        guard_test_write(self.source); guard_test_write(self.target)
        self.staging=self.target.parent/('.tt-move-'+uuid.uuid4().hex); self.published=False

    def prepare(self,options,preferences_relative,workspace_relative):
        try:
            # Inspect file metadata only. No project prose or raw model responses are read.
            files=[]
            for path in self.source.rglob('*'):
                if path.is_symlink() or getattr(path,'is_junction',lambda:False)():
                    raise ValueError('数据文件夹含目录或文件链接，请先移除链接')
                if path.is_file(): files.append((path.relative_to(self.source),path.stat().st_size))
            shutil.copytree(self.source,self.staging)
            for relative,size in files:
                copied=self.staging/relative
                if not copied.is_file() or copied.stat().st_size!=size: raise OSError('迁移文件校验失败：'+str(relative))
            rewritten=relocate(options,self.source,self.target)
            rewritten.update(output_root=str(self.target),workspace_root=str(self.target/workspace_relative),restore_last=False)
            rewritten.pop('output_root_history',None)
            write_json(self.staging/preferences_relative,rewritten)
            # Only exported-file receipts contain absolute paths needed for future saving.
            for database in (self.staging/workspace_relative/'projects').glob('*/project.sqlite'):
                with closing(sqlite3.connect(database)) as connection, connection:
                    row=connection.execute("SELECT value FROM settings WHERE key='v2_output_receipts'").fetchone()
                    if row:
                        receipts=relocate(json.loads(row[0]),self.source,self.target)
                        connection.execute("UPDATE settings SET value=? WHERE key='v2_output_receipts'",(json.dumps(receipts,ensure_ascii=False),))
            if self.target.exists(): self.target.rmdir()
            self.staging.rename(self.target); self.published=True
            return rewritten
        except Exception:
            self.abort(); raise

    def abort(self):
        # Delete only this migration's staging tree under the verified target parent.
        if self.staging.parent!=self.target.parent or not self.staging.name.startswith('.tt-move-'):
            raise ValueError('迁移临时目录边界错误')
        if self.staging.is_dir(): shutil.rmtree(self.staging)
        if self.published:
            guard_test_write(self.target); shutil.rmtree(self.target); self.published=False

    def clean_source(self):
        if not self.published or not self.target.is_dir() or self.source==self.target:
            raise ValueError('新目录尚未启用，不能清理旧目录')
        # self.source was resolved and checked at construction; never delete a drive root.
        validate_root(self.source); guard_test_write(self.source); shutil.rmtree(self.source)


def rebind_logging(root):
    logs=Path(root)/'logs'; logs.mkdir(parents=True,exist_ok=True)
    logger=logging.getLogger()
    for handler in list(logger.handlers):
        if isinstance(handler,logging.FileHandler):
            formatter=handler.formatter; level=handler.level; logger.removeHandler(handler); handler.close()
            replacement=logging.FileHandler(logs/'startup.log',encoding='utf-8'); replacement.setFormatter(formatter); replacement.setLevel(level); logger.addHandler(replacement)
    import sys
    stream=getattr(sys,'_tt_log_stream',None)
    if stream is not None:
        replacement=(logs/'gui-runtime.log').open('a',encoding='utf-8',buffering=1)
        sys.stdout=replacement; sys.stderr=replacement; sys._tt_log_stream=replacement; stream.close()
