import logging
from datetime import datetime
from queue import Queue

import pytest

from yyict_toolbox.logging_system import (
    SUBSCRIBER_QUEUE_SIZE,
    SYSTEM_LOGGER_NAME,
    UPDATE_LOGGER_NAME,
    DisplayQueueHandler,
    LogEvent,
    LogEventHub,
    configure_logging,
    event_hub,
    plugin_logger_name,
    read_log_events,
    source_id_for_logger,
)


@pytest.fixture
def logging_setup(tmp_path):
    """配置到临时目录的日志，并返回兼容队列、事件中心和日志文件路径。"""
    logger = logging.getLogger('yyict_toolbox')
    previous_handlers = logger.handlers[:]
    previous_level, previous_propagate = logger.level, logger.propagate
    logger.handlers = []
    queue = configure_logging(tmp_path)
    hub = event_hub()
    hub.clear()
    try:
        yield queue, hub, tmp_path / 'log/toolbox.log'
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers = previous_handlers
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate
        hub.clear()


def make_event(message='事件', level=logging.INFO, logger_name=SYSTEM_LOGGER_NAME):
    return LogEvent(
        timestamp=datetime.now(),
        level=level,
        logger_name=logger_name,
        message=message,
    )


def test_file_log_records_all_levels_and_rotates(logging_setup):
    queue, _, log_file = logging_setup
    logger = logging.getLogger('yyict_toolbox')
    for level in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR):
        logger.log(level, 'test event %s', logging.getLevelName(level))
    content = log_file.read_text(encoding='utf-8')
    for level in ('DEBUG', 'INFO', 'WARNING', 'ERROR'):
        assert f'test event {level}' in content
    assert queue.qsize() == 4
    file_handler = logger.handlers[0]
    file_handler.doRollover()
    logger.info('after rotation')
    assert (log_file.parent / 'toolbox.log.1').exists()
    assert 'after rotation' in log_file.read_text(encoding='utf-8')


def test_file_log_contains_logger_name_of_every_source(logging_setup):
    _, _, log_file = logging_setup
    logging.getLogger(SYSTEM_LOGGER_NAME).info('系统事件')
    logging.getLogger(UPDATE_LOGGER_NAME).info('更新事件')
    logging.getLogger(plugin_logger_name('quick-links')).info('插件事件')
    content = log_file.read_text(encoding='utf-8')
    assert '[yyict_toolbox.system] 系统事件' in content
    assert '[yyict_toolbox.update] 更新事件' in content
    assert '[yyict_toolbox.plugin.quick-links] 插件事件' in content


def test_file_log_does_not_write_extra_record_attributes(logging_setup):
    _, _, log_file = logging_setup
    logging.getLogger(SYSTEM_LOGGER_NAME).info('普通事件', extra={'password': 'secret-value'})
    content = log_file.read_text(encoding='utf-8')
    assert '普通事件' in content
    assert 'secret-value' not in content


def test_source_id_maps_plugin_logger_to_tool_id():
    assert source_id_for_logger(plugin_logger_name('quick-links')) == 'quick-links'
    assert source_id_for_logger(SYSTEM_LOGGER_NAME) == 'system'
    assert source_id_for_logger(UPDATE_LOGGER_NAME) == 'system'


def test_read_history_includes_rotated_backup_and_current_file(logging_setup):
    _, _, log_file = logging_setup
    logger = logging.getLogger(SYSTEM_LOGGER_NAME)
    logger.info('轮转前事件')
    logging.getLogger('yyict_toolbox').handlers[0].doRollover()
    logger.info('轮转后事件')
    events = read_log_events(log_file)
    assert [event.message for event in events] == ['轮转前事件', '轮转后事件']
    assert all(event.source_id == 'system' for event in events)


def test_read_history_parses_legacy_lines_as_system_source(tmp_path):
    log_directory = tmp_path / 'log'
    log_directory.mkdir()
    log_file = log_directory / 'toolbox.log'
    log_file.write_text(
        '2024-01-02 03:04:05 INFO 旧格式事件\n'
        '2024-01-02 03:04:06 WARNING [warn] 旧格式警告\n',
        encoding='utf-8',
    )
    events = read_log_events(log_file)
    assert [event.message for event in events] == ['旧格式事件', '[warn] 旧格式警告']
    assert [event.source_id for event in events] == ['system', 'system']


def test_read_history_keeps_only_recent_events(logging_setup):
    _, hub, log_file = logging_setup
    logger = logging.getLogger(SYSTEM_LOGGER_NAME)
    for index in range(5):
        logger.info('事件 %d', index)
    events = hub.read_history(limit=2)
    assert [event.message for event in events] == ['事件 3', '事件 4']
    assert log_file.exists()


def test_hub_delivers_the_same_event_to_all_subscribers():
    hub = LogEventHub()
    first = hub.subscribe()
    second = hub.subscribe()
    event = make_event('工具箱已启动')
    hub.publish(event)
    assert first.get_nowait() == event
    assert second.get_nowait() == event
    assert hub.history() == [event]


def test_subscriber_queue_is_bounded_and_keeps_latest_events():
    hub = LogEventHub()
    queue = hub.subscribe()
    total = SUBSCRIBER_QUEUE_SIZE + 10
    for index in range(total):
        hub.publish(make_event(f'事件 {index}'))
    assert queue.qsize() == SUBSCRIBER_QUEUE_SIZE
    messages = [queue.get_nowait().message for _ in range(queue.qsize())]
    # 队列已满时丢弃最旧事件，订阅者拿到的始终是最近的事件。
    assert messages[0] == f'事件 {total - SUBSCRIBER_QUEUE_SIZE}'
    assert messages[-1] == f'事件 {total - 1}'


def test_unsubscribe_stops_event_delivery():
    hub = LogEventHub()
    queue = hub.subscribe()
    hub.unsubscribe(queue)
    hub.publish(make_event('事件'))
    assert queue.empty()


def test_display_queue_is_bounded_and_keeps_recent_event():
    queue = Queue(maxsize=1)
    handler = DisplayQueueHandler(queue)
    for message in ('old', 'new'):
        handler.handle(logging.LogRecord('test', logging.INFO, '', 0, message, (), None))
    assert queue.qsize() == 1
    assert queue.get_nowait().getMessage() == 'new'
