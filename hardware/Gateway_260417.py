import serial
import time
import struct
import requests
import json
from datetime import datetime
import RPi.GPIO as GPIO

# ============================================================
# 설정 영역
# ============================================================
API_URL = "https://<api-id>.execute-api.ap-northeast-2.amazonaws.com/default/blackIceReciver"  # 실제 URL로 교체하세요
API_KEY = "YOUR_API_KEY_HERE"  # 실제 API 키로 교체하세요

M0 = 22
M1 = 27

# 페이로드 9바이트 (node_id 1 + freq 4 + temp 2 + hum 2) + RSSI 1바이트 = 10
EXPECTED_LENGTH = 10

# ============================================================
# 초기화
# ============================================================
GPIO.setmode(GPIO.BCM)
GPIO.setup([M0, M1], GPIO.OUT)
GPIO.output(M0, GPIO.LOW)
GPIO.output(M1, GPIO.LOW)

ser = serial.Serial('/dev/ttyAMA0', 9600, timeout=1)

def send_to_server(device_id, temperature, humidity, conductivity):
    sensor_data = {
        "device_id": device_id,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "temperature": temperature,
        "humidity": humidity,
        "conductivity": conductivity
    }

    headers = {
        "x-api-key": API_KEY,
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(API_URL, data=json.dumps(sensor_data), headers=headers)
        if response.status_code == 200:
            print(f"[서버 전송 성공] {response.text}")
        else:
            print(f"[서버 전송 실패] 상태 코드 {response.status_code}: {response.text}")
    except Exception as e:
        print(f"[서버 통신 에러] {e}")

# ============================================================
# 메인 루프
# ============================================================
try:
    print("=== LoRa 수신 + 서버 전송 대기 중 ===")
    while True:
        if ser.in_waiting >= EXPECTED_LENGTH:
            time.sleep(0.05)
            raw_data = ser.read(ser.in_waiting)

            if len(raw_data) >= EXPECTED_LENGTH:
                packet = raw_data[-EXPECTED_LENGTH:]
                payload = packet[:-1]   # 앞 9바이트: 실제 데이터
                rssi_byte = packet[-1]  # 마지막 1바이트: RSSI

                try:
                    # '<BIhH' = 리틀엔디안, uint8 + uint32 + int16 + uint16
                    device_id, freq_raw, temp_raw, hum_raw = struct.unpack('<BIhH', payload)

                    freq = freq_raw / 100.0
                    temp = temp_raw / 10.0
                    hum = hum_raw / 10.0
                    rssi_dbm = -(256 - rssi_byte)

                    print("-" * 50)
                    print(f"노드 ID: {device_id}")
                    if temp == -99.9 or hum == 99.9:
                        print("경고: DHT 센서 측정 오류 (에러 코드 수신)")
                    else:
                        print(f"노면 주파수: {freq:.2f} Hz | 온도: {temp:.1f} °C | 습도: {hum:.1f} %")
                        send_to_server(
                            device_id=device_id,
                            temperature=temp,
                            humidity=hum,
                            conductivity=freq
                        )

                    print(f"신호 강도(RSSI): {rssi_dbm} dBm")

                except struct.error as e:
                    print(f"구조체 파싱 에러 발생: {e}")
            else:
                print("유효하지 않은 패킷 길이")

        time.sleep(0.1)

except KeyboardInterrupt:
    print("\n프로그램 종료")
    ser.close()
    GPIO.cleanup()