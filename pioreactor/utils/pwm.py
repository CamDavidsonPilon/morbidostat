# -*- coding: utf-8 -*-
import sys, threading, signal
from pioreactor.whoami import is_testing_env
from pioreactor.logging import create_logger

if is_testing_env():
    import fake_rpi

    sys.modules["RPi"] = fake_rpi.RPi  # Fake RPi
    sys.modules["RPi.GPIO"] = fake_rpi.RPi.GPIO  # Fake GPIO

import RPi.GPIO as GPIO

GPIO.setmode(GPIO.BCM)


class PWM:
    """
    This class abstracts out the Rpi's PWM library details

    Example
    -----------
    > from pioreactor.utils.pwm import PWM
    > pwm = PWM(12, 50)
    > pwm.start(20) # 20% duty cycle
    >
    > pwm.change_duty_cycle(25) # 25% duty cycle
    >
    > pwm.stop()
    > pwm.cleanup()

    """

    HARDWARE_PWM_AVAILABLE_PINS = {12, 13}
    HARDWARE_PWM_CHANNELS = {12: 0, 13: 1}
    using_hardware = False

    def __init__(self, pin, hz, always_use_software=False):
        self.logger = create_logger("PWM")

        self.pin = pin
        self.hz = hz
        if (not always_use_software) and (pin in self.HARDWARE_PWM_AVAILABLE_PINS):
            if is_testing_env():
                from pioreactor.utils.mock import MockHardwarePWM as HardwarePWM
            else:
                from rpi_hardware_pwm import HardwarePWM

            self.pwm = HardwarePWM(self.HARDWARE_PWM_CHANNELS[self.pin], self.hz)
            self.using_hardware = True
        else:
            GPIO.setup(self.pin, GPIO.OUT)
            GPIO.output(self.pin, 0)
            self.pwm = GPIO.PWM(self.pin, hz)

        self.logger.debug(
            f"Initialized PWM-{self.pin} on {'hardware' if self.using_hardware else 'software'}."
        )

        # signals only work in main thread
        if threading.current_thread() is threading.main_thread():
            # terminate command, ex: pkill
            def on_kill(*args):
                self.cleanup()
                sys.exit()

            signal.signal(signal.SIGTERM, on_kill)
            signal.signal(signal.SIGINT, on_kill)

    def start(self, initial_duty_cycle):
        self.pwm.start(initial_duty_cycle)

    def stop(self):
        self.pwm.stop()

    def change_duty_cycle(self, dc):
        if self.using_hardware:
            self.pwm.change_duty_cycle(dc)
        else:
            self.pwm.ChangeDutyCycle(dc)

    def cleanup(self):
        self.stop()
        if self.using_hardware:
            pass
        else:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.pin, GPIO.OUT)
            GPIO.output(self.pin, 0)
            GPIO.cleanup(self.pin)
        self.logger.debug(f"Cleaned up PWM-{self.pin}.")

    def __exit__(self):
        self.cleanup()
