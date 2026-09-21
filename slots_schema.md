# slots.json 스키마 — 마감 리포트 렌더러 입력

`mkreport.py`가 읽는 입력 형식이다. **없는 값은 `null`로 두고 키 자체를 빼지 않는다.**
`null`은 `[미확보]`로 렌더되며 근사치로 대체하지 않는다.

## 공통 규칙

- 색·막대폭·부호 표기·푸터는 전부 코드가 정한다. **색 hex를 직접 쓰지 않는다.**
- 등락(`chg`)은 숫자만 넣는다. `+`/`%`는 코드가 붙인다. 10년물 등 bp 단위는 `"unit":"bp"`를 함께 준다.
- 표 셀은 문자열이거나 `{"t":"텍스트","chg":수치}`. 후자면 부호에 따라 색이 붙는다. `{"t":null}`은 `[미확보]`.
- `footer_status`의 `{MISSING}`은 코드가 미확보 건수로 바꾼다.

## 미국장 (`"market":"us"`)

```json
{
  "market": "us",
  "date": "2026-09-18",
  "date_label": "09/18(금)",
  "issue_no": 137,

  "headline": "한 문장. 지수 방향 + 원인 + 가장 큰 개별 재료",
  "subtitle": "정규장 확정 종가(16:00 ET) 기준 · …",
  "key_points": ["…", "…", "…"],
  "summary_prose": "4문장. ①원인(매크로) ②결과(지수·섹터) ③심리(VIX·F&G) ④특이 종목",

  "tiles": [
    {"label": "S&P 500", "value": "7,650.50", "chg": 0.17},
    {"label": "나스닥", "value": "26,522.55", "chg": 0.39},
    {"label": "다우존스", "value": "51,682.64", "chg": -0.18},
    {"label": "필라델피아 반도체", "value": "11,921.69", "chg": 2.78},
    {"label": "러셀2000", "value": "2,860.40", "chg": -0.50},
    {"label": "VIX", "value": "14.81", "chg": -4.08},
    {"label": "미국 10년물", "value": "4.998%", "chg": 5.1, "unit": "bp"},
    {"label": "원/달러", "value": "1,384.00", "chg": 0.21}
  ],

  "aux": [
    {"label": "DXY", "value": null, "chg": null},
    {"label": "WTI", "value": null, "chg": null},
    {"label": "GLD", "value": "401.17", "chg": 0.71},
    {"label": "TLT", "value": "81.25", "chg": -0.65}
  ],

  "section2_title": "섹터 · 종목",
  "sector_note_top": "11개 섹터 ETF 등락률 · 내림차순",
  "sectors": [
    {"name": "기술 XLK", "chg": 0.82},
    {"name": "산업재 XLI", "chg": 0.44}
  ],
  "sector_footnote": "시장 폭 2/11 · SMH/SPY 상대강도 5일 +1.13%p · 20일 +1.96%p · SMH σ강도 0.81",
  "movers": {
    "head": [["상승 상위", "left"], ["등락", "right"], ["하락 상위", "left"], ["등락", "right"]],
    "rows": [
      ["ARM", {"chg": 4.04}, "퀄컴", {"chg": -5.82}],
      ["마이크론", {"chg": 3.92}, "넷플릭스", {"chg": -4.67}]
    ]
  },
  "sector_note": "2~3문장. 표에서 실제로 상위·하위인 섹터가 왜 움직였는지",

  "rate_tiles": [
    {"label": "미국 10년물", "value": "4.998%", "chg": 5.1, "unit": "bp"},
    {"label": "미국 2년물", "value": "4.760%", "chg": 9.0, "unit": "bp"},
    {"label": "2s10s 스프레드", "value": "+25bp", "chg": -3.9, "unit": "bp"}
  ],
  "macro_rows": [
    {"k": "금리", "v": "…"},
    {"k": "심리", "v": "…"},
    {"k": "안전자산", "v": "…"}
  ],
  "consensus": {
    "head": [["종목", "left"], ["투자의견", "left"], ["목표가", "right"],
             ["현재가", "right"], ["Upside", "right"], ["핵심", "left"]],
    "rows": [
      ["마이크론", "매수 유지", "1,180.00", "1,015.80", {"t": "+16.2%", "chg": 16.2}, "HBM 공급 계약 확대"]
    ]
  },
  "cons_footnote": "Upside = 목표가 ÷ 현재가 − 1. 현재가는 정규장 확정 종가.",
  "cons_note": "…",

  "section4_title": "국내 read-through",
  "s4_tiles": [
    {"label": "EWY 한국 ETF", "value": "181.31", "chg": -0.59},
    {"label": "TSMC", "value": "434.67", "chg": 1.02},
    {"label": "쿠팡", "value": "14.29", "chg": -1.24},
    {"label": "코스피 시초 추정", "value": null, "chg": null, "note": "미산출"}
  ],
  "map_head_1": "미국 동향",
  "map_head_2": "국내 대응",
  "map_rows": [
    {"a": "메모리 강세 (MU +3.92%, SMH +2.21%)", "b": "삼성전자 · SK하이닉스", "dir": "긍정"}
  ],
  "s4_footnote": "…",

  "calendar_groups": [
    {"group": "경제 · 증시", "rows": [
      {"d": "09/21(월)", "t": "미국 8월 경기선행지수"}
    ]}
  ],
  "news": [
    {"title": "…", "url": "https://…", "date": "9/18"}
  ],

  "deep_dive": {
    "title": "…",
    "prose": "1단락",
    "rows": [
      {"k": "근거", "v": "…"},
      {"k": "시금석", "v": "…"},
      {"k": "포인트", "v": "…"}
    ]
  },

  "source_note_1": "지수·섹터는 정규장 확정 종가 기준.",
  "s5_footnote": "일정은 확정 공시로 확인된 것만.",
  "footer_status": "XCHK n/n · MISSING {MISSING}"
}
```

## 국내장 (`"market":"kr"`)

밴드 색만 바뀌고 구조는 같다. 다른 부분은 아래뿐이다.

- `tiles` 8개 — KOSPI · KOSDAQ · 원/달러 · 거래대금 · 외국인 · 기관 · 개인 · 미국 10년물(노션 DB 인용)
- `section2_title` = `"업종 · 수급"`, `sectors`는 업종 상대강도 상하위 5
- `section4_title` = `"수급 · 내일 관전"`
- `flow` 표를 추가로 쓴다(수급표). 형식은 `movers`·`consensus`와 같다:
  `{"head": [[…]], "rows": [[…]]}` — 있으면 섹션 4에 렌더되고, 없으면 그 블록이 통째로 빠진다.
- `map_head_1` = `"관전 포인트"`, `map_head_2` = `"판단 기준 수치"`
- `calendar_groups`는 두 갈래: `"경제 · 증시"`와 `"엔터 일정"`

## 게이트 출력 읽는 법

`python3 mkreport.py slots.json .` 실행 시 표준출력:

```
GATE PASS · MISSING 3
ISSUE: 캘린더 요일 불일치: 09/22(수) → 실제 화요일
SUPERLATIVE: ...퀄컴은 사상 최대 하락을 기록했다...
LEFTOVER_SLOTS: 0
WROTE: ./body.html 18131 bytes, ./body.txt 1200 bytes
```

- `ISSUE:` 가 한 줄이라도 있으면 원인을 고쳐 재실행한다.
- `SUPERLATIVE:` 는 막지 않지만 근거를 확인해야 한다. 확인 못 하면 표현을 빼고 재실행한다.
- `LEFTOVER_SLOTS`가 0이 아니면 slots.json에 키가 빠진 것이다.
