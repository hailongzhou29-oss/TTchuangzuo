"""Test writes never reach production preferences, credentials or projects."""
import os,sys
from pathlib import Path

def within(path,root):
    path,root=Path(path).resolve(),Path(root).resolve()
    return path==root or path.is_relative_to(root)

def test_process():
    if os.environ.get('TT_CREATOR_TEST_MODE')=='1': return True
    entry=Path(sys.argv[0]).resolve()
    return entry.parent==Path(__file__).resolve().parents[2]/'tools' and any(x in entry.stem for x in ('test','acceptance','upgrade','live','fixture'))

def guard_test_write(path):
    if not test_process(): return
    project=Path(__file__).resolve().parents[2]
    production=Path(os.environ.get('LOCALAPPDATA',str(project/'user_data')))/'TTChuangzuo'
    if within(path,production) or within(path,project/'user_data'):
        raise PermissionError('测试禁止写入生产配置、凭据或用户项目；请选择隔离测试目录')
    allowed=os.environ.get('TT_CREATOR_TEST_ROOT')
    if allowed and not within(path,allowed):
        raise PermissionError('测试写入超出本轮隔离目录，未修改目标')

def start_test_runtime(root):
    root=Path(root).resolve()
    os.environ['TT_CREATOR_TEST_MODE']='1'
    os.environ['TT_CREATOR_TEST_ROOT']=str(root)
    guard_test_write(root)
    root.mkdir(parents=True,exist_ok=True)
    return root

def legacy_test_profile(connection):
    provenance=(connection.name=='DeepSeek 软件通道实测' or (connection.name=='DeepSeek'
                and connection.model=='deepseek-flash' and connection.context_limit==32768
                and connection.verification.get('auth_models',{}).get('checked')=='2026-10-01T01:26:43.472494+00:00'
                and connection.verification.get('text_generation',{}).get('checked')=='2026-10-01T01:26:50+00:00'))
    return (connection.id=='live_deepseek' and provenance
            and connection.provider=='deepseek' and connection.base_url.rstrip('/')=='https://api.deepseek.com'
            and connection.max_output==128 and connection.timeout==60 and connection.reasoning_levels==('none',) and connection.output_mode=='manual')
