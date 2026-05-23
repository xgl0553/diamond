#!/usr/bin/env python3
"""Fetch Tiantian Fund top-return funds and visualize latest stock holdings.

The script uses Python standard-library networking/parsing and Matplotlib for PNG chart output.
Data sources are public Eastmoney/Tiantian Fund pages:
- fund.eastmoney.com/data/rankhandler.aspx for fund performance ranking.
- fundf10.eastmoney.com/FundArchivesDatas.aspx for disclosed stock holdings.

Fund holdings come from periodic reports and are not real-time positions.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as dt
import html
import json
import logging
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

RANK_URL = "https://fund.eastmoney.com/data/rankhandler.aspx"
ARCHIVE_URL = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://fund.eastmoney.com/data/fundranking.html",
}

RANK_COLUMNS = [
    "fund_code",
    "fund_name",
    "fund_name_spell",
    "nav_date",
    "unit_nav",
    "accumulated_nav",
    "daily_return",
    "weekly_return",
    "monthly_return",
    "three_month_return",
    "six_month_return",
    "one_year_return",
    "two_year_return",
    "three_year_return",
    "ytd_return",
    "since_inception_return",
    "service_fee",
]

HOLDING_COLUMNS = [
    "fund_code",
    "fund_name",
    "fund_rank",
    "fund_ytd_return",
    "report_period",
    "previous_report_period",
    "stock_code",
    "stock_name",
    "weight_pct",
    "shares_10k",
    "market_value_10k",
    "previous_weight_pct",
    "previous_shares_10k",
    "weight_change_pp",
    "shares_change_10k",
    "change_status",
]

SVG_COLORS = ["#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2", "#B279A2"]

CHART_FORMATS = ("png", "svg", "both")


@dataclass(frozen=True)
class HoldingPeriod:
    period: str
    rows: list[dict[str, object]]


class TableParser(HTMLParser):
    """Minimal HTML table parser for Eastmoney's holdings fragments."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._current_table: list[list[str]] = []
        self._current_row: list[str] = []
        self._current_cell: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._in_table = True
            self._current_table = []
        elif self._in_table and tag == "tr":
            self._in_row = True
            self._current_row = []
        elif self._in_row and tag in {"td", "th"}:
            self._in_cell = True
            self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            text = re.sub(r"\s+", " ", "".join(self._current_cell)).strip()
            self._current_row.append(text)
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            if any(cell for cell in self._current_row):
                self._current_table.append(self._current_row)
            self._in_row = False
        elif tag == "table" and self._in_table:
            if self._current_table:
                self.tables.append(self._current_table)
            self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current_cell.append(data)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从天天基金拉取年度收益 Top 基金，展示最新持仓股票及其变化。"
    )
    parser.add_argument("--year", type=int, default=2026, help="收益统计年份，默认 2026。")
    parser.add_argument("--top", type=int, default=200, help="收益排名前 N 只基金，默认 200。")
    parser.add_argument(
        "--fund-type",
        default="all",
        help="天天基金排行基金类型代码，默认 all；常见值：gp 股票型、hh 混合型、zs 指数型、qdii。",
    )
    parser.add_argument(
        "--holdings-topline", type=int, default=10, help="每只基金抓取前 N 大股票持仓，默认 10。"
    )
    parser.add_argument("--max-workers", type=int, default=8, help="并发抓取线程数，默认 8。")
    parser.add_argument("--out", type=Path, default=Path("outputs"), help="输出目录。")
    parser.add_argument(
        "--chart-format",
        choices=CHART_FORMATS,
        default="png",
        help="图表格式：png、svg 或 both，默认 png。",
    )
    parser.add_argument("--timeout", type=int, default=20, help="HTTP 超时秒数。")
    parser.add_argument("--retries", type=int, default=3, help="HTTP 重试次数。")
    return parser.parse_args()


def to_float(value: object) -> float | None:
    text = str(value).replace(",", "").replace("%", "").strip()
    if not text or text in {"---", "--", "nan", "None"}:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return float(match.group(0))


def request_text(url: str, params: dict[str, object], headers: dict[str, str], timeout: int, retries: int) -> str:
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(full_url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = response.read()
                encoding = response.headers.get_content_charset() or "utf-8"
                return data.decode(encoding, errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            sleep_seconds = min(2**attempt, 8) + 0.1 * attempt
            logging.warning("请求失败 %s/%s: %s；%.1fs 后重试", attempt, retries, exc, sleep_seconds)
            time.sleep(sleep_seconds)
    raise RuntimeError(f"请求 {full_url} 多次失败") from last_error


def parse_rank_data(script_text: str) -> list[list[str]]:
    match = re.search(r"datas\s*:\s*(\[.*?\])\s*,\s*allRecords", script_text, re.S)
    if not match:
        raise ValueError("未能在天天基金排行响应中找到 datas 字段，页面结构可能已变化。")
    raw_rows = json.loads(match.group(1))
    return [str(row).split(",") for row in raw_rows]


def fetch_top_funds(args: argparse.Namespace) -> list[dict[str, object]]:
    start_date = f"{args.year}-01-01"
    today = dt.date.today()
    end_date = min(today, dt.date(args.year, 12, 31)).isoformat()
    params = {
        "op": "ph",
        "dt": "kf",
        "ft": args.fund_type,
        "rs": "",
        "gs": "0",
        "sc": "jn",
        "st": "desc",
        "sd": start_date,
        "ed": end_date,
        "qdii": "",
        "tabSubtype": ",,,,,",
        "pi": "1",
        "pn": str(args.top),
        "dx": "1",
        "v": f"{time.time():.6f}",
    }
    text = request_text(RANK_URL, params, HEADERS, args.timeout, args.retries)
    funds: list[dict[str, object]] = []
    for rank, row in enumerate(parse_rank_data(text), start=1):
        padded = row + [""] * max(0, len(RANK_COLUMNS) - len(row))
        item: dict[str, object] = dict(zip(RANK_COLUMNS, padded[: len(RANK_COLUMNS)]))
        for key in [name for name in RANK_COLUMNS if name.endswith("return") or name.endswith("nav")]:
            item[key] = to_float(item.get(key))
        item["rank"] = rank
        item["rank_start_date"] = start_date
        item["rank_end_date"] = end_date
        funds.append(item)
    return funds


def extract_js_string(script_text: str, key: str) -> str:
    marker = f'{key}:"'
    start = script_text.find(marker)
    if start < 0:
        raise ValueError(f"未找到 {key} 字段。")
    index = start + len(marker)
    chars: list[str] = []
    escaped = False
    while index < len(script_text):
        char = script_text[index]
        if escaped:
            chars.append("\\" + char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            break
        else:
            chars.append(char)
        index += 1
    return html.unescape(json.loads('"' + "".join(chars) + '"'))


def strip_tags(fragment: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", fragment, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def find_periods_for_tables(content_html: str, table_count: int) -> list[str]:
    starts = [match.start() for match in re.finditer(r"<table\b", content_html, flags=re.I)]
    period_re = re.compile(r"(\d{4}年\d季度|\d{4}年中报|\d{4}年年报|\d{4}-\d{2}-\d{2})")
    periods: list[str] = []
    for start in starts[:table_count]:
        prefix = strip_tags(content_html[max(0, start - 3000) : start])
        matches = period_re.findall(prefix)
        periods.append(matches[-1] if matches else "未知报告期")
    return periods


def find_column(headers: Iterable[str], patterns: list[str]) -> int | None:
    clean_headers = [re.sub(r"\s+", "", header) for header in headers]
    for pattern in patterns:
        for index, header in enumerate(clean_headers):
            if re.search(pattern, header):
                return index
    return None


def normalize_holding_table(table: list[list[str]]) -> list[dict[str, object]]:
    if len(table) < 2:
        return []
    headers = table[0]
    code_idx = find_column(headers, [r"股票代码", r"代码"])
    name_idx = find_column(headers, [r"股票名称", r"名称"])
    weight_idx = find_column(headers, [r"占净值", r"净值比例", r"持仓占比"])
    shares_idx = find_column(headers, [r"持股数", r"持股数量"])
    value_idx = find_column(headers, [r"持仓市值", r"市值"])
    if code_idx is None or name_idx is None:
        return []

    rows: list[dict[str, object]] = []
    for raw_row in table[1:]:
        row = raw_row + [""] * max(0, len(headers) - len(raw_row))
        code_match = re.search(r"\d{6}", row[code_idx])
        if not code_match:
            continue
        stock_name = row[name_idx].strip()
        if not stock_name or re.search(r"合计|暂无|没有", stock_name):
            continue
        rows.append(
            {
                "stock_code": code_match.group(0),
                "stock_name": stock_name,
                "weight_pct": to_float(row[weight_idx]) if weight_idx is not None else None,
                "shares_10k": to_float(row[shares_idx]) if shares_idx is not None else None,
                "market_value_10k": to_float(row[value_idx]) if value_idx is not None else None,
            }
        )
    return rows


def parse_holding_periods(content_html: str) -> list[HoldingPeriod]:
    parser = TableParser()
    parser.feed(content_html)
    periods = find_periods_for_tables(content_html, len(parser.tables))
    parsed: list[HoldingPeriod] = []
    for index, table in enumerate(parser.tables):
        rows = normalize_holding_table(table)
        if rows:
            period = periods[index] if index < len(periods) else "未知报告期"
            parsed.append(HoldingPeriod(period=period, rows=rows))
    return parsed


def fetch_holding_periods(args: argparse.Namespace, fund_code: str) -> list[HoldingPeriod]:
    all_periods: list[HoldingPeriod] = []
    headers = {**HEADERS, "Referer": f"https://fundf10.eastmoney.com/ccmx_{fund_code}.html"}
    for holding_year in [args.year, args.year - 1]:
        params = {
            "type": "jjcc",
            "code": fund_code,
            "topline": str(args.holdings_topline),
            "year": str(holding_year),
            "month": "",
            "rt": f"{time.time():.6f}",
        }
        text = request_text(ARCHIVE_URL, params, headers, args.timeout, args.retries)
        content = extract_js_string(text, "content")
        all_periods.extend(parse_holding_periods(content))
        if len(all_periods) >= 2:
            break
    unique: list[HoldingPeriod] = []
    seen: set[str] = set()
    for period in all_periods:
        key = period.period + json.dumps(period.rows, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            unique.append(period)
            seen.add(key)
    return unique


def build_latest_change_rows(fund: dict[str, object], periods: list[HoldingPeriod]) -> list[dict[str, object]]:
    latest = periods[0]
    previous_by_code = {row["stock_code"]: row for row in periods[1].rows} if len(periods) > 1 else {}
    rows: list[dict[str, object]] = []
    for current in latest.rows:
        previous = previous_by_code.get(current["stock_code"])
        weight_change = None
        shares_change = None
        status = "无上期对比"
        if previous:
            if current.get("weight_pct") is not None and previous.get("weight_pct") is not None:
                weight_change = round(float(current["weight_pct"]) - float(previous["weight_pct"]), 6)
            if current.get("shares_10k") is not None and previous.get("shares_10k") is not None:
                shares_change = round(float(current["shares_10k"]) - float(previous["shares_10k"]), 6)
            if shares_change is None or math.isclose(shares_change, 0.0, abs_tol=1e-9):
                status = "持平/小幅变动"
            elif shares_change > 0:
                status = "增持"
            else:
                status = "减持"
        elif len(periods) > 1:
            status = "新进"
        rows.append(
            {
                "fund_code": fund["fund_code"],
                "fund_name": fund["fund_name"],
                "fund_rank": fund["rank"],
                "fund_ytd_return": fund.get("ytd_return"),
                "report_period": latest.period,
                "previous_report_period": periods[1].period if len(periods) > 1 else None,
                "stock_code": current["stock_code"],
                "stock_name": current["stock_name"],
                "weight_pct": current.get("weight_pct"),
                "shares_10k": current.get("shares_10k"),
                "market_value_10k": current.get("market_value_10k"),
                "previous_weight_pct": previous.get("weight_pct") if previous else None,
                "previous_shares_10k": previous.get("shares_10k") if previous else None,
                "weight_change_pp": weight_change,
                "shares_change_10k": shares_change,
                "change_status": status,
            }
        )
    return rows


def fetch_one_fund_holdings(args: argparse.Namespace, fund: dict[str, object]) -> list[dict[str, object]]:
    periods = fetch_holding_periods(args, str(fund["fund_code"]))
    return build_latest_change_rows(fund, periods) if periods else []


def fetch_all_holdings(args: argparse.Namespace, funds: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {executor.submit(fetch_one_fund_holdings, args, fund): fund for fund in funds}
        for future in concurrent.futures.as_completed(futures):
            completed += 1
            fund = futures[future]
            try:
                rows.extend(future.result())
            except Exception as exc:
                logging.warning("基金 %s %s 持仓抓取失败: %s", fund["fund_code"], fund["fund_name"], exc)
            if completed % 10 == 0 or completed == len(futures):
                logging.info("持仓抓取进度: %s/%s", completed, len(futures))
    return rows


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def escape_svg(text: object) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def configure_matplotlib() -> object:
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = [
        "Noto Sans CJK SC",
        "SimHei",
        "Microsoft YaHei",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False
    return plt


def save_png_barh(rows: list[dict[str, object]], label_key: str, value_key: str, title: str, xlabel: str, path: Path) -> None:
    rows = [row for row in rows if to_float(row.get(value_key)) is not None]
    if not rows:
        logging.warning("跳过空 PNG 图表: %s", title)
        return
    rows = list(reversed(rows))
    plt = configure_matplotlib()
    height = max(6, min(18, 0.34 * len(rows) + 2))
    _, ax = plt.subplots(figsize=(12, height))
    labels = [str(row[label_key]) for row in rows]
    values = [float(to_float(row[value_key]) or 0) for row in rows]
    ax.barh(labels, values, color=SVG_COLORS[0])
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.grid(axis="x", linestyle="--", alpha=0.25)
    for index, value in enumerate(values):
        ax.text(value, index, f" {value:.2f}", va="center", fontsize=9)
    plt.tight_layout()
    plt.savefig(path, dpi=180)
    plt.close()


def save_png_stacked_change(rows: list[dict[str, object]], path: Path) -> None:
    if not rows:
        return
    rows = list(reversed(rows))
    plt = configure_matplotlib()
    height = max(6, min(18, 0.36 * len(rows) + 2))
    _, ax = plt.subplots(figsize=(12, height))
    labels = [str(row["label"]) for row in rows]
    left = [0] * len(rows)
    series = [
        ("increased_fund_count", "增持", SVG_COLORS[2]),
        ("decreased_fund_count", "减持", SVG_COLORS[3]),
        ("new_fund_count", "新进", SVG_COLORS[1]),
    ]
    for key, name, color in series:
        values = [int(row.get(key, 0) or 0) for row in rows]
        ax.barh(labels, values, left=left, label=name, color=color)
        left = [current + value for current, value in zip(left, values)]
    ax.set_title("持仓变化基金数最多的股票 Top 30")
    ax.set_xlabel("基金数量")
    ax.grid(axis="x", linestyle="--", alpha=0.25)
    ax.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=180)
    plt.close()


def save_png_heatmap(holdings: list[dict[str, object]], top_funds: list[dict[str, object]], top_stocks: list[dict[str, object]], path: Path) -> None:
    fund_codes = [str(fund["fund_code"]) for fund in top_funds[:40]]
    stock_codes = [str(stock["stock_code"]) for stock in top_stocks[:20]]
    if not fund_codes or not stock_codes:
        return
    plt = configure_matplotlib()
    weights = {(str(row["fund_code"]), str(row["stock_code"])): to_float(row.get("weight_pct")) or 0 for row in holdings}
    fund_names = {str(fund["fund_code"]): str(fund["fund_name"])[:10] for fund in top_funds}
    stock_names = {str(stock["stock_code"]): str(stock["stock_name"]) for stock in top_stocks}
    matrix = [[weights.get((fund_code, stock_code), 0) for stock_code in stock_codes] for fund_code in fund_codes]
    fig_height = max(8, 0.24 * len(fund_codes) + 3)
    _, ax = plt.subplots(figsize=(16, fig_height))
    image = ax.imshow(matrix, cmap="YlOrRd", aspect="auto")
    ax.set_title("基金-股票最新持仓权重热力图（%）")
    ax.set_yticks(range(len(fund_codes)), [f"{code} {fund_names.get(code, '')}" for code in fund_codes], fontsize=8)
    ax.set_xticks(range(len(stock_codes)), [f"{code} {stock_names.get(code, '')}" for code in stock_codes], rotation=55, ha="right", fontsize=8)
    ax.set_xlabel("股票")
    ax.set_ylabel("基金")
    plt.colorbar(image, ax=ax, fraction=0.025, pad=0.02)
    plt.tight_layout()
    plt.savefig(path, dpi=180)
    plt.close()


def svg_barh(rows: list[dict[str, object]], label_key: str, value_key: str, title: str, xlabel: str, path: Path) -> None:
    rows = [row for row in rows if to_float(row.get(value_key)) is not None]
    if not rows:
        logging.warning("跳过空图表: %s", title)
        return
    rows = list(reversed(rows))
    width = 1200
    left = 310
    right = 80
    top = 70
    row_h = 28
    height = top + row_h * len(rows) + 70
    max_value = max(float(to_float(row[value_key]) or 0) for row in rows) or 1
    plot_w = width - left - right
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">']
    parts.append('<rect width="100%" height="100%" fill="white"/>')
    parts.append(f'<text x="{width/2}" y="32" text-anchor="middle" font-size="22" font-family="Arial">{escape_svg(title)}</text>')
    for index, row in enumerate(rows):
        y = top + index * row_h
        value = float(to_float(row[value_key]) or 0)
        bar_w = max(1, plot_w * value / max_value)
        parts.append(f'<text x="{left-10}" y="{y+18}" text-anchor="end" font-size="13" font-family="Arial">{escape_svg(row[label_key])}</text>')
        parts.append(f'<rect x="{left}" y="{y+5}" width="{bar_w:.1f}" height="18" fill="{SVG_COLORS[0]}"/>')
        parts.append(f'<text x="{left+bar_w+6}" y="{y+19}" font-size="12" font-family="Arial">{value:.2f}</text>')
    parts.append(f'<text x="{left + plot_w/2}" y="{height-22}" text-anchor="middle" font-size="14" font-family="Arial">{escape_svg(xlabel)}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def svg_stacked_change(rows: list[dict[str, object]], path: Path) -> None:
    rows = list(reversed(rows))
    if not rows:
        return
    width = 1200
    left = 310
    right = 120
    top = 80
    row_h = 30
    height = top + row_h * len(rows) + 80
    keys = [("increased_fund_count", "增持", SVG_COLORS[2]), ("decreased_fund_count", "减持", SVG_COLORS[3]), ("new_fund_count", "新进", SVG_COLORS[1])]
    max_total = max(sum(int(row.get(key, 0) or 0) for key, _, _ in keys) for row in rows) or 1
    plot_w = width - left - right
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">']
    parts.append('<rect width="100%" height="100%" fill="white"/>')
    parts.append(f'<text x="{width/2}" y="32" text-anchor="middle" font-size="22" font-family="Arial">持仓变化基金数最多的股票 Top 30</text>')
    legend_x = left
    for key, name, color in keys:
        parts.append(f'<rect x="{legend_x}" y="48" width="14" height="14" fill="{color}"/>')
        parts.append(f'<text x="{legend_x+20}" y="60" font-size="13" font-family="Arial">{name}</text>')
        legend_x += 70
    for index, row in enumerate(rows):
        y = top + index * row_h
        x = left
        total = 0
        parts.append(f'<text x="{left-10}" y="{y+19}" text-anchor="end" font-size="13" font-family="Arial">{escape_svg(row["label"])}</text>')
        for key, _, color in keys:
            value = int(row.get(key, 0) or 0)
            bar_w = plot_w * value / max_total
            if value:
                parts.append(f'<rect x="{x:.1f}" y="{y+5}" width="{bar_w:.1f}" height="18" fill="{color}"/>')
            x += bar_w
            total += value
        parts.append(f'<text x="{x+6:.1f}" y="{y+19}" font-size="12" font-family="Arial">{total}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def svg_heatmap(holdings: list[dict[str, object]], top_funds: list[dict[str, object]], top_stocks: list[dict[str, object]], path: Path) -> None:
    fund_codes = [str(fund["fund_code"]) for fund in top_funds[:40]]
    stock_codes = [str(stock["stock_code"]) for stock in top_stocks[:20]]
    if not fund_codes or not stock_codes:
        return
    weights = {(str(row["fund_code"]), str(row["stock_code"])): to_float(row.get("weight_pct")) or 0 for row in holdings}
    fund_names = {str(fund["fund_code"]): str(fund["fund_name"])[:10] for fund in top_funds}
    stock_names = {str(stock["stock_code"]): str(stock["stock_name"]) for stock in top_stocks}
    cell = 24
    left = 230
    top = 190
    width = left + cell * len(stock_codes) + 40
    height = top + cell * len(fund_codes) + 50
    max_weight = max(weights.values()) if weights else 1
    max_weight = max_weight or 1
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">']
    parts.append('<rect width="100%" height="100%" fill="white"/>')
    parts.append(f'<text x="{width/2}" y="30" text-anchor="middle" font-size="20" font-family="Arial">基金-股票最新持仓权重热力图（%）</text>')
    for col, code in enumerate(stock_codes):
        x = left + col * cell + 16
        parts.append(f'<text x="{x}" y="{top-8}" transform="rotate(-55 {x} {top-8})" text-anchor="start" font-size="11" font-family="Arial">{escape_svg(code + " " + stock_names.get(code, ""))}</text>')
    for row_idx, fund_code in enumerate(fund_codes):
        y = top + row_idx * cell
        parts.append(f'<text x="{left-8}" y="{y+16}" text-anchor="end" font-size="11" font-family="Arial">{escape_svg(fund_code + " " + fund_names.get(fund_code, ""))}</text>')
        for col, stock_code in enumerate(stock_codes):
            value = weights.get((fund_code, stock_code), 0)
            intensity = int(255 - 190 * value / max_weight)
            color = f"rgb(255,{intensity},{intensity})"
            x = left + col * cell
            parts.append(f'<rect x="{x}" y="{y}" width="{cell-1}" height="{cell-1}" fill="{color}"/>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def summarize_stocks(holdings: list[dict[str, object]]) -> list[dict[str, object]]:
    summary: dict[tuple[str, str], dict[str, object]] = {}
    funds_by_stock: dict[tuple[str, str], set[str]] = {}
    for row in holdings:
        key = (str(row["stock_code"]), str(row["stock_name"]))
        item = summary.setdefault(
            key,
            {
                "stock_code": key[0],
                "stock_name": key[1],
                "holding_fund_count": 0,
                "total_weight_pct": 0.0,
                "avg_weight_pct": 0.0,
                "increased_fund_count": 0,
                "decreased_fund_count": 0,
                "new_fund_count": 0,
                "total_weight_change_pp": 0.0,
                "_weight_observations": 0,
            },
        )
        funds_by_stock.setdefault(key, set()).add(str(row["fund_code"]))
        weight = to_float(row.get("weight_pct"))
        if weight is not None:
            item["total_weight_pct"] = float(item["total_weight_pct"]) + weight
            item["_weight_observations"] = int(item["_weight_observations"]) + 1
        change = to_float(row.get("weight_change_pp"))
        if change is not None:
            item["total_weight_change_pp"] = float(item["total_weight_change_pp"]) + change
        if row.get("change_status") == "增持":
            item["increased_fund_count"] = int(item["increased_fund_count"]) + 1
        elif row.get("change_status") == "减持":
            item["decreased_fund_count"] = int(item["decreased_fund_count"]) + 1
        elif row.get("change_status") == "新进":
            item["new_fund_count"] = int(item["new_fund_count"]) + 1
    rows = []
    for key, item in summary.items():
        observations = int(item.pop("_weight_observations"))
        item["holding_fund_count"] = len(funds_by_stock[key])
        item["avg_weight_pct"] = round(float(item["total_weight_pct"]) / observations, 6) if observations else None
        item["total_weight_pct"] = round(float(item["total_weight_pct"]), 6)
        item["total_weight_change_pp"] = round(float(item["total_weight_change_pp"]), 6)
        item["label"] = f"{item['stock_code']} {item['stock_name']}"
        rows.append(item)
    return sorted(rows, key=lambda row: (int(row["holding_fund_count"]), float(row["total_weight_pct"])), reverse=True)


def visualize(args: argparse.Namespace, funds: list[dict[str, object]], holdings: list[dict[str, object]]) -> list[dict[str, object]]:
    ranked_funds = sorted(funds, key=lambda row: to_float(row.get("ytd_return")) or -999999, reverse=True)
    top30_funds = ranked_funds[:30]
    for row in top30_funds:
        row["label"] = f"{row['fund_code']} {str(row['fund_name'])[:18]}"

    if args.chart_format in {"png", "both"}:
        save_png_barh(top30_funds, "label", "ytd_return", f"{args.year} 年以来收益 Top 30 基金", "今年来收益率（%）", args.out / "fund_ytd_top30.png")
    if args.chart_format in {"svg", "both"}:
        svg_barh(top30_funds, "label", "ytd_return", f"{args.year} 年以来收益 Top 30 基金", "今年来收益率（%）", args.out / "fund_ytd_top30.svg")

    if not holdings:
        return []
    summary = summarize_stocks(holdings)
    by_weight = sorted(summary, key=lambda row: float(row.get("total_weight_pct") or 0), reverse=True)[:30]
    by_change = sorted(
        summary,
        key=lambda row: int(row.get("increased_fund_count", 0) or 0) + int(row.get("decreased_fund_count", 0) or 0) + int(row.get("new_fund_count", 0) or 0),
        reverse=True,
    )[:30]
    ranked_funds_by_rank = sorted(funds, key=lambda row: int(row["rank"]))

    if args.chart_format in {"png", "both"}:
        save_png_barh(summary[:30], "label", "holding_fund_count", "收益 Top 基金中持有次数最多的股票 Top 30", "持有该股票的基金数量", args.out / "stock_by_fund_count_top30.png")
        save_png_barh(by_weight, "label", "total_weight_pct", "收益 Top 基金重仓股票权重汇总 Top 30", "持仓权重合计（百分点，未按基金规模加权）", args.out / "stock_by_weight_top30.png")
        save_png_stacked_change(by_change, args.out / "stock_change_status_top30.png")
        save_png_heatmap(holdings, ranked_funds_by_rank, summary, args.out / "fund_stock_weight_heatmap.png")

    if args.chart_format in {"svg", "both"}:
        svg_barh(summary[:30], "label", "holding_fund_count", "收益 Top 基金中持有次数最多的股票 Top 30", "持有该股票的基金数量", args.out / "stock_by_fund_count_top30.svg")
        svg_barh(by_weight, "label", "total_weight_pct", "收益 Top 基金重仓股票权重汇总 Top 30", "持仓权重合计（百分点，未按基金规模加权）", args.out / "stock_by_weight_top30.svg")
        svg_stacked_change(by_change, args.out / "stock_change_status_top30.svg")
        svg_heatmap(holdings, ranked_funds_by_rank, summary, args.out / "fund_stock_weight_heatmap.svg")
    return summary


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args.out.mkdir(parents=True, exist_ok=True)

    funds = fetch_top_funds(args)
    funds_path = args.out / f"top_funds_{args.year}.csv"
    write_csv(funds_path, funds, ["rank", *RANK_COLUMNS, "rank_start_date", "rank_end_date"])
    logging.info("已保存基金排行: %s", funds_path)

    holdings = fetch_all_holdings(args, funds)
    holdings_path = args.out / f"fund_latest_holdings_{args.year}.csv"
    write_csv(holdings_path, holdings, HOLDING_COLUMNS)
    logging.info("已保存基金持仓: %s", holdings_path)

    summary = visualize(args, funds, holdings)
    if summary:
        summary_path = args.out / f"stock_summary_{args.year}.csv"
        write_csv(
            summary_path,
            summary,
            [
                "stock_code",
                "stock_name",
                "holding_fund_count",
                "total_weight_pct",
                "avg_weight_pct",
                "increased_fund_count",
                "decreased_fund_count",
                "new_fund_count",
                "total_weight_change_pp",
            ],
        )
        logging.info("已保存股票汇总: %s", summary_path)


if __name__ == "__main__":
    main()
