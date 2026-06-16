from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / 'data'
STATIC_DIR = BASE_DIR / 'static'
DB_PATH = DATA_DIR / 'blackice.db'

#서버 설정
HOST = os.getenv('BLACKICE_HOST', '0.0.0.0')
PORT = int(os.getenv('BLACKICE_PORT', '8000'))
GATEWAY_PORT = int(os.getenv('BLACKICE_GATEWAY_PORT', '8001'))
SERVER_PORT = int(os.getenv('BLACKICE_SERVER_PORT', '8002'))
SERVER_URL = os.getenv('BLACKICE_SERVER_URL', f'http://localhost:{SERVER_PORT}')
#학교 위도 경도
SCHOOL_NAME = os.getenv('BLACKICE_SCHOOL_NAME', '성결대학교')
SCHOOL_LAT = float(os.getenv('BLACKICE_SCHOOL_LAT', '37.3802'))
SCHOOL_LON = float(os.getenv('BLACKICE_SCHOOL_LON', '126.9281'))
# 전도도 상태 판별 기준값 설정
CONDUCTIVITY_WET_MAX = 100
CONDUCTIVITY_FROZEN_MAX = 850
CONDUCTIVITY_DRY_MAX = 1000
#아마존 api (환경변수로 설정: BLACKICE_AWS_API_URL, BLACKICE_AWS_API_KEY)
AWS_API_URL = os.getenv('BLACKICE_AWS_API_URL', '')
AWS_API_KEY = os.getenv('BLACKICE_AWS_API_KEY', '')