import logging
import os
import sys
from collections import deque
from threading import Lock

from loguru import logger as uru_logger
from app.core.config import data_path

log_dir = os.path.join(data_path, 'logs')
recent_logs = deque(maxlen=1000)
recent_lock = Lock()


def capture_console(message):
    record = message.record
    with recent_lock:
        recent_logs.append({'time': record['time'].isoformat(),
                            'level': record['level'].name,
                            'icon': record['extra']['icon'],
                            'message': record['extra']['summary']})


def read_console_logs():
    with recent_lock:
        return list(recent_logs)

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
    os.makedirs(log_dir, exist_ok=True)
    uru_logger.remove()
    uru_logger.add(
        f'{log_dir}/app.log', rotation='00:00', retention='7 days',
        compression='zip', encoding='utf-8', level='DEBUG',
        backtrace=False, diagnose=False,
        format='{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}', filter=batch_log_filter,
    )
    uru_logger.add(sys.stdout, format=console_format, level='INFO',
                   colorize=False, backtrace=False, diagnose=False, filter=batch_log_filter)
    uru_logger.add(capture_console, format=console_format, level='INFO',
                   backtrace=False, diagnose=False, filter=batch_log_filter)
    logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO, force=True)
    for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access', 'apscheduler'):
        log = logging.getLogger(name)
        log.handlers.clear()
        log.propagate = True
    logging.getLogger('apscheduler').setLevel(logging.WARNING)
    return uru_logger


logger = setup_loguru_logger()
