import os
import glob
import unittest
from bs4 import BeautifulSoup
import stock_reporter
from stock_reporter import (
    validate_and_sanitize_big_change,
    default_unavailable_big_change,
    extract_link_titles,
    build_line_messages,
    create_dashboard_html,
    VALID_BIG_CHANGE_STATUSES,
    VALID_BIG_CHANGE_CATEGORIES,
    VALID_EVIDENCE_LEVELS,
)


class TestBigChangeEvaluation(unittest.TestCase):
    def setUp(self):
        self.code = "6501"
        self.stock_materials = {
            "top": "日立製作所 株価",
            "performance": "2026年3月期 業績推移",
            "financials": "決算短信要約",
            "news": "- 次世代パワー半導体の大型量産ラインを新設 投資額500億円 [URL: https://finance.yahoo.co.jp/news/detail/12345]\n- 産業用ロボット市場の成長に関する業界まとめ",
            "disclosure": "- トヨタ自動車向け次世代EV駆動システムの大規模長期供給契約を締結 [URL: https://finance.yahoo.co.jp/quote/6501.T/disclosure/67890]\n- 新製品開発に関するお知らせ"
        }
        self.other_materials = {
            "7203": {
                "disclosure": "- 北米における新型ハイブリッド車用バッテリー工場の追加投資について [URL: https://finance.yahoo.co.jp/quote/7203.T/disclosure/99999]",
                "news": "- トヨタ、新型EV投入計画を発表"
            }
        }
        self.all_materials = {
            "6501": self.stock_materials,
            "7203": self.other_materials["7203"]
        }

    def test_valid_fetched_headline_and_url_passes(self):
        """1. 当該銘柄の実際に取得した見出しとURLなら検証を通過する"""
        raw_bc = {
            "status": "identified",
            "category": "大型受注・大型契約",
            "title": "次世代EV駆動システムの大規模長期供給契約",
            "summary": "トヨタ向けに次世代EV駆動システムの大規模長期供給契約を締結",
            "growth_mechanism": "EV普及に伴い売上高および利益率の長期的な底上げに寄与",
            "evidence_level": "disclosure_headline",
            "evidence_title": "トヨタ自動車向け次世代EV駆動システムの大規模長期供給契約を締結",
            "evidence_date": "2026/09/25",
            "source_url": "https://finance.yahoo.co.jp/quote/6501.T/disclosure/67890",
            "unconfirmed_points": "受注規模および利益への寄与度は未確認"
        }
        result = validate_and_sanitize_big_change(
            stock_code=self.code,
            raw_bc=raw_bc,
            stock_materials=self.stock_materials,
            all_materials=self.all_materials
        )
        self.assertEqual(result["status"], "identified")
        self.assertEqual(result["category"], "大型受注・大型契約")
        self.assertEqual(result["evidence_level"], "disclosure_headline")
        self.assertEqual(result["source_url"], "https://finance.yahoo.co.jp/quote/6501.T/disclosure/67890")
        self.assertEqual(result["evidence_title"], "トヨタ自動車向け次世代EV駆動システムの大規模長期供給契約を締結")

    def test_fake_yahoo_article_url_rejected_and_replaced_or_fallback(self):
        """2. Yahoo!形式でも取得済みリストに存在しない架空の記事URLは通さない"""
        raw_bc = {
            "status": "identified",
            "category": "大型受注・大型契約",
            "title": "次世代EV駆動システムの長期供給契約",
            "summary": "EV駆動システムの長期供給契約締結",
            "growth_mechanism": "安定的な受注基盤の確立",
            "evidence_level": "disclosure_headline",
            "evidence_title": "トヨタ自動車向け次世代EV駆動システムの大規模長期供給契約を締結",
            # Geminiが勝手に生成した架空の記事URL（取得済みリストにない）
            "source_url": "https://finance.yahoo.co.jp/news/detail/fake_article_99999",
            "unconfirmed_points": "特になし"
        }
        result = validate_and_sanitize_big_change(
            stock_code=self.code,
            raw_bc=raw_bc,
            stock_materials=self.stock_materials,
            all_materials=self.all_materials
        )
        # 架空URLは排除され、実際に取得していた該当開示URLへ置き換えられる
        self.assertNotEqual(result["source_url"], "https://finance.yahoo.co.jp/news/detail/fake_article_99999")
        self.assertEqual(result["source_url"], "https://finance.yahoo.co.jp/quote/6501.T/disclosure/67890")

    def test_gemini_wrong_url_replaced_by_fetched_url(self):
        """3. GeminiのURLが誤っていても、見出しと対応する取得済みURLがあれば置き換えられる"""
        raw_bc = {
            "status": "identified",
            "category": "新製品・新サービス",
            "title": "パワー半導体ライン新設",
            "summary": "次世代パワー半導体の大型量産ラインを新設",
            "growth_mechanism": "需要急拡大に対応",
            "evidence_level": "news_headline",
            "evidence_title": "次世代パワー半導体の大型量産ラインを新設 投資額500億円",
            # 誤ったURLを出力
            "source_url": "https://finance.yahoo.co.jp/quote/6501.T",
            "unconfirmed_points": "量産開始時期は未定"
        }
        result = validate_and_sanitize_big_change(
            stock_code=self.code,
            raw_bc=raw_bc,
            stock_materials=self.stock_materials,
            all_materials=self.all_materials
        )
        # 実際に取得していたニュースURLに正しく置き換わる
        self.assertEqual(result["source_url"], "https://finance.yahoo.co.jp/news/detail/12345")

    def test_fallback_to_list_page_when_no_article_url(self):
        """4. 記事URLがなければ、該当銘柄の一覧ページへ安全に誘導する"""
        # 見出し「新製品開発に関するお知らせ」はURLが付いていない
        raw_bc = {
            "status": "possible",
            "category": "新製品・新サービス",
            "title": "新製品開発",
            "summary": "新製品の開発発表",
            "growth_mechanism": "新市場開拓",
            "evidence_level": "disclosure_headline",
            "evidence_title": "新製品開発に関するお知らせ",
            "source_url": "https://finance.yahoo.co.jp/quote/6501.T/disclosure/fake_not_in_list",
            "unconfirmed_points": "詳細未確認"
        }
        result = validate_and_sanitize_big_change(
            stock_code=self.code,
            raw_bc=raw_bc,
            stock_materials=self.stock_materials,
            all_materials=self.all_materials
        )
        # 記事URL未取得のため適時開示一覧ページURLへ安全に誘導される
        self.assertEqual(result["source_url"], "https://finance.yahoo.co.jp/quote/6501.T/disclosure")

    def test_fabricated_headline_clears_all_unverified_descriptions(self):
        """5. 架空見出しを検出したら、未検証の説明文も消去される"""
        raw_bc = {
            "status": "identified",
            "category": "大型受注・大型契約",
            "title": "架空の超大型宇宙開発プロジェクト1兆円受注",
            "summary": "NASAから1兆円の宇宙ステーション機器を受注し売上倍増が確定",
            "growth_mechanism": "宇宙産業への独占的展開による莫大な収益獲得",
            "evidence_level": "disclosure_headline",
            "evidence_title": "宇宙航空研究開発機構との極秘大型契約の締結について",
            "evidence_date": "2026/09/20",
            "source_url": "https://finance.yahoo.co.jp/quote/6501.T/disclosure/fake",
            "unconfirmed_points": "利益寄与度は未定"
        }
        result = validate_and_sanitize_big_change(
            stock_code=self.code,
            raw_bc=raw_bc,
            stock_materials=self.stock_materials,
            all_materials=self.all_materials
        )
        # statusがunconfirmedとなり、未検証のテキストがすべて安全な既定値に消去される
        self.assertEqual(result["status"], "unconfirmed")
        self.assertEqual(result["category"], "未確認")
        self.assertEqual(result["title"], "未確認")
        self.assertEqual(result["summary"], "取得済み情報からは具体的な企業変化を確認できず")
        self.assertEqual(result["growth_mechanism"], "未確認")
        self.assertEqual(result["evidence_level"], "no_evidence")
        self.assertIsNone(result["evidence_title"])
        self.assertIsNone(result["evidence_date"])
        # 未検証の「NASA」や「1兆円」「宇宙」などの記述が残らない
        self.assertNotIn("NASA", result["summary"])
        self.assertNotIn("1兆円", result["summary"])
        self.assertNotIn("宇宙", result["title"])
        self.assertIn("取得済みデータで確認できないため未確認に修正", result["unconfirmed_points"])

    def test_cross_stock_contamination_clears_all_unverified_descriptions(self):
        """6. 別銘柄の材料を流用した場合も、未検証の説明文が残らない"""
        raw_bc = {
            "status": "identified",
            "category": "経営改革・事業再編",
            "title": "北米バッテリー工場への追加投資1000億円",
            "summary": "北米における新型ハイブリッド車用バッテリー工場に1000億円の追加投資を決定",
            "growth_mechanism": "北米市場でのシェア拡大",
            "evidence_level": "disclosure_headline",
            # 7203 の開示見出し
            "evidence_title": "北米における新型ハイブリッド車用バッテリー工場の追加投資について",
            "evidence_date": "2026/09/22",
            "source_url": "https://finance.yahoo.co.jp/quote/7203.T/disclosure/99999",
            "unconfirmed_points": "投資額の詳細は未定"
        }
        result = validate_and_sanitize_big_change(
            stock_code=self.code,
            raw_bc=raw_bc,
            stock_materials=self.stock_materials,
            all_materials=self.all_materials
        )
        self.assertEqual(result["status"], "unconfirmed")
        self.assertEqual(result["category"], "未確認")
        self.assertEqual(result["title"], "未確認")
        self.assertEqual(result["summary"], "取得済み情報からは具体的な企業変化を確認できず")
        self.assertIsNone(result["evidence_title"])
        self.assertNotIn("北米バッテリー", result["summary"])
        self.assertIn("別銘柄の開示・ニュースと混同", result["unconfirmed_points"])

    def test_observation_and_speculative_downgraded_not_treated_as_fact(self):
        """7. 観測記事は確定事実として扱わない"""
        # 見出しに「開発か？」等の疑問形・観測を含む場合
        stock_m = {
            "disclosure": "",
            "news": "- 次世代ロボット開発で新市場へ参入か？ [URL: https://finance.yahoo.co.jp/news/detail/55555]"
        }
        raw_bc = {
            "status": "identified",
            "category": "新製品・新サービス",
            "title": "次世代ロボット開発で新市場参入か？",
            "summary": "一部メディアで次世代ロボットへの参入観測が報道される",
            "growth_mechanism": "ロボット市場でのシェア獲得",
            "evidence_level": "news_headline",
            "evidence_title": "次世代ロボット開発で新市場へ参入か？",
            "source_url": "https://finance.yahoo.co.jp/news/detail/55555",
            "unconfirmed_points": "公式発表なし"
        }
        result = validate_and_sanitize_big_change(
            stock_code=self.code,
            raw_bc=raw_bc,
            stock_materials=stock_m,
            all_materials={self.code: stock_m}
        )
        # 確定事実(identified)ではなく兆候(possible)に格下げされる
        self.assertEqual(result["status"], "possible")
        self.assertEqual(result["evidence_title"], "次世代ロボット開発で新市場へ参入か？")
        self.assertEqual(result["source_url"], "https://finance.yahoo.co.jp/news/detail/55555")
        self.assertIn("possible", result["unconfirmed_points"])

    def test_unconfirmed_contract_details_such_as_exclusive_supply_not_treated_as_fact(self):
        """8. 根拠見出しだけでは確認できない契約内容（独占供給等）を事実として表示しない"""
        # 開示見出しには「独占」の文字は一切ない
        raw_bc = {
            "status": "identified",
            "category": "大型受注・大型契約",
            "title": "次世代EV駆動システムの長期独占供給契約",
            "summary": "トヨタ向けに次世代EV駆動システムを長期独占供給する契約を締結",
            "growth_mechanism": "独占的ポジションによる高利益率の維持",
            "evidence_level": "disclosure_headline",
            "evidence_title": "トヨタ自動車向け次世代EV駆動システムの大規模長期供給契約を締結",
            "evidence_date": "2026/09/25",
            "source_url": "https://finance.yahoo.co.jp/quote/6501.T/disclosure/67890",
            "unconfirmed_points": "受注規模は未確認"
        }
        result = validate_and_sanitize_big_change(
            stock_code=self.code,
            raw_bc=raw_bc,
            stock_materials=self.stock_materials,
            all_materials=self.all_materials
        )
        # 「独占」等の未確認契約詳細が見出しに存在しないことが unconfirmed_points に明記される
        self.assertIn("「独占」等の契約詳細は見出しに記載がなく未確認", result["unconfirmed_points"])
        # summaryでも確定した事実として「独占供給」と断定されないよう中立化されている
        self.assertIn("独占等の詳細は未確認", result["summary"])
        self.assertNotIn("長期独占供給する契約を締結", result["summary"])

    def test_html_and_line_use_only_sanitized_big_change(self):
        """9. HTMLとLINEには検証後のbig_change情報だけが渡され、一覧リンクには明記される"""
        # 1件目: 記事URLあり、2件目: 記事URLなし（一覧ページ誘導）
        data = {
            "summary": {
                "total_scraped": 2,
                "top_picks_count": 2,
                "market_trend_comment": "日経平均堅調、新高値銘柄多数。"
            },
            "evaluated_stocks": [
                {
                    "code": "6501",
                    "name": "日立製作所",
                    "rank": "S",
                    "breakout_quality": "High",
                    "confidence": "High",
                    "fundamentals": {
                        "meets_growth_criteria": True,
                        "revenue_growth": "+12.5%",
                        "profit_growth": "+25.0%",
                        "catalyst": "次世代EV駆動システムの長期供給契約"
                    },
                    "technical": {
                        "volume_surge": True,
                        "moving_average_trend": "上昇"
                    },
                    "big_change": {
                        "status": "identified",
                        "category": "大型受注・大型契約",
                        "title": "次世代EV駆動システムの長期供給契約",
                        "summary": "トヨタ向けに次世代EV駆動システムの供給契約を締結",
                        "growth_mechanism": "売上高および利益率の長期的な底上げに寄与",
                        "evidence_level": "disclosure_headline",
                        "evidence_title": "トヨタ自動車向け次世代EV駆動システムの大規模長期供給契約を締結",
                        "evidence_date": "2026/09/25",
                        "source_url": "https://finance.yahoo.co.jp/quote/6501.T/disclosure/67890",
                        "unconfirmed_points": "受注規模は未公表"
                    },
                    "bear_case": "為替変動リスク",
                    "invalidation": "25日移動平均線割れ",
                    "analysis_reason": "大型契約による構造的成長と高値ブレイク",
                    "action_plan": "打診買い"
                },
                {
                    "code": "6701",
                    "name": "日本電気",
                    "rank": "A",
                    "breakout_quality": "Medium",
                    "confidence": "Medium",
                    "fundamentals": {
                        "meets_growth_criteria": False,
                        "revenue_growth": "+5.0%",
                        "profit_growth": "+8.0%",
                        "catalyst": "新製品開発"
                    },
                    "technical": {
                        "volume_surge": False,
                        "moving_average_trend": "横ばい"
                    },
                    "big_change": {
                        "status": "possible",
                        "category": "新製品・新サービス",
                        "title": "新製品開発",
                        "summary": "新製品の開発発表",
                        "growth_mechanism": "市場投入による収益化",
                        "evidence_level": "disclosure_headline",
                        "evidence_title": "新製品開発に関するお知らせ",
                        "evidence_date": None,
                        # 記事URL未取得のため一覧ページURL
                        "source_url": "https://finance.yahoo.co.jp/quote/6701.T/disclosure",
                        "unconfirmed_points": "業績寄与度は未確認"
                    },
                    "bear_case": "競争激化",
                    "invalidation": "直近安値割れ",
                    "analysis_reason": "新製品期待",
                    "action_plan": "様子見"
                }
            ]
        }
        stock_dict = {"6501": "日立製作所", "6701": "日本電気"}

        # LINEメッセージ生成
        line_msgs = build_line_messages(data, "2026.09.29")
        self.assertTrue(len(line_msgs) >= 1)
        self.assertIn("ビッグチェンジ: [🔥材料確認] 大型受注・大型契約", line_msgs[0])
        self.assertIn("ビッグチェンジ: [⚡兆候あり] 新製品・新サービス", line_msgs[0])

        # HTMLダッシュボード生成
        create_dashboard_html(data, stock_dict)
        html_files = glob.glob(os.path.join("docs", "reports", "*.html"))
        self.assertTrue(len(html_files) > 0)
        with open(html_files[0], "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("⑩ ビッグチェンジ判定", content)
            self.assertIn("IDENTIFIED", content)
            self.assertIn("POSSIBLE", content)
            # 個別記事見出しと一覧ページへのリンク表記が区別されていること
            self.assertIn("適時開示見出し", content)
            self.assertIn("一覧ページ", content)

    def test_never_substitute_another_articles_url_when_headline_has_no_url(self):
        """10. 見出しにURLがない場合、同ページ内にある別記事のURLを出力しても代用せず一覧ページへ安全に誘導する"""
        # self.stock_materials には
        # 開示1: "トヨタ自動車向け..." [URL: .../disclosure/67890]
        # 開示2: "新製品開発に関するお知らせ" (URLなし)
        # が存在する。開示2に対してGeminiが開示1のURL（または他の記事URL）を出力した場合
        raw_bc = {
            "status": "possible",
            "category": "新製品・新サービス",
            "title": "新製品開発",
            "summary": "新製品の開発発表",
            "growth_mechanism": "新市場開拓",
            "evidence_level": "disclosure_headline",
            "evidence_title": "新製品開発に関するお知らせ",
            # 同一銘柄の別記事URLを出力
            "source_url": "https://finance.yahoo.co.jp/quote/6501.T/disclosure/67890",
            "unconfirmed_points": "詳細未確認"
        }
        result = validate_and_sanitize_big_change(
            stock_code=self.code,
            raw_bc=raw_bc,
            stock_materials=self.stock_materials,
            all_materials=self.all_materials
        )
        # 別記事のURL「67890」を代用せず、開示一覧ページへ誘導されること
        self.assertNotEqual(result["source_url"], "https://finance.yahoo.co.jp/quote/6501.T/disclosure/67890")
        self.assertEqual(result["source_url"], "https://finance.yahoo.co.jp/quote/6501.T/disclosure")

    def test_unconfirmed_evidence_date_becomes_null(self):
        """11. 取得情報から日付を確認できない場合、evidence_dateはnullにする"""
        raw_bc = {
            "status": "identified",
            "category": "大型受注・大型契約",
            "title": "次世代EV駆動システムの長期供給契約",
            "summary": "トヨタ向けに次世代EV駆動システムの供給契約を締結",
            "growth_mechanism": "売上・利益拡大",
            "evidence_level": "disclosure_headline",
            "evidence_title": "トヨタ自動車向け次世代EV駆動システムの大規模長期供給契約を締結",
            # 取得済みデータに存在しない架空の日付
            "evidence_date": "2026/01/01",
            "source_url": "https://finance.yahoo.co.jp/quote/6501.T/disclosure/67890"
        }
        result = validate_and_sanitize_big_change(
            stock_code=self.code,
            raw_bc=raw_bc,
            stock_materials=self.stock_materials,
            all_materials=self.all_materials
        )
        # 取得情報から確認できないため null に正規化される
        self.assertIsNone(result["evidence_date"])

    def test_confirmed_evidence_date_retained(self):
        """12. 取得情報に日付が含まれている場合、evidence_dateは正しく保持される"""
        stock_m = {
            "disclosure": "- 2026/09/25 トヨタ自動車向け次世代EV駆動システムの大規模長期供給契約を締結 [URL: https://finance.yahoo.co.jp/quote/6501.T/disclosure/67890]",
            "news": ""
        }
        raw_bc = {
            "status": "identified",
            "category": "大型受注・大型契約",
            "title": "次世代EV駆動システムの長期供給契約",
            "summary": "トヨタ向けに次世代EV駆動システムの供給契約を締結",
            "growth_mechanism": "売上・利益拡大",
            "evidence_level": "disclosure_headline",
            "evidence_title": "2026/09/25 トヨタ自動車向け次世代EV駆動システムの大規模長期供給契約を締結",
            "evidence_date": "2026/09/25",
            "source_url": "https://finance.yahoo.co.jp/quote/6501.T/disclosure/67890"
        }
        result = validate_and_sanitize_big_change(
            stock_code=self.code,
            raw_bc=raw_bc,
            stock_materials=stock_m,
            all_materials={self.code: stock_m}
        )
        self.assertEqual(result["evidence_date"], "2026/09/25")


if __name__ == "__main__":
    unittest.main()
