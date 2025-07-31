import json
import logging
from pathlib import Path

def load_config():
    try:
        config_path = Path(__file__).parent / "config.json"
        with open(config_path) as f:
            config = json.load(f)
        
        # Set up logging
        logging.basicConfig(
            level=config.get("log_level", "INFO"),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        return config
    except Exception as e:
        logging.error(f"Failed to load config: {e}")
        raise

# Create the config variable that will be imported
config = load_config()