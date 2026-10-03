"""Local upgrade recovery point; excludes settings credentials and logs."""
import hashlib,json,sqlite3,subprocess,zipfile
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    folder=ROOT/'backups'/('agent_upgrade_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')); folder.mkdir(parents=True,exist_ok=False)
    files=[]
    with zipfile.ZipFile(folder/'source.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for directory in ['app','resources','tools','tests']:
            for path in sorted((ROOT/directory).rglob('*')):
                if path.is_file() and path.suffix in {'.py','.pyw','.json','.ps1'} and '__pycache__' not in path.parts:
                    archive.write(path,path.relative_to(ROOT)); files.append(dict(path=str(path.relative_to(ROOT)),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        for name in ['requirements.txt','README.md']:
            archive.write(ROOT/name,name)
    databases=[]
    for path in sorted((ROOT/'user_data'/'projects').glob('*/project.sqlite')):
        target=folder/'projects'/path.parent.name/'project.sqlite'; target.parent.mkdir(parents=True)
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as source,sqlite3.connect(target) as destination: source.backup(destination)
        databases.append(str(path.relative_to(ROOT)))
    manifest=dict(version=1,head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),files=files,databases=databases,complete=True)
    (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(dict(path=str(folder),source_files=len(files),project_databases=len(databases)),ensure_ascii=False))
if __name__=='__main__': main()
