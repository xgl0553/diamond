# 天天基金 2026 收益 Top200 持仓分析

这个项目提供一个 Python 脚本，用于从天天基金 / 东方财富公开页面拉取指定年度收益排名靠前的基金，并抓取基金最新股票持仓，计算相对上一报告期的持仓变化，最后输出 CSV 数据和 PNG 图表。

> 说明：基金持仓来自基金定期报告披露，通常滞后于实时调仓；图表仅用于数据分析展示，不构成投资建议。

## 安装依赖

建议使用 Python 3.10+。脚本使用标准库完成网络请求和解析，使用 Matplotlib 生成 PNG 图表。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 快速运行

```bash
python tiantian_fund_holdings.py --year 2026 --top 200 --out outputs
```

常用参数：

- `--year`：收益统计年份，默认 `2026`。
- `--top`：拉取收益排名前 N 只基金，默认 `200`。
- `--fund-type`：天天基金基金类型筛选，默认 `all`，也可使用 `gp`、`hh`、`zs`、`qdii` 等天天基金排行页支持的类型。
- `--holdings-topline`：每只基金抓取前多少大持仓，默认 `10`。
- `--max-workers`：并发抓取持仓线程数，默认 `8`。
- `--out`：输出目录，默认 `outputs`。
- `--chart-format`：图表格式，默认 `png`，也可选 `svg` 或 `both`。

## 输出文件

脚本会在输出目录生成：

- `top_funds_YYYY.csv`：年度收益 Top 基金列表。
- `fund_latest_holdings_YYYY.csv`：每只基金最新持仓及相对上一报告期变化。
- `stock_summary_YYYY.csv`：按股票聚合后的持仓基金数、权重、增减仓统计。
- `fund_ytd_top30.png`：收益排名前 30 基金柱状图。
- `stock_by_fund_count_top30.png`：Top 基金中被持有次数最多的股票。
- `stock_by_weight_top30.png`：Top 基金重仓股票权重汇总。
- `stock_change_status_top30.png`：增持 / 减持 / 新进基金数最多的股票。
- `fund_stock_weight_heatmap.png`：基金-股票持仓权重热力图。
