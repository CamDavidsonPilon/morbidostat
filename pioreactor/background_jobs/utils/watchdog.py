# -*- coding: utf-8 -*-
import os, signal
import logging

import click

from pioreactor.whoami import get_unit_from_hostname, UNIVERSAL_EXPERIMENT
from pioreactor.background_jobs.base import BackgroundJob
from pioreactor.utils.timing import RepeatedTimer
from pioreactor.pubsub import publish

JOB_NAME = os.path.splitext(os.path.basename((__file__)))[0]
logger = logging.getLogger(JOB_NAME)

unit = get_unit_from_hostname()


class WatchDog(BackgroundJob):
    def __init__(self, unit, experiment):
        super(WatchDog, self).__init__(
            job_name=JOB_NAME, unit=unit, experiment=experiment
        )
        self.disk_usage_timer = RepeatedTimer(60 * 60, self.get_and_publish_disk_space)

    def get_and_publish_disk_space(self):
        import psutil

        disk_usage_percent = psutil.disk_usage("/").percent

        if disk_usage_percent <= 90:
            logger.debug(f"Disk space at {disk_usage_percent}%.")
        else:
            logger.error(f"Disk space at {disk_usage_percent}%.")
        publish(
            f"pioreactor/{self.unit}/{self.experiment}/watchdog/disk_usage_percent",
            disk_usage_percent,
        )


@click.command(name="watchdog")
def click_watchdog(duty_cycle):
    """
    Start the watchdog on a unit. Reports back to the leader.
    """
    heidi = WatchDog(  # noqa: F841
        unit=get_unit_from_hostname(), exp=UNIVERSAL_EXPERIMENT
    )

    signal.pause()
