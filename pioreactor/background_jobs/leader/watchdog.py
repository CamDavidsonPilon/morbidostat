# -*- coding: utf-8 -*-
import signal, time

import click

from pioreactor.whoami import get_unit_name, UNIVERSAL_EXPERIMENT
from pioreactor.background_jobs.base import BackgroundJob
from pioreactor.pubsub import subscribe


class WatchDog(BackgroundJob):
    def __init__(self, unit, experiment):
        super(WatchDog, self).__init__(
            job_name="watchdog", unit=unit, experiment=experiment
        )

        self.start_passive_listeners()

    def watch_for_lost_state(self, msg):
        if msg.payload.decode() == self.LOST:

            # TODO: this song-and-dance works for monitor, why not extend it to other jobs...

            # let's try pinging the unit a few times first:
            unit = msg.topic.split("/")[1]

            self.logger.warning(
                f"{unit} seems to be lost. Trying to re-establish connection..."
            )
            time.sleep(5)
            self.pub_client.publish(
                f"pioreactor/{unit}/{UNIVERSAL_EXPERIMENT}/monitor/$state/set", self.INIT
            )
            time.sleep(5)
            self.pub_client.publish(
                f"pioreactor/{unit}/{UNIVERSAL_EXPERIMENT}/monitor/$state/set", self.READY
            )
            time.sleep(5)

            current_state = subscribe(
                f"pioreactor/{unit}/{UNIVERSAL_EXPERIMENT}/monitor/$state", timeout=15
            ).payload.decode()

            if current_state == self.LOST:
                # failed, let's confirm to user
                self.logger.error(
                    f"{unit} was lost. We will continue checking for re-connection however."
                )
            else:
                self.logger.info(f"Update: {unit} is connected. All is well.")

            # continue to pull the latest state to see if anything has changed.
            while True:
                time.sleep(60)
                current_state = subscribe(
                    f"pioreactor/{unit}/{UNIVERSAL_EXPERIMENT}/monitor/$state", timeout=15
                ).payload.decode()

                if current_state != self.LOST:
                    self.logger.info(f"Update: {unit} is connected. All is well.")
                    return

    def watch_for_new_experiment(self, msg):
        new_experiment_name = msg.payload.decode()
        self.logger.debug(f"New latest experiment in MQTT: {new_experiment_name}")

    def start_passive_listeners(self):
        self.subscribe_and_callback(
            self.watch_for_lost_state,
            "pioreactor/+/+/monitor/$state",
            allow_retained=False,
        )
        self.subscribe_and_callback(
            self.watch_for_new_experiment,
            "pioreactor/latest_experiment",
            allow_retained=False,
        )


@click.command(name="watchdog")
def click_watchdog():
    """
    Start the watchdog on the leader
    """
    WatchDog(unit=get_unit_name(), experiment=UNIVERSAL_EXPERIMENT)

    signal.pause()
