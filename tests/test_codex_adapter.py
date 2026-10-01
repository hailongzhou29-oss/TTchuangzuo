import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.providers.codex_text import CodexTextProvider, command_prefix
from app.providers.contracts import CancelToken, Connection

SCRIPT = '''import json, sys, time
sys.stdin.reconfigure(encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')
prompt = sys.stdin.read()
print(json.dumps({'type':'thread.started','thread_id':'fixture-thread'}), flush=True)
print(json.dumps({'type':'turn.started'}), flush=True)
print(json.dumps({'type':'item.updated','item':{'id':'m','type':'agent_message','text':'中文'}}), flush=True)
if 'WAIT_FOR_CANCEL' in prompt: time.sleep(20)
print(json.dumps({'type':'item.completed','item':{'id':'m','type':'agent_message','text':'中文路径通过'}}), flush=True)
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':10,'cached_input_tokens':3,'output_tokens':5}}), flush=True)
'''


class CodexAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='CLI 中文 空格 ')
        self.script = Path(self.temporary.name) / '固定事件.py'
        self.script.write_text(SCRIPT, encoding='utf-8')
        self.prefix = [sys.executable, str(self.script)]
        self.provider = CodexTextProvider()
        self.provider.probes[tuple(self.prefix)] = dict(features=['shell_tool', 'unified_exec', 'apps', 'plugins'])
        self.connection = Connection('fixture', 'CLI 固定事件测试', 'codex', 'fixture-model', timeout=15)

    def tearDown(self):
        self.temporary.cleanup()

    def test_real_subprocess_unicode_jsonl_and_usage(self):
        chunks = []
        with patch('app.providers.codex_text.command_prefix', return_value=self.prefix):
            result = self.provider.generate(self.connection, [{'role': 'user', 'content': '中文、空格和 `$(不会执行)`'}], CancelToken(), chunks.append)
        self.assertEqual(result.status, 'completed')
        self.assertEqual(result.text, '中文路径通过')
        self.assertEqual(''.join(chunks), result.text)
        self.assertEqual(result.usage['input'], 10)
        self.assertEqual(result.usage['cached_read'], 3)

    def test_cancel_terminates_process_and_keeps_partial(self):
        token = CancelToken()
        def cancel_after_text(text):
            token.cancel()
        with patch('app.providers.codex_text.command_prefix', return_value=self.prefix):
            start = time.monotonic()
            result = self.provider.generate(self.connection, [{'role': 'user', 'content': 'WAIT_FOR_CANCEL'}], token, cancel_after_text)
        self.assertLess(time.monotonic() - start, 10)
        self.assertEqual(result.status, 'cancelled')
        self.assertEqual(result.text, '中文')

    def test_strict_manual_path_never_falls_back(self):
        with self.assertRaisesRegex(ValueError, '指定的 Codex 文件不存在'):
            command_prefix(str(Path(self.temporary.name) / '不存在.exe'))

    def test_arguments_disable_tools_and_never_embed_prompt_in_shell(self):
        import subprocess
        actual = subprocess.Popen
        captured = []
        def intercept(args, **kwargs):
            captured.append((args, kwargs))
            return actual(args, **kwargs)
        with patch('app.providers.codex_text.command_prefix', return_value=self.prefix), patch('app.providers.codex_text.subprocess.Popen', side_effect=intercept):
            self.provider.generate(self.connection, [{'role':'user','content':'PRIVATE_PROMPT_不得入参数'}], CancelToken(), schema={'type':'object'})
        args, kwargs = captured[0]
        self.assertNotIn('PRIVATE_PROMPT', ' '.join(args))
        self.assertIn('--ignore-user-config', args)
        self.assertIn('--ignore-rules', args)
        self.assertIn('read-only', args)
        self.assertIn('shell_tool', args)
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', args)
        self.assertFalse(kwargs.get('shell', False))
    def test_image_request_keeps_code_mode_tool_dispatch_without_enabling_shell(self):
        import subprocess
        actual=subprocess.Popen
        captured=[]
        self.provider.probes[tuple(self.prefix)]['features']+=['image_generation','code_mode_host']
        def intercept(args,**kwargs):
            captured.append(args)
            return actual(args,**kwargs)
        with patch('app.providers.codex_text.command_prefix',return_value=self.prefix),patch('app.providers.codex_text.subprocess.Popen',side_effect=intercept):
            self.provider.generate(self.connection,[dict(role='user',content='固定事件测试，不产生图片')],CancelToken(),image_request=True)
        options=list(zip(captured[0],captured[0][1:]))
        self.assertIn(('--enable','code_mode_host'),options)
        self.assertNotIn(('--disable','code_mode_host'),options)
        self.assertIn(('--disable','shell_tool'),options)
        self.assertIn(('--disable','unified_exec'),options)


if __name__ == '__main__':
    unittest.main()
