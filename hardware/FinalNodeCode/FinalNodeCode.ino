#include <SoftwareSerial.h>
#include <DHT.h>
#include <LowPower.h>

// --- 핀 정의 ---
SoftwareSerial loRaSerial(2, 4);
#define DHTPIN 5
#define DHTTYPE DHT22
DHT dht(DHTPIN, DHTTYPE);

#define FREQ_PIN 3
#define LORA_M0  6
#define LORA_M1  7
#define LORA_AUX 8

// --- 설정 값 ---
const uint8_t NODE_ID = 1;      // uint8로 변경 (게이트웨이: B = 1바이트)
const int SLEEP_MINUTES = 15;

// --- 게이트웨이 파싱 구조에 맞춘 패킷 (9바이트) ---
// Python: struct.unpack('<BIhH', payload)
//   B  = uint8  node_id      (1B)
//   I  = uint32 freq*100     (4B)
//   h  = int16  temp*10      (2B)
//   H  = uint16 hum*10       (2B)
struct __attribute__((packed)) LoRaPacket {
  uint8_t  node_id;       // 1B
  uint32_t freq_raw;      // 4B  (실제 주파수 × 100)
  int16_t  temp_raw;      // 2B  (실제 온도 × 10)
  uint16_t hum_raw;       // 2B  (실제 습도 × 10)
}; // 총 9바이트 — 게이트웨이 EXPECTED_LENGTH - 1(RSSI)과 일치

void setup() {
  Serial.begin(9600);
  loRaSerial.begin(9600);
  dht.begin();

  pinMode(FREQ_PIN, INPUT);
  pinMode(LORA_M0, OUTPUT);
  pinMode(LORA_M1, OUTPUT);
  pinMode(LORA_AUX, INPUT);

  randomSeed(analogRead(0) + NODE_ID);

  //Serial.println(F("=== LoRa Node Start (Binary 9B) ==="));
}

void loop() {
  // [1] 랜덤 백오프 — 다중 노드 충돌 방지
  int jitter = random(0, 5000);
  //Serial.print(F("Jitter: ")); Serial.print(jitter); Serial.println(F("ms"));
  delay(jitter);

  // [2] LoRa Normal Mode
  digitalWrite(LORA_M0, LOW);
  digitalWrite(LORA_M1, LOW);
  delay(10);

  // [3] 센서 측정
  float t = dht.readTemperature();
  float h = dht.readHumidity();
  float freq = getFrequencyFloat();

  // [4] 패킷 생성 — 정수화하여 게이트웨이 포맷에 맞춤
  LoRaPacket packet;
  packet.node_id = NODE_ID;
  packet.freq_raw = (uint32_t)(freq * 100.0f);

  if (isnan(t) || isnan(h)) {
    packet.temp_raw = -999;   // 게이트웨이: -999/10 = -99.9 → 에러 판정
    packet.hum_raw  = 999;    // 게이트웨이:  999/10 =  99.9 → 에러 판정
    // Serial.println(F("[DHT ERROR] sending error code"));
  } else {
    packet.temp_raw = (int16_t)(t * 10.0f);
    packet.hum_raw  = (uint16_t)(h * 10.0f);
  }

  // [5] 디버그 출력
  //Serial.print(F("TX ID:")); Serial.print(packet.node_id);
  //Serial.print(F(" F:"));    Serial.print(freq, 2);
  //Serial.print(F("Hz T:"));  Serial.print(isnan(t) ? -99.9f : t, 1);
  //Serial.print(F("C H:"));   Serial.print(isnan(h) ? 99.9f : h, 1);
  //Serial.println(F("%"));

  // HEX 덤프 (게이트웨이 디버깅용)
  //Serial.print(F("HEX: "));
  //uint8_t* p = (uint8_t*)&packet;
  //for (int i = 0; i < (int)sizeof(packet); i++) {
  //  if (p[i] < 0x10) Serial.print('0');
  //  Serial.print(p[i], HEX);
  //  Serial.print(' ');
  //}
  //Serial.println();

  // [6] LoRa 전송 (바이너리 9바이트)
  loRaSerial.write((uint8_t*)&packet, sizeof(packet));

  // [7] 송신 완료 대기
  while (digitalRead(LORA_AUX) == LOW) { delay(1); }
  delay(20);

  // [8] LoRa Sleep Mode
  digitalWrite(LORA_M0, HIGH);
  digitalWrite(LORA_M1, HIGH);
  // Serial.println(F("Sleep..."));
  delay(100);

  // [9] 아두이노 수면 (8초 × 사이클)
  int sleepCycles = (SLEEP_MINUTES * 60) / 8;
  for (int i = 0; i < sleepCycles; i++) {
    LowPower.powerDown(SLEEP_8S, ADC_OFF, BOD_OFF);
  }
}

// 주파수 측정 (float 반환)
float getFrequencyFloat() {
  const int sampleCount = 10;
  unsigned long totalPeriod = 0;
  int validSamples = 0;
  for (int i = 0; i < sampleCount; i++) {
    unsigned long high = pulseIn(FREQ_PIN, HIGH, 10000);
    unsigned long low  = pulseIn(FREQ_PIN, LOW, 10000);
    if (high > 0 && low > 0) {
      totalPeriod += (high + low);
      validSamples++;
    }
  }
  if (validSamples > 0) {
    return 1000000.0f / (totalPeriod / validSamples);
  }
  return 0.0f;
}