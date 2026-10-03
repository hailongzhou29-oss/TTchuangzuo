"""Extract approved TT widgets/functions, not its application/controller.

Input must be the verified fixed-commit pages.py; output preserves source layout.
"""
import ast,json,hashlib,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    source=Path(sys.argv[1]).read_text(encoding='utf-8'); tree=ast.parse(source); lines=source.splitlines(); cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ModelSettingsPage'); methods={n.name:n for n in cls.body if isinstance(n,ast.FunctionDef)}
    selected=['_build_codex_tab','toggle_codex_advanced','detect_codex_ui','choose_codex_command','save_codex_command','clear_codex_command','save_current_channel','save_codex_model_settings','channel_form_is_dirty','activate_current_model','current_provider','provider_changed','update_provider_tab_labels','_build_openai_image_settings_tab','_set_openai_image_size_choices','_set_openai_image_ratios','_set_openai_image_quality_choices','_render_openai_image_capability','refresh_openai_image_manual_summary']
    search=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='SearchableModelCombo'); parts=['\n'.join(lines[search.lineno-1:search.end_lineno])]; manifest=[]
    for name in selected:
        n=methods[name]; code='\n'.join(lines[n.lineno-1:n.end_lineno]); manifest.append(dict(function=name,sha256=hashlib.sha256(code.encode()).hexdigest())); adapted=code.replace('尚未由 TT 验证','尚未由本软件验证').replace('TT 历史成功记录','本软件历史成功记录')
        if name=='save_current_channel': adapted=adapted.replace('self.info("设置已保存", f"{MODEL_CHANNEL_LABELS[key]}接口设置已独立保存{state}；密钥已使用 Windows 加密保存。")','secret_state="密钥已使用 Windows 加密保存。" if self.c.model_key_status(key)["saved"] else "尚未保存接口密钥。"\n            self.info("设置已保存", f"{MODEL_CHANNEL_LABELS[key]}接口设置已独立保存{state}；{secret_state}")')
        parts.append(adapted)
    header='''"""Selected TT-YingXu 8f80b197 widgets; original build functions with a local adapter."""
from PySide6.QtCore import Qt,QSize,QTimer,QUrl
from PySide6.QtGui import QStandardItem,QStandardItemModel,QDesktopServices
from PySide6.QtWidgets import *
from app.core.settings_controller import MODEL_CHANNEL_KEYS,MODEL_CHANNEL_LABELS,MODEL_DEFAULT_BASE,MODEL_KEY_URLS,MODEL_PRESETS
def set_status_tone(widget,tone): widget.setProperty('statusTone',tone)
'''
    output=header+parts[0]+'\n\nclass TTSettingsWidgets:\n'+'\n\n'.join(parts[1:])+'\n'; (ROOT/'app/ui/tt_settings_widgets.py').write_text(output,encoding='utf-8'); (ROOT/'docs/TT设置迁移_来源函数.json').write_text(json.dumps(dict(commit='8f80b197e66c61f16c19596c0da5fcdc642017ee',source_sha='15e70a336353cb1376a9c5f76e9c532125f17c8c',functions=manifest),ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__': main()
