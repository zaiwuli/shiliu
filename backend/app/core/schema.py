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
        connection.execute(text('ALTER TABLE shiliu_article_converted ADD COLUMN IF NOT EXISTS target_tid BIGINT'))
        connection.execute(text('ALTER TABLE shiliu_article_converted ADD COLUMN IF NOT EXISTS size_cleared BOOLEAN DEFAULT FALSE'))
        connection.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS shiliu_converted_target_tid_unique ON shiliu_article_converted(target_tid)'))
