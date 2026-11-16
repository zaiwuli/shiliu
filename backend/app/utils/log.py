import logging
import sys

from loguru import logger as uru_logger

def read_console_logs():
    from app.core.database import session_scope
    from app.models import RuntimeLog
    with session_scope() as db:
        rows=db.query(RuntimeLog).order_by(RuntimeLog.id.desc()).limit(1000).all()
        return [{'time':r.time,'level':r.level,'icon':r.icon,'message':r.message} for r in reversed(rows)]

def capture_database(message):
    # Use the engine directly: session_scope logs its failures and would recurse.
    try:
        from app.core.database import engine
        from app.models import RuntimeLog
        from datetime import datetime,timezone
        record=message.record
        with engine.begin() as connection:
            connection.execute(RuntimeLog.__table__.insert().values(time=datetime.now(timezone.utc).isoformat(),level=record['level'].name,icon=ICONS.get(record['level'].name,'ℹ️'),message=record['extra'].get('summary',record['message'])))
    except Exception:
        pass  # stdout still carries diagnostics when the database is unavailable.

ICONS = {'DEBUG': '🔍', 'INFO': 'ℹ️', 'SUCCESS': '✅',
         'WARNING': '⚠️', 'ERROR': '❌', 'CRITICAL': '🚨'}

def batch_log_filter(record):
    return not record['extra'].get('retry_detail', False)


def console_format(record):
    icon = ICONS.get(record['level'].name, 'ℹ️')
    record['extra']['icon'] = icon
    record['extra']['summary'] = record['message'].strip().replace('\r', '').replace('\n', ' · ')
    exception = record['exception']
    if exception:
        record['extra']['summary'] += f'（{exception.type.__name__}: {exception.value}）'
    return '{time:YYYY-MM-DD HH:mm:ss.SSS} | {extra[icon]} {level: <8}\n{extra[icon]} {extra[summary]}\n'


class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = uru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        uru_logger.opt(exception=record.exc_info).log(level, record.getMessage())


def setup_loguru_logger():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(errors='backslashreplace')
    uru_logger.remove()
    uru_logger.add(sys.stdout, format=console_format, level='INFO',
                   colorize=False, backtrace=False, diagnose=False, filter=batch_log_filter)
    uru_logger.add(capture_database, format=console_format, level='INFO', enqueue=True, backtrace=False, diagnose=False, filter=batch_log_filter)
    logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO, force=True)
    for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access', 'apscheduler'):
        log = logging.getLogger(name)
        log.handlers.clear()
        log.propagate = True
    logging.getLogger('apscheduler').setLevel(logging.WARNING)
    return uru_logger


logger = setup_loguru_logger()
