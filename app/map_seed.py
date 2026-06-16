from __future__ import annotations

from .config import SCHOOL_LAT, SCHOOL_LON


def default_nodes() -> list[dict[str, float | str]]:
    return [
        {
            'device_id': '1',
            'name': '성결대 정문 앞',
            'latitude': SCHOOL_LAT + 0.0009,
            'longitude': SCHOOL_LON + 0.0011,
        },
        {
            'device_id': '2',
            'name': '성결대 후문 경사로',
            'latitude': SCHOOL_LAT + 0.0017,
            'longitude': SCHOOL_LON - 0.0010,
        },
        {
            'device_id': '3',
            'name': '기숙사 앞 음지 구간',
            'latitude': SCHOOL_LAT - 0.0013,
            'longitude': SCHOOL_LON + 0.0014,
        },
        {
            'device_id': '4',
            'name': '공학관 옆 도로',
            'latitude': SCHOOL_LAT - 0.0010,
            'longitude': SCHOOL_LON - 0.0012,
        },
        {
            'device_id': '5',
            'name': '도서관 앞 사거리',
            'latitude': SCHOOL_LAT + 0.0002,
            'longitude': SCHOOL_LON - 0.0019,
        },
    ]
