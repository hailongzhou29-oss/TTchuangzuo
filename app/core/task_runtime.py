"""Mutable local execution ownership, separate from frozen creative snapshots."""
import os
import threading
from contextlib import contextmanager
from functools import wraps
from inspect import signature

from app.core.processes import process_alive,process_started
from app.storage.project import new_id,now

_local=threading.local()


def owner_alive(snapshot,runtime=None,*,fallback=process_alive):
    if runtime is None:
        return fallback(snapshot.get('owner_pid'))
    if not process_alive(runtime['pid']):
        return False
    actual=process_started(runtime['pid'])
    return actual is None or runtime['process_started'] is None or actual==runtime['process_started']


def execution_owner(store,task_id):
    with store.connection() as con:
        row=con.execute('SELECT * FROM task_leases WHERE task_id=?',(task_id,)).fetchone()
    return dict(row) if row else None


@contextmanager
def task_execution(store,task_id,operation):
    if not hasattr(_local,'leases'):
        _local.leases={}
    key=(str(store.root),task_id)
    if key in _local.leases:
        # submit -> download and query -> download share one synchronous lease.
        yield _local.leases[key]
        return
    token=new_id()
    with store.connection(write=True) as con:
        if not con.execute('SELECT 1 FROM tasks WHERE id=?',(task_id,)).fetchone():
            raise ValueError('任务不存在，未执行')
        previous=con.execute('SELECT * FROM task_leases WHERE task_id=?',(task_id,)).fetchone()
        if previous and previous['active'] and owner_alive({},dict(previous)):
            raise ValueError('该任务仍在处理，请先等待完成；未重复查询、下载或提交')
        con.execute('INSERT OR REPLACE INTO task_leases VALUES(?,?,?,?,?,?,?)',
                    (task_id,token,os.getpid(),process_started(os.getpid()),operation,1,now()))
    _local.leases[key]=token
    try:
        yield token
    finally:
        _local.leases.pop(key,None)
        with store.connection(write=True) as con:
            con.execute('UPDATE task_leases SET active=0 WHERE task_id=? AND token=?',(task_id,token))


def owned_task(operation):
    def decorate(function):
        contract=signature(function)
        target_name=list(contract.parameters)[1]
        @wraps(function)
        def run(service,*args,**kwargs):
            target=contract.bind(service,*args,**kwargs).arguments[target_name]
            task_id=target['task_id'] if isinstance(target,dict) else target
            with task_execution(service.store,task_id,operation):
                return function(service,*args,**kwargs)
        return run
    return decorate
