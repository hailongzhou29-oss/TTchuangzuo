"""Isolated native checks for script conflict preservation and unavailable catalog recovery."""
import copy
import os
if os.environ.get('TT_UI_VISIBLE_TEST')!='1': os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import sys
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication,QPushButton,QFileDialog
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from unittest.mock import patch
from app.core import script_settings as settings
from app.core.files import write_json
from app.core.services import Workspace
from app.core.speech_records import THIRD,payload,verify
from app.ui.v2_window import MainWindow

def main():
    app=QApplication([]); checks=[]; evidence=ROOT/'docs/evidence'/('script_safety_'+app.platformName()); evidence.mkdir(parents=True,exist_ok=True)
    def check(name,condition):
        checks.append(dict(check=name,passed=bool(condition)))
        if not condition: print('FAIL',name)
    def settle(): app.processEvents(); QTest.qWait(70); app.processEvents()
    def click(window,text):
        target=next(b for b in window.inline.findChildren(QPushButton) if b.text()==text)
        QTest.mouseClick(target,Qt.MouseButton.LeftButton); settle()
    with tempfile.TemporaryDirectory(prefix='tt_script_safety_ui_') as temp:
        root=Path(temp); prefs=root/'settings/preferences.json'; write_json(prefs,dict(restore_last=False,autosave=False))
        window=MainWindow(Workspace(root/'data'),ROOT/'resources',prefs); window.show(); window.new_work('script'); settle()
        page=window.creators['script']; work=window.ensure_work(page)
        generated=payload(dict(title='手改保存验证',outline='角色作出选择。',scenes=[dict(title='门口',nodes=[dict(type='dialogue',speaker='阿宁',text='原句。')])]),work.config)
        work.edit(generated['text']); work.save(); work.store.set_setting('v2_speech:'+work.document_id,dict(revision=work.revision,records=generated['speech_records']))
        window.replace_editor(page,work.text); page.set_view(1)
        base,third=work.text.split(THIRD,1); text=base.replace('原句。','正文手改。')+THIRD+third.replace('原句。','台词手改。')
        page.editor.setPlainText(text); window.save_work(); settle()
        check('both manual edits persist complete revision',work.text==text and work.store.document(work.document_id)['text']==text)
        check('both edits marked unresolved',work.store.setting('v2_third_unsynced:'+work.document_id))
        window.show_speech_conflict(); settle(); window.grab().save(str(evidence/'conflict-choice.png'))
        click(window,'先保留草稿'); check('keep draft does not resolve or erase',work.text==text and work.store.setting('v2_third_unsynced:'+work.document_id))
        window.show_speech_conflict(); window.close_inline(); settle(); check('cancel processing retains whole text',work.text==text)
        path=work.store.root; did=work.document_id; window.close(); settle()
        window=MainWindow(Workspace(root/'data'),ROOT/'resources',prefs); window.show(); window.open_project(path); settle(); page=window.creators['script']; work=window.work
        check('restart restores unresolved full text',work.text==text and work.store.setting('v2_third_unsynced:'+did))
        check('restart shows processing notice','尚未对应' in page.banner.text())
        page.editor.setPlainText(work.text.replace('正文手改。','正文再次手改。')); window.save_work(); text=work.text
        check('later body edit keeps existing third draft','台词手改。' in text and work.store.setting('v2_third_unsynced:'+did))
        with patch.object(QFileDialog,'getSaveFileName',return_value=(str(root/'blocked.md'),'')):
            try: window.export_work('md')
            except ValueError: blocked=True
            else: blocked=False
        check('unresolved draft blocks complete export',blocked and not (root/'blocked.md').exists())
        window.show_speech_conflict(); click(window,'保留正文并重建台词'); verify(work.text)
        check('explicit rebuild syncs current body','正文再次手改。' in work.text.split(THIRD,1)[1] and not work.store.setting('v2_third_unsynced:'+did))
        check('explicit rebuild preserves exact full draft',work.store.setting('v2_third_draft:'+did)['text']==text and any(r['text']==text for r in work.store.revisions(did)))
        page.set_view(0); settle(); form=page.script_form; form.set_value('genre','G04'); form.changed('genre'); form.set_value('subgenres',['G04.1']); form.changed('subgenres')
        selected=copy.deepcopy(page.read_config()['script_settings']); current=work.text; original=settings.CATALOG_PATH
        with patch.object(settings,'CATALOG_PATH',root/'cached-missing.json'):
            settings.reload_catalog(); form.reflow(); settle()
            check('cached catalog failure preserves selected IDs',page.read_config()['script_settings']==selected)
            form.reset_tab(); check('unavailable reset cannot erase selections',page.read_config()['script_settings']==selected)
            check('cached failure disables custom and narrative controls',not form.fields['narrative'].isEnabled() and all(not w.isEnabled() for w in form.custom.values()))
            settings.CATALOG_PATH.write_bytes(original.read_bytes()); QTest.mouseClick(form.catalog_retry,Qt.MouseButton.LeftButton); settle()
            check('cached retry restores original selected IDs',page.read_config()['script_settings']==selected and form.value('genre')=='G04' and form.value('subgenres')==['G04.1'])
            check('cached retry never changes current document',work.text==current and page.editor.toPlainText()==current)
        settings.reload_catalog()
        window.close(); settle()
        original=settings.CATALOG_PATH; original_groups=copy.deepcopy(settings.CATALOG)
        try:
            # Leave the real source file untouched; emulate first-load failure with empty field shells.
            for index,(kind,content) in enumerate([('missing',None),('damaged','{bad'),('empty','{"groups":{}}')]):
                settings.CATALOG_PATH=root/(kind+'.json')
                if content is not None: settings.CATALOG_PATH.write_text(content,encoding='utf-8')
                settings.CATALOG.clear(); settings.CATALOG.update({k:dict(g,rows=[]) for k,g in original_groups.items()}); settings.BY_ID.clear(); settings.reload_catalog()
                prefs=root/kind/'settings/preferences.json'; write_json(prefs,dict(restore_last=False,autosave=False))
                window=MainWindow(Workspace(root/kind/'data'),ROOT/'resources',prefs); window.show(); window.new_work('script'); settle(); page=window.creators['script']; form=page.script_form
                check(kind+' startup remains usable',window.isVisible() and settings.CATALOG_STATE['kind']==kind)
                check(kind+' visible error distinct from auto',form.catalog_error.isVisible() and '规则' in form.catalog_message.text() and form.fields['genre'].currentText()=='规则目录不可用')
                check(kind+' generation disabled safely',not page.generate_button.isEnabled())
                page.idea.setPlainText('失败期间继续保留的创作想法'); page.editor.setPlainText('失败期间保留的用户正文'); window.ensure_work(page); window.save_work(); current=window.work.text
                QTest.mouseClick(form.catalog_retry,Qt.MouseButton.LeftButton); settle()
                check(kind+' failed retry preserves text',window.work.text==current and form.catalog_error.isVisible())
                window.grab().save(str(evidence/('catalog-'+kind+'.png')))
                settings.CATALOG_PATH.write_bytes(original.read_bytes()); QTest.mouseClick(form.catalog_retry,Qt.MouseButton.LeftButton); settle()
                check(kind+' successful retry restores menu',not form.catalog_error.isVisible() and page.generate_button.isEnabled() and form.fields['genre'].count()>24)
                check(kind+' successful retry keeps idea and editor',page.idea.toPlainText()=='失败期间继续保留的创作想法' and page.editor.toPlainText()==current and window.work.text==current)
                window.close(); settle()
        finally: settings.CATALOG_PATH=original; settings.reload_catalog()
    (evidence/'results.json').write_text(json.dumps(dict(mode='native Qt; temporary data; no provider calls',checks=checks),ensure_ascii=False,indent=2),encoding='utf-8')
    passed=sum(c['passed'] for c in checks); print(f'{passed}/{len(checks)} safety UI checks passed; {evidence}')
    return 0 if passed==len(checks) else 1

if __name__=='__main__': raise SystemExit(main())
