import unittest

import tiantian_fund_holdings as app


class TiantianFundHoldingsTests(unittest.TestCase):
    def test_parse_rank_data(self):
        text = 'var rankData = {datas:["000001,示例基金,spell,2026-05-15,1.0,1.2,0.1,1,2,3,4,5,6,7,8,9,0.15"],allRecords:1};'
        rows = app.parse_rank_data(text)
        self.assertEqual(rows[0][0], "000001")
        self.assertEqual(rows[0][1], "示例基金")
        self.assertEqual(rows[0][14], "8")

    def test_parse_holding_periods(self):
        content = """
        <div><h4>2026年1季度股票投资明细</h4>
        <table><tr><th>序号</th><th>股票代码</th><th>股票名称</th><th>占净值比例</th><th>持股数（万股）</th><th>持仓市值（万元）</th></tr>
        <tr><td>1</td><td>600519</td><td>贵州茅台</td><td>8.50%</td><td>12.3</td><td>12345.6</td></tr></table>
        <h4>2025年4季度股票投资明细</h4>
        <table><tr><th>序号</th><th>股票代码</th><th>股票名称</th><th>占净值比例</th><th>持股数（万股）</th><th>持仓市值（万元）</th></tr>
        <tr><td>1</td><td>600519</td><td>贵州茅台</td><td>7.50%</td><td>10.0</td><td>10000.0</td></tr></table></div>
        """
        periods = app.parse_holding_periods(content)
        self.assertEqual(len(periods), 2)
        self.assertEqual(periods[0].period, "2026年1季度")
        self.assertEqual(periods[0].rows[0]["stock_code"], "600519")
        self.assertEqual(periods[0].rows[0]["weight_pct"], 8.5)

    def test_build_latest_change_rows(self):
        fund = {"fund_code": "000001", "fund_name": "示例基金", "rank": 1, "ytd_return": 8.0}
        periods = [
            app.HoldingPeriod("2026年1季度", [{"stock_code": "600519", "stock_name": "贵州茅台", "weight_pct": 8.5, "shares_10k": 12.3, "market_value_10k": 12345.6}]),
            app.HoldingPeriod("2025年4季度", [{"stock_code": "600519", "stock_name": "贵州茅台", "weight_pct": 7.5, "shares_10k": 10.0, "market_value_10k": 10000.0}]),
        ]
        rows = app.build_latest_change_rows(fund, periods)
        self.assertEqual(rows[0]["change_status"], "增持")
        self.assertAlmostEqual(rows[0]["shares_change_10k"], 2.3)
        self.assertAlmostEqual(rows[0]["weight_change_pp"], 1.0)


if __name__ == "__main__":
    unittest.main()
