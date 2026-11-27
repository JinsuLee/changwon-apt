#!/usr/bin/env python3
"""
창원시 성산구(48123) · 의창구(48121) 아파트 매매 실거래가 자동 수집 스크립트
출처: 공공데이터포털 국토교통부 아파트 매매 실거래가 자료 API
실행: DATA_GO_KR_KEY="발급받은_일반인증키(Decoding)" python3 scripts/fetch_changwon_api.py
"""
import datetime
import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict

API_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"
SERVICE_KEY = os.environ.get("DATA_GO_KR_KEY", "").strip()

# 창원시 성산구(48123), 의창구(48121) 법정동코드 5자리
DISTRICTS = {
    "48123": "창원시 성산구",
    "48121": "창원시 의창구",
}

def get_recent_months(count=12):
    today = datetime.date.today()
    months = []
    y, m = today.year, today.month
    for _ in range(count):
        months.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return months

def fetch_month(lawd_cd, deal_ymd):
    params = urllib.parse.urlencode({
        "serviceKey": SERVICE_KEY,
        "LAWD_CD": lawd_cd,
        "DEAL_YMD": deal_ymd,
        "numOfRows": 1000,
        "pageNo": 1,
    })
    req = urllib.request.Request(f"{API_URL}?{params}", headers={"User-Agent": "ChangwonAptBot/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
    root = ET.fromstring(raw)
    items = []
    for item in root.findall(".//item"):
        def txt(tag):
            el = item.find(tag)
            return el.text.strip() if el is not None and el.text else ""
        # 해제된 거래 제외
        if txt("cdealType"):
            continue
        apt_nm = txt("aptNm")
        umd_nm = txt("umdNm")
        exclu = float(txt("excluUseAr") or 0)
        amount_str = txt("dealAmount").replace(",", "")
        if not apt_nm or not amount_str or exclu <= 0:
            continue
        price_eok = round(int(amount_str) / 10000.0, 2)
        yr = txt("dealYear")
        mo = txt("dealMonth").zfill(2)
        dy = txt("dealDay").zfill(2)
        floor = int(txt("floor") or 1)
        build_yr = txt("buildYear") or "2015"
        pyung = round(exclu / 3.3058 * 1.32)
        items.append({
            "district": DISTRICTS[lawd_cd],
            "umd": umd_nm,
            "aptNm": apt_nm,
            "date": f"{yr}-{mo}-{dy}",
            "area": round(exclu, 2),
            "pyungNum": pyung,
            "floor": floor,
            "price": price_eok,
            "buildYear": build_yr,
        })
    return items

def build_complex_object(key, records):
    records.sort(key=lambda r: r["date"], reverse=True)
    latest = records[0]
    max_floor = max(15, max(r["floor"] for r in records))
    areas = sorted({round(r["area"]) for r in records})
    rep_pyung = latest["pyungNum"]
    avg_price = round(sum(r["price"] for r in records[:10]) / min(len(records), 10), 2)
    pyung_price = round((avg_price * 10000) / max(1, rep_pyung))

    # 연도별 평균 시세 계산
    by_ym = defaultdict(list)
    for r in records:
        by_ym[r["date"][:7]].append(r["price"])
    yearly = []
    for ym in sorted(by_ym.keys()):
        vals = by_ym[ym]
        yearly.append({
            "label": ym[2:].replace("-", "."),
            "year": int(ym[:4]),
            "price": round(sum(vals) / len(vals), 2),
        })

    # 기본 3개 동 · 라인 매핑 자동 생성 (전용면적 기반 3Bay/4Bay 초기 분류)
    is_4bay = latest["area"] >= 75
    bay_tag = "4Bay" if is_4bay else "3Bay"
    layout_tag = "판상형"
    default_line = {
        "type": f"{rep_pyung}평",
        "pyung": rep_pyung,
        "area": latest["area"],
        "supply": round(latest["area"] * 1.31, 1),
        "bay": bay_tag,
        "layout": layout_tag,
        "dir": "남향",
        "azimuth": 180,
        "rooms": 4 if latest["area"] >= 95 else 3,
        "baths": 2,
    }
    buildings = {}
    for d in ["101", "102", "103"]:
        buildings[d] = {
            "name": f"{d}동",
            "maxFloor": max_floor,
            "units": max_floor * 4,
            "royal": d == "101",
            "lines": {
                "1": dict(default_line),
                "2": dict(default_line),
                "3": dict(default_line, bay="3Bay" if is_4bay else "3Bay", layout="타워형" if is_4bay else "판상형", dir="남서향", azimuth=205),
                "4": dict(default_line, dir="남동향", azimuth=155),
            }
        }

    tx_list = []
    for r in records[:25]:
        pg = "24평" if r["pyungNum"] <= 26 else ("28평" if r["pyungNum"] <= 30 else ("33평" if r["pyungNum"] <= 36 else "39평"))
        tx_list.append({
            "date": r["date"],
            "pyungGroup": pg,
            "type": f"{r['pyungNum']}평 ({int(r['area'])})",
            "pyungNum": r["pyungNum"],
            "dong": "실거래",
            "floor": r["floor"],
            "price": r["price"],
        })

    return {
        "id": key,
        "name": f"{latest['aptNm']} ({latest['umd']})",
        "shortName": latest["aptNm"][:10],
        "address": f"경남 {latest['district']} {latest['umd']}",
        "totalUnits": max_floor * 12,
        "dongCount": 3,
        "moveIn": f"{latest['buildYear']}년 준공",
        "floorRange": f"최고 {max_floor}층",
        "ratio": "공공API 수집",
        "parking": "단지 정보 참조",
        "royalNote": "101동 · 로열층",
        "repPyung": rep_pyung,
        "recentTxLabel": f"{latest['price']:.2f}억",
        "recentTxSub": f"{latest['date']} · {latest['floor']}층",
        "marketSale": f"{avg_price:.2f}억",
        "marketJeonse": f"최근 1년 {len(records)}건 거래",
        "growth1y": "-",
        "growthSub": f"{latest['district']} 자동수집",
        "gaeumRank": latest["umd"],
        "pyungPrice": pyung_price,
        "fpStyle": "4bay_new_84" if int(latest["buildYear"]) >= 2020 else "4bay_plate_84",
        "pyungSummary": [
            {"label": f"{rep_pyung}평 (전용 {latest['area']}㎡)", "sale": f"최근 {latest['price']:.2f}억", "jeonse": f"평균 {avg_price:.2f}억", "tone": "blue"},
            {"label": "최근 1년 거래", "sale": f"{len(records)}건", "jeonse": f"최고 {max(r['price'] for r in records):.2f}억", "tone": "emerald"},
            {"label": "평당 실거래가", "sale": f"{pyung_price:,}만원", "jeonse": f"{rep_pyung}평 기준", "tone": "violet"},
            {"label": "준공 연도", "sale": f"{latest['buildYear']}년", "jeonse": latest["umd"], "tone": "violet"},
        ],
        "benchmarks": {
            str(rep_pyung): {
                "sale": avg_price,
                "jeonse": round(avg_price * 0.65, 2),
                "low": [round(avg_price * 0.94, 2), round(avg_price * 0.99, 2)],
                "mid": [round(avg_price * 0.98, 2), round(avg_price * 1.03, 2)],
                "high": [round(avg_price * 1.02, 2), round(avg_price * 1.07, 2)],
            }
        },
        "yearlyPrices": yearly,
        "buildings": buildings,
        "transactions": tx_list,
    }

def main():
    if not SERVICE_KEY:
        raise SystemExit("환경변수 DATA_GO_KR_KEY 가 설정되지 않았습니다.")
    grouped = defaultdict(list)
    for lawd_cd in DISTRICTS:
        for ym in get_recent_months(12):
            try:
                rows = fetch_month(lawd_cd, ym)
                for r in rows:
                    k = f"{lawd_cd}_{r['umd']}_{r['aptNm']}".replace(" ", "_")
                    grouped[k].append(r)
            except Exception as e:
                print(f"[WARN] {lawd_cd} {ym}: {e}")

    # 최근 1년 거래 3건 이상인 주요 단지만 추려 JSON 생성 (용량 최적화)
    complexes = {}
    for k, recs in grouped.items():
        if len(recs) >= 3:
            complexes[k] = build_complex_object(k, recs)

    out = {
        "updatedAt": datetime.date.today().isoformat(),
        "districts": list(DISTRICTS.values()),
        "count": len(complexes),
        "complexes": complexes,
    }
    os.makedirs("data", exist_ok=True)
    with open("data/changwon_live.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(complexes)} complexes to data/changwon_live.json")

if __name__ == "__main__":
    main()
