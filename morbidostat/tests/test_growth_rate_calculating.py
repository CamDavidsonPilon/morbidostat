# -*- coding: utf-8 -*-
import pytest

from morbidostat.long_running.growth_rate_calculating import growth_rate_calculating
from paho.mqtt import subscribe


class MockMQTTMsg:
    def __init__(self, topic, payload):
        self.payload = payload
        self.topic = topic


class MockMsgBroker:
    def __init__(self, *list_of_msgs):
        self.list_of_msgs = list_of_msgs
        self.counter = 0
        self.callbacks = []

    def next(self):
        msg = self.list_of_msgs[self.counter]
        self.counter += 1
        if self.counter >= len(self.list_of_msgs):
            self.counter = 0

        for f, topics in self.callbacks:
            print(f, topics)
            if msg.topic in topics:
                f()

        return msg

    def _add_callback(self, func, topics):
        self.callbacks.append([func, topics])

    def subscribe(self, *args, **kwargs):
        topics = args[0]
        while True:
            msg = self.next()
            if msg.topic in topics:
                return msg

    def callback(self, func, topics, hostname):
        self._add_callback(func, topics)
        return


@pytest.fixture
def mock_sub(monkeypatch):
    mock_broker = MockMsgBroker(
        MockMQTTMsg("morbidostat/_testing/od_raw_batched", '{"135": 0.778586260567034, "90": 0.20944389172032837}'),
        MockMQTTMsg("morbidostat/_testing/od_raw_batched", '{"135": 0.778586260567034, "90": 0.20944389172032837}'),
        MockMQTTMsg("morbidostat/_testing/od_raw_batched", '{"135": 0.778586260567034, "90": 0.20944389172032837}'),
        MockMQTTMsg("morbidostat/_testing/io_event", '{"volume_change": "1.5", "event": "add_media"}'),
        MockMQTTMsg("morbidostat/_testing/od_raw_batched", '{"135": 1.778586260567034, "90": 1.20944389172032837}'),
        MockMQTTMsg("morbidostat/_testing/kill", None),
    )

    monkeypatch.setattr(subscribe, "simple", mock_broker.subscribe)
    monkeypatch.setattr(subscribe, "callback", mock_broker.callback)


def test_subscribing(mock_sub):
    with pytest.raises(SystemExit):
        growth_rate_calculating()
