from __future__ import annotations
import os
from datetime import datetime
import joblib
import pandas as pd

# 모델 파일 경로 설정 (필요시 절대 경로로 변경)
MODEL_PATH = os.path.join(os.path.dirname(__file__), 'conductivity_prediction_model.pkl')

# 전역 변수로 모델 로드 상태 관리
loaded_model = None

def load_model():
    global loaded_model
    if loaded_model is None:
        if os.path.exists(MODEL_PATH):
            loaded_model = joblib.load(MODEL_PATH)
            print("Model loaded successfully.")
        else:
            raise FileNotFoundError(f"모델 파일을 찾을 수 없습니다: {MODEL_PATH}")

def infer_road_state(temperature_c: float, humidity_pct: float, frequency_hz: float, hour: int = None) -> tuple[str, int, str]:

    # 모델 로드 (이미 로드된 경우 건너뜀)
    load_model()
    
    # 시간 값이 주어지지 않은 경우 시스템의 현재 시간 사용
    if hour is None:
        hour = datetime.now().hour
        
    conductivity = frequency_hz
    
    # 모델 입력을 위한 데이터프레임 생성 (학습된 특성 순서 유지)
    new_data = pd.DataFrame(
        [[hour, temperature_c, humidity_pct, conductivity]],
        columns=['time_hour', 'temperature', 'humidity', 'conductivity']
    )
    
    # 예측 수행
    prediction = loaded_model.predict(new_data)[0]
    
    # AI 예측 결과 문자열을 기존 시스템의 status 및 score로 매핑
    if "안전" in prediction:
        status = 'safe'
        score = 10
    elif "빗길" in prediction or "조심" in prediction:
        status = 'caution'
        score = 60
    elif "눈길" in prediction or "위험" in prediction or "결빙" in prediction:
        status = 'danger'
        score = 95
    else:
        status = 'unknown'
        score = 0
        
    # 결과 사유 작성
    reasons = f"AI 모델 예측: {prediction} (시간:{hour}시, 온도:{temperature_c}, 습도:{humidity_pct}, 전도도:{conductivity})"
    
    return status, score, reasons