import datetime as dt
import json
import re
import time
import urllib.parse
import urllib.request
from html import unescape

from sqlalchemy.orm import Session

from app.models import CrawlBatch, FundHoldingItem, FundRankItem

RANK_URL = "https://fund.eastmoney.com/data/rankhandler.aspx"
HOLDING_URL = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://fund.eastmoney.com/data/fundranking.html"}


def _get(url: str, params: dict[str, str]) -> str:
    req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse_rank_rows(text: str) -> list[list[str]]:
    m = re.search(r"datas\s*:\s*(\[.*?\])\s*,\s*allRecords", text, re.S)
    return [str(row).split(",") for row in json.loads(m.group(1))] if m else []


def _extract_content(js_text: str) -> str:
    m = re.search(r'content:"(.*)",arryear', js_text, re.S)
    return unescape(m.group(1).encode('utf-8').decode('unicode_escape')) if m else ""


def _parse_top10_holdings(content: str) -> list[dict]:
    rows = re.findall(r"<tr>(.*?)</tr>", content, re.S)
    result = []
    for tr in rows:
        tds = re.findall(r"<td.*?>(.*?)</td>", tr, re.S)
        if len(tds) < 6:
            continue
        code = re.sub(r"<.*?>", "", tds[1]).strip()
        name = re.sub(r"<.*?>", "", tds[2]).strip()
        if not re.fullmatch(r"\d{6}", code):
            continue
        weight = re.sub(r"[%,\s]", "", re.sub(r"<.*?>", "", tds[3]))
        shares = re.sub(r"[,\s]", "", re.sub(r"<.*?>", "", tds[4]))
        mv = re.sub(r"[,\s]", "", re.sub(r"<.*?>", "", tds[5]))
        result.append({"stock_code": code, "stock_name": name, "shares_10k": float(shares or 0), "market_value_10k": float(mv or 0)})
        if len(result) == 10:
            break
    return result


def run_crawl(db: Session, batch: CrawlBatch, top_n: int = 100) -> None:
    start_date = dt.date(dt.date.today().year, 1, 1).isoformat()
    end_date = dt.date.today().isoformat()
    rank_text = _get(RANK_URL, {"op": "ph", "dt": "kf", "ft": "all", "rs": "", "gs": "0", "sc": "jn", "st": batch.direction, "sd": start_date, "ed": end_date, "qdii": "", "tabSubtype": ",,,,,", "pi": "1", "pn": str(top_n), "dx": "1", "v": f"{time.time():.6f}"})
    rows = _parse_rank_rows(rank_text)
    for idx, row in enumerate(rows, start=1):
        p = row + [""] * 16
        db.add(FundRankItem(batch_id=batch.id, rank_no=idx, fund_code=p[0], fund_name=p[1], fund_name_spell=p[2], nav_date=None, unit_nav=float(p[4]) if p[4] and p[4] != "---" else None, ytd_return=float(p[14]) if len(p) > 14 and p[14] and p[14] != "---" else None))
        hold_js = _get(HOLDING_URL, {"type": "jjcc", "code": p[0], "topline": "10", "year": str(dt.date.today().year), "month": "", "rt": f"{time.time():.6f}"})
        holdings = _parse_top10_holdings(_extract_content(hold_js))
        for i, h in enumerate(holdings, start=1):
            db.add(FundHoldingItem(batch_id=batch.id, fund_code=p[0], fund_name=p[1], holding_rank_no=i, stock_code=h["stock_code"], stock_name=h["stock_name"], shares_10k=h["shares_10k"], market_value_10k=h["market_value_10k"], previous_shares_10k=0, previous_market_value_10k=0, change_status="无上期对比"))
    batch.status = "success"
    batch.message = "采集完成"
    db.commit()
