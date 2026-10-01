from __future__ import annotations

import csv
import json
import math
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

from app.core.files import write_json
from app.storage.project import new_id, now

FORMATS = {'film', 'series', 'tv_series', 'television_series', 'micro_drama', 'animation', 'documentary', 'short_film', 'unknown'}
SOURCE_TYPES = {'novel', 'short_story', 'online_novel', 'essay_collection', 'biography', 'memoir', 'news', 'nonfiction',
                'true_event', 'historical_material', 'stage_play', 'comic', 'game', 'original_screenplay', 'book', 'other', 'unknown'}
RELATIONS = {'adapted_from', 'loosely_adapted', 'inspired_by', 'remake', 'sequel', 'multi_source', 'screen_to_book'}


class CaseLibrary:
    def __init__(self, root: Path, seed_path: Path):
        self.path = root / 'case_library.sqlite'
        root.mkdir(parents=True, exist_ok=True)
        with self.connection(write=True) as con:
            con.execute('CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,payload TEXT NOT NULL,version INTEGER NOT NULL,deleted INTEGER NOT NULL DEFAULT 0,favorite INTEGER NOT NULL DEFAULT 0)')
            con.execute('CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY,record_id TEXT NOT NULL,version INTEGER NOT NULL,payload TEXT NOT NULL,created TEXT NOT NULL)')
            con.execute('CREATE TABLE IF NOT EXISTS methods(id TEXT PRIMARY KEY,record_ids TEXT NOT NULL,payload TEXT NOT NULL,state TEXT NOT NULL,version INTEGER NOT NULL,created TEXT NOT NULL)')
            con.execute('CREATE TABLE IF NOT EXISTS library_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            seeded = con.execute("SELECT value FROM library_settings WHERE key='seed_imported'").fetchone()
            if not seeded:
                data = json.loads(seed_path.read_text(encoding='utf-8-sig'))
                for record in data['records']:
                    self.validate(record)
                    con.execute('INSERT OR IGNORE INTO records(id,payload,version) VALUES(?,?,1)', (record['work_id'], json.dumps(record, ensure_ascii=False)))
                    con.execute('INSERT INTO versions VALUES(?,?,?,?,?)', (new_id(), record['work_id'], 1, json.dumps(record, ensure_ascii=False), now()))
                con.execute('INSERT INTO library_settings VALUES(?,?)', ('seed_imported', json.dumps(True)))

    @contextmanager
    def connection(self, write=False):
        con = sqlite3.connect(self.path, timeout=5)
        con.row_factory = sqlite3.Row
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

    @staticmethod
    def blank(title, year=None, screen_format='unknown'):
        return dict(work_id=new_id(), title=title, release_year=year, screen_format=screen_format, record_status='research_candidate',
            verified_fields=[], adaptation_sources=[], award_records=[], rating_snapshots=[], box_office_snapshots=[],
            short_drama_metrics=[], analysis_status='not_analyzed', selection_criteria_status='not_evaluated', evidence=[], notes=[])

    @staticmethod
    def validate(record):
        if not isinstance(record, dict) or not all(isinstance(record.get(key), str) and record[key].strip() for key in ('work_id', 'title', 'screen_format')):
            raise ValueError('案例最低身份字段缺失')
        if record['screen_format'] not in FORMATS:
            raise ValueError('案例作品形式无效')
        year = record.get('release_year')
        if year is not None and (not isinstance(year, int) or isinstance(year, bool) or not 1800 <= year <= 2100):
            raise ValueError('影视年份无效；未知保持空值')
        for field in ('adaptation_sources', 'award_records', 'rating_snapshots', 'box_office_snapshots', 'short_drama_metrics', 'evidence', 'verified_fields', 'notes'):
            if not isinstance(record.get(field, []), list) or len(record.get(field, [])) > 1000:
                raise ValueError('案例列表字段无效：' + field)
        source_ids = set()
        evidence_ids = set()
        for evidence in record.get('evidence', []):
            if not isinstance(evidence, dict) or not isinstance(evidence.get('evidence_id'), str) or evidence['evidence_id'] in evidence_ids:
                raise ValueError('证据 ID 无效或重复')
            url = urlparse(evidence.get('url') or '')
            if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password:
                raise ValueError('证据须为公开网页地址，不执行文件/脚本路径')
            if not isinstance(evidence.get('supports', []), list):
                raise ValueError('证据支持字段格式无效')
            evidence_ids.add(evidence['evidence_id'])
        for source in record.get('adaptation_sources', []):
            if not isinstance(source, dict) or not all(isinstance(source.get(key), str) and source[key] for key in ('source_id', 'title', 'source_type', 'relation_type')):
                raise ValueError('原作/关系字段缺失')
            if source['source_id'] in source_ids or source['source_type'] not in SOURCE_TYPES or source['relation_type'] not in RELATIONS:
                raise ValueError('原作 ID、类型或改编方向无效')
            if source.get('evidence_id') and source['evidence_id'] not in evidence_ids:
                raise ValueError('改编关系证据引用不存在')
            source_ids.add(source['source_id'])
        for rating in record.get('rating_snapshots', []):
            if not isinstance(rating, dict) or not all(rating.get(key) for key in ('platform', 'collected_at', 'source')):
                raise ValueError('评分快照缺平台、采集时间或来源')
            score, maximum, count = rating.get('score'), rating.get('scale'), rating.get('count')
            if score is not None and (not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score) or not isinstance(maximum, (int, float)) or maximum <= 0 or not 0 <= score <= maximum):
                raise ValueError('评分数值或满分口径无效')
            if count is not None and (not isinstance(count, int) or isinstance(count, bool) or count < 0):
                raise ValueError('评分人数无效')
        for box in record.get('box_office_snapshots', []):
            if not isinstance(box, dict) or not all(box.get(key) for key in ('currency', 'region', 'period', 'as_of', 'source')):
                raise ValueError('票房快照缺币种、地区、期间、日期或来源')
            amount = box.get('amount')
            if amount is not None and (not isinstance(amount, (int, float)) or isinstance(amount, bool) or not math.isfinite(amount) or amount < 0):
                raise ValueError('票房数值无效')
        for award in record.get('award_records', []):
            if not isinstance(award, dict) or award.get('status') not in {'won', 'nominated', 'shortlisted', 'recommended'} or not all(award.get(key) for key in ('organization', 'category', 'subject_type', 'subject_id', 'source')):
                raise ValueError('奖项必须区分获奖/提名/入围/推荐并标实际授奖对象')
            if award['subject_type']=='source_work' and award['subject_id'] not in source_ids:
                raise ValueError('原著奖项须关联实际原作ID')
            if award['subject_type']=='screen_work' and award['subject_id']!=record['work_id']:
                raise ValueError('影视奖项关联错误作品')
            if award['subject_type'] not in {'source_work','screen_work','season','episode'}:
                raise ValueError('授奖对象类型无效')
        for metric in record.get('short_drama_metrics', []):
            if not isinstance(metric,dict) or not all(metric.get(k) for k in ('platform','metric','unit','interval','definition','source')):
                raise ValueError('微短剧指标须保留平台、单位、区间、口径和来源，不混用播放/收入/消耗')
        return record

    def records(self, query='', screen_format=None, year_min=None, year_max=None, source_type=None, favorites=False, deleted=False,
                rating_platform=None, min_rating=None, min_count=None, rating_after=None, unknown_ratings=False):
        with self.connection() as con:
            rows = con.execute('SELECT * FROM records WHERE deleted=? ORDER BY rowid', (int(deleted),)).fetchall()
        result = []
        for row in rows:
            record = json.loads(row['payload'])
            record.update(_version=row['version'], _favorite=bool(row['favorite']))
            if query.casefold() not in json.dumps(record, ensure_ascii=False).casefold():
                continue
            if favorites and not record['_favorite']:
                continue
            if screen_format and record['screen_format'] != screen_format:
                continue
            if source_type and not any(s['source_type'] == source_type for s in record.get('adaptation_sources', [])):
                continue
            year = record.get('release_year')
            if (year_min is not None or year_max is not None) and (year is None or (year_min is not None and year < year_min) or (year_max is not None and year > year_max)):
                continue
            ratings = record.get('rating_snapshots', [])
            if unknown_ratings and any(r.get('score') is not None for r in ratings):
                continue
            if min_rating is not None or min_count is not None or rating_after or rating_platform:
                filtered = [r for r in ratings if (not rating_platform or r['platform'] == rating_platform) and r.get('score') is not None and
                    (min_rating is None or r['score'] >= min_rating) and (min_count is None or (r.get('count') is not None and r['count'] >= min_count)) and
                    (not rating_after or r['collected_at'] >= rating_after)]
                if not filtered:
                    continue
            result.append(record)
        return result

    def get(self, work_id):
        with self.connection() as con:
            row = con.execute('SELECT * FROM records WHERE id=?', (work_id,)).fetchone()
        if not row:
            raise ValueError('案例 ID 不存在')
        return dict(json.loads(row['payload']), _version=row['version'], _favorite=bool(row['favorite']), _deleted=bool(row['deleted']))

    def save(self, record, base_version=None):
        record = {key: value for key, value in record.items() if not key.startswith('_')}
        self.validate(record)
        with self.connection(write=True) as con:
            old = con.execute('SELECT version FROM records WHERE id=?', (record['work_id'],)).fetchone()
            if old and base_version != old['version']:
                raise ValueError('案例已更新，请比较当前版本后保存；不自动合并同名作品')
            version = old['version'] + 1 if old else 1
            text = json.dumps(record, ensure_ascii=False)
            if old:
                con.execute('UPDATE records SET payload=?,version=? WHERE id=?', (text, version, record['work_id']))
            else:
                con.execute('INSERT INTO records(id,payload,version) VALUES(?,?,?)', (record['work_id'], text, version))
            con.execute('INSERT INTO versions VALUES(?,?,?,?,?)', (new_id(), record['work_id'], version, text, now()))
        return record['work_id']

    def preview_import(self, path):
        path = Path(path)
        if path.stat().st_size > 8 * 1024**2:
            raise ValueError('案例导入超过8MB，请分批')
        if path.suffix.lower() == '.json':
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            rows = data.get('records') if isinstance(data, dict) else data
            if not isinstance(rows, list):
                raise ValueError('JSON须含records列表或为记录列表')
        elif path.suffix.lower() == '.csv':
            rows = []
            with path.open(encoding='utf-8-sig', newline='') as handle:
                reader = csv.DictReader(handle)
                if not {'title', 'release_year', 'screen_format'} <= set(reader.fieldnames or []):
                    raise ValueError('CSV最低字段映射：title,release_year,screen_format；未知复杂字段须手工补映射')
                for row in reader:
                    rows.append(self.blank(row['title'], int(row['release_year']) if row['release_year'].strip() else None, row['screen_format'] or 'unknown'))
        else:
            raise ValueError('案例导入只支持JSON/CSV')
        if not 1 <= len(rows) <= 500:
            raise ValueError('每批案例数量须为1—500')
        ids = set()
        for row in rows:
            self.validate(row)
            if row['work_id'] in ids:
                raise ValueError('导入记录ID重复')
            ids.add(row['work_id'])
        return rows

    def import_records(self, rows):
        # New IDs remain independent; existing IDs require an explicit editor merge.
        for row in rows:
            with self.connection() as con:
                exists = con.execute('SELECT id FROM records WHERE id=?', (row['work_id'],)).fetchone()
            if exists:
                raise ValueError('导入包含现有ID，先人工比较/编辑，不覆盖旧记录')
        with self.connection(write=True) as con:
            for row in rows:
                self.validate(row)
                text = json.dumps(row, ensure_ascii=False)
                con.execute('INSERT INTO records(id,payload,version) VALUES(?,?,1)', (row['work_id'], text))
                con.execute('INSERT INTO versions VALUES(?,?,?,?,?)', (new_id(), row['work_id'], 1, text, now()))

    def favorite(self, work_id, value):
        self.get(work_id)
        with self.connection(write=True) as con:
            con.execute('UPDATE records SET favorite=? WHERE id=?', (int(value), work_id))

    def trash(self, work_id, restore=False):
        self.get(work_id)
        with self.connection(write=True) as con:
            con.execute('UPDATE records SET deleted=? WHERE id=?', (0 if restore else 1, work_id))

    def append_metric(self, work_id, field, metric):
        if field not in {'rating_snapshots', 'box_office_snapshots', 'award_records', 'short_drama_metrics'}:
            raise ValueError('未知指标集合')
        record = self.get(work_id)
        record.setdefault(field, []).append(metric)
        self.save(record, record['_version'])

    def versions(self, work_id):
        with self.connection() as con:
            return [dict(version=row['version'], record=json.loads(row['payload']), created=row['created']) for row in con.execute('SELECT * FROM versions WHERE record_id=? ORDER BY version', (work_id,))]

    def coverage(self):
        records = self.records()
        years = sorted({r['release_year'] for r in records if r.get('release_year') is not None})
        return dict(target_range=[1980, 2026], records=len(records), known_identity_years=years,
                    adaptation_relations=sum(len(r.get('adaptation_sources', [])) for r in records),
                    systematic_search_years=[], unsearched_years=list(range(1980, 2027)),
                    note='记录存在不等于完成该年份系统采集；未检索年份不是零作品。')

    def export(self, path, work_ids=None):
        rows = [r for r in self.records() if not work_ids or r['work_id'] in work_ids]
        rows = [{key: value for key, value in row.items() if not key.startswith('_')} for row in rows]
        write_json(Path(path), dict(schema_version=1, records=rows, coverage=self.coverage(), scope='事实/来源/原创研究，不含原作全文'))

    def propose_method(self, record_ids, payload):
        for work_id in record_ids:
            self.get(work_id)
        keys = {'title', 'body', 'stages', 'applies_to', 'applicable_when', 'not_applicable_when', 'evidence_boundary', 'counterexamples'}
        if not isinstance(payload, dict) or set(payload) != keys or not all(isinstance(payload[k], str) and payload[k].strip() for k in ('title','body','applicable_when','not_applicable_when','evidence_boundary')):
            raise ValueError('方法候选须写明规则、适用/不适用条件与证据边界')
        mid = new_id()
        with self.connection(write=True) as con:
            con.execute('INSERT INTO methods VALUES(?,?,?,?,?,?)', (mid, json.dumps(record_ids), json.dumps(payload, ensure_ascii=False), 'candidate', 1, now()))
        return mid

    def get_method(self, method_id):
        with self.connection() as con:
            row = con.execute('SELECT * FROM methods WHERE id=?', (method_id,)).fetchone()
        if not row:
            raise ValueError('方法候选不存在')
        return dict(row, payload=json.loads(row['payload']), record_ids=json.loads(row['record_ids']))

    def approve_method(self, method_id):
        self.get_method(method_id)
        with self.connection(write=True) as con:
            con.execute('UPDATE methods SET state=? WHERE id=?', ('approved', method_id))

    def use_method(self, method_id, project_rules):
        method = self.get_method(method_id)
        if method['state'] != 'approved':
            raise ValueError('方法尚未审核，不能自动进入创作规则')
        payload = method['payload']
        body = payload['body'] + '\n适用：' + payload['applicable_when'] + '\n不适用：' + payload['not_applicable_when'] + '\n证据边界：' + payload['evidence_boundary']
        rule = dict(rule_id='METHOD_' + method_id[:12].upper(), version=str(method['version']), title=payload['title'], body=body,
                    stages=payload['stages'], applies_to=payload['applies_to'], enabled=True, priority=70,
                    source='用户审核的案例方法；案例ID：' + ','.join(method['record_ids']))
        project_rules.import_package(dict(schema_version=1, rules=[rule]))
        return rule['rule_id']
