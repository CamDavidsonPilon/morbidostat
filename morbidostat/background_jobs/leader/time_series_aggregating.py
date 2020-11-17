# -*- coding: utf-8 -*-
"""
This job runs on the leader, and is a replacement for the NodeRed aggregation job.

"""
import signal
import time
import os
import traceback
from threading import Timer
import json

import click


from morbidostat.pubsub import subscribe_and_callback, publish
from morbidostat.background_jobs import BackgroundJob
from morbidostat.whoami import unit, experiment, hostname

JOB_NAME = os.path.splitext(os.path.basename((__file__)))[0]


def current_time():
    return time.time_ns() // 1_000_000


class RepeatedTimer(object):
    def __init__(self, interval, function, *args, **kwargs):
        self._timer = None
        self.interval = interval
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.is_running = False
        self.start()
        self.daemon = True

    def _run(self):
        self.is_running = False
        self.start()
        self.function(*self.args, **self.kwargs)

    def start(self):
        if not self.is_running:
            self._timer = Timer(self.interval, self._run)
            self._timer.daemon = True
            self._timer.start()
            self.is_running = True

    def cancel(self):
        self._timer.cancel()
        self.is_running = False


class TimeSeriesAggregation(BackgroundJob):
    def __init__(
        self,
        topic,
        output_dir,
        extract_label,
        skip_cache=False,
        record_every_n_seconds=None,  # controls how often we should sample data. Ex: growth_rate is ~5min
        write_every_n_seconds=30,  # controls how often we write to disk. Ex: about 30seconds
        time_window_seconds=None,
        **kwargs,
    ):

        super(TimeSeriesAggregation, self).__init__(job_name=JOB_NAME, **kwargs)
        self.topic = topic
        self.output_dir = output_dir
        self.aggregated_time_series = self.read(skip_cache)
        self.extract_label = extract_label
        self.time_window_seconds = time_window_seconds
        self.cache = {}

        self.write_thead = RepeatedTimer(write_every_n_seconds, self.write)
        self.write_thead.start()

        self.append_cache_thread = RepeatedTimer(record_every_n_seconds, self.append_cache_and_clear)
        self.append_cache_thread.start()

        self.start_passive_listeners()

    def on_exit(self):
        self.write_thead.cancel()
        self.append_cache_thread.cancel()

    @property
    def output(self):
        pieces = filter(lambda s: s != "+", self.topic.split("/")[3:])
        return self.output_dir + "_".join(pieces) + ".json"

    def read(self, skip_cache):
        if skip_cache:
            return {"series": [], "data": []}
        try:
            with open(self.output, "r") as f:
                return json.load(f)
        except Exception as e:
            return {"series": [], "data": []}

    def write(self):
        self.latest_write = current_time()
        with open(self.output, "w") as f:
            json.dump(self.aggregated_time_series, f)

    def append_cache_and_clear(self):
        self.update_data_series()
        self.cache = {}

    def update_data_series(self):
        time = current_time()

        for label, latest_value in self.cache.copy().items():  # copy because a thread may try to update this while iterating.

            if label not in self.aggregated_time_series["series"]:
                self.aggregated_time_series["series"].append(label)
                self.aggregated_time_series["data"].append([])

            ix = self.aggregated_time_series["series"].index(label)
            self.aggregated_time_series["data"][ix].append({"x": time, "y": latest_value})

            if self.time_window_seconds:
                self.aggregated_time_series["data"][ix] = [
                    data
                    for data in self.aggregated_time_series["data"][ix]
                    if data["x"] > (current_time() - self.time_window_seconds * 1000)
                ]

    def on_message(self, message):
        label = self.extract_label(message.topic)
        self.cache[label] = float(message.payload)

    def on_clear(self, message):
        payload = message.payload
        if not payload:
            self.cache = {}
            self.aggregated_time_series = {"series": [], "data": []}
            self.write()
        else:
            publish(f"morbidostat/{self.unit}/{self.experiment}/log", "Only empty messages allowed to empty the cache.")

    def start_passive_listeners(self):
        subscribe_and_callback(self.on_message, self.topic)
        subscribe_and_callback(
            self.on_clear, f"morbidostat/{self.unit}/{self.experiment}/{self.job_name}/aggregated_time_series/set"
        )


@click.command()
@click.option("--output-dir", "-o", default="/home/pi/morbidostatui/backend/build/data/", help="the output directory")
@click.option("--skip-cache", is_flag=True, help="skip using the saved data on disk")
@click.option("--verbose", "-v", count=True, help="print to std.out")
def run(output_dir, skip_cache, verbose):
    def single_sensor_label_from_topic(topic):
        split_topic = topic.split("/")
        return f"{split_topic[1]}-{split_topic[-1]}"

    def unit_from_topic(topic):
        split_topic = topic.split("/")
        return f"{split_topic[1]}"

    raw135 = TimeSeriesAggregation(
        f"morbidostat/+/{experiment}/od_raw/135/+",
        output_dir,
        experiment=experiment,
        unit=unit,
        verbose=verbose,
        skip_cache=skip_cache,
        extract_label=single_sensor_label_from_topic,
        write_every_n_seconds=45,
        time_window_seconds=120 * 60,  # TODO: move this to a config param
        record_every_n_seconds=5,
    )

    filtered135 = TimeSeriesAggregation(
        f"morbidostat/+/{experiment}/od_filtered/135/+",
        output_dir,
        experiment=experiment,
        unit=unit,
        verbose=verbose,
        skip_cache=skip_cache,
        extract_label=single_sensor_label_from_topic,
        write_every_n_seconds=45,
        time_window_seconds=120 * 60,  # TODO: move this to a config param
        record_every_n_seconds=5,
    )

    growth_rate = TimeSeriesAggregation(
        f"morbidostat/+/{experiment}/growth_rate",
        output_dir,
        experiment=experiment,
        unit=unit,
        verbose=verbose,
        skip_cache=skip_cache,
        extract_label=unit_from_topic,
        write_every_n_seconds=45,
        record_every_n_seconds=5 * 60,  # TODO: move this to a config param
    )

    alt_media_fraction = TimeSeriesAggregation(
        f"morbidostat/+/{experiment}/alt_media_calculating/alt_media_fraction",
        output_dir,
        experiment=experiment,
        unit=unit,
        verbose=verbose,
        skip_cache=skip_cache,
        extract_label=unit_from_topic,
        write_every_n_seconds=45,
        record_every_n_seconds=1,
    )

    while True:
        signal.pause()


if __name__ == "__main__":
    run()
