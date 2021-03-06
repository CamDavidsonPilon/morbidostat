# -*- coding: utf-8 -*-
import os, time
from datetime import datetime
import click
from pioreactor.config import config, get_active_workers_in_inventory
from pioreactor.whoami import get_unit_name
from pioreactor.logging import create_logger
from pioreactor.utils.timing import current_utc_time


LAST_BACKUP_TIMESTAMP_PATH = "/home/pi/.pioreactor/.last_backup_time"


def backup_database(output, force):
    """
    This action will create a backup of the SQLite3 database into specified output. It then
    will try to copy the backup to any available worker Pioreactors as a further backup.

    This job actually consumes a lot of power, and I've seen the LED output
    drop due to this running. See issue #81. For now, we will skip the backup if `od_reading` is running

    Elsewhere, a cronjob is set up as well to run this action every N days.

    """

    import sqlite3
    from sh import rsync, ErrorReturnCode

    logger = create_logger("backup_database")

    # let's check to see how old the last backup is and alert the user if too old.
    if os.path.isfile(LAST_BACKUP_TIMESTAMP_PATH):
        with open(LAST_BACKUP_TIMESTAMP_PATH, "r") as f:
            latest_backup_at = datetime.datetime.strptime(
                f.read(), "%Y-%m-%dT%H:%M:%S.%f"
            )

        if (datetime.utcnow() - latest_backup_at).days > 30:
            logger.warning("Database hasn't been backed up in over 30 days. Running now.")

    def progress(status, remaining, total):
        logger.debug(f"Copied {total-remaining} of {total} SQLite3 pages.")
        logger.debug(f"Writing to local backup {output}.")

    logger.debug(f"Starting backup of database to {output}")
    time.sleep(1)  # pause a second so the log entry above gets recorded into the DB.

    con = sqlite3.connect(config.get("storage", "database"))
    bck = sqlite3.connect(output)

    with bck:
        con.backup(bck, pages=-1, progress=progress)

    bck.close()
    con.close()

    with open(LAST_BACKUP_TIMESTAMP_PATH, "w") as f:
        f.write(current_utc_time())

    logger.info("Completed backup of database.")

    n_backups = 2
    backups_complete = 0
    available_workers = get_active_workers_in_inventory()

    while (backups_complete < n_backups) and (len(available_workers) > 0):
        backup_unit = available_workers.pop()
        if backup_unit == get_unit_name():
            continue

        try:
            rsync("-hz", "--partial", "--inplace", output, f"{backup_unit}:{output}")
        except ErrorReturnCode:
            logger.debug(
                f"Unable to backup database to {backup_unit}. Is it online?",
                exc_info=True,
            )
            logger.warning(f"Unable to backup database to {backup_unit}. Is it online?")
        else:
            logger.debug(f"Backed up database to {backup_unit}:{output}.")
            backups_complete += 1

    return


@click.command(name="backup_database")
@click.option("--output", default="/home/pi/.pioreactor/pioreactor.sqlite.backup")
def click_backup_database(output, force):
    """
    (leader only) Backup db to workers.
    """
    return backup_database(output, force)
