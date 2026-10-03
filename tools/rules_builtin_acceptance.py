"""Isolated rule/navigation acceptance, never accesses production settings or keys."""
import json,os,sys,tempfile,shutil
from pathlib import Path
if '--visible' not in sys.argv: os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication
from app.ui.v2_window import MainWindow
from app.core.services import Workspace
from app.core.selection import Registry,selection
def main():
    app=QApplication([]); checks=[]; folder=ROOT/'docs/evidence/rules_builtin'; folder.mkdir(parents=True,exist_ok=True)
    def check(name,value): checks.append(dict(check=name,passed=bool(value)))
    with tempfile.TemporaryDirectory(prefix='tt_rules_builtin_') as temp:
        root=Path(temp); window=MainWindow(Workspace(root/'data'),ROOT/'resources',root/'prefs/preferences.json'); window.show(); app.processEvents()
        check('five pages and no independent materials navigation',window.pages.count()==5 and window.materials_nav.isHidden()); window.new_work('rewrite'); page=window.creators['rewrite']; page.use_reference('用户原文',dict(name='用户提供',type='粘贴')); work=window.ensure_work(page); work.edit('已有作品'); work.save(); work.store.set_setting('v2_references',[dict(id='old-ref',title='历史资料',text='历史资料',enabled=True)]); work.store.set_setting('v2_rule_overrides',{'R04':{'enabled':True}}); project=work.store.root; window.open_project(project)
        check('old body reference and rule data retained',window.work.text=='已有作品' and window.work.store.setting('v2_references')[0]['text']=='历史资料' and window.work.store.setting('v2_rule_overrides')['R04']['enabled']); window.show_materials(page); app.processEvents(); check('project settings remain inside work page',window.inline is not None and window.materials_page not in [window.pages.widget(i) for i in range(window.pages.count())]); window.close_inline()
        rows=Registry(ROOT/'resources').effective(selection('novel')); check('only hit rules loaded',len(rows)<30 and all(r.get('version') for r in rows)); window.navigate(1); window.grab().save(str(folder/'01-five-pages.png')); window.close(); app.processEvents()
        bad=root/'bad'; bad.mkdir(); (bad/'v2_rules.json').write_text('{bad',encoding='utf-8'); registry=Registry(bad); check('broken rule registry keeps viewing possible',bool(registry.error))
        try: registry.effective(selection('novel'))
        except ValueError as error: blocked='创作规则暂时无法加载' in str(error)
        else: blocked=False
        check('broken rules block generation with Chinese recovery',blocked); shutil.copy(ROOT/'resources/v2_rules.json',bad/'v2_rules.json'); check('retry recovers exact rules',registry.reload() and len(registry.rows)>100)
    result=dict(checks=checks,passed=sum(c['passed'] for c in checks),total=len(checks),paid_calls=0); (folder/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(result,ensure_ascii=True)); return 0 if result['passed']==result['total'] else 1
if __name__=='__main__': raise SystemExit(main())
