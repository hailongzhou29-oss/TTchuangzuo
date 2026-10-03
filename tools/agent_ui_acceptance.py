"""Native assistant candidate UI, using clearly marked simulated responses."""
import base64,json,os,sys,tempfile,time
from pathlib import Path
if '--visible' not in sys.argv: os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication,QPushButton
from PySide6.QtCore import QBuffer,QIODevice
from PySide6.QtGui import QImage,QColor
from app.ui.v2_window import MainWindow
from app.ui.cover_panel import CoverPanel
from app.core.services import Workspace
from app.core.agent_candidates import AgentCandidates
from app.providers.contracts import Connection,TextResult
from app.providers.image_contracts import ImageConnection,ImageResult

class ImageProvider:
    calls=0
    def submit(self,c,secret,snapshot,cancel,**options):
        self.calls+=1; self.prompt=snapshot['prompt']; image=QImage(64,96,QImage.Format.Format_RGB32); image.fill(QColor('#758da4')); buffer=QBuffer(); buffer.open(QIODevice.OpenModeFlag.WriteOnly); image.save(buffer,'PNG'); return ImageResult(status='generated',items=[dict(b64_json=base64.b64encode(bytes(buffer.data())).decode())],accepted=True,model=c.model)
    def bytes_for(self,item,c,cancel): return base64.b64decode(item['b64_json'])

class Provider:
    calls=0
    def generate(self,c,secret,messages,cancel,on_text,**options):
        self.calls+=1; text=json.dumps(dict(text='林宁握紧旧信，说：“我会留下。”\n结尾保持。',explanation='模拟输出：加强人物决心，保留结尾。'),ensure_ascii=False); on_text(text); return TextResult(text=text,status='completed',model=c.model,accepted=True)

def main():
    app=QApplication([]); out=ROOT/'docs/evidence'/('agent_ui' if '--visible' in sys.argv else 'agent_ui_offscreen'); out.mkdir(parents=True,exist_ok=True); checks=[]
    def check(name,value): checks.append(dict(check=name,passed=bool(value)))
    def spin(ms=90):
        end=time.monotonic()+ms/1000
        while time.monotonic()<end: app.processEvents(); time.sleep(.01)
    with tempfile.TemporaryDirectory(prefix='tt_agent_ui_') as temp:
        root=Path(temp); window=MainWindow(Workspace(root/'data'),ROOT/'resources',root/'prefs/preferences.json'); window.allow_test_connections=True; window.text_test_provider=Provider(); c=Connection('ui_fixture','隔离测试（模拟）','deepseek','fixture-only',base_url='https://example.org',context_limit=65536,max_output=8192,verification=dict(development_test=True)); window.connections.save(c); window.options['default_connection']=c.id; window.assistant.refresh_models(); window.show(); window.new_work('novel'); spin(); page=window.creators['novel']; work=window.ensure_work(page); base='林宁把旧信收好，迟疑着要不要离开。\n结尾保持。'; work.edit(base); work.save(); window.replace_editor(page,base); page.set_view(1); window.set_assistant_visible(True); spin()
        window.chat_request('修改当前正文，让人物更狠，结尾不改'); deadline=time.monotonic()+8
        while window.active_task and time.monotonic()<deadline: spin(30)
        check('assistant completes without UI deadlock',window.active_task is None); pending=AgentCandidates(work.store).pending(); check('response becomes candidate without replacing body',len(pending)==1 and work.text==base); window.grab().save(str(out/'01-candidate-assistant.png')); cid=pending[0]['id']; window.show_agent_candidate(cid); spin(); window.grab().save(str(out/'02-compare.png'))
        action=next(b for b in window.inline.findChildren(QPushButton) if b.text()=='采用修改'); action.click(); spin(); check('explicit adoption changes only current document','我会留下' in work.text and work.text.endswith('结尾保持。')); window.grab().save(str(out/'03-adopted.png')); window.undo_agent_candidate(cid); spin(); check('undo restores exact original',work.text==base)
        window.assistant.input.setPlainText('未发送中文长输入保留'); width=window.assistant_width
        for _ in range(5): window.toggle_assistant(); spin(25); window.toggle_assistant(); spin(25)
        check('repeated collapse preserves input and restored width',window.assistant.input.toPlainText()=='未发送中文长输入保留' and abs(window.assistant.width()-width)<45); window.navigate(0); window.navigate(2); spin(); check('page round trip preserves body',window.work.text==base); window.grab().save(str(out/'04-restored.png'))
        panel=CoverPanel(window,work); window.show_inline('作品封面',panel); spin(); check('cover prompt editable meaningful and unpaid',panel.prompt.isVisible() and not panel.prompt.isReadOnly() and '旧信' in panel.prompt.toPlainText() and '构图' in panel.prompt.toPlainText() and window.active_image_task is None); window.grab().save(str(out/'05-cover-prompt.png')); window.close_inline()
        image_provider=ImageProvider(); window.image_test_provider=image_provider; image_c=ImageConnection('fixture-image','隔离图片测试（模拟）','image_http','fixture-image',base_url='https://example.org',sizes=('1024x1536',)); window.image_connections.save(image_c,'fixture-image-test'); window.options['default_image']=image_c.id; panel=CoverPanel(window,work); window.show_inline('作品封面',panel); spin(); panel.generate(); deadline=time.monotonic()+8
        while window.active_image_task and time.monotonic()<deadline: spin(30)
        check('simulated image is decoded before preview',bool(panel.candidate) and panel.candidate.get('width')==64 and panel.candidate.get('height')==96 and panel.adopt_button.isVisible()); check('simulated image does not mark real model capability',not window.image_connections.get(image_c.id).verification.get('image_generation')); panel.adopt(); spin(); cover=next(c for c in work.store.covers() if c['id']==work.store.setting('active_cover'))['spec']; check('adopted cover retains prompt pixels task and hashes',cover['actual_pixels']==[64,96] and bool(cover['file_hash']) and bool(cover['source_hash']) and bool(cover['task_id']) and (work.store.root/cover['image']).is_file()); old_cover=work.store.setting('active_cover'); panel=CoverPanel(window,work); window.show_inline('作品封面',panel); spin(); check('opening new candidate retains old adopted cover',work.store.setting('active_cover')==old_cover); window.close_inline(); window.resize(800,650); spin(); window.grab().save(str(out/'06-narrow-assistant.png')); check('narrow assistant is accessible',window.assistant_toggle.isVisible()); window.close(); spin()
    result=dict(checks=checks,passed=sum(c['passed'] for c in checks),total=len(checks),paid_calls=0,network_calls=0,login_calls=0,model='simulated',physical_dpr=app.primaryScreen().devicePixelRatio()); (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(result,ensure_ascii=True)); return int(result['passed']!=result['total'])
if __name__=='__main__': raise SystemExit(main())
