import os
import sys
import subprocess
import sqlite3
import json
import tempfile
import logging
from flask import Flask, request, jsonify, render_template

# --- Basic Logging Setup ---
# Helps with debugging on Render or locally
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Flask App Initialization ---
app = Flask(__name__)

# --- Configuration ---
# Use relative paths suitable for Render's ephemeral filesystem
# Files will be stored within the application directory but WILL BE LOST on restarts/redeploys.
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
# Using a subdirectory name less likely to conflict if user runs locally too
GARMINDB_DATA_DIR = os.path.join(APP_ROOT, '.garmindb_render_data')
GARMINDB_CONFIG_FILE = os.path.join(GARMINDB_DATA_DIR, 'GarminConnectConfig.json')
GARMINDB_DATABASE_PATH = os.path.join(GARMINDB_DATA_DIR, 'garmin.db') # Assuming default DB name

# --- !! IMPORTANT WARNINGS !! ---
# 1. EPHEMERAL FILESYSTEM: On Render's Free Tier, the GARMINDB_DATA_DIR and its
#    contents (config file, database) WILL BE DELETED when the app restarts
#    (due to inactivity, deployment, crash, etc.). Users will need to re-login
#    and re-sync data frequently. Consider Render Disks (paid) for persistence.
# 2. SECURITY: Writing credentials temporarily to a file, even on an ephemeral
#    filesystem, carries risks. Ensure Render environment variables/secrets
#    are used if possible for sensitive data in more complex setups, although
#    GarminDB primarily relies on the JSON config file.
# 3. TIMEOUTS: GarminDB syncs (especially the first --all) can take longer than
#    typical web request timeouts (e.g., 30-60 seconds). The `/login-and-fetch`
#    endpoint might fail on long syncs. Using `--latest` helps, but robust
#    handling requires background workers (paid feature).
# ---

# --- Configuration File Handling ---

# Basic structure for the config file if it needs to be created
# Add essential fields based on GarminConnectConfig.json.example
# Adjust data_types as needed
DEFAULT_CONFIG_STRUCTURE = {
    "connection": {
        "username": "",
        "password": "",
        "authentication_method": "GARMIN", # Or "GOOGLE", "FACEBOOK"
        # Add other connection fields if necessary (mfa_secret, etc.)
    },
    "settings": {
        "data_directory": GARMINDB_DATA_DIR, # Tell garmindb where to work (might require garmindb support this) - check garmindb docs if this works
        "database": {
            "name": "garmin.db", # Default name
            # Add other database settings if needed
        },
        "download": {
             # Example: Add start/end dates if you want to control them via code
             # "start_date": "2010-01-01",
             # "end_date": None
             "data_types": [ # Specify data types you want to sync
                 "activities",
                 # "steps", "heart_rate", "sleep", etc.
             ]
         }
        # Add other top-level settings if needed
    }
}

def ensure_data_dir_exists():
    """Creates the data directory if it doesn't exist."""
    try:
        os.makedirs(GARMINDB_DATA_DIR, exist_ok=True)
        # Optional: Set permissions if needed, though may not work reliably on PaaS
        # os.chmod(GARMINDB_DATA_DIR, 0o700)
    except OSError as e:
        logging.error(f"Error creating data directory {GARMINDB_DATA_DIR}: {e}")
        # Decide if this is fatal or can be ignored
        raise # Re-raise the exception to signal failure

def load_config_template():
    """Loads the config structure, prioritizing existing file, then default."""
    ensure_data_dir_exists() # Make sure dir exists before trying to read
    config_data = DEFAULT_CONFIG_STRUCTURE.copy() # Start with default
    # Note: We don't actually read the existing file here to get a 'template'
    # because we always want to overwrite it completely in update_config_file
    # with the fresh credentials and default settings.
    # If you wanted to preserve other settings users might manually put in the
    # file (not feasible/recommended in this setup), you'd read the file here.
    return config_data

def update_config_file(username, password):
    """Safely updates the config file with new credentials."""
    logging.info(f"Attempting to update config file for user: {username}")
    try:
        ensure_data_dir_exists() # Ensure directory exists first
        config_data = load_config_template() # Get base structure

        # Update credentials (adjust path based on actual config structure)
        config_data['connection']['username'] = username
        config_data['connection']['password'] = password
        # Potentially update other fields if needed (e.g., auth_method)

        # Write to a temporary file first, then rename (atomic operation on most OS)
        # This avoids leaving a corrupted file if writing fails midway
        temp_fd, temp_path = tempfile.mkstemp(dir=GARMINDB_DATA_DIR)
        logging.debug(f"Writing config to temporary file: {temp_path}")
        with os.fdopen(temp_fd, 'w') as tf:
            json.dump(config_data, tf, indent=4)

        # Replace the actual config file with the temporary one
        os.rename(temp_path, GARMINDB_CONFIG_FILE)
        logging.info(f"Successfully updated config file: {GARMINDB_CONFIG_FILE}")
        # Optional: Set secure permissions (e.g., chmod 600 on Linux/macOS)
        # try:
        #     os.chmod(GARMINDB_CONFIG_FILE, 0o600)
        # except OSError as e:
        #     logging.warning(f"Could not set permissions on config file: {e}")
        return True

    except Exception as e:
        logging.error(f"Error updating config file {GARMINDB_CONFIG_FILE}: {e}")
        # Clean up temp file if rename failed and file exists
        if 'temp_path' in locals() and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logging.info(f"Removed temporary config file: {temp_path}")
            except OSError as rm_e:
                logging.error(f"Error removing temporary config file {temp_path}: {rm_e}")
        return False

def clear_credentials_in_config():
    """Overwrites the config file removing credentials for security."""
    logging.info("Attempting to clear credentials from config file.")
    try:
        ensure_data_dir_exists() # Ensure directory exists first
        config_data = load_config_template() # Get base structure

        # Ensure credentials are empty in the structure we write
        config_data['connection']['username'] = ""
        config_data['connection']['password'] = ""

        # Write to a temporary file first, then rename
        temp_fd, temp_path = tempfile.mkstemp(dir=GARMINDB_DATA_DIR)
        logging.debug(f"Writing cleared config to temporary file: {temp_path}")
        with os.fdopen(temp_fd, 'w') as tf:
            json.dump(config_data, tf, indent=4)

        os.rename(temp_path, GARMINDB_CONFIG_FILE)
        logging.info(f"Successfully cleared credentials from config file: {GARMINDB_CONFIG_FILE}")
        # try:
        #     os.chmod(GARMINDB_CONFIG_FILE, 0o600)
        # except OSError as e:
        #     logging.warning(f"Could not set permissions on cleared config file: {e}")
        return True

    except FileNotFoundError:
        logging.warning(f"Config file {GARMINDB_CONFIG_FILE} not found while trying to clear credentials. Ignoring.")
        return True # If file doesn't exist, credentials are clear
    except Exception as e:
        logging.error(f"Error clearing credentials from config file {GARMINDB_CONFIG_FILE}: {e}")
        # Clean up temp file if rename failed
        if 'temp_path' in locals() and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logging.info(f"Removed temporary config file during clearing error: {temp_path}")
            except OSError as rm_e:
                logging.error(f"Error removing temporary config file {temp_path} during clearing error: {rm_e}")
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

    # 1. Update the config file with received credentials
    if not update_config_file(username, password):
         logging.error("Failed to update configuration before running sync.")
         return jsonify({"error": "Server error: Failed to update configuration. Check server logs."}), 500

    activities = [] # Initialize activities list
    sync_success = False

    # --- Add this diagnostic block ---
    logging.info("--- Checking Runtime Environment ---")
    try:
        logging.info(f"Python Executable: {sys.executable}") # Ensure 'import sys' is at the top of app.py
        logging.info(f"Python Version: {sys.version}")
        logging.info(f"Runtime sys.path: {sys.path}") # Log Python's search path

        # Check direct import
        try:
            import garmindb
            logging.info(">>> Successfully imported 'garmindb' module directly.")
            # Optional: Check type or specific attribute if needed
            # logging.info(f"Type of imported garmindb: {type(garmindb)}")
        except ImportError as imp_err:
            logging.error(f">>> FAILED to import 'garmindb' module directly: {imp_err}")

        # Check packages via pip freeze
        logging.info("Running 'pip freeze' check...")
        reqs_process = subprocess.run(
            [sys.executable, '-m', 'pip', 'freeze'],
            capture_output=True, text=True, check=True, timeout=15 # Add timeout
        )
        installed_packages_list = reqs_process.stdout.strip().split('\n')
        logging.info(f"Output of 'pip freeze' at runtime:\n{reqs_process.stdout.strip()}")
        if any('garmindb' in pkg.lower() for pkg in installed_packages_list):
             logging.info(">>> garmindb package IS found in pip freeze output.")
        else:
             logging.warning(">>> garmindb package IS NOT found in pip freeze output!")

    except Exception as e:
        logging.error(f"Could not run runtime environment checks: {e}", exc_info=True)
    logging.info("--- End Runtime Environment Check ---")
    # --- End diagnostic block ---


    try:
        # 2. Run GarminDB sync process using the config file
        # Using --latest for incremental updates (faster, less likely to timeout)
        # Specify limited data types initially (e.g., --activities) to speed up.
        # Ensure garmindb command can correctly use config file in GARMINDB_DATA_DIR
        # It might need explicit --config or rely on being run with CWD set? Check docs.
        # Assuming it picks up config from CWD or standard location relative to execution.
        # The command might need adjustment based on how GarminDB finds its config/db.
        # Forcing current working directory *might* help if garmindb uses relative paths from CWD
        # cwd_to_run = GARMINDB_DATA_DIR
        cwd_to_run = APP_ROOT # Or maybe run from app root? Test what works.

        logging.info(f"Running GarminDB command. CWD: {cwd_to_run}")
        command = [
            'python',                   # Use the python interpreter directly
            '-m',                       # The flag to run a library module
            'garmindb.garmindb_cli',    # The specific module that contains the main() function for garmindb
            # --- Add the arguments for garmindb below ---
            '--activities',
            '--download',
            '--import',
            '--analyze',
            '--latest'
        ]

        # Execute the command
        # Using check=True raises CalledProcessError if command returns non-zero exit code
        # Set timeout if needed, but long syncs might exceed it anyway
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            # timeout=120, # Example: 2 minute timeout - adjust or remove
            cwd=cwd_to_run # Run command from this directory if needed by garmindb
        )

        logging.info(f"GarminDB sync process successful. Output:\n{process.stdout}")
        sync_success = True # Mark sync as successful

        # 3. Query the Database (only after successful sync)
        logging.info(f"Querying database file: {GARMINDB_DATABASE_PATH}")
        if not os.path.exists(GARMINDB_DATABASE_PATH):
             logging.warning("Database file not found after sync. Cannot query.")
             # Don't treat as fatal error if sync *appeared* successful but db missing
             # Could happen if no new data of the requested type was found?
             return jsonify({"success": True, "activities": [], "message": "Sync ran, but no database file found or no new data."})


        conn = sqlite3.connect(GARMINDB_DATABASE_PATH)
        conn.row_factory = sqlite3.Row # Return rows as dictionary-like objects
        cursor = conn.cursor()

        # Modify this query based on the actual GarminDB schema for activities table
        # Check table names and column names in the DB file created by garmindb
        cursor.execute("""
            SELECT activity_id, activity_name, start_time_gmt, distance, duration
            FROM activities
            ORDER BY start_time_gmt DESC
            LIMIT 10
        """)
        activities = [dict(row) for row in cursor.fetchall()]
        conn.close()
        logging.info(f"Successfully queried {len(activities)} activities from database.")

        return jsonify({"success": True, "activities": activities})

    except subprocess.CalledProcessError as e:
        logging.error(f"GarminDB Command Failed! Return Code: {e.returncode}")
        logging.error(f"Stderr:\n{e.stderr}")
        logging.error(f"Stdout:\n{e.stdout}")
        # Provide a generic error to the user, log details server-side
        return jsonify({"error": "Failed to sync data with Garmin. Check server logs for details."}), 500
    except subprocess.TimeoutExpired as e:
        logging.error(f"GarminDB command timed out after {e.timeout} seconds.")
        logging.error(f"Stderr:\n{e.stderr}")
        logging.error(f"Stdout:\n{e.stdout}")
        return jsonify({"error": f"Data sync timed out after {e.timeout} seconds. Try again later or sync less data."}), 504 # Gateway Timeout
    except FileNotFoundError:
         # This happens if the 'garmindb' command itself isn't found in the server's PATH
         logging.critical("CRITICAL: 'garmindb' command not found in PATH. Ensure it's installed in the deployment environment.")
         return jsonify({"error": "Server configuration error: garmindb command not found."}), 500
    except sqlite3.Error as e:
        logging.error(f"Database Query Error: {e}")
        # If sync succeeded but DB query failed, maybe return success but empty data?
        # Or signal error depending on desired behaviour.
        if sync_success:
            return jsonify({"success": True, "activities": [], "message": "Sync may have succeeded, but failed to read data afterwards."})
        else:
            return jsonify({"error": "Database error occurred after sync attempt. Check server logs."}), 500
    except Exception as e:
        # Catch any other unexpected errors
        logging.error(f"An unexpected error occurred during login/fetch: {e}", exc_info=True) # Log traceback
        return jsonify({"error": "An unexpected server error occurred. Check server logs."}), 500
    finally:
        # 4. IMPORTANT: Clear credentials from config file regardless of success/failure
        if not clear_credentials_in_config():
             # Log critical warning if cleanup fails, but don't necessarily block user response
             logging.critical("CRITICAL WARNING: Failed to clear credentials from config file after fetch attempt!")


@app.route('/get-data', methods=['GET'])
def get_data():
    """Fetches and returns existing data from the database file."""
    logging.info("Received request on /get-data")
    activities = []
    try:
        # Check if the database file exists first (it might not on ephemeral storage)
        if not os.path.exists(GARMINDB_DATABASE_PATH):
            logging.info("Database file not found. Returning empty data.")
            return jsonify({"activities": [], "message": "No data found. Please login and sync first."})

        logging.info(f"Querying database file: {GARMINDB_DATABASE_PATH}")
        conn = sqlite3.connect(GARMINDB_DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Adjust query as needed
        cursor.execute("""
            SELECT activity_id, activity_name, start_time_gmt, distance, duration
            FROM activities
            ORDER BY start_time_gmt DESC
            LIMIT 20
        """) # Fetch more for this route?
        activities = [dict(row) for row in cursor.fetchall()]
        conn.close()
        logging.info(f"Successfully queried {len(activities)} activities for get-data.")
        return jsonify({"activities": activities})

    except sqlite3.Error as e:
        logging.error(f"Database query error on get-data: {e}")
        return jsonify({"error": "Database error occurred reading data. Check server logs."}), 500
    except Exception as e:
        logging.error(f"An unexpected error occurred during get-data: {e}", exc_info=True) # Log traceback
        return jsonify({"error": "An unexpected server error occurred reading data. Check server logs."}), 500

# Note: The `if __name__ == '__main__': app.run(...)` block is removed
# as Gunicorn (or another WSGI server) will run the app in production.
# You can still add it back temporarily for local testing if needed,
# but ensure it's removed or commented out before deploying.
# Example for local testing:
# if __name__ == '__main__':
#     # Create data dir for local testing if it doesn't exist
#     ensure_data_dir_exists()
#     # Run with debug=True for development ONLY, use port other than 80/443
#     app.run(debug=True, port=5001, host='0.0.0.0')