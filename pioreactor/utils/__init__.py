# -*- coding: utf-8 -*-
import psutil


def pio_jobs_running():
    jobs = []
    for proc in psutil.process_iter(attrs=["pid", "name", "cmdline"]):
        if proc.info["cmdline"] and (proc.info["cmdline"][0] == "python3"):
            job = proc.info["cmdline"][3].split(".")[-1]
            jobs.append(job)
    return jobs


def pump_ml_to_duration(ml, duty_cycle, duration_=0):
    """
    ml: the desired volume
    duration_ : the coefficient from calibration
    """
    return ml / duration_


def pump_duration_to_ml(duration, duty_cycle, duration_=0):
    """
    duration: the desired volume
    duration_ : the coefficient from calibration
    """
    return duration * duration_