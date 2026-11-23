"""API 전체를 페이지 단위로 받아 data/raw/<name>/pNNNNN.json 으로 저장한다. 이미 받은 페이지는 건너뛴다."""
import json
import math
import sys
import time
from pathlib import Path

from apis import fetch_page

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"


def download(name, rows):
    out = RAW / name
    out.mkdir(parents=True, exist_ok=True)
    body, raw = fetch_page(name, 1, rows=1)
    if body is None:
        sys.exit(f"{name}: 첫 요청 실패 {raw}")
    total = int(body["totalCount"])
    pages = math.ceil(total / rows)
    print(f"{name}: {total:,}건, {rows}건씩 {pages}페이지", flush=True)
    t0 = time.time()
    for p in range(1, pages + 1):
        f = out / f"p{p:05d}.json"
        if f.exists():
            continue
        body, raw = fetch_page(name, p, rows=rows)
        if body is None:
            print(f"  p{p} 실패: {raw}", flush=True)
            continue
        items = body.get("items") or {}
        items = items.get("item", []) if isinstance(items, dict) else items
        if isinstance(items, dict):
            items = [items]
        f.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        if p % 20 == 0 or p == pages:
            el = time.time() - t0
            print(f"  {p}/{pages} 페이지, {el:.0f}초 경과", flush=True)


if __name__ == "__main__":
    download(sys.argv[1], int(sys.argv[2]))
