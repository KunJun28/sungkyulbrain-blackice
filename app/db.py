from __future__ import annotations

import csv
import io
import sqlite3
from pathlib import Path
from typing import Any

from .config import DB_PATH
from .inference import infer_road_state
from .models import SensorPacket


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = connect()
    cur = conn.cursor()
    cur.executescript(
        '''
        CREATE TABLE IF NOT EXISTS device_info (
            device_id TEXT PRIMARY KEY,
            gateway_id TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            installed_at TEXT NOT NULL,
            note TEXT
        );

        CREATE TABLE IF NOT EXISTS hardware_sensing (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            measured_at TEXT NOT NULL,
            temperature_c REAL NOT NULL,
            humidity_pct REAL NOT NULL,
            frequency_hz REAL NOT NULL,
            battery_v REAL NOT NULL,
            random_delay_ms INTEGER NOT NULL,
            sequence_no INTEGER NOT NULL,
            FOREIGN KEY(device_id) REFERENCES device_info(device_id)
        );

        CREATE TABLE IF NOT EXISTS kma_api (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            measured_at TEXT NOT NULL,
            sky_condition TEXT DEFAULT '',
            precipitation_mm REAL DEFAULT 0,
            source TEXT DEFAULT 'mock'
        );

        CREATE TABLE IF NOT EXISTS inference_result (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sensing_id INTEGER NOT NULL,
            road_status TEXT NOT NULL,
            risk_score INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(sensing_id) REFERENCES hardware_sensing(id)
        );

        CREATE TABLE IF NOT EXISTS gateway_delivery_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            gateway_id TEXT NOT NULL,
            sequence_no INTEGER NOT NULL,
            delivered_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL
        );
        '''
    )
    conn.commit()
    conn.close()


def upsert_device(packet: SensorPacket) -> None:
    conn = connect()
    conn.execute(
        '''
        INSERT INTO device_info(device_id, gateway_id, latitude, longitude, installed_at, note)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(device_id) DO UPDATE SET
            gateway_id=excluded.gateway_id,
            latitude=excluded.latitude,
            longitude=excluded.longitude
        ''',
        (packet.device_id, packet.gateway_id, packet.latitude, packet.longitude, packet.measured_at, 'school-nearby node'),
    )
    conn.commit()
    conn.close()


def store_packet(packet: SensorPacket, payload_json: str, delivered_at: str) -> dict[str, Any]:
    upsert_device(packet)
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        '''
        INSERT INTO hardware_sensing(device_id, measured_at, temperature_c, humidity_pct, frequency_hz, battery_v, random_delay_ms, sequence_no)
        VALUES(?,?,?,?,?,?,?,?)
        ''',
        (
            packet.device_id,
            packet.measured_at,
            packet.measurement.temperature_c,
            packet.measurement.humidity_pct,
            packet.measurement.frequency_hz,
            packet.battery_v,
            packet.random_delay_ms,
            packet.sequence_no,
        ),
    )
    sensing_id = cur.lastrowid
    status, risk_score, reason = infer_road_state(
        packet.measurement.temperature_c,
        packet.measurement.humidity_pct,
        packet.measurement.frequency_hz,
    )
    cur.execute(
        '''
        INSERT INTO inference_result(sensing_id, road_status, risk_score, reason, created_at)
        VALUES(?,?,?,?,?)
        ''',
        (sensing_id, status, risk_score, reason, delivered_at),
    )
    cur.execute(
        '''
        INSERT INTO gateway_delivery_log(device_id, gateway_id, sequence_no, delivered_at, payload_json, status)
        VALUES(?,?,?,?,?,?)
        ''',
        (packet.device_id, packet.gateway_id, packet.sequence_no, delivered_at, payload_json, 'stored'),
    )
    conn.commit()
    conn.close()
    return {'road_status': status, 'risk_score': risk_score, 'reason': reason, 'sensing_id': sensing_id}


def fetch_nodes() -> list[dict[str, Any]]:
    conn = connect()
    rows = conn.execute(
        '''
        SELECT d.device_id, d.gateway_id, d.latitude, d.longitude, d.note AS name,
               s.measured_at, s.temperature_c, s.humidity_pct, s.frequency_hz,
               i.road_status, i.risk_score, i.reason
        FROM device_info d
        LEFT JOIN hardware_sensing s ON s.id = (
            SELECT hs.id FROM hardware_sensing hs
            WHERE hs.device_id = d.device_id
            ORDER BY hs.measured_at DESC, hs.id DESC LIMIT 1
        )
        LEFT JOIN inference_result i ON i.sensing_id = s.id
        ORDER BY d.device_id
        '''
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def fetch_node_detail(device_id: str) -> dict[str, Any] | None:
    conn = connect()
    row = conn.execute(
        '''
        SELECT d.device_id, d.gateway_id, d.latitude, d.longitude, d.note AS name,
               s.measured_at, s.temperature_c, s.humidity_pct, s.frequency_hz, s.battery_v, s.random_delay_ms, s.sequence_no,
               i.road_status, i.risk_score, i.reason
        FROM device_info d
        LEFT JOIN hardware_sensing s ON s.id = (
            SELECT hs.id FROM hardware_sensing hs
            WHERE hs.device_id = d.device_id
            ORDER BY hs.measured_at DESC, hs.id DESC LIMIT 1
        )
        LEFT JOIN inference_result i ON i.sensing_id = s.id
        WHERE d.device_id = ?
        ''',
        (device_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def fetch_recent(limit: int = 20) -> list[dict[str, Any]]:
    conn = connect()
    rows = conn.execute(
        '''
        SELECT s.device_id, s.measured_at, s.temperature_c, s.humidity_pct, s.frequency_hz,
               i.road_status, i.risk_score
        FROM hardware_sensing s
        JOIN inference_result i ON i.sensing_id = s.id
        ORDER BY s.measured_at DESC, s.id DESC
        LIMIT ?
        ''',
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


# 새로 추가된 함수: 특정 디바이스의 데이터 이력을 조회합니다.
def fetch_readings_by_device(device_id: str, limit: int = 100) -> list[dict[str, Any]]:
    conn = connect()
    rows = conn.execute(
        '''
        SELECT s.device_id, s.measured_at, s.temperature_c, s.humidity_pct, s.frequency_hz, s.battery_v,
               i.road_status, i.risk_score, i.reason
        FROM hardware_sensing s
        LEFT JOIN inference_result i ON i.sensing_id = s.id
        WHERE s.device_id = ?
        ORDER BY s.measured_at DESC, s.id DESC
        LIMIT ?
        ''',
        (device_id, limit),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def export_readings_csv() -> str:
    conn = connect()
    rows = conn.execute(
        '''
        SELECT d.device_id, d.gateway_id, d.latitude, d.longitude,
               s.measured_at, s.temperature_c, s.humidity_pct, s.frequency_hz, s.battery_v,
               i.road_status, i.risk_score, i.reason
        FROM hardware_sensing s
        JOIN device_info d ON d.device_id = s.device_id
        JOIN inference_result i ON i.sensing_id = s.id
        ORDER BY s.measured_at DESC, s.id DESC
        '''
    ).fetchall()
    conn.close()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['device_id', 'gateway_id', 'latitude', 'longitude', 'measured_at', 'temperature_c', 'humidity_pct', 'frequency_hz', 'battery_v', 'road_status', 'risk_score', 'reason'])
    for row in rows:
        writer.writerow([row[k] for k in row.keys()])
    return buffer.getvalue()