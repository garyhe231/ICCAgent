"""Configuration for the ICC AI Agent."""
import os

# Supported trade lanes
TRADE_LANES = {
    "TPEB": {
        "label": "Trans-Pacific Eastbound",
        "origins": ["China Base Ports", "SEA"],
        "destinations": ["PSW", "PNW", "EC", "Gulf"],
        "port_pairs": [
            ("China Base Ports", "PSW"),
            ("China Base Ports", "PNW"),
            ("China Base Ports", "EC"),
            ("China Base Ports", "Gulf"),
            ("SEA", "PSW"),
            ("SEA", "EC"),
        ],
    },
    "FEWB": {
        "label": "Far East Westbound",
        "origins": ["China Base Ports", "SEA", "NEA"],
        "destinations": ["North Europe", "Med"],
        "port_pairs": [
            ("China Base Ports", "North Europe"),
            ("China Base Ports", "Med"),
            ("SEA", "North Europe"),
            ("SEA", "Med"),
            ("NEA", "North Europe"),
        ],
    },
}

# Default trade lane (backwards compat)
TRADE_LANE = "TPEB"
ORIGIN_REGIONS = TRADE_LANES["TPEB"]["origins"]
DESTINATION_GROUPS = TRADE_LANES["TPEB"]["destinations"]

# Output dir for saved briefings
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Data dir for local Phase-0 seed data
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
