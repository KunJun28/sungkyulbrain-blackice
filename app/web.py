from __future__ import annotations

import json
import mimetypes
import time
import re
from datetime import datetime, timezone, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .bootstrap import bootstrap
from .config import BASE_DIR, SCHOOL_LAT, SCHOOL_LON, SCHOOL_NAME, STATIC_DIR, AWS_API_URL, AWS_API_KEY
from .inference import infer_road_state
from .map_seed import default_nodes  # DB 대신 하드코딩된 노드 리스트를 직접 가져옵니다.
from .db import export_readings_csv, store_packet
from .models import SensorPacket, utc_now


KST = timezone(timedelta(hours=9))

def _extract_time(item: dict) -> str:
    """AWS/DynamoDB item에서 시간 필드를 최대한 호환되게 추출."""
    for key in ('time', 'measured_at', 'timestamp', 'created_at'):
        value = item.get(key)
        if value:
            return str(value)
    return ''

def _parse_time(value: str) -> datetime:
    """정렬용 시간 파서. 실패하면 최소값으로 처리."""
    if not value or value == '데이터 없음':
        return datetime.min.replace(tzinfo=timezone.utc)
    raw = str(value).strip()
    try:
        # 2026-05-24 19:14:36 또는 2026-05-24T19:14:36 모두 처리
        normalized = raw.replace('Z', '+00:00')
        if 'T' not in normalized and re.match(r'^\d{4}-\d{2}-\d{2} ', normalized):
            normalized = normalized.replace(' ', 'T', 1)
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            # DB가 KST 문자열로 저장된 경우가 많으므로 naive는 KST로 간주
            dt = dt.replace(tzinfo=KST)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)

def _format_display_time(value: str) -> str:
    """화면/API에 내려줄 측정시간 문자열을 통일."""
    if not value or value == '데이터 없음':
        return '데이터 없음'
    raw = str(value).strip()
    m = re.match(r'^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(?::(\d{2}))?', raw)
    if m:
        return f"{m.group(1)} {m.group(2)}:{m.group(3) or '00'}"
    dt = _parse_time(raw)
    if dt.year <= 1:
        return raw
    return dt.astimezone(KST).strftime('%Y-%m-%d %H:%M:%S')

def _hour_from_measured_at(value: str) -> int | None:
    display = _format_display_time(value)
    m = re.match(r'^\d{4}-\d{2}-\d{2} (\d{2}):', display)
    return int(m.group(1)) if m else None

def _fix_reason_time(reason: str, measured_at: str) -> str:
    """AI reason 안의 시간:n시가 측정시간과 다르면 측정시간 기준으로 보정."""
    hour = _hour_from_measured_at(measured_at)
    if hour is None:
        return reason
    return re.sub(r'시간\s*:\s*\d{1,2}\s*시', f'시간:{hour}시', str(reason))

def _infer_with_time_fix(t: float, h: float, c: float, measured_at: str):
    status, risk_score, reason = infer_road_state(t, h, c)
    return status, risk_score, _fix_reason_time(reason, measured_at)

AWS_CACHE_TTL_SEC = 5
AWS_REQUEST_DELAY_SEC = 1
_AWS_CACHE = {"time": 0.0, "data": None}

def fetch_aws_data() -> list:
    """Fetch AWS sensor data with simple throttling/cache to reduce HTTP 429 errors."""
    now = time.time()
    cached = _AWS_CACHE.get("data")
    if cached is not None and now - float(_AWS_CACHE.get("time", 0.0)) < AWS_CACHE_TTL_SEC:
        return cached

    time.sleep(AWS_REQUEST_DELAY_SEC)

    req = Request(AWS_API_URL, method='GET', headers={'x-api-key': AWS_API_KEY})
    try:
        with urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
    except HTTPError as e:
        if e.code == 429 and cached is not None:
            print("AWS Fetch Warning: HTTP 429, using cached data")
            return cached
        raise

    # ── 여기가 핵심 추가 부분 ──
    # 이중 JSON 인코딩 처리 (API Gateway가 body를 문자열로 감쌀 때)
    if isinstance(data, str):
        data = json.loads(data)

    # 새 Lambda 형식: {latest: [...], history: [...]}
    if isinstance(data, dict) and 'latest' in data:
        data = data.get('latest', []) + data.get('history', [])

    # 혹시 리스트가 아니면 빈 리스트로
    if not isinstance(data, list):
        data = []
    # ── 끝 ──

    _AWS_CACHE["time"] = time.time()
    _AWS_CACHE["data"] = data
    return data

#bootstrap()

class BlackIceRequestHandler(BaseHTTPRequestHandler):
    server_version = 'BlackIceHTTP/1.0'

    def _send_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, content_type: str = 'text/plain; charset=utf-8', status: int = 200) -> None:
        body = text.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get('Content-Length', '0'))
        raw = self.rfile.read(length) if length else b'{}'
        return json.loads(raw.decode('utf-8'))

    def _serve_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._send_text('Not Found', status=404)
            return
        content = path.read_bytes()
        mime, _ = mimetypes.guess_type(path.name)
        self.send_response(200)
        self.send_header('Content-Type', mime or 'application/octet-stream')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, x-api-key')
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        
        if parsed.path == '/':
            html = (STATIC_DIR / 'index.html').read_text(encoding='utf-8')
            html = html.replace('__SCHOOL_NAME__', SCHOOL_NAME)
            html = html.replace('__SCHOOL_LAT__', str(SCHOOL_LAT))
            html = html.replace('__SCHOOL_LON__', str(SCHOOL_LON))
            self._send_text(html, content_type='text/html; charset=utf-8')
            return
            
        if parsed.path.startswith('/static/'):
            rel = parsed.path.replace('/static/', '', 1)
            self._serve_file(STATIC_DIR / rel)
            return

        if parsed.path == '/api/health':
            self._send_json({'status': 'ok', 'time': utc_now()})
            return

        # 1. 전체 노드 맵 데이터 (map_seed.py 위치 + AWS 센서 결합)
        if parsed.path == '/api/map/nodes':
            try:
                # DB 조회 대신 map_seed.py의 파이썬 리스트를 그대로 사용합니다.
                local_devices = default_nodes()

                aws_data = fetch_aws_data()

                latest_nodes = {}
                for item in aws_data:
                    did = str(item.get('device_id', 'unknown'))
                    t_str = _extract_time(item)
                    if did not in latest_nodes or _parse_time(t_str) > _parse_time(_extract_time(latest_nodes[did])):
                        latest_nodes[did] = item

                nodes = []
                for d in local_devices:
                    did = str(d['device_id'])
                    aws_item = latest_nodes.get(did)

                    if aws_item:
                        t = float(aws_item.get('temperature', 0))
                        h = float(aws_item.get('humidity', 0))
                        c = float(aws_item.get('conductivity', 0))
                        measured_at = _format_display_time(_extract_time(aws_item))
                        status, risk_score, reason = _infer_with_time_fix(t, h, c, measured_at)
                    else:
                        t = h = c = 0
                        measured_at = '데이터 없음'
                        status, risk_score, reason = 'unknown', 0, '데이터 없음'

                    nodes.append({
                        'device_id': did,
                        'latitude': float(d['latitude']),
                        'longitude': float(d['longitude']),
                        'name': d.get('name', f"Node {did}"),
                        'measured_at': measured_at,
                        'temperature_c': t,
                        'humidity_pct': h,
                        'conductivity': c,      
                        'frequency_hz': c,      
                        'road_status': status,
                        'risk_score': risk_score,
                        'reason': reason
                    })

                self._send_json({
                    'school': {'name': SCHOOL_NAME, 'latitude': SCHOOL_LAT, 'longitude': SCHOOL_LON},
                    'nodes': nodes
                })
            except Exception as e:
                print("AWS Fetch Error:", e)
                self._send_json({'error': 'Failed to fetch from AWS', 'detail': str(e)}, status=502)
            return

        # 2. 개별 노드 상세 데이터 (map_seed.py 단일 위치 + AWS 센서 결합)
        if parsed.path.startswith('/api/map/node/'):
            device_id = parsed.path.rsplit('/', 1)[-1]
            try:
                # DB 대신 map_seed.py 리스트에서 해당 디바이스 ID를 검색합니다.
                local_devices = default_nodes()
                target_device = None
                for d in local_devices:
                    if str(d['device_id']) == str(device_id):
                        target_device = d
                        break

                if not target_device:
                    self._send_json({'error': 'node not found in map_seed.py'}, status=404)
                    return

                aws_data = fetch_aws_data()
                
                target_item = None
                for item in aws_data:
                    if str(item.get('device_id')) == str(device_id):
                        if target_item is None or _parse_time(_extract_time(item)) > _parse_time(_extract_time(target_item)):
                            target_item = item
                
                if target_item:
                    t = float(target_item.get('temperature', 0))
                    h = float(target_item.get('humidity', 0))
                    c = float(target_item.get('conductivity', 0))
                    measured_at = _format_display_time(_extract_time(target_item))
                    status, risk_score, reason = _infer_with_time_fix(t, h, c, measured_at)
                else:
                    t = h = c = 0
                    measured_at = '데이터 없음'
                    status, risk_score, reason = 'unknown', 0, '데이터 없음'
                    
                self._send_json({
                    'device_id': str(target_device['device_id']),
                    'latitude': float(target_device['latitude']),
                    'longitude': float(target_device['longitude']),
                    'name': target_device.get('name', f"Node {target_device['device_id']}"),
                    'measured_at': measured_at,
                    'temperature_c': t,
                    'humidity_pct': h,
                    'conductivity': c,
                    'frequency_hz': c,
                    'road_status': status,
                    'risk_score': risk_score,
                    'reason': reason
                })
            except Exception as e:
                self._send_json({'error': 'AWS fetch failed', 'detail': str(e)}, status=502)
            return

        # 3. 우측 하단 최근 목록 데이터
        if parsed.path == '/api/readings/recent':
            query = parse_qs(parsed.query)
            limit = int(query.get('limit', ['20'])[0])
            try:
                aws_data = fetch_aws_data()
                
                aws_data.sort(key=lambda x: _parse_time(_extract_time(x)), reverse=True)
                
                items = []
                for item in aws_data[:limit]:
                    t = float(item.get('temperature', 0))
                    h = float(item.get('humidity', 0))
                    c = float(item.get('conductivity', 0))
                    measured_at = _format_display_time(_extract_time(item))
                    status, risk_score, reason = _infer_with_time_fix(t, h, c, measured_at)
                    
                    items.append({
                        'device_id': str(item.get('device_id', 'unknown')),
                        'measured_at': measured_at,
                        'temperature_c': t,
                        'humidity_pct': h,
                        'conductivity': c,
                        'frequency_hz': c,
                        'road_status': status,
                        'risk_score': risk_score
                    })
                self._send_json({'items': items})
            except Exception as e:
                self._send_json({'error': 'AWS fetch failed', 'detail': str(e)}, status=502)
            return

        self._send_text('Not Found', status=404)

    def do_POST(self) -> None:
        self._send_json({'error': 'not implemented'}, status=404)

    def log_message(self, format: str, *args) -> None:
        return