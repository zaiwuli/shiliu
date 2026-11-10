import ast,io,json,re
from datetime import datetime,timezone
import pandas as pd
from sqlalchemy import text,create_engine,inspect
from sqlalchemy.dialects.postgresql import insert
from app.core.database import session_scope,engine
from app.models import Article,Batch

def links(value):
 if value is None:return []
 if isinstance(value,list):return list(dict.fromkeys(str(x).strip() for x in value if x))
 if not isinstance(value,(str,list)) and pd.isna(value):return []
 value=str(value).strip()
 if not value:return []
 if value.startswith('['):
  try:return links(json.loads(value))
  except Exception:
   try:return links(ast.literal_eval(value))
   except Exception:raise ValueError('无法解析数组字段')
 if value.startswith('{'):
  import csv
  return links(next(csv.reader([value[1:-1]],escapechar='\\')))
 if 'ed2k://' in value or 'magnet:?' in value:
  return list(dict.fromkeys(x.strip(' ,\r\n') for x in re.split(r'(?=ed2k://|magnet:\?)',value) if x.strip(' ,\r\n')))
 return list(dict.fromkeys(x.strip() for x in re.split(r'[,\r\n]+',value) if x.strip()))

def serialize(row):
 return {c.name:getattr(row,c.name) for c in row.__table__.columns}

def filtered(db,filters):
 q=db.query(Article)
 for key in ['website','section','source','batch_id','merge_status']:
  if filters.get(key) not in [None,'']:q=q.filter(getattr(Article,key)==filters[key])
 if filters.get('keyword'):
  keyword=filters['keyword'].strip();tid=keyword.lstrip('#')
  if tid.isascii() and tid.isdigit() and len(tid)<=18:q=q.filter(Article.tid==int(tid))
  else:q=q.filter(Article.title.ilike('%'+keyword+'%'))
 if filters.get('ids'):q=q.filter(Article.id.in_(filters['ids']))
 if filters.get('keep_section'):q=q.filter(Article.section!=filters['keep_section'])
 return q

def ingest(rows,kind):
 count={'inserted':0,'existing':0,'failed':0,'errors':[]}
 with session_scope() as db:
  b=Batch(kind=kind,status='running');db.add(b);db.flush();bid=b.id
  for index,row in enumerate(rows):
   try:
    with db.begin_nested():
     tid=int(row['tid']);website=str(row.get('website') or 'sehuatang').strip();title=str(row.get('title') or '').strip();section=str(row.get('section') or '').strip()
     if not title or not section:raise ValueError('标题和板块不能为空')
     old=db.query(Article).filter_by(tid=tid,website=website).first()
     if old:
      count['existing']+=1;continue
     date=row.get('publish_date');date=pd.to_datetime(date).date() if date else None
     a=Article(tid=tid,website=website,title=title,section=section,category=row.get('category'),match_number=row.get('match_number') or row.get('number'),publish_date=date,magnet=links(row.get('magnet')),edk=links(row.get('edk')),preview_images=links(row.get('preview_images')),detail_url=row.get('detail_url'),size=int(row['size']) if row.get('size') is not None else None,source=kind,batch_id=bid,merge_status='pending')
     db.add(a);db.flush();count['inserted']+=1
   except Exception as e:
    count['failed']+=1
    if len(count['errors'])<50:count['errors'].append({'row':index+2,'error':str(e)})
  b.status='completed';b.message=json.dumps(count,ensure_ascii=False);b.finished_at=datetime.now(timezone.utc)
 return {'batch_id':bid,**count}

def convert(a,clear_size=False):
 urls=links(a.magnet)+links(a.edk);urls=list(dict.fromkeys(urls))
 if not urls:raise ValueError('没有可合并的下载链接')
 for key,limit in [('title',255),('section',255),('category',255),('detail_url',255),('website',32)]:
  if len(getattr(a,key) or '')>limit:raise ValueError(f'{key} 超过 {limit} 字符')
 if not clear_size and a.size is not None and not -2147483648<=a.size<=2147483647:raise ValueError('大小超出目标整数范围')
 return dict(tid=a.tid,title=a.title,number=a.match_number,publish_date=a.publish_date,magnet='\n'.join(urls),preview_images=','.join(links(a.preview_images)),detail_url=a.detail_url,size=None if clear_size else a.size,section=a.section,category=a.category,website=a.website)

