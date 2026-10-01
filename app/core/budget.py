"""Local conservative reservations; all money is an estimate, never a bill."""
import json
import sqlite3
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation, ROUND_UP

from app.storage.project import now


class BudgetError(ValueError):
    pass


def number(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise BudgetError('单价或金额不是有效数字') from None
    if not result.is_finite() or result < 0:
        raise BudgetError('单价或金额须为非负有限数')
    return result


def validate_price(price, image=False):
    if not price:
        return None
    common = {'currency','version','source'}
    required = common | ({'per_image'} if image else {'input_per_million','cached_read_per_million','output_per_million','input_includes_cached'})
    if not isinstance(price,dict) or set(price)!=required or not all(isinstance(price.get(key),str) and price[key].strip() for key in common):
        raise BudgetError('价表缺币种、版本、来源或单价；不推测供应商当前价格')
    if not image and not isinstance(price['input_includes_cached'],bool):
        raise BudgetError('价表须明确input是否包含cached_read，不重复计费')
    for key in required-common-{'input_includes_cached'}:
        number(price[key])
    return price


def estimate(price, usage=None, input_tokens=None, output_limit=None, image_count=None):
    if not price:
        return None
    if image_count is not None:
        validate_price(price,True)
        result=number(price['per_image'])*image_count
    else:
        validate_price(price)
        if usage is not None:
            incoming,outgoing,cached=usage.get('input'),usage.get('output'),usage.get('cached_read')
            if incoming is None or outgoing is None:
                return None
            if cached is None:
                # Missing cache split: estimate the conservative input upper bound.
                result=Decimal(incoming)*max(number(price['input_per_million']),number(price['cached_read_per_million']))
            else:
                uncached=incoming-cached if price['input_includes_cached'] else incoming
                if uncached<0:
                    raise BudgetError('用量缓存子项超过input，无法可靠估价')
                result=Decimal(uncached)*number(price['input_per_million'])+Decimal(cached)*number(price['cached_read_per_million'])
            result+=Decimal(outgoing)*number(price['output_per_million'])
        else:
            result=Decimal(input_tokens)*max(number(price['input_per_million']),number(price['cached_read_per_million']))+Decimal(output_limit)*number(price['output_per_million'])
        result/=Decimal(1000000)
    return str(result.quantize(Decimal('.00000001'),rounding=ROUND_UP))


class BudgetBook:
    def __init__(self,root):
        root.mkdir(parents=True,exist_ok=True)
        self.path=root/'budget.sqlite'
        with self.connection(True) as con:
            con.execute('''CREATE TABLE IF NOT EXISTS reservations(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,
                task_id TEXT NOT NULL,amount TEXT NOT NULL,currency TEXT NOT NULL,state TEXT NOT NULL,
                price_snapshot TEXT NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL)''')

    @contextmanager
    def connection(self,write=False):
        con=sqlite3.connect(self.path,timeout=5)
        con.row_factory=sqlite3.Row
        try:
            if write:
                con.execute('BEGIN IMMEDIATE')
            yield con
            if write:
                con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def reserve(self,project_id,task_id,ordinal,amount,price,limits):
        if amount is None:
            if limits.get('task_amount') or limits.get('project_amount'):
                raise BudgetError('价表未知，金额限制不能可靠执行；请补价表或关闭金额控制，仅用次数/输出限制')
            return None
        if limits.get('currency') and limits['currency']!=price['currency']:
            raise BudgetError('价表与预算币种不同，不自动汇率换算')
        key=task_id+':'+str(ordinal)
        with self.connection(True) as con:
            existing=con.execute('SELECT id FROM reservations WHERE id=?',(key,)).fetchone()
            if existing:
                raise BudgetError('同一调用已预留，拒绝重复收费提交')
            rows=con.execute("SELECT * FROM reservations WHERE project_id=? AND currency=? AND state!='released'",(project_id,price['currency'])).fetchall()
            project_sum=sum((number(row['amount']) for row in rows),Decimal(0))
            task_sum=sum((number(row['amount']) for row in rows if row['task_id']==task_id),Decimal(0))
            for field,total in [('task_amount',task_sum),('project_amount',project_sum)]:
                if limits.get(field) is not None and total+number(amount)>number(limits[field]):
                    raise BudgetError('本地估算与并发预留将超过'+('单次任务' if field=='task_amount' else '当前项目')+'金额上限，未发起下一调用')
            con.execute('INSERT INTO reservations VALUES(?,?,?,?,?,?,?,?,?)',(key,project_id,task_id,amount,price['currency'],'reserved',json.dumps(price,ensure_ascii=False),now(),now()))
        return key

    def settle(self,key,amount=None,rejected=False):
        if not key:
            return
        with self.connection(True) as con:
            if rejected:
                con.execute('UPDATE reservations SET state=?,updated=? WHERE id=?',('released',now(),key))
            elif amount is None:
                con.execute('UPDATE reservations SET state=?,updated=? WHERE id=?',('unconfirmed',now(),key))
            else:
                con.execute('UPDATE reservations SET amount=?,state=?,updated=? WHERE id=?',(amount,'estimated',now(),key))

    def rows(self,project_id):
        with self.connection() as con:
            return [dict(row) for row in con.execute('SELECT * FROM reservations WHERE project_id=? ORDER BY created,id',(project_id,))]

    def reconcile(self,key,amount,note,project_id):
        if not isinstance(note,str) or not note.strip():
            raise BudgetError('账单核对须记录说明，不把未知费用自动归零')
        amount=str(number(amount))
        with self.connection(True) as con:
            row=con.execute('SELECT * FROM reservations WHERE id=? AND project_id=?',(key,project_id)).fetchone()
            if not row:
                raise BudgetError('预留记录不属于当前项目')
            metadata=json.loads(row['price_snapshot'])
            metadata['reconciliation']=dict(note=note.strip(),checked=now(),source='用户对照账单，非自动服务回执')
            con.execute('UPDATE reservations SET amount=?,state=?,price_snapshot=?,updated=? WHERE id=?',
                (amount,'user_reconciled',json.dumps(metadata,ensure_ascii=False),now(),key))
