import os
import sys # Make sure sys is imported
import subprocess
import sqlite3
import json
import tempfile
import logging
from flask import Flask, request, jsonify, render_template

# --- Basic Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Flask App Initialization ---
app = Flask(__name__)

# --- Configuration ---
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
GARMINDB_DATA_DIR = os.path.join(APP_ROOT, '.garmindb_render_data')
GARMINDB_CONFIG_FILE = os.path.join(GARMINDB_DATA_DIR, 'GarminConnectConfig.json')
GARMINDB_DATABASE_PATH = os.path.join(GARMINDB_DATA_DIR, 'garmin.db')

# --- !! IMPORTANT WARNINGS !! ---
# Copied from previous versions - still relevant
# 1. EPHEMERAL FILESYSTEM...
# 2. SECURITY...
# 3. TIMEOUTS...
# ---

# --- Configuration File Handling ---
DEFAULT_CONFIG_STRUCTURE = {
    "connection": { "username": "", "password": "", "authentication_method": "GARMIN", },
    "settings": {
        "data_directory": GARMINDB_DATA_DIR,
        "database": { "name": "garmin.db", },
        "download": { "data_types": ["activities",] }
    }
}

def ensure_data_dir_exists():
    """Creates the data directory if it doesn't exist."""
    try:
        os.makedirs(GARMINDB_DATA_DIR, exist_ok=True)
    except OSError as e:
        logging.error(f"Error creating data directory {GARMINDB_DATA_DIR}: {e}")
        raise

def load_config_template():
    """Loads the config structure."""
    ensure_data_dir_exists()
    return DEFAULT_CONFIG_STRUCTURE.copy()

def update_config_file(username, password):
    """Safely updates the config file with new credentials."""
    logging.info(f"Attempting to update config file for user: {username}")
    try:
        ensure_data_dir_exists()
        config_data = load_config_template()
        config_data['connection']['username'] = username
        config_data['connection']['password'] = password

        temp_fd, temp_path = tempfile.mkstemp(dir=GARMINDB_DATA_DIR)
        logging.debug(f"Writing config to temporary file: {temp_path}")
        with os.fdopen(temp_fd, 'w') as tf:
            json.dump(config_data, tf, indent=4)
        os.rename(temp_path, GARMINDB_CONFIG_FILE)
        logging.info(f"Successfully updated config file: {GARMINDB_CONFIG_FILE}")
        return True
    except Exception as e:
        logging.error(f"Error updating config file {GARMINDB_CONFIG_FILE}: {e}", exc_info=True)
        if 'temp_path' in locals() and os.path.exists(temp_path):
            try: os.remove(temp_path)
            except OSError as rm_e: logging.error(f"Error removing temp update file {temp_path}: {rm_e}")
        return False

def clear_credentials_in_config():
    """Overwrites the config file removing credentials for security."""
    logging.info("Attempting to clear credentials from config file.")
    try:
        ensure_data_dir_exists()
        config_data = load_config_template()
        config_data['connection']['username'] = ""
        config_data['connection']['password'] = ""

        temp_fd, temp_path = tempfile.mkstemp(dir=GARMINDB_DATA_DIR)
        logging.debug(f"Writing cleared config to temporary file: {temp_path}")
        with os.fdopen(temp_fd, 'w') as tf:
            json.dump(config_data, tf, indent=4)
        os.rename(temp_path, GARMINDB_CONFIG_FILE)
        logging.info(f"Successfully cleared credentials from config file: {GARMINDB_CONFIG_FILE}")
        return True
    except FileNotFoundError:
        logging.warning(f"Config file {GARMINDB_CONFIG_FILE} not found while trying to clear credentials. Ignoring.")
        return True
    except Exception as e:
        logging.error(f"Error clearing credentials from config file {GARMINDB_CONFIG_FILE}: {e}", exc_info=True)
        if 'temp_path' in locals() and os.path.exists(temp_path):
            try: os.remove(temp_path)
            except OSError as rm_e: logging.error(f"Error removing temp clear file {temp_path}: {rm_e}")
        return False

# --- Flask Routes ---

@app.route('/')
def index():
    """Serves the main HTML page."""
    return render_template('index.html')

@app.route('/login-and-fetch', methods=['POST'])
def login_and_fetch():
    """Receives credentials, runs GarminDB sync, queries data, returns results."""
    logging.info("Received request on /login-and-fetch")
    data = request.get_json()
    if not data:
        logging.warning("Request received without JSON data.")
        return jsonify({"error": "Invalid request. JSON data required."}), 400

    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        logging.warning("Request received without username or password.")
        return jsonify({"error": "Username and password required"}), 400

    # 1. Update the config file
    if not update_config_file(username, password):
         logging.error("Failed to update configuration before running sync.")
         return jsonify({"error": "Server error: Failed to update configuration. Check server logs."}), 500

    activities = []
    sync_success = False

    # --- Runtime Environment Diagnostic Block ---
    logging.info("--- Checking Runtime Environment ---")
    try:
        logging.info(f"Python Executable: {sys.executable}")
        logging.info(f"Python Version: {sys.version}")
        logging.info(f"Runtime sys.path: {sys.path}")

        # Check direct import
        try:
            import garmindb
            logging.info(">>> Successfully imported 'garmindb' module directly.")
        except ImportError as imp_err:
            logging.error(f">>> FAILED to import 'garmindb' module directly: {imp_err}")

        # Check packages via pip freeze
        logging.info("Running 'pip freeze' check...")
        reqs_process = subprocess.run(
            [sys.executable, '-m', 'pip', 'freeze'],
            capture_output=True, text=True, check=True, timeout=15
        )
        installed_packages_list = reqs_process.stdout.strip().split('\n')
        logging.info(f"Output of 'pip freeze' at runtime:\n{reqs_process.stdout.strip()}")
        if any('garmindb' in pkg.lower() for pkg in installed_packages_list):
             logging.info(">>> garmindb package IS found in pip freeze output.")
        else:
             logging.warning(">>> garmindb package IS NOT found in pip freeze output!")

        # Check contents of venv bin directory
        venv_bin_dir = os.path.dirname(sys.executable)
        logging.info(f"Checking contents of venv bin directory: {venv_bin_dir}")
        try:
            bin_contents = os.listdir(venv_bin_dir)
            logging.info(f"Contents: {bin_contents}")
            # Check specifically for the 'garmindb' *script* file
            if 'garmindb' in bin_contents:
                logging.info(">>> 'garmindb' executable script IS found in venv/bin.")
            else:
                logging.warning(">>> 'garmindb' executable script IS NOT found in venv/bin!")
        except Exception as list_e:
            logging.error(f"Could not list venv bin directory: {list_e}")

    except Exception as e:
        logging.error(f"Could not run runtime environment checks: {e}", exc_info=True)
    logging.info("--- End Runtime Environment Check ---")
    # --- End diagnostic block ---

    # --- Main Execution Block ---
    try:
        venv_bin_dir = os.path.dirname(sys.executable)
        GARMINDB_CLI_PY_PATH = os.path.join(venv_bin_dir, 'garmindb_cli.py')
        logging.info(f"Attempting to execute script file directly: {GARMINDB_CLI_PY_PATH}")
        # 2. Run GarminDB sync process using python -m
        logging.info(f"Running GarminDB command via python -m.")
        command = [
            sys.executable,             # Use absolute path to python
            '-m',
            'garmindb.garmindb_cli',
            # --- Arguments ---
            '--activities',
            '--download',
            '--import',
            '--analyze',
            '--latest'
        ]

        # Execute the command - NO cwd or env arguments
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True # Raises CalledProcessError on non-zero exit
            # timeout=120, # Optional: Add timeout
        )

        logging.info(f"GarminDB sync process successful. Output:\n{process.stdout}")
        sync_success = True

        # 3. Query the Database
        logging.info(f"Querying database file: {GARMINDB_DATABASE_PATH}")
        if not os.path.exists(GARMINDB_DATABASE_PATH):
             logging.warning("Database file not found after sync. Cannot query.")
             return jsonify({"success": True, "activities": [], "message": "Sync ran, but no database file found or no new data."})

        conn = sqlite3.connect(GARMINDB_DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT activity_id, activity_name, start_time_gmt, distance, duration
            FROM activities ORDER BY start_time_gmt DESC LIMIT 10
        """)
        activities = [dict(row) for row in cursor.fetchall()]
        conn.close()
        logging.info(f"Successfully queried {len(activities)} activities from database.")
        return jsonify({"success": True, "activities": activities})

    # --- Exception Handling ---
    except subprocess.CalledProcessError as e:
        # This is where "No module named garmindb.garmindb_cli" will likely end up
        logging.error(f"GarminDB Command Failed! Return Code: {e.returncode}")
        logging.error(f"Stderr:\n{e.stderr}") # Check stderr for the exact error
        logging.error(f"Stdout:\n{e.stdout}")
        return jsonify({"error": "Failed to run sync process. Check server logs for details (Stderr might contain the reason)."}), 500
    except subprocess.TimeoutExpired as e:
        logging.error(f"GarminDB command timed out after {e.timeout} seconds.")
        logging.error(f"Stderr:\n{e.stderr}")
        logging.error(f"Stdout:\n{e.stdout}")
        return jsonify({"error": f"Data sync timed out after {e.timeout} seconds."}), 504
    except FileNotFoundError:
        # This error means the *python executable itself* wasn't found - extremely unlikely here
        logging.critical(f"CRITICAL: Python executable not found at: {sys.executable}", exc_info=True)
        return jsonify({"error": "Server configuration error: Python executable not found."}), 500
    except sqlite3.Error as e:
        logging.error(f"Database Query Error: {e}", exc_info=True)
        if sync_success:
            return jsonify({"success": True, "activities": [], "message": "Sync may have succeeded, but failed to read data afterwards."})
        else:
            return jsonify({"error": "Database error occurred after sync attempt. Check server logs."}), 500
    except Exception as e:
        logging.error(f"An unexpected error occurred during login/fetch: {e}", exc_info=True)
        return jsonify({"error": "An unexpected server error occurred. Check server logs."}), 500
    finally:
        # 4. Clear credentials
        if not clear_credentials_in_config():
             logging.critical("CRITICAL WARNING: Failed to clear credentials from config file after fetch attempt!")


@app.route('/get-data', methods=['GET'])
def get_data():
    """Fetches and returns existing data from the database file."""
    logging.info("Received request on /get-data")
    activities = []
    try:
        if not os.path.exists(GARMINDB_DATABASE_PATH):
            logging.info("Database file not found. Returning empty data.")
            return jsonify({"activities": [], "message": "No data found. Please login and sync first."})

        logging.info(f"Querying database file: {GARMINDB_DATABASE_PATH}")
        conn = sqlite3.connect(GARMINDB_DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT activity_id, activity_name, start_time_gmt, distance, duration
            FROM activities ORDER BY start_time_gmt DESC LIMIT 20
        """)
        activities = [dict(row) for row in cursor.fetchall()]
        conn.close()
        logging.info(f"Successfully queried {len(activities)} activities for get-data.")
        return jsonify({"activities": activities})

    except sqlite3.Error as e:
        logging.error(f"Database query error on get-data: {e}", exc_info=True)
        return jsonify({"error": "Database error occurred reading data. Check server logs."}), 500
    except Exception as e:
        logging.error(f"An unexpected error occurred during get-data: {e}", exc_info=True)
        return jsonify({"error": "An unexpected server error occurred reading data. Check server logs."}), 500

# --- End of Flask Routes ---

# No if __name__ == '__main__': block for production deployment with Gunicorn