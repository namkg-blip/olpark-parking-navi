import time

import requests

from env import load_env

APIS = {
    "KEY_LINKED_2025": "https://api.kcisa.kr/openapi/API_CPM_009/request",
    "KEY_PERFORMANCE": "https://api.kcisa.kr/openapi/service/rest/meta/KSCperf",
    "KEY_INOUT_2025": "https://api.kcisa.kr/openapi/API_CPM_008/request",
    "KEY_RENTAL": "https://api.kcisa.kr/openapi/service/rest/meta12/getKSCD0803",
}

_env = load_env()
MIN_INTERVAL = 5.5
_last_call = [0.0]


def _throttle():
    wait = MIN_INTERVAL - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.time()


def fetch_page(name, page, rows=1000, retries=4):
    """한 페이지를 받아 (body dict 또는 None, 원문 일부) 를 돌려준다. 키는 원문에서 가린다.
    서버 제한이 5초에 1회라 모든 호출을 MIN_INTERVAL 간격으로 보낸다."""
    key = _env[name]
    for attempt in range(retries):
        _throttle()
        r = requests.get(APIS[name], params={"serviceKey": key, "numOfRows": rows, "pageNo": page},
                         headers={"Accept": "application/json"}, timeout=120)
        text = r.text.replace(key, "***")
        try:
            data = r.json()
        except ValueError:
            data = None
        if isinstance(data, dict) and "response" in data:
            return data["response"]["body"], text[:300]
        time.sleep(2 * (attempt + 1))
    return None, text[:500]
