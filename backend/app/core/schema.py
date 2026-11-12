"""Transactional migration of collector-owned tables only."""
from sqlalchemy import inspect, text

TABLES = ('article', 'article_converted', 'task', 'batch', 'task_log', 'config')

def initialize_collector_tables(engine, metadata):
    with engine.begin() as connection:
        connection.execute(text('SELECT pg_advisory_xact_lock(704936218)'))
        tables = set(inspect(connection).get_table_names())
        for suffix in TABLES:
            old, new = 'immortal_' + suffix, 'shiliu_' + suffix
            if old in tables and new in tables:
                raise RuntimeError(f'新旧表同时存在，请先核对数据：{old} / {new}')
        for suffix in TABLES:
            old, new = 'immortal_' + suffix, 'shiliu_' + suffix
            if old in tables:
                connection.execute(text(f'ALTER TABLE "{old}" RENAME TO "{new}"'))
        metadata.create_all(connection, tables=[t for t in metadata.sorted_tables if not t.info.get('external')])
        connection.execute(text('ALTER TABLE shiliu_retry ADD COLUMN IF NOT EXISTS source_batch_id BIGINT'))
        connection.execute(text('ALTER TABLE shiliu_batch ADD COLUMN IF NOT EXISTS details JSON'))
        connection.execute(text('ALTER TABLE shiliu_article ADD COLUMN IF NOT EXISTS origin_batch_id BIGINT'))
        connection.execute(text('CREATE INDEX IF NOT EXISTS shiliu_article_origin_batch_idx ON shiliu_article(origin_batch_id)'))
        connection.execute(text('CREATE INDEX IF NOT EXISTS shiliu_article_ledger_origin_idx ON shiliu_article ((COALESCE(origin_batch_id,batch_id)))'))
        connection.execute(text('CREATE INDEX IF NOT EXISTS shiliu_retry_source_batch_idx ON shiliu_retry(source_batch_id)'))
        connection.execute(text('UPDATE shiliu_article a SET origin_batch_id=r.source_batch_id FROM shiliu_retry r, shiliu_batch b WHERE a.origin_batch_id IS NULL AND a.batch_id=b.id AND b.kind=\'retry\' AND a.website=r.website AND a.tid=r.tid AND r.source_batch_id IS NOT NULL'))
        connection.execute(text('ALTER TABLE shiliu_article_converted ADD COLUMN IF NOT EXISTS target_tid BIGINT'))
        connection.execute(text('ALTER TABLE shiliu_article_converted ADD COLUMN IF NOT EXISTS size_cleared BOOLEAN DEFAULT FALSE'))
        connection.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS shiliu_converted_target_tid_unique ON shiliu_article_converted(target_tid)'))
