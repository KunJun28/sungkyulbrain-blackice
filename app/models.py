from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SensorMeasurement:
    frequency_hz: float
    temperature_c: float
    humidity_pct: float


@dataclass
class SensorPacket:
    schema_version: int
    device_id: str
    gateway_id: str
    sequence_no: int
    measured_at: str
    battery_v: float
    random_delay_ms: int
    latitude: float
    longitude: float
    measurement: SensorMeasurement

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> 'SensorPacket':
        measurement = payload.get('measurement', {})
        return cls(
            schema_version=int(payload.get('schema_version', 1)),
            device_id=str(payload['device_id']),
            gateway_id=str(payload.get('gateway_id', 'gateway-1')),
            sequence_no=int(payload.get('sequence_no', 0)),
            measured_at=str(payload.get('measured_at') or utc_now()),
            battery_v=float(payload.get('battery_v', 3.7)),
            random_delay_ms=int(payload.get('random_delay_ms', 0)),
            latitude=float(payload['latitude']),
            longitude=float(payload['longitude']),
            measurement=SensorMeasurement(
                frequency_hz=float(measurement['frequency_hz']),
                temperature_c=float(measurement['temperature_c']),
                humidity_pct=float(measurement['humidity_pct']),
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data['measurement'] = asdict(self.measurement)
        return data
