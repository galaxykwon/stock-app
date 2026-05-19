"""
한국투자증권 KIS OpenAPI — Vercel Serverless (FastAPI)
프론트엔드 HTML + 백엔드 API 통합 서버
"""

import os
import httpx
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 설정 ─────────────────────────────────────────────────────────
APP_KEY    = os.environ.get("KIS_APP_KEY", "")
APP_SECRET = os.environ.get("KIS_APP_SECRET", "")
KIS_BASE   = "https://openapi.koreainvestment.com:9443"

_token_cache: dict = {"access_token": None, "expires_at": None}
_data_cache:  dict = {}

# ─── 토큰 ─────────────────────────────────────────────────────────
async def get_token() -> str:
    now = datetime.now()
    if _token_cache["access_token"] and _token_cache["expires_at"] and _token_cache["expires_at"] > now:
        return _token_cache["access_token"]
    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        res = await client.post(
            f"{KIS_BASE}/oauth2/tokenP",
            json={"grant_type": "client_credentials", "appkey": APP_KEY, "appsecret": APP_SECRET},
            headers={"content-type": "application/json"},
        )
    data = res.json()
    token = data.get("access_token", "")
    _token_cache["access_token"] = token
    _token_cache["expires_at"] = now + timedelta(hours=23)
    return token

def headers(tr_id: str) -> dict:
    return {
        "content-type": "application/json",
        "authorization": f"Bearer {_token_cache.get('access_token','')}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": tr_id,
        "custtype": "P",
    }

def cache_ttl() -> int:
    now = datetime.now()
    t = now.hour * 100 + now.minute
    return 60 if (now.weekday() < 5 and 900 <= t <= 1530) else 3600

def today() -> str:
    now = datetime.now()
    wd = now.weekday()
    if wd == 5: now -= timedelta(days=1)
    elif wd == 6: now -= timedelta(days=2)
    if now.hour < 9:
        now -= timedelta(days=1)
        if now.weekday() == 5: now -= timedelta(days=1)
        elif now.weekday() == 6: now -= timedelta(days=2)
    return now.strftime("%Y%m%d")

async def kis_get(path: str, params: dict, tr_id: str) -> dict:
    await get_token()
    async with httpx.AsyncClient(verify=False, timeout=15) as client:
        res = await client.get(f"{KIS_BASE}{path}", params=params, headers=headers(tr_id))
    return res.json()

# ─── 순위 파싱 ────────────────────────────────────────────────────
def parse_rank(raw: dict, market: str, inv_type: str) -> dict:
    output = raw.get("output", [])
    if not output:
        return {"market": market, "type": inv_type, "items": [], "msg": raw.get("msg1", "")}
    items = []
    for i, item in enumerate(output[:10]):
        items.append({
            "rank": i + 1,
            "code": item.get("mksc_shrn_iscd", ""),
            "name": item.get("hts_kor_isnm", ""),
            "price": int(item.get("stck_prpr", 0) or 0),
            "change_rate": float(item.get("prdy_ctrt", 0) or 0),
            "foreign_net_amt": int(item.get("frgn_ntby_tr_pbmn", 0) or 0),
            "foreign_net_vol": int(item.get("frgn_ntby_qty", 0) or 0),
            "inst_net_amt": int(item.get("orgn_ntby_tr_pbmn", 0) or 0),
            "inst_net_vol": int(item.get("orgn_ntby_qty", 0) or 0),
            "retail_net_vol": int(item.get("indv_ntby_qty", 0) or 0),
        })
    return {"market": market, "type": inv_type, "items": items, "updated": datetime.now().isoformat()}

# ─── API 엔드포인트 ───────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}

@app.get("/api/token-test")
async def token_test():
    token = await get_token()
    ok = bool(token and len(token) > 10)
    return {"success": ok, "preview": token[:20] + "..." if ok else "실패"}

@app.get("/api/rank/foreign")
async def rank_foreign(market: str = Query("J")):
    ck = f"foreign_{market}"
    if ck in _data_cache and _data_cache[ck]["exp"] > datetime.now():
        return _data_cache[ck]["data"]
    raw = await kis_get(
        "/uapi/domestic-stock/v1/quotations/foreign-institution-total",
        {"fid_cond_mrkt_div_code": market, "fid_cond_scr_div_code": "16449",
         "fid_input_iscd": "0000", "fid_div_cls_code": "0",
         "fid_rank_sort_cls_code": "0", "fid_etc_cls_code": "0"},
        "FHPTJ04430000",
    )
    result = parse_rank(raw, market, "foreign")
    _data_cache[ck] = {"data": result, "exp": datetime.now() + timedelta(seconds=cache_ttl())}
    return result

@app.get("/api/rank/institution")
async def rank_institution(market: str = Query("J")):
    ck = f"inst_{market}"
    if ck in _data_cache and _data_cache[ck]["exp"] > datetime.now():
        return _data_cache[ck]["data"]
    raw = await kis_get(
        "/uapi/domestic-stock/v1/quotations/foreign-institution-total",
        {"fid_cond_mrkt_div_code": market, "fid_cond_scr_div_code": "16449",
         "fid_input_iscd": "0000", "fid_div_cls_code": "1",
         "fid_rank_sort_cls_code": "0", "fid_etc_cls_code": "0"},
        "FHPTJ04400000",
    )
    result = parse_rank(raw, market, "institution")
    _data_cache[ck] = {"data": result, "exp": datetime.now() + timedelta(seconds=cache_ttl())}
    return result

@app.get("/api/stock-search")
async def stock_search(code: str = Query(...), market: str = Query("J")):
    async def price():
        return await kis_get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            {"fid_cond_mrkt_div_code": market, "fid_input_iscd": code},
            "FHKST01010100",
        )
    async def investor():
        return await kis_get(
            "/uapi/domestic-stock/v1/quotations/inquire-investor",
            {"fid_cond_mrkt_div_code": market, "fid_input_iscd": code,
             "fid_input_date_1": today(), "fid_input_date_2": today()},
            "FHKST01010300",
        )
    p, inv = await asyncio.gather(price(), investor())
    o = p.get("output", {})
    inv_list = inv.get("output", [{}])
    iv = inv_list[0] if inv_list else {}
    return {
        "code": code,
        "name": o.get("hts_kor_isnm", ""),
        "price": int(o.get("stck_prpr", 0) or 0),
        "change_rate": float(o.get("prdy_ctrt", 0) or 0),
        "volume": int(o.get("acml_vol", 0) or 0),
        "foreign_net_amt": int(iv.get("frgn_ntby_tr_pbmn", 0) or 0),
        "foreign_net_vol": int(iv.get("frgn_ntby_qty", 0) or 0),
        "inst_net_amt": int(iv.get("orgn_ntby_tr_pbmn", 0) or 0),
        "inst_net_vol": int(iv.get("orgn_ntby_qty", 0) or 0),
        "retail_net_amt": int(iv.get("indv_ntby_tr_pbmn", 0) or 0),
        "retail_net_vol": int(iv.get("indv_ntby_qty", 0) or 0),
    }

# ─── 프론트엔드 HTML (싱글 파일, 인라인) ─────────────────────────
@app.get("/", response_class=HTMLResponse)
async def frontend():
    return HTML_PAGE

# HTML은 아래 별도 변수에 정의
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1"/>
<meta name="theme-color" content="#178FE0"/>
<meta name="apple-mobile-web-app-capable" content="yes"/>
<title>매매동향</title>
<style>
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
body{font-family:'Pretendard','Apple SD Gothic Neo','Malgun Gothic',sans-serif;background:#F8F8F6;min-height:100vh;font-size:14px;color:#1a1a1a}
.app{max-width:480px;margin:0 auto;background:#F8F8F6;min-height:100vh}
/* 헤더 */
.hdr{background:#fff;border-bottom:.5px solid #E0E0DA;padding:14px 16px 0;position:sticky;top:0;z-index:10}
.hdr-row{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
.ttl{font-size:18px;font-weight:500}
.live{background:#E24B4A;color:#fff;font-size:10px;font-weight:600;padding:2px 7px;border-radius:99px;margin-left:8px}
.rbtn{background:none;border:.5px solid #C8C8C0;border-radius:8px;padding:5px 10px;font-size:12px;color:#666;cursor:pointer}
/* 탭 */
.tabs{display:flex}
.tab{flex:1;text-align:center;padding:8px 0;font-size:14px;color:#888;background:none;border:none;border-bottom:2px solid transparent;cursor:pointer}
.tab.on{color:#178FE0;border-bottom:2px solid #178FE0;font-weight:500}
/* 서브탭 */
.stabs{display:flex;gap:8px;padding:10px 16px;background:#fff;border-bottom:.5px solid #E0E0DA}
.stab{padding:6px 16px;font-size:13px;border-radius:99px;border:.5px solid #E0E0DA;cursor:pointer;background:none;color:#666}
.stab.on{background:#E6F1FB;color:#185FA5;border-color:#B5D4F4;font-weight:500}
/* 필터 */
.filters{display:flex;gap:8px;padding:10px 16px 4px}
.fbtn{padding:5px 14px;font-size:12px;border-radius:99px;border:.5px solid #E0E0DA;cursor:pointer;background:none;color:#666}
.fbtn.on{background:#E6F1FB;color:#185FA5;border-color:#B5D4F4;font-weight:500}
/* 날짜 */
.drow{padding:6px 16px;font-size:12px;color:#999}
/* 리스트 */
.list{padding:0 16px 16px}
.stitle{font-size:13px;font-weight:500;color:#666;margin:8px 0}
/* 카드 */
.card{background:#fff;border:.5px solid #E0E0DA;border-radius:10px;padding:11px 13px;margin-bottom:7px;cursor:pointer;transition:border-color .15s}
.card.sel{border-color:#B5D4F4;background:#F5F9FF}
.ctop{display:flex;align-items:center;gap:8px}
.rnk{width:22px;height:22px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;flex-shrink:0}
.sname{font-size:14px;font-weight:500;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.scode{font-size:11px;color:#bbb;flex-shrink:0}
.namt{font-size:14px;font-weight:500;flex-shrink:0}
.brow{display:flex;align-items:center;gap:6px;margin-top:6px}
.bbg{flex:1;height:5px;background:#F0F0EC;border-radius:99px;overflow:hidden}
.bfill{height:100%;border-radius:99px;min-width:2px;transition:width .4s}
.rchg{font-size:11px;min-width:52px;text-align:right}
/* 디테일 */
.dtl{margin-top:10px;padding-top:10px;border-top:.5px solid #F0F0EC}
.dgrid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:8px}
.dchip{text-align:center;padding:7px 4px;background:#F8F8F6;border-radius:6px;border:.5px solid #E0E0DA}
.dchip span{display:block;font-size:10px;color:#888;margin-bottom:2px}
.dchip b{font-size:12px;font-weight:600}
.dprice{display:flex;justify-content:space-between;font-size:13px;margin-top:6px}
/* 검색 */
.sarea{padding:12px 16px 0}
.srow{display:flex;gap:8px;margin-bottom:10px}
.sinp{flex:1;padding:9px 12px;border:.5px solid #C8C8C0;border-radius:8px;font-size:14px;background:#F8F8F6;outline:none;font-family:inherit}
.sinp:focus{border-color:#B5D4F4;background:#fff}
.sbtn{padding:9px 18px;background:#178FE0;color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;font-family:inherit}
.qrow{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.qbtn{padding:4px 10px;font-size:12px;border:.5px solid #E0E0DA;border-radius:99px;background:none;cursor:pointer;color:#444;font-family:inherit}
/* 검색결과 */
.rcard{background:#fff;border:.5px solid #E0E0DA;border-radius:12px;padding:14px;margin:0 16px}
.rchdr{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px}
.rname{font-size:16px;font-weight:600}
.rcode{font-size:12px;color:#bbb;margin-top:2px}
.rprice{font-size:18px;font-weight:600}
.rrate{font-size:12px;margin-top:2px}
.divdr{height:.5px;background:#F0F0EC;margin:10px 0}
.igrid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
.ibox{text-align:center;padding:10px 4px;background:#F8F8F6;border-radius:8px;border:.5px solid #E0E0DA}
.ilbl{font-size:11px;color:#888;margin-bottom:4px}
.iamt{font-size:13px;font-weight:600;margin-bottom:2px}
.ivol{font-size:10px;color:#bbb}
/* 상태 */
.empty{text-align:center;padding:40px 16px;color:#bbb;font-size:14px}
.loading{text-align:center;padding:32px;color:#888;font-size:14px}
.errmsg{margin:8px 16px;padding:12px;background:#FFF0F0;border:.5px solid #F7C1C1;border-radius:8px;font-size:13px;color:#A32D2D}
/* 푸터 */
.footer{text-align:center;padding:20px 16px;font-size:11px;color:#ccc;border-top:.5px solid #E8E8E4;margin-top:8px}
/* 페이지 토글 */
.page{display:none}.page.on{display:block}
</style>
</head>
<body>
<div class="app">

  <!-- 헤더 -->
  <div class="hdr">
    <div class="hdr-row">
      <div style="display:flex;align-items:center">
        <span class="ttl">매매동향</span>
        <span class="live">LIVE</span>
      </div>
      <button class="rbtn" id="refreshBtn" onclick="doRefresh()">↺ 새로고침</button>
    </div>
    <div class="tabs">
      <button class="tab on" onclick="switchTab('rank',this)">순위</button>
      <button class="tab" onclick="switchTab('search',this)">종목검색</button>
    </div>
  </div>

  <!-- 순위 페이지 -->
  <div id="pg-rank" class="page on">
    <div class="stabs" id="market-stabs">
      <button class="stab on" onclick="switchMarket('J',this)">코스피</button>
      <button class="stab" onclick="switchMarket('Q',this)">코스닥</button>
    </div>
    <div class="filters">
      <button class="fbtn on" onclick="switchInv('foreign',this)">외국인</button>
      <button class="fbtn" onclick="switchInv('institution',this)">기관</button>
    </div>
    <div class="drow" id="dateLabel">기준일: 로딩 중...</div>
    <div id="errBox" class="errmsg" style="display:none"></div>
    <div class="list">
      <div class="stitle" id="rankTitle">외국인 순매수 상위 10 · 코스피</div>
      <div id="rankList"><div class="loading">데이터 불러오는 중...</div></div>
    </div>
  </div>

  <!-- 검색 페이지 -->
  <div id="pg-search" class="page">
    <div class="sarea">
      <div class="stabs" id="search-stabs" style="padding:0 0 10px">
        <button class="stab on" onclick="switchSMkt('J',this)">코스피</button>
        <button class="stab" onclick="switchSMkt('Q',this)">코스닥</button>
      </div>
      <div class="srow">
        <input class="sinp" id="searchInput" type="text" placeholder="종목코드 6자리 (예: 005930)" maxlength="6"
          onkeydown="if(event.key==='Enter')doSearch()"/>
        <button class="sbtn" onclick="doSearch()">조회</button>
      </div>
      <div class="qrow">
        <button class="qbtn" onclick="quick('005930','J')">삼성전자</button>
        <button class="qbtn" onclick="quick('000660','J')">SK하이닉스</button>
        <button class="qbtn" onclick="quick('035420','J')">NAVER</button>
        <button class="qbtn" onclick="quick('005380','J')">현대차</button>
        <button class="qbtn" onclick="quick('247540','Q')">에코프로비엠</button>
        <button class="qbtn" onclick="quick('196170','Q')">알테오젠</button>
      </div>
    </div>
    <div id="searchResult"></div>
  </div>

  <div class="footer">한국투자증권 KIS OpenAPI · 장중 60초 자동갱신</div>
</div>

<script>
// ── 상태 ──────────────────────────────────────────────────────────
let market = 'J', inv = 'foreign', sMkt = 'J';
let selCode = null, rankData = null;
let autoTimer = null;

// ── 탭/마켓/투자자 전환 ───────────────────────────────────────────
function switchTab(name, el) {
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('on'));
  el.classList.add('on');
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('on'));
  document.getElementById('pg-'+name).classList.add('on');
}
function switchMarket(m, el) {
  market = m;
  document.querySelectorAll('#market-stabs .stab').forEach(b=>b.classList.remove('on'));
  el.classList.add('on');
  loadRank();
}
function switchInv(i, el) {
  inv = i;
  document.querySelectorAll('.fbtn').forEach(b=>b.classList.remove('on'));
  el.classList.add('on');
  loadRank();
}
function switchSMkt(m, el) {
  sMkt = m;
  document.querySelectorAll('#search-stabs .stab').forEach(b=>b.classList.remove('on'));
  el.classList.add('on');
}

// ── 유틸 ──────────────────────────────────────────────────────────
const fmtAmt = v => { const n=Math.round(Number(v)/100000000); return (n>=0?'+':'')+n.toLocaleString()+'억'; };
const fmtRate = v => { const n=Number(v); return (n>=0?'+':'')+n.toFixed(2)+'%'; };
const fmtPrice = v => Number(v).toLocaleString()+'원';
const colorOf = v => Number(v)>0?'#E24B4A':Number(v)<0?'#185FA5':'#888';
const rankStyle = r => r===1?'background:#FAC775;color:#633806':r===2?'background:#D3D1C7;color:#444':r===3?'background:#F0997B;color:#4A1B0C':'background:#EEECEA;color:#666';

// ── 순위 로드 ─────────────────────────────────────────────────────
async function loadRank() {
  document.getElementById('rankList').innerHTML='<div class="loading">데이터 불러오는 중...</div>';
  document.getElementById('errBox').style.display='none';
  selCode = null;
  try {
    const ep = inv==='foreign' ? `/api/rank/foreign?market=${market}` : `/api/rank/institution?market=${market}`;
    const res = await fetch(ep);
    const data = await res.json();
    rankData = data;
    renderRank(data);
    const now = new Date();
    document.getElementById('dateLabel').textContent =
      `기준: ${now.getFullYear()}.${String(now.getMonth()+1).padStart(2,'0')}.${String(now.getDate()).padStart(2,'0')} ${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`;
  } catch(e) {
    document.getElementById('rankList').innerHTML='';
    const eb = document.getElementById('errBox');
    eb.style.display='block';
    eb.textContent='⚠️ 데이터 오류: '+e.message+' — 백엔드 API 연결 확인 필요';
  }
  const mk = market==='J'?'코스피':'코스닥';
  const il = inv==='foreign'?'외국인':'기관';
  document.getElementById('rankTitle').textContent = `${il} 순매수 상위 10 · ${mk}`;
}

function renderRank(data) {
  const items = data.items||[];
  if (!items.length) {
    document.getElementById('rankList').innerHTML='<div class="empty">데이터 없음 (장 마감/휴장일)</div>';
    return;
  }
  const maxAmt = Math.max(...items.map(x=>Math.abs(inv==='foreign'?x.foreign_net_amt:x.inst_net_amt)),1);
  document.getElementById('rankList').innerHTML = items.map((item,i) => {
    const netAmt = inv==='foreign'?item.foreign_net_amt:item.inst_net_amt;
    const pct = Math.min(100, Math.round(Math.abs(netAmt)/maxAmt*100));
    const barColor = inv==='foreign'?'#E24B4A':'#178FE0';
    const r = i+1;
    return `<div class="card${selCode===item.code?' sel':''}" id="card-${item.code}" onclick="toggleDetail('${item.code}',${i})">
      <div class="ctop">
        <span class="rnk" style="${rankStyle(r)}">${r}</span>
        <span class="sname">${item.name||item.code}</span>
        <span class="scode">${item.code}</span>
        <span class="namt" style="color:${colorOf(netAmt)}">${fmtAmt(netAmt)}</span>
      </div>
      <div class="brow">
        <div class="bbg"><div class="bfill" style="width:${pct}%;background:${barColor}"></div></div>
        <span class="rchg" style="color:${colorOf(item.change_rate)}">${fmtRate(item.change_rate)}</span>
      </div>
      ${selCode===item.code ? detailHtml(item) : ''}
    </div>`;
  }).join('');
}

function toggleDetail(code, idx) {
  selCode = selCode===code ? null : code;
  if (rankData) renderRank(rankData);
}

function detailHtml(item) {
  return `<div class="dtl">
    <div class="dgrid">
      <div class="dchip"><span>외국인</span><b style="color:${colorOf(item.foreign_net_amt)}">${fmtAmt(item.foreign_net_amt)}</b></div>
      <div class="dchip"><span>기관</span><b style="color:${colorOf(item.inst_net_amt)}">${fmtAmt(item.inst_net_amt)}</b></div>
      <div class="dchip"><span>개인(추정)</span><b style="color:${colorOf(-(item.foreign_net_vol+item.inst_net_vol))}">${fmtAmt(-(item.foreign_net_amt+item.inst_net_amt))}</b></div>
    </div>
    <div class="dprice">
      <span style="color:#888">현재가</span>
      <span style="font-weight:600;color:${colorOf(item.change_rate)}">${fmtPrice(item.price)}</span>
    </div>
  </div>`;
}

// ── 새로고침 ──────────────────────────────────────────────────────
function doRefresh() {
  const btn = document.getElementById('refreshBtn');
  btn.textContent = '⟳ 갱신 중...';
  btn.disabled = true;
  loadRank().finally(() => { btn.textContent='↺ 새로고침'; btn.disabled=false; });
}

// ── 종목 검색 ─────────────────────────────────────────────────────
async function doSearch() {
  const code = document.getElementById('searchInput').value.trim();
  if (!code) return;
  const res = document.getElementById('searchResult');
  res.innerHTML='<div class="loading">조회 중...</div>';
  try {
    const data = await (await fetch(`/api/stock-search?code=${code}&market=${sMkt}`)).json();
    if (!data.name && !data.price) throw new Error('종목을 찾을 수 없습니다');
    res.innerHTML = `<div class="rcard">
      <div class="rchdr">
        <div><div class="rname">${data.name||code}</div><div class="rcode">${code}</div></div>
        <div style="text-align:right">
          <div class="rprice" style="color:${colorOf(data.change_rate)}">${fmtPrice(data.price)}</div>
          <div class="rrate" style="color:${colorOf(data.change_rate)}">${fmtRate(data.change_rate)}</div>
        </div>
      </div>
      <div class="divdr"></div>
      <div class="igrid">
        ${['외국인','기관','개인'].map((lbl,i)=>{
          const amt = [data.foreign_net_amt,data.inst_net_amt,data.retail_net_amt][i]||0;
          const vol = [data.foreign_net_vol,data.inst_net_vol,data.retail_net_vol][i]||0;
          return `<div class="ibox"><div class="ilbl">${lbl}</div>
            <div class="iamt" style="color:${colorOf(amt)}">${fmtAmt(amt)}</div>
            <div class="ivol">${Number(vol).toLocaleString()}주</div></div>`;
        }).join('')}
      </div>
      <div class="divdr"></div>
      <div style="display:flex;gap:16px;font-size:13px">
        <div><div style="font-size:11px;color:#888;margin-bottom:2px">거래량</div><b>${Number(data.volume||0).toLocaleString()}</b></div>
      </div>
    </div>`;
  } catch(e) {
    res.innerHTML=`<div class="errmsg">⚠️ ${e.message}</div>`;
  }
}

function quick(code, mkt) {
  sMkt = mkt;
  document.querySelectorAll('#search-stabs .stab').forEach((b,i)=>b.classList.toggle('on',['J','Q'][i]===mkt));
  document.getElementById('searchInput').value = code;
  doSearch();
}

// ── 자동 갱신 (60초) ─────────────────────────────────────────────
loadRank();
autoTimer = setInterval(loadRank, 60000);
</script>
</body>
</html>"""
