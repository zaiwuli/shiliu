"""Collector-owned persistence. The external article table is never written here."""
import os,json,sqlite3,hashlib,zipfile
from pathlib import Path
from datetime import datetime,timezone,timedelta
from contextlib import closing
from sqlalchemy import delete
from app.core.config import data_path,config_manager
from app.core.database import session_scope
from app.models import Config,PushRecord,RuntimeLog,RecoveryRecord

def get_config(key,default=None):
 with session_scope() as db:
  row=db.get(Config,key)
  return dict(row.content) if row else default

def set_config(key,content):
 with session_scope() as db:
  row=db.get(Config,key)
  if row:row.content=content
  else:db.add(Config(key=key,content=content))

MIGRATION_KEY="_".join(("local","storage","migration","v1"))

def migrate_local_storage():
 root=Path(data_path)
 sources={}
 def remember(path):sources[str(path.relative_to(root))]=hashlib.sha256(path.read_bytes()).hexdigest()
 # One transaction + a marker makes re-running after upgrades idempotent.
 with session_scope() as db:
  if db.bind.dialect.name=='postgresql':
   from sqlalchemy import text
   db.execute(text('SELECT pg_advisory_xact_lock(704936219)'))
  existing=db.get(Config,MIGRATION_KEY)
  if existing:
   sources=existing.content.get('sources',{})
  else:
   _import_local_storage(db,root,sources,remember)
 # Delete only byte-for-byte verified migration sources after the DB commit succeeds.
 for relative,digest in sources.items():
  path=(root/relative).resolve()
  if not path.is_relative_to(root.resolve()):raise RuntimeError('迁移路径超出数据目录')
  if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==digest:path.unlink()

def _import_local_storage(db,root,sources,remember):
  for filename,key in [('avdb-settings.json','avdb'),('network-settings.json','network')]:
   path=root/filename
   if path.exists():
    row=db.get(Config,key)
    legacy=json.loads(path.read_text(encoding='utf-8'))
    if row:row.content={**legacy,**row.content}
    else:db.add(Config(key=key,content=legacy))
    remember(path)
  db.flush()
  if not db.get(Config,'network'):
   cfg=config_manager.get()
   db.add(Config(key='network',content={'PROXY':cfg.PROXY or '','FLARE_SOLVERR_URL':cfg.FLARE_SOLVERR_URL or ''}))
  if not db.get(Config,'avdb'):
   db.add(Config(key='avdb',content={'url':os.getenv('AVDB_URL',''),'api_key':os.getenv('AVDB_API_KEY',''),'username':'','password':''}))
  path=root/'push-records.sqlite3'
  if path.exists():
   remember(path)
   with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as legacy:
    legacy.row_factory=sqlite3.Row
    for row in legacy.execute('SELECT * FROM push_records ORDER BY id'):
     values=dict(row);values['tids']=json.loads(values['tids']);values['quick']=bool(values['quick'])
     # IDs may already be in use in the destination; preserve legacy identity separately.
     legacy_id=values.pop('id')
     marker='legacy_push_'+str(legacy_id)
     if not db.get(Config,marker):
      record=PushRecord(**values);db.add(record);db.flush()
      db.add(Config(key=marker,content={'record_id':record.id}))
  for path in sorted((root/'recovery').glob('*.json')):
   remember(path)
   if not db.get(RecoveryRecord,path.stem):
    value=json.loads(path.read_text(encoding='utf-8'))
    db.add(RecoveryRecord(id=path.stem,kind=value['kind'],payload=value['payload']))
  for path in sorted((root/'logs').glob('*')):
   if not path.is_file():continue
   digest=hashlib.sha256(path.read_bytes()).hexdigest()
   marker='legacy_log_'+digest
   if db.get(Config,marker):continue
   if path.suffix=='.zip':
    with zipfile.ZipFile(path) as archive:
     texts=[archive.read(n).decode('utf-8',errors='replace') for n in archive.namelist() if n.endswith('.log')]
   elif path.suffix=='.log':texts=[path.read_text(encoding='utf-8',errors='replace')]
   else:continue
   remember(path)
   for value in texts:
    for line in value.splitlines():
     if line.strip():db.add(RuntimeLog(time=datetime.now(timezone.utc).isoformat(),level='LEGACY',icon='ℹ️',message=line))
   db.add(Config(key=marker,content={'imported':True}))
  db.add(Config(key=MIGRATION_KEY,content={"completed":True,'sources':sources}))

def prune_runtime_logs():
 with session_scope() as db:
  db.execute(delete(RuntimeLog).where(RuntimeLog.time<(datetime.now(timezone.utc)-timedelta(days=7)).isoformat()))
