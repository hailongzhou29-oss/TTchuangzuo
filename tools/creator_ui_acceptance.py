"""AI-first creation via actual UI/service stages; only isolated fixed responses."""
import json,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from app.core.services import Workspace
from app.core.writing import WritingService
from app.core.knowledge import FactService
from app.providers.contracts import Connection,TextResult
from app.providers.image_contracts import ImageConnection
from app.ui.window import MainWindow
from app.ui.model_settings import SettingsDialog
from app.ui.image_settings import ImageSettingsPage

app=QApplication([])
checks=[]
def check(name,value):
    checks.append(dict(check=name,passed=bool(value)))
class Fixture:
    def generate(self,connection,secret,messages,cancel,on_text,**options):
        keys=options['schema']['properties']
        if 'premise' in keys:
            value=dict(premise='老师与学生寻找丢失的地图。',protagonist_goal='找到地图',obstacle='旧记录缺失',turn='地图一直在教室里',ending_direction='共同核对证据',characters=[dict(name='老师',description='谨慎的历史教师'),dict(name='学生',description='善于观察的学生')])
        elif 'nodes' in keys:
            value=dict(nodes=[dict(node_id='N1',title='失踪的地图',purpose='人物开始寻找',events=['发现记录缺失','询问老师','找到线索'],dependencies=[])])
        else:
            context=json.loads(messages[1]['content'].split('\n',1)[1])
            eid=next(entity['id'] for entity in context['entities'] if entity['name']=='老师')
            value=dict(title='失踪的地图',outline='老师和学生通过证据找到地图。',scenes=[dict(scene_id='S1',location='教室',time_of_day='日',interior_exterior='内',estimated_seconds=15,duration_status='estimated',blocks=[dict(block_id='A1',kind='action',text='老师打开柜子。',order=0),dict(block_id='D1',kind='dialogue',speaker_id=eid,text='先看这条记录。',order=1)])])
        text=json.dumps(value,ensure_ascii=False)
        on_text(text)
        return TextResult(text=text,status='completed',finish_reason='stop',model=connection.model)

with tempfile.TemporaryDirectory(prefix='TT AI创作主流程 ') as temporary:
    root=Path(temporary)
    window=MainWindow(Workspace(root/'data'),ROOT/'resources',root/'settings'/'preferences.json')
    window.connections.save(Connection('fixture','固定响应验证','deepseek','fixture',base_url='https://example.invalid'),'fixture-only-key')
    window.image_connections.save(ImageConnection('cli','Codex生图','image_codex','fixture',cli_path='fixture.cmd'))
    window.refresh_models()
    window.show()
    window.navigation.setCurrentRow(2)
    page=window.creator_page
    check('进入剧本栏目直接显示AI创作和赛道',window.pages.currentWidget()==page and page.track_list.count()==5)
    check('赛道显示可直接查看的核心规则正文',len(page.core_rule.toPlainText())>200 and '输出' in page.core_rule.toPlainText())
    page.direction.clear()
    original=window.start_text_task
    def dispatch(**kwargs):
        original(provider=Fixture(),**kwargs)
    window.start_text_task=dispatch
    for stage,label in [('idea_generate','AI方案'),('outline_generate','AI大纲'),('write','AI剧本')]:
        page.generate(stage)
        check(label+'提交前不要求手写原稿',window.store.document(window.document_id)['text']=='')
        active=window.active_task
        snapshot=active['snapshot']
        check(label+'请求带入所选赛道核心规则',any(rule['rule_id']=='CR_S01' and '场次规则' in rule['body'] for rule in snapshot['rule_snapshot']))
        deadline=time.monotonic()+5
        while window.active_task and time.monotonic()<deadline:
            QTest.qWait(25)
        check(label+'结果在主创作页出现并可确认',page.confirm.isEnabled() and bool(page.result.toPlainText()))
        page.confirm_result()
        if stage=='idea_generate':
            check('确认AI方案后自动登记人物，用户无需建表',{entity['name'] for entity in FactService(window.store).entities()}=={'老师','学生'})
    check('完整AI剧本采用后成为可保存正文','老师：先看这条记录。' in window.store.document(window.document_id)['text'])
    settings=SettingsDialog(window)
    settings.show()
    check('模型设置前台只有文字图片Codex外观和高级五页',[settings.tabs.tabText(i) for i in range(settings.tabs.count())]==['文字模型','图片模型','Codex CLI','外观','高级'])
    check('文字模型技术参数默认收起',not settings.advanced.isVisible())
    image=settings.findChild(ImageSettingsPage)
    check('打开图片设置自动载入已有连接而不显示空表单',image.current_id=='cli' and image.provider.currentData()=='image_codex' and image.model.text()=='fixture')
    check('Codex生图不显示无关API密钥和地址字段',image.key.isHidden() and image.base.isHidden())
    settings.tabs.setCurrentIndex(1)
    QTest.qWait(50)
    settings.grab().save(str(ROOT/'docs/evidence/ui_简化模型设置.png'))
    settings.close()
    window.pages.setCurrentWidget(page)
    window.grab().save(str(ROOT/'docs/evidence/ui_AI创作赛道与规则.png'))
    window.close()
evidence=ROOT/'docs/evidence/creator_ui_results.json'
evidence.write_text(json.dumps(dict(mode='隔离固定响应，未请求真实创作模型',checks=checks),ensure_ascii=False,indent=2),encoding='utf-8')
for result in checks:
    print(('PASS ' if result['passed'] else 'FAIL ')+result['check'])
if not all(result['passed'] for result in checks):
    raise SystemExit(1)
