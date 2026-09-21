#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
마감 리포트 렌더러(단일 파일) — slots.json -> body.html / body.txt

  python3 mkreport.py slots.json [outdir]

설계 원칙
  - LLM은 값만 만든다. 색·막대폭·[미확보]·부호 표기·게이트는 전부 여기서 결정한다.
  - null = 미확보. 절대 근사치로 대체하지 않는다.
  - 표준 라이브러리만 사용(클라우드 런타임에 numpy/pandas 없음).
"""

import sys, os, json, re, html
from datetime import date, datetime, timedelta

# ── 팔레트 (지시서 §1-3 확정) ─────────────────────────────────────────────
UP, DOWN, FLAT, NA = "#C8102E", "#1D5BB0", "#1E8449", "#8a877f"
INK, MUTED = "#1a1a1a", "#6b6963"
FLAT_EPS = 0.05           # ±0.05% 이내 = 보합
BAR_MAX_PX = 118          # 템플릿 막대 칸 폭

BANDS = {
    "us": {"BAND": "#0B2A4A", "BAND_TINT": "#eef2f6", "MARKET_TAG": "US MARKET"},
    "kr": {"BAND": "#0F3D3E", "BAND_TINT": "#eaf1f1", "MARKET_TAG": "KR MARKET"},
}

DIR_COLORS = {"긍정": UP, "부담": DOWN, "주의": MUTED, "중립": MUTED}

MISSING = "[미확보]"
# 확정 슬롯에 들어가면 안 되는 말 (지시서 §4-E-4)
HEDGE_WORDS = ["약 ", "추정", "근사", "가량", "안팎", "내외"]
WEEKDAY_KO = "월화수목금토일"


# ── 작은 템플릿 엔진 ──────────────────────────────────────────────────────
# {{#NAME}}…{{/NAME}}  : NAME이 리스트면 반복, 불리언이면 조건
# {{KEY}}              : 치환 (HTML 이스케이프, __RAW_ 접두는 원문 유지)
SECTION_RE = re.compile(r"\{\{#([A-Z0-9_]+)\}\}(.*?)\{\{/\1\}\}", re.S)
VAR_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


def render(tpl, ctx):
    def section(m):
        name, inner = m.group(1), m.group(2)
        val = ctx.get(name)
        if isinstance(val, list):
            return "".join(render(inner, {**ctx, **item}) for item in val)
        return render(inner, ctx) if val else ""

    prev = None
    while prev != tpl:                      # 중첩 섹션을 안쪽부터 펼친다
        prev = tpl
        tpl = SECTION_RE.sub(section, tpl)

    def var(m):
        v = ctx.get(m.group(1))
        if v is None:
            return ""
        return v if m.group(1).startswith("RAW_") else html.escape(str(v), quote=True)

    return VAR_RE.sub(var, tpl)


# ── 값 → 표시 변환 ────────────────────────────────────────────────────────
def color_of(chg):
    if chg is None:
        return NA
    if abs(chg) <= FLAT_EPS:
        return FLAT
    return UP if chg > 0 else DOWN


def fmt_chg(chg, unit="%", digits=2):
    """등락 표기. bp는 부호 붙인 정수형, %는 소수 2자리."""
    if chg is None:
        return MISSING
    if unit == "bp":
        return "{:+.1f}bp".format(chg)
    return "{:+.{d}f}{u}".format(chg, d=digits, u=unit)


def cell(value, chg=None, unit="%"):
    """타일 한 칸: VALUE / VALUE_COLOR / CHG / COLOR 를 만든다."""
    missing = value is None
    return {
        "VALUE": MISSING if missing else str(value),
        "VALUE_COLOR": NA if missing else INK,
        "CHG": fmt_chg(chg, unit),
        "COLOR": color_of(chg),
    }


def tile(t):
    d = cell(t.get("value"), t.get("chg"), t.get("unit", "%"))
    d["LABEL"] = t.get("label", "")
    if t.get("note"):
        d["LABEL"] = "{} · {}".format(d["LABEL"], t["note"])
    return d


def bars(items):
    """섹터 중앙축 막대. 폭 = |chg| / max|chg| * 118px."""
    vals = [abs(s["chg"]) for s in items if s.get("chg") is not None]
    top = max(vals) if vals else 0.0
    out = []
    for s in items:
        chg = s.get("chg")
        px = 0 if (chg is None or top == 0) else int(round(abs(chg) / top * BAR_MAX_PX))
        out.append({
            "NAME": s.get("name", ""),
            "CHG": fmt_chg(chg),
            "COLOR": color_of(chg),
            "BAR_PX": px,
            "IF_POS": bool(chg is not None and chg > FLAT_EPS),
            "IF_NEG": bool(chg is not None and chg < -FLAT_EPS),
        })
    return out


def table(spec):
    """{"head":[["종목","left"],…], "rows":[[셀,…],…]} -> 헤더/행 컨텍스트.

    셀은 문자열이거나 {"t":텍스트,"chg":수치} — 후자면 부호에 따라 색이 붙는다.
    """
    aligns = [a for _, a in spec.get("head", [])]
    head = [{"TEXT": t, "ALIGN": a} for t, a in spec.get("head", [])]
    rows = []
    for r in spec.get("rows", []):
        cells = []
        for i, c in enumerate(r):
            align = aligns[i] if i < len(aligns) else "left"
            if isinstance(c, dict):
                txt = c.get("t")
                if txt is None and c.get("chg") is not None:
                    txt = fmt_chg(c["chg"], c.get("unit", "%"))
                cells.append({
                    "TEXT": MISSING if txt is None else str(txt),
                    "ALIGN": align,
                    "COLOR": NA if txt is None else color_of(c.get("chg")) if "chg" in c else INK,
                })
            else:
                cells.append({"TEXT": str(c), "ALIGN": align, "COLOR": INK})
        rows.append({"CELLS": cells})
    return head, rows


# ── 게이트 (지시서 §4-E) ──────────────────────────────────────────────────
def count_missing(s):
    """미확보 '항목' 수. 한 항목에 값·등락이 둘 다 비어도 1건으로 센다."""
    n = 0
    for key in ("tiles", "aux", "rate_tiles", "s4_tiles"):
        for it in s.get(key) or []:
            if it.get("value") is None or it.get("chg") is None:
                n += 1
    for it in s.get("sectors") or []:        # 섹터는 등락률만 쓰는 항목
        if it.get("chg") is None:
            n += 1
    return n


def superlatives(s):
    """최상급·기록 표현을 뽑아 [종료] 로그에 올린다(지시서 §4-E-6).

    기계가 근거까지 확인할 수는 없으므로 HOLD로 막지 않고 '확인 대상'으로만 내민다.
    """
    text = " ".join(filter(None, [
        s.get("headline", ""), s.get("subtitle", ""),
        " ".join(s.get("key_points") or []),
        s.get("summary_prose", ""), s.get("sector_note", ""), s.get("cons_note", ""),
        (s.get("deep_dive") or {}).get("prose", ""),
    ]))
    pats = ["사상 첫", "사상 최고", "사상 최저", "역대", "최대 상승", "최대 하락",
            "최고치", "최저치", "신기록", "최강", "처음으로", r"\d+년 만"]
    found = []
    for p in pats:
        for m in re.finditer(p, text):
            found.append(text[max(0, m.start() - 12): m.end() + 12].strip())
    return sorted(set(found))


def gate(s):
    """반환: (PASS|HOLD, [사유…], [확인대상…]). 사유가 있으면 제목 꼬리표를 붙인다."""
    issues = []

    # 1) 필수 슬롯
    req_tiles = [t for t in (s.get("tiles") or []) if t.get("value") is None]
    if req_tiles:
        issues.append("타일 미확보 {}건: {}".format(
            len(req_tiles), ", ".join(t.get("label", "?") for t in req_tiles)))
    sectors = s.get("sectors") or []
    if sectors and any(x.get("chg") is None for x in sectors):
        issues.append("섹터 등락 미확보 포함")

    # 2) 방향 충돌 — 헤드라인/키포인트/산문의 지수·금리 부호가 슬롯과 어긋나는지
    issues += direction_conflicts(s)

    # 3) 캘린더 날짜 ↔ 요일 정합
    issues += calendar_mismatch(s)

    # 4) 확정 슬롯에 추측성 단어
    hard = " ".join(filter(None, [
        s.get("headline", ""), s.get("subtitle", ""),
        " ".join(s.get("key_points") or []),
    ]))
    hit = [w for w in HEDGE_WORDS if w in hard]
    if hit:
        issues.append("제목·키포인트에 추측성 표현: {}".format(", ".join(w.strip() for w in hit)))

    # 5) 뉴스 발행일
    issues += stale_news(s)

    # 6) 최상급 표현은 막지 않고 목록으로 내민다
    return ("PASS" if not issues else "HOLD"), issues, superlatives(s)


def _target_date(s):
    try:
        return datetime.strptime(s["date"], "%Y-%m-%d").date()
    except Exception:
        return None


def direction_conflicts(s):
    """본문 텍스트가 '상승/하락'을 말하는데 슬롯 부호가 반대면 잡는다."""
    out = []
    text = " ".join(filter(None, [
        s.get("headline", ""), " ".join(s.get("key_points") or []), s.get("summary_prose", ""),
    ]))
    if not text:
        return out

    up_w = ("상승", "급등", "반등", "강세", "올라", "뛰")
    dn_w = ("하락", "급락", "약세", "밀려", "내려", "떨어")

    for t in (s.get("tiles") or []):
        label, chg = t.get("label", ""), t.get("chg")
        if chg is None or not label:
            continue
        key = label.split()[0]
        for m in re.finditer(re.escape(key), text):
            seg = text[m.start(): m.start() + 40]
            said_up = any(w in seg for w in up_w)
            said_dn = any(w in seg for w in dn_w)
            if said_up and chg < -FLAT_EPS:
                out.append("방향 충돌: '{}' 문장은 상승인데 슬롯은 {:+.2f}%".format(key, chg))
            elif said_dn and chg > FLAT_EPS:
                out.append("방향 충돌: '{}' 문장은 하락인데 슬롯은 {:+.2f}%".format(key, chg))
    return sorted(set(out))


def calendar_mismatch(s):
    out, td = [], _target_date(s)
    if not td:
        return out
    rows = list(s.get("calendar") or [])
    for g in (s.get("calendar_groups") or []):     # 두 갈래(경제·엔터) 형태도 함께 검사
        rows += list(g.get("rows") or [])
    for row in rows:
        d = str(row.get("d", ""))
        m = re.match(r"(\d{1,2})/(\d{1,2})\((.)\)", d)
        if not m:
            continue
        mm, dd, wd = int(m.group(1)), int(m.group(2)), m.group(3)
        year = td.year + (1 if (td.month == 12 and mm == 1) else 0)
        try:
            real = date(year, mm, dd)
        except ValueError:
            out.append("캘린더 날짜 없음: {}".format(d))
            continue
        if WEEKDAY_KO[real.weekday()] != wd:
            out.append("캘린더 요일 불일치: {} → 실제 {}요일".format(d, WEEKDAY_KO[real.weekday()]))
    return out


def stale_news(s):
    out, td = [], _target_date(s)
    if not td:
        return out
    for n in (s.get("news") or []):
        raw = str(n.get("date", "")).strip()
        m = re.match(r"(\d{1,2})/(\d{1,2})$", raw)
        if not m:
            out.append("뉴스 발행일 확인 불가: {}".format(n.get("title", "?")[:24]))
            continue
        try:
            nd = date(td.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            out.append("뉴스 발행일 형식 오류: {}".format(raw))
            continue
        if nd < td - timedelta(days=1) or nd > td:
            out.append("뉴스 발행일 범위 밖({}): {}".format(raw, n.get("title", "?")[:24]))
    return out


# ── slots.json -> 템플릿 컨텍스트 ─────────────────────────────────────────
def build(s):
    market = s.get("market", "us")
    ctx = dict(BANDS.get(market, BANDS["us"]))

    ctx.update({
        "REPORT_KIND": "미국장" if market == "us" else "국내장",
        "DATE_LABEL": s.get("date_label", ""),
        "ISSUE_NO": s.get("issue_no", ""),
        "HEADLINE": s.get("headline", ""),
        "SUBTITLE": s.get("subtitle", ""),
        "SUMMARY_PROSE": s.get("summary_prose", ""),
        "SECTION2_TITLE": s.get("section2_title", "섹터 · 종목"),
        "SECTION4_TITLE": s.get("section4_title", ""),
        "SECTOR_NOTE": s.get("sector_note", ""),
        "SECTOR_FOOTNOTE": s.get("sector_footnote", ""),
        "SECTOR_NOTE_TOP": s.get("sector_note_top", ""),
        "IF_SECTOR_NOTE_TOP": bool(s.get("sector_note_top")),
        "CONS_NOTE": s.get("cons_note", ""),
        "CONS_FOOTNOTE": s.get("cons_footnote", ""),
        "MAP_HEAD_1": s.get("map_head_1", ""),
        "MAP_HEAD_2": s.get("map_head_2", ""),
        "S4_FOOTNOTE": s.get("s4_footnote", ""),
        "FLOW_FOOTNOTE": s.get("flow_footnote", ""),
        "S5_FOOTNOTE": s.get("s5_footnote", ""),
        "SOURCE_NOTE_1": s.get("source_note_1", ""),
    })

    tiles = [tile(t) for t in (s.get("tiles") or [])]
    ctx["TILES_ROW1"], ctx["TILES_ROW2"] = tiles[:4], tiles[4:8]

    aux = [tile(a) for a in (s.get("aux") or [])]
    ctx["AUX"], ctx["IF_AUX"] = aux, bool(aux)

    ctx["KEY_POINTS"] = [{"N": str(i + 1), "TEXT": t}
                         for i, t in enumerate(s.get("key_points") or [])]

    ctx["SECTORS"] = bars(s.get("sectors") or [])

    mh, mr = table(s.get("movers") or {})
    ctx["MOVERS_HEAD"], ctx["MOVERS_ROWS"] = mh, mr

    rt = [tile(t) for t in (s.get("rate_tiles") or [])]
    ctx["RATE_TILES"], ctx["IF_RATE_TILES"] = rt, bool(rt)

    ctx["MACRO_ROWS"] = [{"K": r.get("k", ""), "V": r.get("v", "")}
                         for r in (s.get("macro_rows") or [])]

    ch, cr = table(s.get("consensus") or {})
    ctx["CONS_HEAD"], ctx["CONS_ROWS"] = ch, cr

    s4 = [tile(t) for t in (s.get("s4_tiles") or [])]
    ctx["S4_TILES"], ctx["IF_S4_TILES"] = s4, bool(s4)

    fh, fr = table(s.get("flow") or {})
    ctx["FLOW_HEAD"], ctx["FLOW_ROWS"] = fh, fr
    ctx["IF_S4_FLOW"] = bool(fr)

    ctx["MAP_ROWS"] = [{
        "A": r.get("a", ""), "B": r.get("b", ""),
        "DIR": r.get("dir", "중립"),
        "DIR_COLOR": DIR_COLORS.get(r.get("dir", "중립"), MUTED),
    } for r in (s.get("map_rows") or [])]

    ctx["CAL_GROUPS"] = [{
        "GROUP": g.get("group", ""),
        "PAD_TOP": 0 if i == 0 else 10,
        "ROWS": [{"D": r.get("d", ""), "T": r.get("t", "")} for r in (g.get("rows") or [])],
    } for i, g in enumerate(s.get("calendar_groups") or [])]

    ctx["NEWS"] = [{"TITLE": n.get("title", ""), "URL": n.get("url", ""),
                    "DATE": n.get("date", "")} for n in (s.get("news") or [])]

    dd = s.get("deep_dive") or {}
    ctx["DEEP_TITLE"] = dd.get("title", "")
    ctx["DEEP_PROSE"] = dd.get("prose", "")
    ctx["DEEP_ROWS"] = [{"K": r.get("k", ""), "V": r.get("v", "")} for r in (dd.get("rows") or [])]

    status, issues, warns = gate(s)
    footer = s.get("footer_status", "")
    footer = footer.replace("{MISSING}", str(count_missing(s)))
    if "GATE" not in footer:
        footer = "{} · GATE {}".format(footer.rstrip(" ·"), status).lstrip(" ·").strip()
    ctx["FOOTER_STATUS"] = footer
    return ctx, status, issues, warns


# ── 평문(plain) ───────────────────────────────────────────────────────────
def plain(s, ctx):
    L = []
    add = L.append
    add("[{} 마감] {}".format(ctx["REPORT_KIND"], s.get("headline", "")))
    add(s.get("date_label", ""))
    add(s.get("subtitle", ""))
    add("")
    add("── 지수 ──")
    for t in (s.get("tiles") or []):
        d = tile(t)
        add("{}  {}  {}".format(d["LABEL"], d["VALUE"], d["CHG"]))
    add("")
    add("── 1. 마감 요약 ──")
    for i, k in enumerate(s.get("key_points") or []):
        add("{}. {}".format(i + 1, k))
    add("")
    add(s.get("summary_prose", ""))
    if s.get("aux"):
        add("")
        parts = []
        for a in s["aux"]:
            d = tile(a)
            parts.append("{} {}".format(d["LABEL"], MISSING) if d["VALUE"] == MISSING
                         else "{} {} {}".format(d["LABEL"], d["VALUE"], d["CHG"]))
        add(" / ".join(parts))
    add("")
    add("── 2. {} ──".format(s.get("section2_title", "")))
    for x in (s.get("sectors") or []):
        add("{}  {}".format(x.get("name", ""), fmt_chg(x.get("chg"))))
    if s.get("sector_note"):
        add("")
        add(s["sector_note"])
    add("")
    add("── 3. 매크로 · 컨센서스 ──")
    for r in (s.get("macro_rows") or []):
        add("{}: {}".format(r.get("k", ""), r.get("v", "")))
    if s.get("cons_note"):
        add("")
        add(s["cons_note"])
    add("")
    add("── 4. {} ──".format(s.get("section4_title", "")))
    for r in (s.get("map_rows") or []):
        add("{} → {} [{}]".format(r.get("a", ""), r.get("b", ""), r.get("dir", "중립")))
    add("")
    add("── 5. 일정 · 뉴스 ──")
    for g in (s.get("calendar_groups") or []):
        add("[{}]".format(g.get("group", "")))
        for r in (g.get("rows") or []):
            add("{} — {}".format(r.get("d", ""), r.get("t", "")))
    for n in (s.get("news") or []):
        add("{} ({}) {}".format(n.get("title", ""), n.get("date", ""), n.get("url", "")))
    dd = s.get("deep_dive") or {}
    add("")
    add("── 6. 공부섹터 — {} ──".format(dd.get("title", "")))
    add(dd.get("prose", ""))
    for r in (dd.get("rows") or []):
        add("{}: {}".format(r.get("k", ""), r.get("v", "")))
    add("")
    add(ctx["FOOTER_STATUS"])
    add("투자 판단의 참고 자료이며 투자 권유가 아닙니다.")
    return "\n".join(L)


TEMPLATE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{REPORT_KIND}} 마감 리포트 — {{DATE_LABEL}}</title>
</head>
<!--
  마감 리포트 공용 템플릿 (미국장·국내장)
  - 슬롯: {{NAME}}  /  반복: {{#ROWS}} … {{/ROWS}}  /  조건: {{#IF_X}} … {{/IF_X}}
  - 색은 render.py가 등락 부호로 결정: UP=#C8102E DOWN=#1D5BB0 FLAT(±0.05%)=#1E8449 NA=#8a877f
    → 각 행의 {{COLOR}} 에 위 4개 중 하나만 들어간다. LLM은 색을 쓰지 않는다.
  - 밴드 색 {{BAND}}: 미국장 #0B2A4A / 국내장 #0F3D3E. 연한 배경 {{BAND_TINT}}: #eef2f6 / #eaf1f1.
  - 막대 폭 {{BAR_PX}} = round(|chg| / max|chg| * 118). render.py 계산.
  - 값이 null이면 render.py가 "[미확보]"를 회색으로 넣는다. 근사치 대체 금지.
  - 이메일 호환을 위해 flex/grid 대신 table 사용, 폰트는 시스템 고딕 폴백.
-->
<body style="margin:0; padding:0; background:#f0efec;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f0efec;">
<tr><td align="center" style="padding:16px 8px;">
<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="width:640px; max-width:100%; background:#ffffff; color:#1a1a1a; font-family:'Noto Sans KR','Apple SD Gothic Neo','Malgun Gothic',sans-serif; font-size:13px; line-height:1.6; font-variant-numeric:tabular-nums;">

<!-- ===== 밴드 ===== -->
<tr><td style="background:{{BAND}}; color:#ffffff; padding:20px 40px 22px 40px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td style="font-size:11px; letter-spacing:0.08em; color:#c7d3dc;">DAILY MARKET WRAP · {{MARKET_TAG}}</td>
      <td align="right" style="font-size:11px; letter-spacing:0.08em; color:#c7d3dc;">{{DATE_LABEL}} · No.{{ISSUE_NO}}</td>
    </tr>
    <tr><td colspan="2" style="padding-top:10px; font-size:23px; font-weight:900; line-height:1.35; letter-spacing:-0.01em; color:#ffffff;">{{HEADLINE}}</td></tr>
    <tr><td colspan="2" style="padding-top:8px; font-size:12.5px; color:#dbe4ea;">{{SUBTITLE}}</td></tr>
  </table>
</td></tr>

<!-- ===== 지수 타일 (8칸, 4×2) ===== -->
<tr><td style="background:{{BAND_TINT}}; border-bottom:1px solid #d5dbe2; padding:14px 40px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr>
    {{#TILES_ROW1}}
      <td width="25%" style="padding:4px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff; border:1px solid #d5dbe2;">
          <tr><td style="padding:8px 10px;">
            <div style="font-size:10px; color:#6b6963; font-family:'JetBrains Mono',Menlo,Consolas,monospace;">{{LABEL}}</div>
            <div style="font-size:15px; font-weight:700; font-family:'JetBrains Mono',Menlo,Consolas,monospace; color:{{VALUE_COLOR}};">{{VALUE}}</div>
            <div style="font-size:11.5px; color:{{COLOR}}; font-family:'JetBrains Mono',Menlo,Consolas,monospace;">{{CHG}}</div>
          </td></tr>
        </table>
      </td>
    {{/TILES_ROW1}}
    </tr>
    <tr>
    {{#TILES_ROW2}}
      <td width="25%" style="padding:4px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff; border:1px solid #d5dbe2;">
          <tr><td style="padding:8px 10px;">
            <div style="font-size:10px; color:#6b6963; font-family:'JetBrains Mono',Menlo,Consolas,monospace;">{{LABEL}}</div>
            <div style="font-size:15px; font-weight:700; font-family:'JetBrains Mono',Menlo,Consolas,monospace; color:{{VALUE_COLOR}};">{{VALUE}}</div>
            <div style="font-size:11.5px; color:{{COLOR}}; font-family:'JetBrains Mono',Menlo,Consolas,monospace;">{{CHG}}</div>
          </td></tr>
        </table>
      </td>
    {{/TILES_ROW2}}
    </tr>
  </table>
</td></tr>

<tr><td style="padding:22px 40px 26px 40px;">

<!-- ===== 1. 마감 요약 ===== -->
<div style="font-size:14px; font-weight:700; color:{{BAND}}; border-bottom:2px solid {{BAND}}; padding-bottom:4px; margin-bottom:10px;">1. 마감 요약</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {{BAND}}; margin-bottom:10px;">
  <tr><td style="padding:12px 16px; font-size:12.5px;">
    {{#KEY_POINTS}}
    <table role="presentation" cellpadding="0" cellspacing="0"><tr>
      <td valign="top" style="font-weight:700; color:{{BAND}}; width:16px; padding:2px 0;">{{N}}</td>
      <td style="padding:2px 0;">{{TEXT}}</td>
    </tr></table>
    {{/KEY_POINTS}}
  </td></tr>
</table>
<p style="margin:0 0 10px 0; font-size:13.5px; line-height:1.75; text-align:justify;">{{SUMMARY_PROSE}}</p>
{{#IF_AUX}}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid #d5dbe2; border-bottom:1px solid #d5dbe2; font-size:11.5px; margin-bottom:6px;">
  <tr>
  {{#AUX}}
    <td width="25%" style="padding:6px 4px;"><span style="color:#6b6963;">{{LABEL}}</span> &nbsp;<span style="color:{{VALUE_COLOR}};">{{VALUE}}</span> <span style="color:{{COLOR}};">{{CHG}}</span></td>
  {{/AUX}}
  </tr>
</table>
{{/IF_AUX}}
<div style="font-size:10.5px; color:#6b6963; margin-bottom:22px;">{{SOURCE_NOTE_1}} <span style="color:#C8102E;">상승</span> <span style="color:#1D5BB0;">하락</span> <span style="color:#1E8449;">보합(±0.05%)</span>. [미확보]는 수집 실패 항목, 근사치로 대체하지 않음.</div>

<!-- ===== 2. 섹터·종목 ===== -->
<div style="font-size:14px; font-weight:700; color:{{BAND}}; border-bottom:2px solid {{BAND}}; padding-bottom:4px; margin-bottom:10px;">2. {{SECTION2_TITLE}}</div>
{{#IF_SECTOR_NOTE_TOP}}<div style="font-size:11px; color:#6b6963; margin-bottom:4px;">{{SECTOR_NOTE_TOP}}</div>{{/IF_SECTOR_NOTE_TOP}}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:12px; margin-bottom:6px;">
  {{#SECTORS}}
  <tr>
    <td width="100" align="right" style="padding:2px 8px 2px 0;">{{NAME}}</td>
    <td width="118" align="right" style="padding:2px 0;">{{#IF_NEG}}<div style="display:inline-block; height:11px; width:{{BAR_PX}}px; background:{{COLOR}}; vertical-align:middle;"></div>{{/IF_NEG}}</td>
    <td width="1" style="background:{{BAND}}; padding:0;"><div style="width:1px; height:13px;"></div></td>
    <td width="118" align="left" style="padding:2px 0;">{{#IF_POS}}<div style="display:inline-block; height:11px; width:{{BAR_PX}}px; background:{{COLOR}}; vertical-align:middle;"></div>{{/IF_POS}}</td>
    <td align="right" style="padding:2px 0 2px 8px; color:{{COLOR}}; font-family:'JetBrains Mono',Menlo,Consolas,monospace;">{{CHG}}</td>
  </tr>
  {{/SECTORS}}
</table>
<div style="font-size:10.5px; color:#6b6963; border-top:1px solid #d5dbe2; padding-top:4px; margin-bottom:10px;">{{SECTOR_FOOTNOTE}}</div>

<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; font-size:12.5px; margin-bottom:10px;">
  <tr style="background:{{BAND_TINT}};">
    {{#MOVERS_HEAD}}<th align="{{ALIGN}}" style="padding:6px 8px; color:{{BAND}}; font-weight:700;">{{TEXT}}</th>{{/MOVERS_HEAD}}
  </tr>
  {{#MOVERS_ROWS}}
  <tr style="border-bottom:1px solid #e3e6ea;">
    {{#CELLS}}<td align="{{ALIGN}}" style="padding:4px 8px; color:{{COLOR}}; border-bottom:1px solid #e3e6ea;">{{TEXT}}</td>{{/CELLS}}
  </tr>
  {{/MOVERS_ROWS}}
</table>
<p style="margin:0 0 22px 0; font-size:12.5px; line-height:1.7; color:#3d3b37;">{{SECTOR_NOTE}}</p>

<!-- ===== 3. 매크로·컨센서스 ===== -->
<div style="font-size:14px; font-weight:700; color:{{BAND}}; border-bottom:2px solid {{BAND}}; padding-bottom:4px; margin-bottom:10px;">3. 매크로 · 컨센서스</div>
{{#IF_RATE_TILES}}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:10px;">
  <tr>
  {{#RATE_TILES}}
    <td width="33%" style="padding:4px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #d5dbe2;"><tr><td style="padding:8px 10px;">
        <div style="font-size:10px; color:#6b6963; font-family:'JetBrains Mono',Menlo,Consolas,monospace;">{{LABEL}}</div>
        <div style="font-size:18px; font-weight:700; font-family:'JetBrains Mono',Menlo,Consolas,monospace; color:{{VALUE_COLOR}};">{{VALUE}}</div>
        <div style="font-size:11.5px; color:{{COLOR}};">{{CHG}}</div>
      </td></tr></table>
    </td>
  {{/RATE_TILES}}
  </tr>
</table>
{{/IF_RATE_TILES}}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; font-size:12.5px; margin-bottom:10px;">
  {{#MACRO_ROWS}}
  <tr>
    <td width="100" style="padding:5px 8px; font-weight:700; color:{{BAND}}; background:{{BAND_TINT}}; border-bottom:1px solid #e3e6ea;">{{K}}</td>
    <td style="padding:5px 8px; border-bottom:1px solid #e3e6ea;">{{V}}</td>
  </tr>
  {{/MACRO_ROWS}}
</table>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; font-size:12px; margin-bottom:6px;">
  <tr style="background:{{BAND_TINT}};">
    {{#CONS_HEAD}}<th align="{{ALIGN}}" style="padding:6px 8px; color:{{BAND}}; font-weight:700;">{{TEXT}}</th>{{/CONS_HEAD}}
  </tr>
  {{#CONS_ROWS}}
  <tr>
    {{#CELLS}}<td align="{{ALIGN}}" style="padding:4px 8px; color:{{COLOR}}; border-bottom:1px solid #e3e6ea;">{{TEXT}}</td>{{/CELLS}}
  </tr>
  {{/CONS_ROWS}}
</table>
<div style="font-size:10.5px; color:#6b6963; margin-bottom:6px;">{{CONS_FOOTNOTE}}</div>
<p style="margin:0 0 22px 0; font-size:12.5px; line-height:1.7; color:#3d3b37;">{{CONS_NOTE}}</p>

<!-- ===== 4. 국내 read-through (미국장) / 수급·내일 관전 (국내장) ===== -->
<div style="font-size:14px; font-weight:700; color:{{BAND}}; border-bottom:2px solid {{BAND}}; padding-bottom:4px; margin-bottom:10px;">4. {{SECTION4_TITLE}}</div>
{{#IF_S4_TILES}}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:10px;">
  <tr>
  {{#S4_TILES}}
    <td width="25%" style="padding:4px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #d5dbe2;"><tr><td style="padding:8px 10px;">
        <div style="font-size:10px; color:#6b6963; font-family:'JetBrains Mono',Menlo,Consolas,monospace;">{{LABEL}}</div>
        <div style="font-size:15px; font-weight:700; font-family:'JetBrains Mono',Menlo,Consolas,monospace; color:{{VALUE_COLOR}};">{{VALUE}}</div>
        <div style="font-size:11.5px; color:{{COLOR}};">{{CHG}}</div>
      </td></tr></table>
    </td>
  {{/S4_TILES}}
  </tr>
</table>
{{/IF_S4_TILES}}
{{#IF_S4_FLOW}}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; font-size:12.5px; margin-bottom:6px;">
  <tr style="background:{{BAND_TINT}};">
    {{#FLOW_HEAD}}<th align="{{ALIGN}}" style="padding:6px 8px; color:{{BAND}}; font-weight:700;">{{TEXT}}</th>{{/FLOW_HEAD}}
  </tr>
  {{#FLOW_ROWS}}
  <tr>
    {{#CELLS}}<td align="{{ALIGN}}" style="padding:5px 8px; color:{{COLOR}}; border-bottom:1px solid #e3e6ea;">{{TEXT}}</td>{{/CELLS}}
  </tr>
  {{/FLOW_ROWS}}
</table>
<div style="font-size:10.5px; color:#6b6963; margin-bottom:10px;">{{FLOW_FOOTNOTE}}</div>
{{/IF_S4_FLOW}}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; font-size:12.5px; margin-bottom:6px;">
  <tr style="background:{{BAND_TINT}};">
    <th align="left" width="130" style="padding:6px 8px; color:{{BAND}}; font-weight:700;">{{MAP_HEAD_1}}</th>
    <th align="left" style="padding:6px 8px; color:{{BAND}}; font-weight:700;">{{MAP_HEAD_2}}</th>
    <th align="left" width="52" style="padding:6px 8px; color:{{BAND}}; font-weight:700;">방향</th>
  </tr>
  {{#MAP_ROWS}}
  <tr>
    <td style="padding:5px 8px; border-bottom:1px solid #e3e6ea;">{{A}}</td>
    <td style="padding:5px 8px; border-bottom:1px solid #e3e6ea;">{{B}}</td>
    <td style="padding:5px 8px; border-bottom:1px solid #e3e6ea; color:{{DIR_COLOR}}; font-weight:700;">{{DIR}}</td>
  </tr>
  {{/MAP_ROWS}}
</table>
<div style="font-size:10.5px; color:#6b6963; margin-bottom:22px;">{{S4_FOOTNOTE}}</div>

<!-- ===== 5. 일정·뉴스 ===== -->
<div style="font-size:14px; font-weight:700; color:{{BAND}}; border-bottom:2px solid {{BAND}}; padding-bottom:4px; margin-bottom:10px;">5. 일정 · 뉴스</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:12.5px; margin-bottom:6px;">
  <tr>
    <td width="50%" valign="top" style="padding-right:12px;">
      {{#CAL_GROUPS}}
      <div style="font-weight:700; color:{{BAND}}; padding:{{PAD_TOP}}px 8px 4px 8px;">{{GROUP}}</div>
      {{#ROWS}}
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
        <td width="44" style="padding:4px 8px; color:{{BAND}}; font-family:'JetBrains Mono',Menlo,Consolas,monospace; font-weight:700; border-bottom:1px solid #e3e6ea;">{{D}}</td>
        <td style="padding:4px 8px; border-bottom:1px solid #e3e6ea;">{{T}}</td>
      </tr></table>
      {{/ROWS}}
      {{/CAL_GROUPS}}
    </td>
    <td width="50%" valign="top" style="padding-left:12px;">
      <div style="font-weight:700; color:{{BAND}}; padding:0 8px 4px 8px;">뉴스</div>
      {{#NEWS}}
      <div style="padding:4px 8px; border-bottom:1px solid #e3e6ea;"><a href="{{URL}}" style="color:{{BAND}}; text-decoration:underline;">{{TITLE}}</a> <span style="color:#6b6963;">· {{DATE}}</span></div>
      {{/NEWS}}
    </td>
  </tr>
</table>
<div style="font-size:10.5px; color:#6b6963; margin-bottom:22px;">{{S5_FOOTNOTE}}</div>

<!-- ===== 6. 공부섹터 ===== -->
<div style="font-size:14px; font-weight:700; color:{{BAND}}; border-bottom:2px solid {{BAND}}; padding-bottom:4px; margin-bottom:10px;">6. 공부섹터 — {{DEEP_TITLE}}</div>
<p style="margin:0 0 10px 0; font-size:13px; line-height:1.75; text-align:justify;">{{DEEP_PROSE}}</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; font-size:12.5px; margin-bottom:22px;">
  {{#DEEP_ROWS}}
  <tr>
    <td width="100" style="padding:5px 8px; font-weight:700; color:{{BAND}}; background:{{BAND_TINT}}; border-bottom:1px solid #e3e6ea;">{{K}}</td>
    <td style="padding:5px 8px; border-bottom:1px solid #e3e6ea;">{{V}}</td>
  </tr>
  {{/DEEP_ROWS}}
</table>

<!-- ===== 푸터 ===== -->
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid {{BAND}}; font-size:10.5px; color:#6b6963;">
  <tr>
    <td style="padding-top:10px; font-family:'JetBrains Mono',Menlo,Consolas,monospace;">{{FOOTER_STATUS}}</td>
    <td align="right" style="padding-top:10px;">투자 판단의 참고 자료이며 투자 권유가 아닙니다.</td>
  </tr>
</table>

</td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.stderr.write("usage: mkreport.py slots.json [outdir]\n")
        return 2
    with open(args[0], encoding="utf-8-sig") as f:
        slots = json.load(f)
    outdir = args[1] if len(args) > 1 else "."

    ctx, status, issues, warns = build(slots)
    body_html = render(TEMPLATE, ctx)
    body_txt = plain(slots, ctx)

    with open(os.path.join(outdir, "body.html"), "w", encoding="utf-8") as f:
        f.write(body_html)
    with open(os.path.join(outdir, "body.txt"), "w", encoding="utf-8") as f:
        f.write(body_txt)

    print("GATE {} · MISSING {}".format(status, count_missing(slots)))
    for i in issues:
        print("ISSUE: {}".format(i))
    for w in warns:
        print("SUPERLATIVE: ...{}...".format(w))
    print("LEFTOVER_SLOTS: {}".format(len(re.findall(r"\{\{[^}]*\}\}", body_html))))
    print("WROTE: {}/body.html {} bytes, {}/body.txt {} bytes".format(
        outdir, len(body_html.encode("utf-8")), outdir, len(body_txt.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
