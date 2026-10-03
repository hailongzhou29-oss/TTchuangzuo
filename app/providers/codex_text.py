from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from app.core.files import atomic_write, write_json
from app.providers.contracts import CancelToken, Connection, TextResult, normalize_usage, redact

HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
DISABLE_FEATURES = ('shell_tool', 'unified_exec', 'apps', 'plugins', 'hooks', 'browser_use', 'browser_use_external',
                    'computer_use', 'image_generation', 'code_mode_host', 'skill_search', 'view_image', 'goals')


def merged_environment_path():
    """TT bridge's process/user/machine PATH discovery; no credential reads."""
    values=[os.environ.get('PATH','')]
    if os.name=='nt':
        import winreg
        for root,subkey in ((winreg.HKEY_CURRENT_USER,r'Environment'),(winreg.HKEY_LOCAL_MACHINE,r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment')):
            try:
                with winreg.OpenKey(root,subkey) as key: values.append(str(winreg.QueryValueEx(key,'Path')[0]))
            except OSError: pass
    parts=[]
    for value in values:
        for item in value.split(os.pathsep):
            item=os.path.expandvars(item.strip().strip('"'))
            if item and item.casefold() not in {p.casefold() for p in parts}: parts.append(item)
    return os.pathsep.join(parts)

def command_prefix(path: str = ''):
    search=merged_environment_path()
    candidate = Path(path) if path else Path(shutil.which('codex.exe',path=search) or shutil.which('codex.cmd',path=search) or shutil.which('codex',path=search) or '')
    if not candidate.is_file():
        raise ValueError('指定的 Codex 文件不存在' if path else 'PATH 未找到 Codex，请选择已有 CLI 文件')
    if candidate.suffix.lower() == '.exe':
        return [str(candidate.resolve())]
    if candidate.suffix.lower() == '.js':
        node = shutil.which('node',path=search)
        if not node:
            raise ValueError('JS CLI 入口需要已有 Node.js')
        return [node, str(candidate.resolve())]
    if candidate.suffix.lower() in {'.cmd', '.ps1', '.bat'}:
        # Resolve the standard npm layout, never run a shell with task/user arguments.
        entry = candidate.parent / 'node_modules' / '@openai' / 'codex' / 'bin' / 'codex.js'
        node = candidate.parent / 'node.exe'
        if not node.is_file():
            node = Path(shutil.which('node',path=search) or '')
        if entry.is_file() and node.is_file():
            return [str(node.resolve()), str(entry.resolve())]
        raise ValueError('该包装器不是可识别的 npm CLI；请选择实际 codex.exe 或 codex.js')
    raise ValueError('请选择 codex.exe、标准 npm 包装器或 codex.js')


class CodexTextProvider:
    def __init__(self,state_root=None):
        self.probes = {}; self.state_root=state_root

    def detect(self, path='', login=False):
        prefix = command_prefix(path)
        version = subprocess.run(prefix + ['--version'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15, creationflags=HIDDEN)
        if version.returncode or not re.search(r'codex-cli\s+\d+\.\d+\.\d+', version.stdout):
            raise ValueError('所选 CLI 未返回可识别的版本')
        help_result = subprocess.run(prefix + ['exec', '--help'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15, creationflags=HIDDEN)
        required = ['--ignore-user-config', '--ignore-rules', '--ephemeral', '--json', '--output-schema', '--sandbox']
        if help_result.returncode or any(flag not in help_result.stdout for flag in required):
            raise ValueError('CLI 缺少所需隔离/输出能力，请使用支持这些参数的现有版本')
        feature_result = subprocess.run(prefix + ['features', 'list'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15, creationflags=HIDDEN)
        available = {line.split()[0] for line in feature_result.stdout.splitlines() if line.strip()}
        if feature_result.returncode or 'shell_tool' not in available:
            raise ValueError('无法确认 CLI 的工具禁用能力')
        result = dict(prefix=prefix, version=version.stdout.strip(), features=sorted(available), logged_in=None)
        if login:
            status = subprocess.run(prefix + ['login', 'status'], capture_output=True, timeout=15, creationflags=HIDDEN)
            result['logged_in'] = status.returncode == 0
        self.probes[tuple(prefix)] = result
        from app.core.codex_state import remember
        remember(self.state_root,path,result)
        return result

    @staticmethod
    def stop(process):
        if process.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=HIDDEN, timeout=10)
            else:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    def generate(self, connection: Connection, messages: list[dict], cancel: CancelToken,
                 on_text=lambda text: None, schema=None, reasoning=None, image_request=False, reference_paths=None):
        connection.validate()
        started = time.monotonic()
        result = TextResult(model=connection.model)
        if cancel.cancelled:
            result.status, result.accepted = 'cancelled', False
            return result
        prefix = command_prefix(connection.cli_path)
        from app.core.codex_state import cached_probe
        probe = self.probes.get(tuple(prefix)) or cached_probe(self.state_root,prefix) or self.detect(connection.cli_path)
        if image_request and 'image_generation' not in probe['features']:
            raise ValueError('该 CLI 未发现内置图片工具入口；未切换到 API')
        if reasoning and reasoning not in connection.reasoning_levels:
            raise ValueError('该 CLI 模型未声明支持所选推理强度')
        isolated=os.environ.get('TT_CREATOR_TEST_ROOT') if os.environ.get('TT_CREATOR_TEST_MODE')=='1' else None
        with tempfile.TemporaryDirectory(prefix='TT 创作 CLI ',dir=isolated) as temporary:
            root = Path(temporary)
            args = prefix + ['exec', '--ignore-user-config', '--ignore-rules', '--ephemeral', '--json', '--color', 'never',
                             '--sandbox', 'read-only', '--skip-git-repo-check', '--cd', str(root),
                             '-c', 'web_search="disabled"', '-c', 'approval_policy="never"']
            if connection.model.strip() and connection.model.strip().casefold() not in {'default','使用codex默认模型'}:
                args += ['--model', connection.model.strip()]
            for feature in DISABLE_FEATURES:
                if image_request and feature in {'image_generation','view_image','code_mode_host'}:
                    continue
                if feature in probe['features']:
                    args += ['--disable', feature]
            if image_request:
                args += ['--enable', 'image_generation']
                if 'code_mode_host' in probe['features']:
                    args += ['--enable','code_mode_host']
                for index, source in enumerate(reference_paths or []):
                    source = Path(source)
                    target = root / ('reference_' + str(index) + source.suffix.lower())
                    shutil.copyfile(source, target)
                    args += ['--image', str(target)]
            if schema:
                schema_path = root / 'output.schema.json'
                write_json(schema_path, schema)
                args += ['--output-schema', str(schema_path)]
            if reasoning:
                args += ['-c', 'model_reasoning_effort=' + json.dumps(reasoning)]
            args.append('-')
            packet = ('仅依据本次消息调用内置 imagegen 生成图片，不调用 API 脚本、shell、网页或扫描工程。\n' if image_request else
                      '仅依据本次消息完成写作任务。不要调用工具、扫描目录、联网研究或修改文件。\n')
            packet += f'本次输出目标上限 {connection.max_output} token；这对 CLI 是软限制。\n'
            packet += json.dumps(messages, ensure_ascii=False)
            environment=os.environ.copy(); environment['PATH']=merged_environment_path(); environment['NO_COLOR']='1'
            process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='replace', creationflags=HIDDEN, cwd=root,env=environment)
            result.accepted = None
            result.diagnostics = dict(process_id=process.pid, started_at=datetime.now(timezone.utc).isoformat(), events=[])
            events = queue.Queue()
            def reader(pipe, kind):
                try:
                    for line in pipe:
                        events.put((kind, line))
                finally:
                    events.put((kind, None))
                    pipe.close()
            readers = [threading.Thread(target=reader, args=(process.stdout, 'stdout'), daemon=True),
                       threading.Thread(target=reader, args=(process.stderr, 'stderr'), daemon=True)]
            for thread in readers:
                thread.start()
            process.stdin.write(packet)
            process.stdin.close()
            finished_streams = 0
            messages_by_id = {}
            received_bytes = 0
            try:
                while finished_streams < 2:
                    if cancel.cancelled or time.monotonic() - started > connection.timeout:
                        self.stop(process)
                        result.status = 'cancelled' if cancel.cancelled else 'uncertain'
                        result.error = '已停止等待，保留部分候选；服务端可能仍计费' if cancel.cancelled else 'CLI 超时，结果待确认；未自动重发'
                        break
                    try:
                        kind, line = events.get(timeout=.1)
                    except queue.Empty:
                        continue
                    if line is None:
                        finished_streams += 1
                        continue
                    received_bytes += len(line.encode('utf-8'))
                    if received_bytes > 16 * 1024**2:
                        self.stop(process)
                        raise ValueError('CLI 输出超过本地接收限制')
                    if kind == 'stderr':
                        # Never persist authentication, environment or raw CLI stderr.
                        continue
                    event = json.loads(line)
                    event_type = event.get('type')
                    received_at=datetime.now(timezone.utc).isoformat()
                    if event_type in {'thread.started','turn.started','turn.completed','turn.failed','error'}:
                        result.diagnostics['events'].append(dict(type=event_type,received_at=received_at))
                        result.diagnostics['last_event_at']=received_at
                    if isinstance(event.get('model'),str) and re.fullmatch(r'[A-Za-z0-9._:/-]{1,120}',event['model']): result.model=event['model']
                    if event_type == 'turn.started':
                        result.accepted = True
                    elif event_type == 'thread.started':
                        result.request_id = str(event.get('thread_id') or '')
                    elif event_type == 'turn.completed':
                        result.raw_usage = event.get('usage') if isinstance(event.get('usage'), dict) else None
                        result.finish_reason = 'stop'
                        break
                    elif event_type in {'turn.failed', 'error'}:
                        result.status = 'failed'
                        detail=event.get('error') or {}
                        code=detail.get('code','') if isinstance(detail,dict) else ''
                        # Persist allowlisted categories only, never raw event messages/stderr.
                        safe_codes={'context_window_exceeded','usage_limit_reached','unauthorized','rate_limit_exceeded','invalid_request','server_error','insufficient_quota','model_not_found'}
                        result.diagnostics['error_category']=code if code in safe_codes else 'cli_task_failed'
                        if code=='unauthorized':
                            from app.core.codex_state import remember
                            remember(self.state_root,connection.cli_path,authenticated=False)
                        result.error = '写作服务返回失败，原稿未改变；'+('已有片段可在改稿与候选查看' if result.text else '未收到正文')
                        result.finish_reason = 'error'
                        self.stop(process)
                        break
                    elif event_type.startswith('item.'):
                        item = event.get('item') or {}
                        if item.get('type') == 'agent_message' and isinstance(item.get('text'), str):
                            item_id = str(item.get('id') or 'message')
                            previous = messages_by_id.get(item_id, '')
                            current = redact(item['text'])
                            if current.startswith(previous):
                                delta = current[len(previous):]
                                if delta:
                                    result.text += delta
                                    on_text(delta)
                            else:
                                result.text += '\n' + current
                                on_text('\n' + current)
                            messages_by_id[item_id] = current
                if result.status not in {'cancelled', 'uncertain', 'failed'} or result.finish_reason == 'stop':
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: self.stop(process)
                    if process.returncode == 0 and result.finish_reason == 'stop' and result.text.strip():
                        result.status = 'completed'
                        from app.core.codex_state import remember
                        remember(self.state_root,connection.cli_path,probe,authenticated=True)
                    elif result.finish_reason != 'error':
                        result.status = 'failed' if process.returncode else 'uncertain'
                        result.error = 'CLI 未返回有效正文及完整完成事件'
                elif result.finish_reason != 'error' and result.status not in {'cancelled','uncertain'}:
                    result.status='uncertain'; result.error='写作服务未返回正文及完整结束事件，结果待确认；未自动重发'
            finally:
                self.stop(process)
                for thread in readers:
                    thread.join(timeout=2)
                result.diagnostics['exit_code']=process.poll()
                result.diagnostics['ended_at']=datetime.now(timezone.utc).isoformat()
        result.elapsed = round(time.monotonic() - started, 3)
        result.usage = normalize_usage('codex', result.raw_usage)
        result.warnings.append('CLI 用量不能换算为人民币；输出长度为软限制')
        return result
