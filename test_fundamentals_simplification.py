import unittest
from bs4 import BeautifulSoup

# stock_reporter の該当関数をインポート
import stock_reporter
from stock_reporter import (
    _parse_yen_amount,
    default_unavailable_fundamentals,
    parse_performance_table,
)

class TestFundamentalsSimplification(unittest.TestCase):
    def test_yen_amount_parsing(self):
        """1. Yahoo!の掲載金額を正しい単位（百万円）で読み取れる"""
        self.assertEqual(_parse_yen_amount("13兆5,254億円"), 13525400.0)
        self.assertEqual(_parse_yen_amount("1.5兆円"), 1500000.0)
        self.assertEqual(_parse_yen_amount("283億円"), 28300.0)
        self.assertEqual(_parse_yen_amount("15億2,000万円"), 1520.0)
        self.assertEqual(_parse_yen_amount("1,963,862百万円"), 1963862.0)
        self.assertEqual(_parse_yen_amount("3,700万円"), 37.0)
        self.assertIsNone(_parse_yen_amount(""))
        self.assertIsNone(_parse_yen_amount(None))

    def test_quarterly_summary_yahoo_q1_standalone(self):
        """2. 第1四半期（Q1）は3カ月単独（standalone）として認識され、売上+10%・経常+20%でmet判定"""
        sample_q1_html = """
        <html>
        <body>
        <div>決算短信の要約</div>
        <p>2026年3月期 第1四半期の連結業績は、売上高は前年同期比 15.0% 増の 1,150百万円、営業利益は前年同期比 25.0% 増の 125百万円、経常利益は前年同期比 30.0% 増の 130百万円となりました。</p>
        </body>
        </html>
        """
        y_data = stock_reporter.fetch_quarterly_summary_yahoo("9999", html_text=sample_q1_html)
        self.assertIsNotNone(y_data)
        self.assertEqual(y_data["basis"], "standalone")
        self.assertEqual(y_data["revenue_growth_pct"], 15.0)
        self.assertEqual(y_data["ord_growth_pct"], 30.0)

        fund = stock_reporter.calculate_quarterly_fundamentals("9999", y_data=y_data)
        self.assertEqual(fund["quarter_data_basis"], "standalone")
        self.assertEqual(fund["quarterly_growth_criteria_status"], "met")
        self.assertTrue(fund["meets_growth_criteria"])
        self.assertIsNotNone(fund["margin_change_pp"])
        self.assertTrue(fund["margin_change_pp"] > 0)
        self.assertTrue(fund["quarterly_margin_expansion"])

    def test_quarterly_summary_yahoo_q2_cumulative(self):
        """3. 第2四半期累計（中間期）はcumulativeとなり、単独ではないため成長条件判定はunconfirmed"""
        sample_q2_html = """
        <html>
        <body>
        <div>決算短信の要約</div>
        <p>2026年3月期 第2四半期（中間期）の連結累計期間の業績は、売上高は前年同期比 18.0% 増の 2,500百万円、経常利益は前年同期比 35.0% 増の 300百万円となりました。</p>
        </body>
        </html>
        """
        y_data = stock_reporter.fetch_quarterly_summary_yahoo("9999", html_text=sample_q2_html)
        self.assertIsNotNone(y_data)
        self.assertEqual(y_data["basis"], "cumulative")

        fund = stock_reporter.calculate_quarterly_fundamentals("9999", y_data=y_data)
        self.assertEqual(fund["quarter_data_basis"], "cumulative")
        # 累計値の前年比を単独の前年比として判定してはならないため unconfirmed
        self.assertEqual(fund["quarterly_growth_criteria_status"], "unconfirmed")
        self.assertFalse(fund["meets_growth_criteria"])
        self.assertIn("累計", fund["revenue_growth"])

    def test_growth_criteria_not_met(self):
        """4. 単独データがあるが売上または利益の条件未達の場合、not_met と判定される"""
        sample_q1_html = """
        <html>
        <body>
        <div>決算短信の要約</div>
        <p>2026年3月期 第1四半期において、売上高は前年同期比 5.0% 増の 1,050百万円、経常利益は前年同期比 10.0% 増の 110百万円となりました。</p>
        </body>
        </html>
        """
        y_data = stock_reporter.fetch_quarterly_summary_yahoo("9999", html_text=sample_q1_html)
        fund = stock_reporter.calculate_quarterly_fundamentals("9999", y_data=y_data)
        self.assertEqual(fund["quarter_data_basis"], "standalone")
        self.assertEqual(fund["quarterly_growth_criteria_status"], "not_met")
        self.assertFalse(fund["meets_growth_criteria"])

    def test_prior_deficit_no_anomalous_percentage_and_turnaround(self):
        """5. 前年赤字の場合、異常な成長率%を計算せず黒字転換（profit_turnaround）を別表示"""
        sample_turnaround_html = """
        <html>
        <body>
        <div>決算短信の要約</div>
        <p>2026年3月期 第1四半期の連結業績は、売上高は前年同期比 20.0% 増の 1,200百万円となりました。経常損益は 150百万円の黒字（前年同期は 50百万円の赤字）に転換しました。</p>
        </body>
        </html>
        """
        y_data = stock_reporter.fetch_quarterly_summary_yahoo("9999", html_text=sample_turnaround_html)
        self.assertTrue(y_data.get("profit_turnaround"))
        self.assertIsNone(y_data.get("ord_growth_pct"))

        fund = stock_reporter.calculate_quarterly_fundamentals("9999", y_data=y_data)
        self.assertTrue(fund["profit_turnaround"])
        self.assertIsNone(fund["quarterly_ordinary_profit_growth_pct"])
        self.assertIn("黒字転換", fund["profit_growth"])

    def test_missing_data_unconfirmed(self):
        """6. データ不足・欠落時は unconfirmed となり、候補から削除しない"""
        fund = stock_reporter.calculate_quarterly_fundamentals("9999", y_data=None)
        self.assertEqual(fund["quarterly_growth_criteria_status"], "unconfirmed")
        self.assertFalse(fund["meets_growth_criteria"])
        self.assertEqual(fund["quarter_data_basis"], "unavailable")

    def test_performance_table_cagr_and_forecast_separation(self):
        """7. 通期業績推移で実績と会社予想を明確に区別し、実績が十分あればCAGRを算出"""
        html_table = """
        <html>
        <body>
        <table>
            <tr><th>決算期</th><th>売上高</th><th>売上総利益</th><th>売上総利益率</th><th>営業利益</th><th>営業利益率</th><th>経常利益</th><th>経常利益率</th><th>当期純利益</th></tr>
            <tr><td>2022年3月期</td><td>10,000</td><td>3,000</td><td>30.0%</td><td>1,000</td><td>10.0%</td><td>1,000</td><td>10.0%</td><td>700</td></tr>
            <tr><td>2023年3月期</td><td>12,000</td><td>3,600</td><td>30.0%</td><td>1,300</td><td>10.8%</td><td>1,300</td><td>10.8%</td><td>900</td></tr>
            <tr><td>2024年3月期</td><td>14,000</td><td>4,200</td><td>30.0%</td><td>1,600</td><td>11.4%</td><td>1,600</td><td>11.4%</td><td>1,100</td></tr>
            <tr><td>2025年3月期</td><td>17,280</td><td>5,200</td><td>30.1%</td><td>2,000</td><td>11.6%</td><td>2,000</td><td>11.6%</td><td>1,400</td></tr>
            <tr><td>2026年3月期（会社予想）</td><td>20,000</td><td>6,000</td><td>30.0%</td><td>2,500</td><td>12.5%</td><td>2,500</td><td>12.5%</td><td>1,700</td></tr>
        </table>
        </body>
        </html>
        """
        soup = BeautifulSoup(html_table, "html.parser")
        annual_rows = parse_performance_table(soup)
        self.assertEqual(len(annual_rows), 5)
        self.assertTrue(annual_rows[-1]["is_forecast"])
        self.assertFalse(annual_rows[0]["is_forecast"])

        fund = stock_reporter.calculate_quarterly_fundamentals("9999", annual_rows=annual_rows)
        # 3年売上CAGR: (17,280 / 10,000) ** (1/3) - 1 = 1.20 - 1 = 20.0%
        self.assertIsNotNone(fund.get("annual_cagr_3y"))
        self.assertAlmostEqual(fund["annual_cagr_3y"], 20.0, places=1)
        self.assertIn("予", fund["history_summary"])

    def test_no_kabuyoho_references(self):
        """8. 株予報（kabuyoho）へのアクセス・参照がコード内に存在しない"""
        import inspect
        source = inspect.getsource(stock_reporter)
        self.assertNotIn("kabuyoho.ifis.co.jp", source)
        self.assertNotIn("fetch_quarterly_data_kabuyoho", source)

    def test_margin_profit_type_consistency(self):
        """9. 現在と前年で利益の種類を混ぜない（営業なら両方営業、経常なら両方経常）"""
        sample_html = """
        <html>
        <body>
        <div>決算短信の要約</div>
        <p>2026年3月期 第1四半期の連結業績は、売上高は前年同期比 10.0% 増の 1,100百万円、営業利益は前年同期比 20.0% 増の 120百万円、経常利益は前年同期比 25.0% 増の 125百万円となりました。</p>
        </body>
        </html>
        """
        y_data = stock_reporter.fetch_quarterly_summary_yahoo("9999", html_text=sample_html)
        fund = stock_reporter.calculate_quarterly_fundamentals("9999", y_data=y_data)
        # 営業利益が優先され、margin_profit_type が 'operating' であること
        self.assertEqual(fund["margin_profit_type"], "operating")
        # 今期利益率: 120 / 1100 = 10.91%
        # 前期売上: 1000, 前期営業利益: 100 -> 前期利益率: 10.0%
        # margin_change_pp = 10.91 - 10.0 = +0.91pp
        self.assertIsNotNone(fund["margin_change_pp"])
        self.assertAlmostEqual(fund["margin_change_pp"], 0.91, places=1)

    def test_existing_features_maintained(self):
        """10. 既存機能（テクニカル計算、英字混在コード対応、429診断、Stage構成）の保持"""
        # 英字混在コードの正規化
        stock_dict = {"130A": "ベリタス", "219A": "ハートシード", "9999": "テスト社"}
        self.assertEqual(stock_reporter.normalize_code("130A", stock_dict), "130A")
        self.assertEqual(stock_reporter.normalize_code("130a", stock_dict), "130A")
        self.assertEqual(stock_reporter.normalize_code("ハートシード", stock_dict, raw_name="ハートシード"), "219A")

        # 429診断
        class FakeAPIError(Exception):
            pass
        err_daily = FakeAPIError("Resource has been exhausted (e.g. check quota): daily limit exceeded")
        is_perm, reason = stock_reporter._diagnose_429_reason(err_daily)
        self.assertTrue(is_perm)

        err_rpm = FakeAPIError("rate limit exceeded: requests per minute")
        is_perm2, reason2 = stock_reporter._diagnose_429_reason(err_rpm)
        self.assertFalse(is_perm2)

        # テクニカル計算（データ不足時のNone保持）
        tech_unavail = stock_reporter.default_unavailable_technicals()
        self.assertIsNone(tech_unavail["latest_close"])
        self.assertEqual(tech_unavail["data_status"], "unavailable")

    def test_yen_amount_various_units(self):
        """11. 15億円などの単位表記を正しく読み取れる"""
        self.assertEqual(_parse_yen_amount("15億円"), 1500.0)
        self.assertEqual(_parse_yen_amount("15億"), 1500.0)
        self.assertEqual(_parse_yen_amount("15億2000万"), 1520.0)
        self.assertEqual(_parse_yen_amount("15億2,000万円"), 1520.0)
        self.assertEqual(_parse_yen_amount("1.5兆"), 1500000.0)
        self.assertEqual(_parse_yen_amount("3700万"), 37.0)
        self.assertEqual(_parse_yen_amount(" 15 億円 "), 1500.0)

    def test_q4_not_standalone_without_explicit_evidence(self):
        """12. 第4四半期を明確な根拠なく3カ月単独（standalone）と判定せずcumulativeとする"""
        sample_q4_cumulative_html = """
        <html>
        <body>
        <div>決算短信の要約</div>
        <p>2026年3月期 第4四半期（通期）の連結業績は、売上高は前年同期比 15.0% 増の 10,000百万円、経常利益は前年同期比 25.0% 増の 1,000百万円となりました。</p>
        </body>
        </html>
        """
        y_data = stock_reporter.fetch_quarterly_summary_yahoo("9999", html_text=sample_q4_cumulative_html)
        self.assertIsNotNone(y_data)
        # 3カ月単独の文言がないため cumulative と判定される
        self.assertEqual(y_data["basis"], "cumulative")

        sample_q4_standalone_html = """
        <html>
        <body>
        <div>決算短信の要約</div>
        <p>2026年3月期 第4四半期連結会計期間（3カ月間）の業績は、売上高は前年同期比 15.0% 増の 2,800百万円、経常利益は前年同期比 25.0% 増の 300百万円となりました。</p>
        </body>
        </html>
        """
        y_data2 = stock_reporter.fetch_quarterly_summary_yahoo("9999", html_text=sample_q4_standalone_html)
        self.assertIsNotNone(y_data2)
        # 明確な3カ月単独の文言がある場合は standalone と判定される
        self.assertEqual(y_data2["basis"], "standalone")

    def test_growth_criteria_not_met_by_operating_profit_alone(self):
        """13. 経常利益が未取得の場合、営業利益だけで成長条件metと判定せずunconfirmedとする"""
        sample_op_only_html = """
        <html>
        <body>
        <div>決算短信の要約</div>
        <p>2026年3月期 第1四半期の連結業績は、売上高は前年同期比 15.0% 増の 1,500百万円、営業利益は前年同期比 40.0% 増の 200百万円となりました。</p>
        </body>
        </html>
        """
        y_data = stock_reporter.fetch_quarterly_summary_yahoo("9999", html_text=sample_op_only_html)
        self.assertIsNotNone(y_data)
        self.assertIsNone(y_data.get("ord_growth_pct"))
        self.assertEqual(y_data.get("op_growth_pct"), 40.0)

        fund = stock_reporter.calculate_quarterly_fundamentals("9999", y_data=y_data)
        self.assertEqual(fund["quarter_data_basis"], "standalone")
        # 経常利益未取得のため、営業利益+40%があってもmetではなくunconfirmedとなる
        self.assertEqual(fund["quarterly_growth_criteria_status"], "unconfirmed")
        self.assertFalse(fund["meets_growth_criteria"])
        # 営業利益の成長率は参考情報として保持されていること
        self.assertEqual(fund["quarterly_operating_profit_growth_pct"], 40.0)


if __name__ == "__main__":
    unittest.main()
