# src/main.py

import os
import sys
import json
import time
import requests
import random
import psycopg2
import util
import config

from fusionsolar import Client
from requests.exceptions import RequestException, ConnectionError

# CONSTANTS

# DATABASE FUNCTIONS

def push_to_database(conn, plant_name, power_mode_data, plant_code_from_station):
    """ 
    Pushes the power control mode data to the database.
    
    @conn: Database connection object
    @plant_name: Name of the plant
    @power_mode_data: Data returned from the API for the plant
    @plant_code_from_station: Plant code from the station data
    @returns: Boolean flag indicating database push success or failure
    """
    plant_code = None
    data_block = {}
    is_success = False

    # Determine whether the plant device is online or offline
    if power_mode_data and power_mode_data.get('success'):
        is_success = True
        data_block = power_mode_data.get('data', {})
        plant_code = data_block.get('plantCode')

    if not plant_code:
        plant_code = plant_code_from_station

    control_mode = data_block.get('controlMode')
    kw_param = data_block.get('limitedPowerGridValueParam')
    percent_param = data_block.get('limitedPowerGridPercentParam')
    zero_param = data_block.get('zeroExportLimitationParam')

    # SQL QUERY
    sql = f"""
        INSERT INTO {config.DB_TARGET_TABLE} (plant_code, plant_name, api_success, control_mode, limited_kw_param, limited_percent_param, zero_export_param, last_updated)
        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (plant_code) DO UPDATE SET
            plant_name = EXCLUDED.plant_name,
            api_success = EXCLUDED.api_success,
            control_mode = EXCLUDED.control_mode,
            limited_kw_param = EXCLUDED.limited_kw_param,
            limited_percent_param = EXCLUDED.limited_percent_param,
            zero_export_param = EXCLUDED.zero_export_param,
            last_updated = NOW();
    """

    # Run the query to database
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (
                plant_code, plant_name, is_success, control_mode,
                json.dumps(kw_param), json.dumps(percent_param), json.dumps(zero_param)
            ))
        conn.commit()
        print(f"\n[INFO]: Data for plant '{plant_code}' saved to database.")
        return True
    except Exception as e:
        conn.rollback()
        print(f"[DATABASE ERROR]: Failed to save data for plant '{plant_code}'. Error: {e}")
        return False

# STATE FUNCTIONS

def load_state():
    """
    Loads the last processed plant code from the state file.
    """
    print(f"[INFO]: Loading state from '{config.STATE_FILE_PATH}'.")
    try:
        with open(config.STATE_FILE_PATH, 'r') as f:
            state = json.load(f)
            last_processed_code = state.get("last_processed_plant_code")
            if last_processed_code:
                print(f"[INFO]: State loading successful.")
                print(f"[INFO]: Last plant was '{last_processed_code}'. Resuming from the next plant.")
                return last_processed_code
            else:
                print("[INFO]: State file is empty. Starting from the first plant.")
                return None
    except FileNotFoundError:
        print("[INFO]: State file not found. Starting from the first plant.")
        return None
    except (json.JSONDecodeError, Exception) as e:
        print(f"[ERROR]: Could not read state file. Error: {e}")
        return None

def save_state(plant_code):
    """
    Saves the last successfully processed plant code to the state file.
    
    @plant_code: The unique code of the last processed plant
    """
    state = {"last_processed_plant_code": plant_code}

    if not os.path.exists(config.STATE_FILE_DIR):
        try:
            os.makedirs(config.STATE_FILE_DIR)
            print(f"[INFO]: Created state directory at {config.STATE_FILE_DIR}.")
        except Exception as e:
            print(f"[ERROR]: Could not create state directory. Error: {e}")
            return

    try:
        with open(config.STATE_FILE_PATH, 'w') as f:
            json.dump(state, f, indent=4)
    except Exception as e:
        print(f"\n[ERROR]: Could not save state. Error: {e}")

# API REQUEST FUNCTIONS

def fetch_stations(client, max_retries=3):
    """
    Fetch the list of stations (plants) from the FusionSolar API.
    
    @client: Instance of the FusionSolar API client
    @max_retries: Maximum number of retry attempts
    """
    print("[INFO]: Fetching station list.")

    retries = 0
    while retries <= max_retries:
        try:
            stations = client.get_station_list().get('data', [])
            if stations:
                print(f"[INFO]: Station list fetch successful.")
                return stations

            print("[API FETCH ERROR]: No station data found.")
            retries += 1
            if retries <= max_retries:
                delay = 5 * (2 ** (retries - 1))
                print(f"[INFO]: Retrying in {delay} seconds (attempt {retries}/{max_retries})...")
                time.sleep(delay)
            else:
                print("[ERROR]: Maximum retries reached. Exiting.")
                sys.exit(1)
        except Exception as e:
            retries += 1
            if retries > max_retries:
                print(f"[ERROR]: Maximum retries reached. Last error: {e}")
                sys.exit(1)

            delay = 5 * (2 ** (retries - 1))
            print(f"[WARNING]: Error fetching stations: {e}. Retrying in {delay} seconds (attempt {retries}/{max_retries})...")
            time.sleep(delay)

    print("[API FETCH ERROR]: No station data found after retries.")
    sys.exit(1)

def fetch_plant_power_control_data(client, plant_code, plant_name):
    """
    Query the API for a specific plant's power control mode.
    
    @client: Instance of the FusionSolar API client
    @plant_code: Unique code of the plant
    @plant_name: Name of the plant for display purposes
    """
    print(f"[INFO]: Processing '{plant_name}' ({plant_code}).")

    api_url = f"https://{config.FS_DOMAIN}/rest/openapi/pvms/nbi/v1/configuration/active-power-control-mode"
    payload = {"plantCode": plant_code}

    response = _api_request_with_retry(client, api_url, payload)
    
    if response is None:
        return None
        
    if response.status_code == 200:
        power_mode_data = response.json()
        if power_mode_data.get('success'):
            return power_mode_data
        else:
            print(f"\n[API CALL FAILURE]: {power_mode_data.get('message')}")
    else:
        print(f"\n[HTTP ERROR]: {response.status_code}")
    return None

def display_power_control_data(plant_data, power_mode_data, plant_name):
    """
    Display the collected power control mode data for a single plant.
    
    @plant_data: Data returned from the API for the plant
    @power_mode_data: Power control mode data for the plant
    @plant_name: Name of the plant for display purposes
    """
    print(f"\n===== API RESPONSE FOR {plant_name} =====")
    print(json.dumps(plant_data, indent=4))
    print("=========================")

    if power_mode_data and power_mode_data.get('success'):
        data = power_mode_data.get('data', {})
        control_mode = data.get('controlMode')
        print(f"Control Mode: {control_mode}")

        # Extract data for each mode
        if control_mode == 'noLimit':
            print("Mode is 'noLimit'. No further parameters.")
        elif control_mode == 'limitedPowerGridKW':
            params = data.get('limitedPowerGridValueParam', {})
            print(f"Mode is 'limitedPowerGridKW': {params}")
        elif control_mode == 'limitedPowerGridPercent':
            params = data.get('limitedPowerGridPercentParam', {})
            print(f"Mode is 'limitedPowerGridPercent': {params}")
        elif control_mode == 'zeroExportLimitation':
            params = data.get('zeroExportLimitationParam', {})
            print(f"Mode is 'zeroExportLimitation': {params}")
    else:
        if power_mode_data:
            print(f"[API CALL FAILURE]: {power_mode_data.get('message')}")
        else:
            print("[API CALL FAILURE]: No valid response received")

def _api_request_with_retry(client, url, payload, max_retries=3, base_delay=5):
    """
    Make an API request with automatic retry on failure.
    
    @client: FusionSolar client with active session
    @url: API endpoint URL
    @payload: Request payload (JSON)
    @max_retries: Maximum number of retry attempts
    @base_delay: Base delay between retries (will be increased exponentially)
    """
    retries = 0
    while retries <= max_retries:
        try:
            response = client.session.post(url=url, json=payload, timeout=30)
            return response
        except (ConnectionError, RequestException) as e:
            retries += 1
            if retries > max_retries:
                print(f"[ERROR]: Maximum retries reached. Last error: {e}")
                return None

            delay = base_delay * (2 ** (retries - 1)) + random.uniform(0, 1)
            print(f"\n[WARNING]: Connection error: {e}. Retrying in {delay:.1f} seconds (attempt {retries}/{max_retries})...")
            time.sleep(delay)
    return None

# MAIN FUNCTION

def get_power_control_mode(plant_limit=None, cooldown_seconds=60, max_retries=3):
    """ 
    Get the power control mode of a plant and push it to the database.
    
    @plant_limit: Limit on the number of plants to process
    @cooldown_seconds: Seconds to wait between processing each plant
    @max_retries: Maximum number of retries for API requests
    """
    db_conn = None
    exit_code = 0
    try:
        util.clear_screen()

        # Connect to the database
        print("[INFO]: Connecting to the local PostgreSQL database.")
        db_conn = psycopg2.connect(
            host=config.HOST, database=config.DATABASE,
            user=config.DB_USERNAME, password=config.DB_PASSWORD
        )
        print("[INFO]: Database connection successful.")

        # Login to the FusionSolar API
        with Client(user_name=config.FS_USERNAME, system_code=config.FS_PASSWORD) as client:
            start_index = 0
            all_stations = fetch_stations(client, max_retries) # Get all stations from the API
            last_processed_code = load_state() # Load the last processed plant
            if last_processed_code:
                station_codes = [s['stationCode'] for s in all_stations]
                try:
                    start_index = station_codes.index(last_processed_code) + 1
                except ValueError:
                    print(f"[WARNING]: Last processed plant '{last_processed_code}' not in API list. Restarting.")

            # Limiter (if specified)
            stations_to_process = all_stations[start_index:]
            if plant_limit:
                stations_to_process = stations_to_process[:plant_limit]

            # Todo buffer for total plants to process
            # Delete the state file when collection is complete
            total_to_process = len(stations_to_process)
            if total_to_process == 0:
                print("\n[INFO]: All plants are up to date. Exiting.")
                try:
                    if os.path.exists(config.STATE_FILE_PATH):
                        os.remove(config.STATE_FILE_PATH)
                        print("[INFO]: State file deletion successful.")
                except Exception as e:
                    print(f"[ERROR]: Could not delete state file. Error: {e}")
                    sys.exit(1)
                return 
            print(f"[INFO]: Found {len(all_stations)} plants in total. {total_to_process} plants left to process.")

            # Initial cooldown
            print("[INFO]: Initializing collector. Loading...")
            time.sleep(cooldown_seconds)

            # Loop through each station
            for index, station in enumerate(stations_to_process):
                plant_code = station['stationCode']
                plant_name = station['stationName']
                print(f"\n[INFO]: Processing station {index + 1} of {total_to_process}.")
                
                # Fetch data
                power_mode_response = fetch_plant_power_control_data(client, plant_code, plant_name)

                # Push to database
                if power_mode_response is not None:
                    plant_data = power_mode_response.get('data', {})
                    display_power_control_data(plant_data, power_mode_response, plant_name) # Display the data
                    db_success = push_to_database(db_conn, plant_name, power_mode_response, plant_code)
                    if db_success:
                        save_state(plant_code) # Save the existing processed plant
                    else:
                        print(f"\n[WARNING]: Database push failed for {plant_code}. State NOT updated. This plant will be retried on next run.")
                else:
                    print(f"\n[WARNING]: No data received from '{plant_name}'.")
                    failure_payload = {
                        "success": False,
                        "message": "Failed to retrieve data after multiple retries."
                    }
                    db_success = push_to_database(db_conn, plant_name, failure_payload, plant_code)
                    if not db_success:
                        print(f"[WARNING]: Database push failed for '{plant_code}'.")

                # Cooldown
                # NOTE: Different endpoints may have different cooldown requirements
                if index < total_to_process - 1:
                    print(f"[INFO]: Waiting {cooldown_seconds} seconds before processing the next station...")
                    time.sleep(cooldown_seconds)
    except psycopg2.Error as e:
        print(f"[DATABASE ERROR]: {e}")
        exit_code = 1
    except Exception as e:
        print(f"[SCRIPT ERROR]: {e}")
        exit_code = 1
    finally:
        if db_conn is not None:
            db_conn.close()
            print("\n[INFO]: Database connection closed.")
            print("[INFO]: Exiting script.")
            sys.exit(exit_code)

# DRIVER CODE

if __name__ == "__main__":
    get_power_control_mode()