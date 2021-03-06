# -*- coding: utf-8 -*-
"""
This job runs on the leader, and is a replacement for the NodeRed database streaming job.
"""
import signal
import os
import click
import json
from collections import namedtuple
from dataclasses import dataclass


from pioreactor.pubsub import QOS
from pioreactor.background_jobs.base import BackgroundJob
from pioreactor.whoami import get_unit_name, UNIVERSAL_EXPERIMENT
from pioreactor.config import config
from pioreactor.utils.timing import current_utc_time

JOB_NAME = os.path.splitext(os.path.basename((__file__)))[0]

SetAttrSplitTopic = namedtuple(
    "SetAttrSplitTopic", ["pioreactor_unit", "experiment", "timestamp"]
)

TopicToParserToTable = namedtuple("TopicToParserToTable", ["topic", "parser", "table"])


@dataclass
class TopicToParserToTableContrib:
    """
    plugins subclass this.
    parser (callable) must accept (topic: str, payload: str)

    TODO: untested
    """

    topic: str
    parser: callable
    table: str

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # TODO: this can first check the db to make sure the requested table is defined.
        MqttToDBStreamer.topics_to_tables_from_plugins.append(cls)


class MqttToDBStreamer(BackgroundJob):

    topics_to_tables_from_plugins = []

    def __init__(self, topics_to_tables, **kwargs):

        from sqlite3worker import Sqlite3Worker

        super(MqttToDBStreamer, self).__init__(job_name=JOB_NAME, **kwargs)
        self.sqliteworker = Sqlite3Worker(
            config["storage"]["database"], max_queue_size=250, raise_on_error=False
        )

        topics_to_tables.extend(self.topics_to_tables_from_plugins)

        topics_and_callbacks = [
            {
                "topic": topic_to_table.topic,
                "callback": self.create_on_message_callback(
                    topic_to_table.parser, topic_to_table.table
                ),
            }
            for topic_to_table in topics_to_tables
        ]

        self.start_passive_listeners(topics_and_callbacks)

    def on_disconnect(self):
        self.sqliteworker.close()  # close the db safely

    def create_on_message_callback(self, parser, table):
        def _callback(message):
            # TODO: filter testing experiments here
            try:
                new_row = parser(message.topic, message.payload)
            except Exception as e:
                self.logger.debug(
                    f"message.payload that caused error: `{message.payload}`"
                )
                raise e

            if new_row is None:
                # parsers can return None to exit out.
                return

            cols_placeholder = ", ".join(new_row.keys())
            values_placeholder = ", ".join([":" + c for c in new_row.keys()])
            SQL = f"""INSERT INTO {table} ({cols_placeholder}) VALUES ({values_placeholder})"""
            self.sqliteworker.execute(SQL, new_row)

        return _callback

    def start_passive_listeners(self, topics_and_callbacks):
        for topic_and_callback in topics_and_callbacks:
            self.subscribe_and_callback(
                topic_and_callback["callback"],
                topic_and_callback["topic"],
                qos=QOS.EXACTLY_ONCE,
                allow_retained=False,
            )


def produce_metadata(topic):
    # helper function for parsers below
    split_topic = topic.split("/")
    return (
        SetAttrSplitTopic(split_topic[1], split_topic[2], current_utc_time()),
        split_topic,
    )


def mqtt_to_db_streaming():

    ###################
    # parsers
    ###################
    # - must return a dictionary with the column names (order isn't important)
    # - `produce_metadata` is a helper function, see defintion.
    # - parsers can return None as well, to skip adding the message to the database.
    #

    def parse_od(topic, payload):
        metadata, split_topic = produce_metadata(topic)
        payload = json.loads(payload)
        return {
            "experiment": metadata.experiment,
            "pioreactor_unit": metadata.pioreactor_unit,
            "timestamp": payload["timestamp"],
            "od_reading_v": payload["voltage"],
            "angle": payload["angle"],
            "channel": split_topic[-1],
        }

    def parse_od_filtered(topic, payload):
        metadata, split_topic = produce_metadata(topic)
        payload = json.loads(payload)

        return {
            "experiment": metadata.experiment,
            "pioreactor_unit": metadata.pioreactor_unit,
            "timestamp": payload["timestamp"],
            "normalized_od_reading": payload["od_filtered"],
            "angle": payload["angle"],
            "channel": split_topic[-1],
        }

    def parse_dosing_events(topic, payload):
        payload = json.loads(payload)
        metadata, _ = produce_metadata(topic)

        return {
            "experiment": metadata.experiment,
            "pioreactor_unit": metadata.pioreactor_unit,
            "timestamp": payload["timestamp"],
            "volume_change_ml": payload["volume_change"],
            "event": payload["event"],
            "source_of_event": payload["source_of_event"],
        }

    def parse_led_events(topic, payload):
        payload = json.loads(payload)
        metadata, _ = produce_metadata(topic)

        return {
            "experiment": metadata.experiment,
            "pioreactor_unit": metadata.pioreactor_unit,
            "timestamp": payload["timestamp"],
            "channel": payload["channel"],
            "intensity": payload["intensity"],
            "event": payload["event"],
            "source_of_event": payload["source_of_event"],
        }

    def parse_growth_rate(topic, payload):
        metadata, _ = produce_metadata(topic)
        payload = json.loads(payload)

        return {
            "experiment": metadata.experiment,
            "pioreactor_unit": metadata.pioreactor_unit,
            "timestamp": payload["timestamp"],
            "rate": float(payload["growth_rate"]),
        }

    def parse_temperature(topic, payload):
        metadata, _ = produce_metadata(topic)

        if not payload:
            return None

        payload = json.loads(payload)

        return {
            "experiment": metadata.experiment,
            "pioreactor_unit": metadata.pioreactor_unit,
            "timestamp": payload["timestamp"],
            "temperature_c": float(payload["temperature"]),
        }

    def parse_pid_logs(topic, payload):
        metadata, _ = produce_metadata(topic)
        payload = json.loads(payload)
        return {
            "experiment": metadata.experiment,
            "pioreactor_unit": metadata.pioreactor_unit,
            "timestamp": metadata.timestamp,
            "setpoint": payload["setpoint"],
            "output_limits_lb": payload["output_limits_lb"],
            "output_limits_ub": payload["output_limits_ub"],
            "Kd": payload["Kd"],
            "Ki": payload["Ki"],
            "Kp": payload["Kp"],
            "integral": payload["integral"],
            "proportional": payload["proportional"],
            "derivative": payload["derivative"],
            "latest_input": payload["latest_input"],
            "latest_output": payload["latest_output"],
            "job_name": payload["job_name"],
            "target_name": payload["target_name"],
        }

    def parse_alt_media_fraction(topic, payload):
        metadata, _ = produce_metadata(topic)
        payload = json.loads(payload)

        return {
            "experiment": metadata.experiment,
            "pioreactor_unit": metadata.pioreactor_unit,
            "timestamp": payload["timestamp"],
            "alt_media_fraction": float(payload["alt_media_fraction"]),
        }

    def parse_logs(topic, payload):
        metadata, split_topic = produce_metadata(topic)
        payload = json.loads(payload)
        return {
            "experiment": metadata.experiment,
            "pioreactor_unit": metadata.pioreactor_unit,
            "timestamp": payload["timestamp"],
            "message": payload["message"],
            "task": payload["task"],
            "level": payload["level"],
            "source": split_topic[-1],  # should be app, ui, etc.
        }

    def parse_kalman_filter_outputs(topic, payload):
        metadata, _ = produce_metadata(topic)
        payload = json.loads(payload)
        return {
            "experiment": metadata.experiment,
            "pioreactor_unit": metadata.pioreactor_unit,
            "timestamp": metadata.timestamp,
            "state": json.dumps(payload["state"]),
            "covariance_matrix": json.dumps(payload["covariance_matrix"]),
        }

    def parse_automation_settings(topic, payload):
        payload = json.loads(payload.decode())
        return payload

    def parse_stirring_rates(topic, payload):
        metadata = produce_metadata(topic)
        return {
            "experiment": metadata.experiment,
            "pioreactor_unit": metadata.pioreactor_unit,
            "timestamp": metadata.timestamp,
            "rpm": float(payload),
        }

    def parse_od_statistics(topic, payload):
        metadata, split_topic = produce_metadata(topic)
        return {
            "experiment": metadata.experiment,
            "pioreactor_unit": metadata.pioreactor_unit,
            "timestamp": metadata.timestamp,
            "source": split_topic[-2],
            "estimator": split_topic[-1],
            "estimate": float(payload),
        }

    topics_to_tables = [
        TopicToParserToTable(
            "pioreactor/+/+/growth_rate_calculating/od_filtered/+",
            parse_od_filtered,
            "od_readings_filtered",
        ),
        TopicToParserToTable(
            "pioreactor/+/+/od_reading/od_raw/+", parse_od, "od_readings_raw"
        ),
        TopicToParserToTable(
            "pioreactor/+/+/dosing_events", parse_dosing_events, "dosing_events"
        ),
        TopicToParserToTable("pioreactor/+/+/led_events", parse_led_events, "led_events"),
        TopicToParserToTable(
            "pioreactor/+/+/growth_rate_calculating/growth_rate",
            parse_growth_rate,
            "growth_rates",
        ),
        TopicToParserToTable(
            "pioreactor/+/+/temperature_control/temperature",
            parse_temperature,
            "temperature_readings",
        ),
        TopicToParserToTable("pioreactor/+/+/pid_log", parse_pid_logs, "pid_logs"),
        TopicToParserToTable(
            "pioreactor/+/+/alt_media_calculating/alt_media_fraction",
            parse_alt_media_fraction,
            "alt_media_fraction",
        ),
        TopicToParserToTable("pioreactor/+/+/logs/+", parse_logs, "logs"),
        TopicToParserToTable(
            "pioreactor/+/+/dosing_automation/dosing_automation_settings",
            parse_automation_settings,
            "dosing_automation_settings",
        ),
        TopicToParserToTable(
            "pioreactor/+/+/led_automation/led_automation_settings",
            parse_automation_settings,
            "led_automation_settings",
        ),
        TopicToParserToTable(
            "pioreactor/+/+/temperature_automation/temperature_automation_settings",
            parse_automation_settings,
            "temperature_automation_settings",
        ),
        TopicToParserToTable(
            "pioreactor/+/+/growth_rate_calculating/kalman_filter_outputs",
            parse_kalman_filter_outputs,
            "kalman_filter_outputs",
        ),
        TopicToParserToTable(
            "pioreactor/+/+/stirring/rpm", parse_stirring_rates, "stirring_rates"
        ),
        TopicToParserToTable(
            "pioreactor/+/od_blank/+", parse_od_statistics, "od_reading_statistics"
        ),
        TopicToParserToTable(
            "pioreactor/+/od_normalization/+",
            parse_od_statistics,
            "od_reading_statistics",
        ),
    ]

    MqttToDBStreamer(  # noqa: F841
        topics_to_tables, experiment=UNIVERSAL_EXPERIMENT, unit=get_unit_name()
    )

    signal.pause()


@click.command(name="mqtt_to_db_streaming")
def click_mqtt_to_db_streaming():
    """
    (leader only) Send MQTT streams to the database. Parsers should return a dict of all the entries in the corresponding table.
    """
    mqtt_to_db_streaming()
