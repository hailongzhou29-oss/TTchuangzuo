"""Native isolated TT settings acceptance. No network, login or production keys."""
import json,os,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
if '--visible' not in sys.argv: os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication,QGroupBox
from app.ui.v2_window import MainWindow
from app.core.services import Workspace
from app.providers.contracts import Connection
from app.providers.image_contracts import ImageConnection
from app.storage.connections import ConnectionStore
from app.core.settings_controller import site_id

def main():
    app=QApplication([]); checks=[]; out=ROOT/'docs/evidence'/('settings_reuse' if '--visible' in sys.argv else 'settings_reuse_offscreen'); out.mkdir(parents=True,exist_ok=True)
    def check(name,value): checks.append(dict(check=name,passed=bool(value)))
    def spin():
        for _ in range(8): app.processEvents(); time.sleep(.015)
    with tempfile.TemporaryDirectory(prefix='tt_settings_reuse_') as temp:
        root=Path(temp); window=MainWindow(Workspace(root/'data'),ROOT/'resources',root/'prefs/preferences.json'); window.show(); window.navigate(4); spin(); page=window.settings
        check('TT three forms plus advanced',[page.tabs.tabText(i) for i in range(4)]==['国内模型','Codex 本地','通用图片API','高级设置'] and page.tabs.count()==4)
        original_default=window.options.get('default_connection'); ds=page.forms['deepseek_official']; ds[2].lineEdit().setText('fixture-model-ds'); page.save_current_channel('deepseek_official')
        check('save DS without switching default',page.c.channel_configs['deepseek_official'].model=='fixture-model-ds' and window.options.get('default_connection')==original_default)
        page.provider_list.setCurrentRow(2); qwen=page.forms['aliyun_bailian']; qwen[2].lineEdit().setText('fixture-model-qwen'); page.save_current_channel('aliyun_bailian'); page.provider_list.setCurrentRow(1)
        check('platform values independent',ds[2].model_value()=='fixture-model-ds' and page.c.channel_configs['aliyun_bailian'].model=='fixture-model-qwen')
        ds[2].lineEdit().setText('unsaved-model'); page.activate_current_model(); check('dirty activation blocked',window.options.get('default_connection')==original_default and '先保存' in page.status.text()); ds[2].lineEdit().setText('fixture-model-ds'); page.activate_current_model(); check('explicit saved activation',window.options.get('default_connection')==page.c.channel_configs['deepseek_official'].id)
        with patch.object(page.c,'list_models',side_effect=ValueError('模拟列表不可用')):
            page.load_models('deepseek_official')
            deadline=time.monotonic()+3
            while page.operations and time.monotonic()<deadline: app.processEvents(); time.sleep(.02)
        check('failed list retains manually entered model',ds[2].model_value()=='fixture-model-ds' and '可继续手填' in page.status.text()); page.save_current_channel('deepseek_official')
        page.tabs.setCurrentIndex(1); spin(); page.codex_model.clear(); page.save_codex_model_settings(); check('Codex default model allowed',page.c.saved(page.c.channel_configs['codex_local']) is not None and not page.c.channel_configs['codex_local'].model)
        check('four Codex cards',all(any(b.title()==name for b in page.codex_tab.findChildren(QGroupBox)) for name in ['Codex 状态','图片生成渠道','本地运行','能力检测']))
        cap=page.c.codex_image_capability(dict(available=True,authenticated=False,features=['image_generation'])); check('unlogged image feature not usable',cap['skillPresent'] and not cap['ready'] and not cap['lastSuccessAt'])
        cap=page.c.codex_image_capability(dict(available=True,authenticated=True,features=['image_generation'])); check('discovery does not claim real image success',cap['ready'] and not cap['lastSuccessAt'])
        # These tokens are generated fixtures in a disposable product vault.
        foreign=ConnectionStore(root/'other_product'); fc=Connection('foreign','别的软件','deepseek','model',base_url='https://example.org'); foreign.save(fc,'fixture-other'); foreign_bytes=foreign.vault.path.read_bytes()
        c=page.c; values=c.openai_image_settings(); values.update(baseUrl='https://first.example.org/v1',modelId='fixture-image-a',manualSize='1024x1536',unitPrices={'1K':1.2},pricingEnabled=True)
        first=c.save_openai_image_settings(values,'fixture-a'); values.update(baseUrl='https://second.example.org/v1',modelId='fixture-image-b',manualSize='1536x1024',unitPrices={'1K':2.4}); second=c.save_openai_image_settings(values,'fixture-b')
        check('image saving does not activate',window.options.get('default_image') is None)
        restored=c.activate_openai_image_site(first['siteId']); first_c=window.image_connections.get('image_site_'+first['siteId']); second_c=window.image_connections.get('image_site_'+second['siteId'])
        check('independent site parameters and prices',restored['modelId']=='fixture-image-a' and restored['unitPrices']['1K']==1.2 and first_c.sizes==('1024x1536',) and second_c.sizes==('1536x1024',))
        check('site secrets isolated',window.image_connections.secret_snapshot(first_c)=='fixture-a' and window.image_connections.secret_snapshot(second_c)=='fixture-b')
        c.activate_openai_image_site(second['siteId']); check('old connection snapshot retains original site',first_c.base_url=='https://first.example.org/v1' and window.image_connections.secret_snapshot(first_c)=='fixture-a')
        page.tabs.setCurrentIndex(0); page.provider_list.setCurrentRow(1); spin(); page.status.clear(); window.grab().save(str(out/'01-domestic.png')); page.tabs.setCurrentIndex(1); spin(); window.grab().save(str(out/'02-codex.png'))
        page.refresh_openai_image_sites_ui(); page.tabs.setCurrentIndex(2); page.activate_openai_image_site_ui(page.openai_image_site_selector.findData(second['siteId'])); spin(); window.grab().save(str(out/'03-images.png'))
        active_image=window.options['default_image']; page.openai_image_model.lineEdit().setText('not-saved'); page.set_active_image_provider_ui('openai_compatible'); check('dirty image activation is blocked',window.options['default_image']==active_image and '先保存' in page.status.text()); page.openai_image_model.lineEdit().setText('fixture-image-b')
        window.resize(800,650); spin(); window.grab().save(str(out/'04-narrow.png')); check('narrow window remains responsive',window.width()==800 and page.tabs.isVisible())
        c.clear_all_keys(); check('clearing keys is product isolated',not window.connections.vault.path.exists() and foreign.vault.path.read_bytes()==foreign_bytes and not c.openai_image_key_status('openai_images_v1',first['baseUrl'])['saved'])
        changed=Connection('changed','测试','deepseek','old',base_url='https://example.org',verification={'success':True},capability_status='已验证'); window.connections.save(changed); changed=window.connections.get('changed'); from dataclasses import replace
        window.connections.save(replace(changed,model='new')); check('model change invalidates verified capabilities',not window.connections.get('changed').verification)
        window.close(); spin()
    result=dict(checks=checks,passed=sum(c['passed'] for c in checks),total=len(checks),paid_calls=0,network_calls=0,login_calls=0,qt_platform=app.platformName(),dpr=app.primaryScreen().devicePixelRatio()); (out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(result,ensure_ascii=True)); return int(result['passed']!=result['total'])
if __name__=='__main__': raise SystemExit(main())
