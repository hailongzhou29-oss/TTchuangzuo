import json
import os
import uuid
from pathlib import Path

from app.core.cover import validate_image
from app.core.files import atomic_write
from app.providers.codex_text import CodexTextProvider
from app.providers.contracts import Connection
from app.providers.image_contracts import ImageResult


class CodexImageProvider:
    def __init__(self, bridge=None, generated_root=None):
        self.bridge = bridge or CodexTextProvider()
        self.generated_root = generated_root or (Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'generated_images')

    def detect(self, connection):
        result = self.bridge.detect(connection.cli_path, login=True)
        result['image_tool_declared'] = 'image_generation' in result['features']
        result['image_generated'] = False
        return result

    def submit(self, connection, secret, snapshot, cancel, references=None, mask=None, output_root=None):
        if snapshot['count'] != 1 or mask:
            raise ValueError('当前 CLI 通道只支持单图生成/参考编辑，不支持蒙版参数')
        settings = Connection(connection.id, connection.name, 'codex', connection.model,
                              cli_path=connection.cli_path, timeout=connection.timeout, max_output=1024)
        schema = {'type': 'object', 'properties': {'image_paths': {'type': 'array', 'items': {'type': 'string'}},
                  'failure_reason':{'type':'string'}},'required':['image_paths','failure_reason'],'additionalProperties':False}
        prompt = '使用内置 $imagegen 生成一张实际栅格图片。不得调用 OPENAI_API_KEY、SDK 或 HTTP API fallback。不得用旧图、SVG或文字回答冒充生成。\n'
        prompt += snapshot['prompt'] + '\n目标画幅：' + snapshot['requested_ratio']
        if snapshot.get('provider_size'):
            prompt += '\n期望原生尺寸：' + snapshot['provider_size'] + '。无原生参数时如实返回实际结果，不后处理冒充。'
        prompt += '\n最终返回 image_paths 路径清单与 failure_reason。成功时 failure_reason 为空；无产物时返回空清单，并说明工具是否缺失及实际失败原因。'
        result = self.bridge.generate(settings, [{'role': 'user', 'content': prompt}], cancel,
            schema=schema, image_request=True, reference_paths=references)
        image_result = ImageResult(status=result.status, request_id=result.request_id, model=connection.model,
            raw_usage=result.raw_usage, accepted=result.accepted, elapsed=result.elapsed, error=result.error)
        def failure(message):
            try:
                decoded=json.loads(result.text)
                reason=decoded.get('failure_reason','') if isinstance(decoded,dict) else ''
                if isinstance(reason,str) and reason:
                    message+='；CLI诊断：'+reason[:1500]
            except (ValueError,TypeError):
                pass
            image_result.status, image_result.error = 'failed', message
            return image_result
        if result.status != 'completed':
            return image_result
        try:
            thread = str(uuid.UUID(result.request_id))
        except (ValueError, TypeError):
            return failure('CLI 未返回可核验的本次会话 ID，未登记图片')
        folder = (self.generated_root / thread).resolve()
        allowed_root = self.generated_root.resolve()
        if not folder.is_relative_to(allowed_root) or not folder.is_dir():
            return failure('CLI 只有文字或未产生本次会话图片，未当成成功')
        files = [path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'}]
        if len(files) != 1:
            return failure(f'本次会话应有1张图片，实际{len(files)}张；未扫描其他目录或自动重发')
        path = files[0].resolve()
        if path.parent != folder or path.stat().st_mtime + 2 < snapshot['submitted_timestamp']:
            return failure('图片不属于本次新任务或为旧产物，未登记')
        image = validate_image(path)
        if output_root is None:
            raise ValueError('缺少本次项目任务沙箱')
        target = Path(output_root) / ('generated' + path.suffix.lower())
        atomic_write(target, path.read_bytes())
        image_result.status = 'generated'
        image_result.items = [dict(path=str(target), width=image.width(), height=image.height())]
        image_result.warnings.append('CLI 宿主模型与内置图模型分别记录；本通道可能消耗套餐额度，不承诺免费')
        return image_result
