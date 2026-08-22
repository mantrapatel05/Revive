import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv('DATA_DIR', BASE_DIR / 'data/generated'))
RESULTS_DIR = Path(os.getenv('RESULTS_DIR', BASE_DIR / 'data/evaluation'))
MODEL_DIR = Path(os.getenv('MODEL_DIR', BASE_DIR / 'models'))
MODEL_PATH = Path(os.getenv('MODEL_PATH', MODEL_DIR / 'calibrated_tlearner.joblib'))
DATABASE_PATH = Path(os.getenv('DATABASE_PATH', BASE_DIR / 'revive.db'))
RAZORPAY_KEY_ID = os.getenv('RAZORPAY_KEY_ID', '')
RAZORPAY_KEY_SECRET = os.getenv('RAZORPAY_KEY_SECRET', '')
RAZORPAY_WEBHOOK_SECRET = os.getenv('RAZORPAY_WEBHOOK_SECRET', '')
GROQ_API_KEY = os.getenv('GROQ_API_KEY', os.getenv('OPENAI_API_KEY', ''))
GROQ_MODEL = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')
OPENAI_API_KEY = GROQ_API_KEY
OPENAI_MODEL = GROQ_MODEL
ENABLE_TESTMODE_EXECUTION = os.getenv('ENABLE_TESTMODE_EXECUTION', 'false').lower() == 'true'
MAX_AUTO_ACTION_AMOUNT = float(os.getenv('MAX_AUTO_ACTION_AMOUNT', '3000'))
MIN_RECOVERY_PROBABILITY = float(os.getenv('MIN_RECOVERY_PROBABILITY', '0.20'))
MODEL_VERSION = 'calibrated-tlearner-v5'
POLICY_VERSION = 'policy-v5'
PROMPT_VERSION = 'reasoning-v1'
SCENARIO_VERSION = 'sim-v5.0'
