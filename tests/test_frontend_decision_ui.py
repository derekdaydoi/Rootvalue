import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendDecisionContractTests(unittest.TestCase):
    def read(self, name: str) -> str:
        return (ROOT / name).read_text(encoding="utf-8")

    def test_morning_brief_and_capital_guardrail_are_present(self):
        html = self.read("index.html")
        ui = self.read("enhancements.js")
        self.assertIn('id="morningBrief"', html)
        self.assertIn("function decisionSnapshot", ui)
        self.assertIn("function capitalCopy", ui)
        self.assertIn("function businessDaysSince", ui)
        self.assertIn("ageBusinessDays>1", ui)
        self.assertIn("selectionUsable", ui)
        self.assertIn("weakBreadth&&sharpIndexDrop", ui)
        self.assertIn("const top=s.ready?s.sectors[0]:null", ui)
        self.assertIn("const list=snapshot.ready?", ui)
        self.assertIn("notice.marketOnly", ui)
        self.assertIn("capital.layersIncomplete", ui)
        self.assertIn("Độ rộng watchlist", ui)
        self.assertIn("market.historicalTable", ui)
        self.assertNotIn("const fallback=", ui)
        self.assertIn("Độ rộng chỉ đo universe cấu hình", ui)
        self.assertIn(".slice(0,8)", ui)
        self.assertNotIn(".slice(0,20)", ui)

    def test_sparklines_preserve_gaps_and_have_text_alternatives(self):
        app = self.read("app.js")
        self.assertIn("function monotonePath", app)
        self.assertIn("const raw=values.map(toFinite)", app)
        self.assertIn("if(v===null)", app)
        self.assertIn('role="img"', app)
        self.assertNotIn('aria-hidden="true"><polyline', app)

    def test_chart_domain_and_surface_rules_are_professional(self):
        analysis = self.read("analysis.js")
        styles = self.read("styles.css") + self.read("rootvalue-v2.css")
        self.assertNotIn("if(min>0)min=0", analysis)
        self.assertIn("range*.08", analysis)
        self.assertIn("periods.length>=6", analysis)
        self.assertNotIn("OpenAI Sans", styles)
        self.assertNotIn("linear-gradient", styles)
        self.assertIn("stroke-width:2.5", styles)

    def test_chart_breaks_calendar_gaps_and_marks_zero_crossings(self):
        analysis = self.read("analysis.js")
        styles = self.read("rootvalue-v2.css")
        self.assertIn("function rvPeriodsAdjacent", analysis)
        self.assertIn("right.year-left.year===1", analysis)
        self.assertIn("right.year*4+right.quarter-(left.year*4+left.quarter)===1", analysis)
        self.assertIn("!rvPeriodsAdjacent(previousPeriod,p)", analysis)
        self.assertIn("crossesZero=dataMin<0&&dataMax>0", analysis)
        self.assertIn("if(crossesZero)gridValues.push(0)", analysis)
        self.assertIn("Math.abs(val)>zeroTolerance", analysis)
        self.assertIn("rv-zero-line", analysis)
        self.assertIn(".rv-zero-line", styles)
        self.assertIn("if(!seg.length){previousPeriod=null;return;}", analysis)
        self.assertIn("seg.length===1?seg:[seg[0],seg[seg.length-1]]", analysis)

    def test_global_stale_series_never_count_as_ready(self):
        polish = self.read("polish.js")
        styles = self.read("rootvalue-v2.css")
        self.assertIn("function globalSeriesState", polish)
        self.assertIn("function globalSeriesFresh", polish)
        self.assertIn("externalInputs.every(globalSeriesFresh)", polish)
        self.assertIn("globalSeriesAsOf", polish)
        self.assertIn("rv-series-status", polish)
        self.assertIn("stale-data", polish)
        self.assertNotIn("GLOBAL?.status==='ok'||GLOBAL?.status==='partial'", polish)
        self.assertIn(".rv-series-status.stale", styles)

    def test_company_dashboard_falls_back_to_raw_companies(self):
        analysis = self.read("analysis.js")
        self.assertIn("function rvRawCompanies(){return STATE.data?.companies?.rows||{};}", analysis)
        self.assertIn("window.rvBuildDashboardFallback(raw)", analysis)
        self.assertIn("const rawSymbols=Object.keys(rvRawCompanies())", analysis)
        self.assertIn("const marketSymbols=(STATE.data?.market?.rows||[]).map", analysis)
        self.assertIn("STATE.company=candidates.find", analysis)
        self.assertIn("!decisionSnapshot(STATE.data||{}).ready", analysis)
        self.assertNotIn("const leaders=ranked", analysis)


if __name__ == "__main__":
    unittest.main()
