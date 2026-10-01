"""Action scope records; handler return never implies full acceptance success."""
from app.core.files import digest
from app.storage.project import new_id,now

METHOD_IDS={'new_project':'P01','import_file':'P02','continue_project':'P03','toggle_project_view':'P05','copy_project':'P06',
 'rename_project':'P07','archive_project':'P08','trash_project':'P09','backup_project':'P10','restore_backup':'P10',
 'new_document':'S08','toggle_outline_lock':'S10','confirm_draft':'S12','save':'E01','find_dialog':'E03',
 'annotation':'E08','lock_selection':'E09','validate':'E12','versions':'E13','export':'E14','enter_focus':'E15',
 'review_candidate':'E16','reference_info':'R02','compare_source':'R08','similarity_check':'R09','branch':'A01',
 'new_inspiration':'I01','research_public':'I02','open_knowledge':'D01','edit_selected_rule':'D04','restore_rule_base':'D07',
 'start_text_task':'C01','stop_text_task':'C02','regenerate_task':'C03','continue_unfinished':'C04','quote_to_document':'C05',
 'view_context':'C08','task_history':'C09','new_chat':'C10','pin_documents':'C07','change_theme':'K15',
 'restore_layout_defaults':'K16','start_automatic_backup':'K18','clear_analysis_cache':'K19','export_diagnostics':'K20','open_cover':'F01'}
FEE_M={'C01','C03','C04','D06','S06','S07'}

def action_id(function):
    return METHOD_IDS.get(getattr(function,'__name__',''))

_DEFAULT=object()

def freeze(owner,code,label,*,store=_DEFAULT):
    store=owner.store if store is _DEFAULT else store
    project=store.metadata()['id'] if store else None
    document=store.document(owner.document_id) if store is owner.store and store and owner.document_id else None
    text=owner.editor.toPlainText() if document and hasattr(owner,'editor') else ''
    selected=owner.editor.textCursor().selectedText() if document and hasattr(owner,'editor') else ''
    return dict(operation_id=new_id(),action_id=code,label=label,scope=dict(project_id=project,document_id=document['id'] if document else None),
      input_snapshot=dict(base_revision=document['head'] if document else None,text_hash=digest(text),selected_hash=digest(selected)),
      fee_type='M' if code in FEE_M else 'W' if code=='I02' else 'L',result_location='所属项目或当前控件',
      undo='版本/回收区/界面撤销；付费请求不保证退费',created=now())

def record(owner,snapshot,state,error_code=None,*,store=_DEFAULT):
    store=owner.store if store is _DEFAULT else store
    if not store:
        return
    project_id=store.metadata()['id']
    if snapshot['scope']['project_id'] not in {None,project_id}:
        raise ValueError('操作记录所属项目与冻结范围不一致，未写入')
    snapshot=dict(snapshot,result_project_id=project_id)
    import json
    with store.connection(write=True) as con:
        con.execute('CREATE TABLE IF NOT EXISTS action_operations(id TEXT PRIMARY KEY,action_id TEXT NOT NULL,snapshot TEXT NOT NULL,state TEXT NOT NULL,error_code TEXT,created TEXT NOT NULL)')
        con.execute('INSERT INTO action_operations VALUES(?,?,?,?,?,?)',(snapshot['operation_id'],snapshot['action_id'],json.dumps(snapshot,ensure_ascii=False),state,error_code,snapshot['created']))
