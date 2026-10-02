import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

class Settings:
    PROJECT_NAME: str = "Weather-Advisory Support Bot"
    PROJECT_VERSION: str = "1.0.0"
    
    # LLM Settings
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    MODEL_NAME: str = os.getenv("MODEL_NAME", "gpt-4o-mini")
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai").lower()
    
    # Server Settings
    BACKEND_HOST: str = os.getenv("BACKEND_HOST", "127.0.0.1")
    BACKEND_PORT: int = int(os.getenv("BACKEND_PORT", "8000"))
    
    # Weather API Settings
    OPEN_METEO_GEOCODING_URL: str = os.getenv(
        "OPEN_METEO_GEOCODING_URL", 
        "https://geocoding-api.open-meteo.com/v1/search"
    )
    OPEN_METEO_FORECAST_URL: str = os.getenv(
        "OPEN_METEO_FORECAST_URL", 
        "https://api.open-meteo.com/v1/forecast"
    )
    
    # Policies Path
    SOP_FILE_PATH: Path = ROOT_DIR / os.getenv("SOP_FILE_PATH", "policies/sops.yaml")
    
    # HTTP Timeouts
    API_TIMEOUT_SECONDS: float = 10.0

settings = Settings()
