#현재 사용안함

from __future__ import annotations


from .db import connect, init_db, store_packet
from .map_seed import default_nodes
from .models import SensorMeasurement, SensorPacket


def bootstrap() -> None:
    init_db()
    conn = connect()
    for node in default_nodes():
        conn.execute(
            """
            INSERT INTO device_info(device_id, gateway_id, latitude, longitude, installed_at, note)
            VALUES(?,?,?,?,datetime('now'),?)
            ON CONFLICT(device_id) DO UPDATE SET
                latitude=excluded.latitude,
                longitude=excluded.longitude,
                note=excluded.note
            """,
            (node['device_id'], 'gateway-1', node['latitude'], node['longitude'], node['name']),
        )
    conn.commit()
    sensing_count = conn.execute('SELECT COUNT(*) FROM hardware_sensing').fetchone()[0]
    conn.close()

    if sensing_count == 0:
        seed_mock_readings()


def seed_mock_readings() -> None:
    seed_data = [
        #('node-a1', 2480, 5.1, 43, 3.98, 120, 1),
        ('node-a2', 1320, -0.4, 82, 3.84, 460, 2),
        ('node-a3', 1080, -3.2, 91, 3.76, 720, 3),
        ('node-a4', 2210, 2.3, 58, 3.93, 210, 4),
        ('node-a5', 1280, 0.6, 76, 3.88, 380, 5),
    ]
    node_map = {node['device_id']: node for node in default_nodes()}
    for device_id, freq, temp, hum, battery, delay, seq in seed_data:
        node = node_map[device_id]
        packet = SensorPacket(
            schema_version=1,
            device_id=device_id,
            gateway_id='gateway-1',
            sequence_no=seq,
            measured_at=f'2026-03-31T0{seq}:20:00+09:00',
            battery_v=battery,
            random_delay_ms=delay,
            latitude=float(node['latitude']),
            longitude=float(node['longitude']),
            measurement=SensorMeasurement(
                frequency_hz=freq,
                temperature_c=temp,
                humidity_pct=hum,
            ),
        )
        store_packet(packet, payload_json=repr(packet.to_dict()), delivered_at=packet.measured_at)
