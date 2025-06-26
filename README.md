# Fusion Solar Collector

This project collects power control mode data from Huawei FusionSolar plants via the FusionSolar API and stores it in a PostgreSQL database.

## Features

- Fetches a list of solar plants (stations) from FusionSolar.
- Queries each plant for its power control mode and relevant parameters.
- Stores the collected data in a PostgreSQL database.
- Supports resuming from the last processed plant in case of interruption.
- Handles API and database errors with retries and logging.

## Requirements

- Python 3.7+
- PostgreSQL database
- Required Python packages: `requests`, `psycopg2`

## Configuration

Edit the `config.py` file to set your FusionSolar API credentials, database connection details, and other settings.

## Usage

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
2. Run the collector:
   ```
   python src/main.py
   ```

The script will fetch data from the FusionSolar API and store it in your configured database. Progress is saved, so you can safely interrupt and resume the process.

## Notes

- Ensure your FusionSolar API credentials and database access are correct.
- The script respects API rate limits by waiting between requests.
- Check the logs for any errors or warnings.

## Extras

- Example query to create the target table:

   ```bash
   CREATE TABLE inverter_power_modes (
      plant_code VARCHAR(255) PRIMARY KEY,
      plant_name VARCHAR(255) NOT NULL,
      api_success BOOLEAN NOT NULL,
      control_mode VARCHAR(50),
      limited_kw_param JSONB,
      limited_percent_param JSONB,
      zero_export_param JSONB,
      last_updated TIMESTAMPTZ DEFAULT NOW() NOT NULL
   );
   ```

- Systemd script:

   ```bash
   [Unit]
   Description=Adam Fusion Solar Collector
   After=network-online.target
   Wants=network-online.target
   Requires=network-online.target

   [Service]
   # CODE DIR
   WorkingDirectory=/home/almalinux/adam/fusion-solar-collector/src

   # ENVIRONMENT
   User=almalinux
   Group=almalinux
   Environment="PATH=/home/almalinux/adam/fusion-solar-collector/venv/bin"

   # COMMAND
   ExecStart=/home/almalinux/adam/fusion-solar-collector/venv/bin/python main.py

   # RELIABILITY
   Restart=on-failure
   RestartSec=60
   StartLimitInterval=300
   StartLimitBurst=3

   # LOGGING
   StandardOutput=journal
   StandardError=journal

   # SECURITY
   NoNewPrivileges=true
   PrivateTmp=true

   [Install]
   WantedBy=multi-user.target
   ```