import os
import glob
import unittest
from bs4 import BeautifulSoup
import stock_reporter
from stock_reporter import (
    apply_python_rank_guard,
    build_line_messages,
    create_dashboard_html,
    default_unavailable_technicals,
    default_unavailable_fundamentals,
    default_unavailable_big_change,
)


class TestPythonRankGuard(unittest.TestCase):
    def setUp(self):
        self.code = "7203"
        self.stock_dict = {self.code: "トヨタ自動車"}

    def test_rule_r1_technical_contradiction_demotes_s_to_a(self):
        """1. ルールR1: S評価で客観テクニカルが完全未達（52w/2y/終値超/MA50下回/出来高急増なし）ならSからAへ補正"""
        stock = {
            "code": self.code,
            "name": "トヨタ自動車",
            "rank": "S",
            "python_technical": {
                "data_status": "ok",
                "breakout_52w": False,
                "breakout_2y": False,
                "close_above_52w_high": False,
                "above_ma50": False,
                "volume_surge": False
            },
            "python_fundamentals": {
                "data_status": "ok",
                "quarter_data_basis": "standalone",
                "quarterly_growth_criteria_status": "met",
                "quarterly_revenue_growth_pct": 15.0,
                "quarterly_ordinary_profit_growth_pct": 25.0
            },
            "big_change": {
                "status": "identified",
                "category": "大型受注・大型契約"
            }
        }
        res = apply_python_rank_guard(stock)
        self.assertTrue(res["guard_applied"])
        self.assertEqual(res["original_rank"], "S")
        self.assertEqual(res["final_rank"], "A")
        self.assertEqual(res["rule_applied"], "R1")
        self.assertIn("主要なブレイク・出来高条件が確認できない", res["reason"])
        self.assertTrue(res["review_required"])

    def test_rule_r1_does_not_fire_when_any_technical_item_is_none(self):
        """2. ルールR1: テクニカル指標のいずれかがNone（未取得・判定不能）なら発動しない"""
        # above_ma50 が None（上場直後などでMA50未計算等）
        stock = {
            "code": self.code,
            "name": "トヨタ自動車",
            "rank": "S",
            "python_technical": {
                "data_status": "ok",
                "breakout_52w": False,
                "breakout_2y": False,
                "close_above_52w_high": False,
                "above_ma50": None,  # None
                "volume_surge": False
            }
        }
        res = apply_python_rank_guard(stock)
        self.assertFalse(res["guard_applied"])
        self.assertEqual(res["final_rank"], "S")
        self.assertIsNone(res["rule_applied"])

    def test_rule_r1_does_not_fire_when_breakout_or_surge_is_true(self):
        """3. ルールR1: 出来高急増または高値ブレイクがTrueならS評価を維持"""
        stock = {
            "code": self.code,
            "name": "トヨタ自動車",
            "rank": "S",
            "python_technical": {
                "data_status": "ok",
                "breakout_52w": True,  # ザラ場ブレイクあり
                "breakout_2y": False,
                "close_above_52w_high": False,
                "above_ma50": False,
                "volume_surge": False
            }
        }
        res = apply_python_rank_guard(stock)
        self.assertFalse(res["guard_applied"])
        self.assertEqual(res["final_rank"], "S")

    def test_rule_r1_on_a_rank_sets_review_flag_without_demoting_to_b(self):
        """4. ルールR1: A評価の銘柄には要確認フラグを付与するのみで、Bへの自動降格は行わない"""
        stock = {
            "code": self.code,
            "name": "トヨタ自動車",
            "rank": "A",
            "python_technical": {
                "data_status": "ok",
                "breakout_52w": False,
                "breakout_2y": False,
                "close_above_52w_high": False,
                "above_ma50": False,
                "volume_surge": False
            }
        }
        res = apply_python_rank_guard(stock)
        self.assertFalse(res["guard_applied"])
        self.assertEqual(res["final_rank"], "A")
        self.assertTrue(res["review_required"])
        self.assertIn("要確認", res["review_reason"])

    def test_rule_r2_fundamentals_and_technical_contradiction_demotes_s_to_a(self):
        """5. ルールR2: 四半期成長not_met + テクニカル未達 + ビッグチェンジ未確認ならSからAへ補正"""
        stock = {
            "code": self.code,
            "name": "トヨタ自動車",
            "rank": "S",
            "python_technical": {
                "data_status": "ok",
                "breakout_52w": False,
                "breakout_2y": False,
                "close_above_52w_high": False,
                "above_ma50": True,  # MA50を上回っているためR1は非発動
                "volume_surge": False
            },
            "python_fundamentals": {
                "data_status": "ok",
                "quarter_data_basis": "standalone",
                "quarterly_growth_criteria_status": "not_met",
                "quarterly_revenue_growth_pct": 5.0,  # 10%未満
                "quarterly_ordinary_profit_growth_pct": 8.0,  # 20%未満
                "profit_turnaround": False
            },
            "big_change": {
                "status": "unconfirmed",
                "category": "未確認"
            }
        }
        res = apply_python_rank_guard(stock)
        self.assertTrue(res["guard_applied"])
        self.assertEqual(res["original_rank"], "S")
        self.assertEqual(res["final_rank"], "A")
        self.assertEqual(res["rule_applied"], "R2")
        self.assertIn("四半期単独の業績成長条件が未達", res["reason"])
        self.assertTrue(res["review_required"])

    def test_rule_r2_does_not_fire_if_big_change_is_identified(self):
        """6. ルールR2: 確定的なビッグチェンジ(identified)が存在すれば、SからAへの補正を防ぐ"""
        stock = {
            "code": self.code,
            "name": "トヨタ自動車",
            "rank": "S",
            "python_technical": {
                "data_status": "ok",
                "breakout_52w": False,
                "breakout_2y": False,
                "close_above_52w_high": False,
                "above_ma50": True,
                "volume_surge": False
            },
            "python_fundamentals": {
                "data_status": "ok",
                "quarter_data_basis": "standalone",
                "quarterly_growth_criteria_status": "not_met",
                "quarterly_revenue_growth_pct": 4.0,
                "quarterly_ordinary_profit_growth_pct": 5.0,
                "profit_turnaround": False
            },
            # 確定的なビッグチェンジあり
            "big_change": {
                "status": "identified",
                "category": "大型受注・大型契約"
            }
        }
        res = apply_python_rank_guard(stock)
        self.assertFalse(res["guard_applied"])
        self.assertEqual(res["final_rank"], "S")

    def test_rule_r2_does_not_fire_if_growth_criteria_unconfirmed_or_cumulative(self):
        """7. ルールR2: 累計値のみやデータ不足で未確定(unconfirmed)の場合はSを下げない"""
        stock = {
            "code": self.code,
            "name": "トヨタ自動車",
            "rank": "S",
            "python_technical": {
                "data_status": "ok",
                "breakout_52w": False,
                "breakout_2y": False,
                "volume_surge": False
            },
            "python_fundamentals": {
                "data_status": "ok",
                "quarter_data_basis": "cumulative",  # 累計のみ
                "quarterly_growth_criteria_status": "unconfirmed",
                "quarterly_revenue_growth_pct": None,
                "quarterly_ordinary_profit_growth_pct": None
            },
            "big_change": {
                "status": "unconfirmed"
            }
        }
        res = apply_python_rank_guard(stock)
        self.assertFalse(res["guard_applied"])
        self.assertEqual(res["final_rank"], "S")

    def test_rule_r2_does_not_fire_if_ordinary_profit_growth_undetermined(self):
        """8. ルールR2: 売上10%以上で経常利益成長率が判定不能な場合は発動させない"""
        stock = {
            "code": self.code,
            "name": "トヨタ自動車",
            "rank": "S",
            "python_technical": {
                "data_status": "ok",
                "breakout_52w": False,
                "breakout_2y": False,
                "volume_surge": False
            },
            "python_fundamentals": {
                "data_status": "ok",
                "quarter_data_basis": "standalone",
                "quarterly_growth_criteria_status": "not_met",
                "quarterly_revenue_growth_pct": 18.0,  # 売上達成
                "quarterly_ordinary_profit_growth_pct": None,  # 経常利益未取得
                "profit_turnaround": False
            },
            "big_change": {
                "status": "unconfirmed"
            }
        }
        res = apply_python_rank_guard(stock)
        self.assertFalse(res["guard_applied"])
        self.assertEqual(res["final_rank"], "S")

    def test_rank_never_upgraded_by_python(self):
        """9. Pythonからランクを引き上げることは絶対にしない（BはBのまま）"""
        stock = {
            "code": self.code,
            "name": "トヨタ自動車",
            "rank": "B",
            # テクニカル・業績・ビッグチェンジすべて完璧なデータ
            "python_technical": {
                "data_status": "ok",
                "breakout_52w": True,
                "breakout_2y": True,
                "close_above_52w_high": True,
                "above_ma50": True,
                "volume_surge": True
            },
            "python_fundamentals": {
                "data_status": "ok",
                "quarter_data_basis": "standalone",
                "quarterly_growth_criteria_status": "met",
                "quarterly_revenue_growth_pct": 35.0,
                "quarterly_ordinary_profit_growth_pct": 80.0,
                "profit_turnaround": True
            },
            "big_change": {
                "status": "identified",
                "category": "新製品・新サービス"
            }
        }
        res = apply_python_rank_guard(stock)
        self.assertFalse(res["guard_applied"])
        self.assertEqual(res["final_rank"], "B")

    def test_big_change_unconfirmed_alone_does_not_demote(self):
        """10. ビッグチェンジ未確認のみを理由にSランクを下げることはしない"""
        stock = {
            "code": self.code,
            "name": "トヨタ自動車",
            "rank": "S",
            "python_technical": {
                "data_status": "ok",
                "breakout_52w": True,
                "breakout_2y": True,
                "close_above_52w_high": True,
                "above_ma50": True,
                "volume_surge": True
            },
            "python_fundamentals": {
                "data_status": "ok",
                "quarter_data_basis": "standalone",
                "quarterly_growth_criteria_status": "met",
                "quarterly_revenue_growth_pct": 20.0,
                "quarterly_ordinary_profit_growth_pct": 40.0
            },
            # ビッグチェンジのみ未確認
            "big_change": {
                "status": "unconfirmed",
                "category": "未確認"
            }
        }
        res = apply_python_rank_guard(stock)
        self.assertFalse(res["guard_applied"])
        self.assertEqual(res["final_rank"], "S")

    def test_html_and_line_integration_with_rank_guard(self):
        """11. HTMLおよびLINEメッセージにおいてガード補正および要確認フラグが明示される"""
        data = {
            "summary": {
                "total_scraped": 2,
                "top_picks_count": 2,
                "market_trend_comment": "新高値ブレイク銘柄分析"
            },
            "evaluated_stocks": [
                {
                    "code": "7203",
                    "name": "トヨタ自動車",
                    "rank": "S",
                    "confidence": "High",
                    "action_plan": "打診買い",
                    "analysis_reason": "高値更新期待",
                    "python_technical": {
                        "data_status": "ok",
                        "breakout_52w": False,
                        "breakout_2y": False,
                        "close_above_52w_high": False,
                        "above_ma50": False,
                        "volume_surge": False
                    },
                    "python_fundamentals": {
                        "data_status": "ok",
                        "quarter_data_basis": "standalone",
                        "quarterly_growth_criteria_status": "met"
                    },
                    "big_change": {
                        "status": "unconfirmed"
                    }
                },
                {
                    "code": "6701",
                    "name": "日本電気",
                    "rank": "A",
                    "confidence": "Medium",
                    "action_plan": "様子見",
                    "analysis_reason": "保ち合い",
                    "python_technical": {
                        "data_status": "ok",
                        "breakout_52w": False,
                        "breakout_2y": False,
                        "close_above_52w_high": False,
                        "above_ma50": False,
                        "volume_surge": False
                    },
                    "python_fundamentals": {
                        "data_status": "ok",
                        "quarter_data_basis": "standalone",
                        "quarterly_growth_criteria_status": "not_met"
                    },
                    "big_change": {
                        "status": "unconfirmed"
                    }
                }
            ]
        }
        stock_dict = {"7203": "トヨタ自動車", "6701": "日本電気"}

        # LINEメッセージの検証
        line_msgs = build_line_messages(data, "2026.09.29")
        self.assertTrue(len(line_msgs) >= 1)
        # トヨタはSからAへ補正されたことがLINEに表示される
        self.assertIn("A[🛡️元S補正]", line_msgs[0])
        # 日本電気はAランクに[⚠️要確認]が付与される
        self.assertIn("A[⚠️要確認]", line_msgs[0])

        # HTMLダッシュボードの検証
        create_dashboard_html(data, stock_dict)
        html_files = glob.glob(os.path.join("docs", "reports", "*.html"))
        self.assertTrue(len(html_files) > 0)
        with open(html_files[0], "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("⑥ ランクガード補正", content)
            self.assertIn("🛡️ ガード補正(元S:R1)", content)
            self.assertIn("⑥ ランクガード要確認", content)

    def test_rule_r4_confirmed_tob_sets_review_flag(self):
        """12. ルールR4: 確認済みのTOB・完全子会社化・上場廃止等の材料なら要確認フラグを付与（機械的にBに強制しない）"""
        stock = {
            "code": self.code,
            "name": "トヨタ自動車",
            "rank": "A",
            "confidence": "High",
            "bear_case": "親会社による完全子会社化を目的としたTOBの実施を発表、上場廃止が決定",
            "python_technical": {
                "data_status": "ok",
                "breakout_52w": True,
                "breakout_2y": True,
                "close_above_52w_high": True,
                "above_ma50": True,
                "volume_surge": True
            },
            "python_fundamentals": {
                "data_status": "ok",
                "quarter_data_basis": "standalone",
                "quarterly_growth_criteria_status": "met"
            },
            "big_change": {
                "status": "unconfirmed"
            }
        }
        res = apply_python_rank_guard(stock)
        self.assertEqual(res["final_rank"], "A")  # 機械的なB降格は行わない
        self.assertTrue(res["review_required"])
        self.assertEqual(res["rule_applied"], "R4")
        self.assertIn("TOB・完全子会社化・上場廃止等の確認済み材料あり", res["review_reason"])

    def test_rule_r4_speculative_rumor_or_denial_does_not_trigger(self):
        """13. ルールR4: 単なる観測・噂・否定記事の場合は要確認フラグを発動させない"""
        stock = {
            "code": self.code,
            "name": "トヨタ自動車",
            "rank": "S",
            "confidence": "High",
            "bear_case": "一部メディアで買収観測やTOBの噂が報道されたが、会社側は否定している",
            "python_technical": {
                "data_status": "ok",
                "breakout_52w": True,
                "breakout_2y": True,
                "close_above_52w_high": True,
                "above_ma50": True,
                "volume_surge": True
            },
            "python_fundamentals": {
                "data_status": "ok",
                "quarter_data_basis": "standalone",
                "quarterly_growth_criteria_status": "met",
                "quarterly_revenue_growth_pct": 20.0,
                "quarterly_ordinary_profit_growth_pct": 30.0
            },
            "big_change": {
                "status": "unconfirmed"
            }
        }
        res = apply_python_rank_guard(stock)
        self.assertEqual(res["final_rank"], "S")
        self.assertFalse(res["review_required"])
        self.assertIsNone(res["rule_applied"])

    def test_confidence_downgraded_from_high_to_medium_when_data_missing_and_bc_unconfirmed(self):
        """14. テクニカル・業績未取得かつビッグチェンジ未確認時、confidenceがHighならMediumへ補正（rank不変）"""
        stock = {
            "code": self.code,
            "name": "トヨタ自動車",
            "rank": "A",
            "confidence": "High",
            "python_technical": {
                "data_status": "unavailable"
            },
            "python_fundamentals": {
                "data_status": "unavailable"
            },
            "big_change": {
                "status": "unconfirmed"
            }
        }
        res = apply_python_rank_guard(stock)
        self.assertEqual(res["final_rank"], "A")  # rankは変更しない
        self.assertEqual(res["original_confidence"], "High")
        self.assertEqual(res["final_confidence"], "Medium")
        self.assertTrue(res["confidence_adjusted"])
        self.assertEqual(stock["confidence"], "Medium")

    def test_confidence_not_downgraded_if_any_metric_or_big_change_exists(self):
        """15. テクニカルまたは業績またはビッグチェンジが存在すればconfidenceは維持される"""
        stock = {
            "code": self.code,
            "name": "トヨタ自動車",
            "rank": "A",
            "confidence": "High",
            "python_technical": {
                "data_status": "ok",
                "breakout_52w": True
            },
            "python_fundamentals": {
                "data_status": "unavailable"
            },
            "big_change": {
                "status": "unconfirmed"
            }
        }
        res = apply_python_rank_guard(stock)
        self.assertEqual(res["final_confidence"], "High")
        self.assertFalse(res["confidence_adjusted"])

    def test_rank_guard_reapplication_preserves_initial_history(self):
        """16. 同じ銘柄にランクガードを再適用しても、最初の補正履歴が消えない"""
        stock = {
            "code": self.code,
            "name": "トヨタ自動車",
            "rank": "S",
            "confidence": "High",
            "python_technical": {
                "data_status": "ok",
                "breakout_52w": False,
                "breakout_2y": False,
                "close_above_52w_high": False,
                "above_ma50": False,
                "volume_surge": False
            },
            "python_fundamentals": {
                "data_status": "ok",
                "quarter_data_basis": "standalone",
                "quarterly_growth_criteria_status": "met"
            },
            "big_change": {
                "status": "unconfirmed"
            }
        }
        # 1回目の適用: S -> A へ補正
        res1 = apply_python_rank_guard(stock)
        self.assertEqual(res1["original_rank"], "S")
        self.assertEqual(res1["final_rank"], "A")
        self.assertTrue(res1["guard_applied"])

        # 2回目の適用: stock['rank'] はすでに 'A' だが、初回original_rank='S'が保持される
        res2 = apply_python_rank_guard(stock)
        self.assertEqual(res2["original_rank"], "S")
        self.assertEqual(res2["final_rank"], "A")
        self.assertTrue(res2["guard_applied"])
        self.assertEqual(stock["original_rank"], "S")


if __name__ == "__main__":
    unittest.main()
