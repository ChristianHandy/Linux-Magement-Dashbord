# updater.py - Enhanced error handling, better distribution support, and fixed notification propagation
import os
import logging

SUPPORTED_DISTRIBUTIONS = ['ubuntu', 'debian', 'fedora', 'centos']

def get_current_distribution():
    try:
        # Attempting to fetch distribution information
        with open('/etc/os-release', 'r') as file:
            for line in file:
                if line.startswith('ID='):
                    return line.strip().split('=')[1].lower()
    except Exception as e:
        logging.error(f"Error fetching distribution: {e}")
        raise RuntimeError("Could not determine the Linux distribution.")

def notify_error(update_id, message):
    try:
        # Assuming some kind of notification mechanism exists
        logging.info(f"Sending notification for Update {update_id}: {message}")
    except Exception as e:
        logging.error(f"Failed to send notification for Update {update_id}: {e}")

def process_update(update_id):
    try:
        current_distro = get_current_distribution()

        if current_distro not in SUPPORTED_DISTRIBUTIONS:
            raise ValueError(f"Unsupported distribution: {current_distro}")

        logging.info(f"Preparing to process update {update_id} for {current_distro}...")

        # Simulated update processing...
        logging.info(f"Update {update_id} processed successfully.")

    except ValueError as ve:
        logging.warning(f"Validation error for Update {update_id}: {ve}")
        notify_error(update_id, str(ve))
    except RuntimeError as re:
        logging.critical(f"Runtime error in Update {update_id}: {re}")
        notify_error(update_id, "Critical error encountered.")
        raise
    except Exception as e:
        logging.error(f"Unexpected error processing Update {update_id}: {e}")
        notify_error(update_id, "Unexpected error occurred.")

def main():
    logging.basicConfig(level=logging.INFO)

    updates = ['update1', 'update2', 'update3']

    for update_id in updates:
        try:
            process_update(update_id)
        except Exception as e:
            logging.error(f"Aborting processing due to error: {e}")

if __name__ == "__main__":
    main()
