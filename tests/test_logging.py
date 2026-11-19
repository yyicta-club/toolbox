import logging
from queue import Queue

from yyict_toolbox.logging_system import DisplayQueueHandler, configure_logging


def test_file_log_records_all_levels_and_rotates(tmp_path):
    logger = logging.getLogger('yyict_toolbox')
    previous_handlers = logger.handlers[:]
    previous_level, previous_propagate = logger.level, logger.propagate
    logger.handlers = []
    try:
        queue = configure_logging(tmp_path)
        for level in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR):
            logger.log(level, 'test event %s', logging.getLevelName(level))
        content = (tmp_path / 'log/toolbox.log').read_text(encoding='utf-8')
        for level in ('DEBUG', 'INFO', 'WARNING', 'ERROR'):
            assert f'test event {level}' in content
        assert queue.qsize() == 4
        file_handler = logger.handlers[0]
        file_handler.doRollover()
        logger.info('after rotation')
        assert (tmp_path / 'log/toolbox.log.1').exists()
        assert 'after rotation' in (tmp_path / 'log/toolbox.log').read_text(encoding='utf-8')
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers = previous_handlers
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


def test_display_queue_is_bounded_and_keeps_recent_event():
    queue = Queue(maxsize=1)
    handler = DisplayQueueHandler(queue)
    for message in ('old', 'new'):
        handler.handle(logging.LogRecord('test', logging.INFO, '', 0, message, (), None))
    assert queue.qsize() == 1
    assert queue.get_nowait().getMessage() == 'new'
