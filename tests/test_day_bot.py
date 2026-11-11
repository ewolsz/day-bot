"""The bot's decisions and its handling of the broker, with a fake Alpaca. No network."""

import copy
import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bot"))
import day_bot  # noqa: E402
import rules  # noqa: E402
from rules import ET  # noqa: E402

CFG = json.loads((ROOT / "config" / "day_bot.json").read_text())
DAY = "2026-11-10"


def at(hm: str, sec: int = 0) -> datetime:
    h, m = hm.split(":")
    return datetime(2026, 11, 10, int(h), int(m), sec, tzinfo=ET)


def bar(hm, o, h, lo, c, v=1000):
    return {"t": at(hm), "o": o, "h": h, "l": lo, "c": c, "v": v}


def morning(breakout_at="10:10", base=100.0, close=101.5, vol=1000, until="10:10"):
    """Range 99.00 to 101.00 (stop 100.00), flat bars, then a close above at `breakout_at`."""
    rows = [bar("09:30", base, base + 1, base - 1, base, vol), bar("09:35", base, base + 0.8, base - 0.5, base + 0.2, vol),
            bar("09:40", base + 0.2, base + 0.9, base - 0.2, base + 0.5, vol)]
    t = at("09:45")
    while t <= at(until):
        hm = t.strftime("%H:%M")
        if hm == breakout_at:
            rows.append(bar(hm, base + 0.6, close + 0.1, base + 0.5, close, vol))
        elif hm > breakout_at:
            rows.append(bar(hm, close, close + 0.2, close - 0.2, close, vol))
        else:
            rows.append(bar(hm, base + 0.5, base + 0.9, base + 0.3, base + 0.6, vol))
        t += timedelta(minutes=5)
    return rows


def state(**kw):
    s = {"equity": 5000.0, "cash": 5000.0, "deployed": 0.0, "trades": 0, "risk_used": 0.0,
         "symbols": set(), "day_pnl": 0.0}
    s.update(kw)
    return s


class Decide(unittest.TestCase):
    def test_fresh_breakout_becomes_one_bracket_order(self):
        r = day_bot.decide(CFG, {"AAPL": morning()}, {"AAPL": 101.5}, state(), at("10:15", 20))
        self.assertEqual(len(r["orders"]), 1)
        o = r["orders"][0]
        self.assertEqual((o["symbol"], o["stop"], o["target"]), ("AAPL", 100.0, 104.5))
        self.assertEqual(o["qty"], 14)                                   # $1,500 cap / 101.50
        req = o["request"]
        self.assertEqual(req["order_class"], "bracket")
        self.assertEqual(req["stop_loss"], {"stop_price": "100.00"})
        self.assertEqual(req["take_profit"], {"limit_price": "104.50"})
        self.assertEqual(req["client_order_id"], "day-20261110-AAPL-r2100")
        self.assertEqual(day_bot.parse_tag(req["client_order_id"]), {"day": DAY, "symbol": "AAPL", "risk": 21.0})

    def test_bar_still_forming_is_not_a_trigger(self):
        r = day_bot.decide(CFG, {"AAPL": morning()}, {}, state(), at("10:13"))
        self.assertEqual(r["orders"], [])

    def test_old_trigger_is_skipped(self):
        r = day_bot.decide(CFG, {"AAPL": morning(until="10:20")}, {}, state(), at("10:25", 20))
        self.assertEqual(r["orders"], [])

    def test_already_traded_today_is_skipped(self):
        r = day_bot.decide(CFG, {"AAPL": morning()}, {}, state(symbols={"AAPL"}, trades=1), at("10:15", 20))
        self.assertEqual(r["orders"], [])

    def test_breakout_after_the_window_is_ignored(self):
        r = day_bot.decide(CFG, {"AAPL": morning(breakout_at="10:30", until="10:30")}, {}, state(), at("10:35", 20))
        self.assertEqual(r["orders"], [])

    def test_price_that_ran_away_is_blocked(self):
        r = day_bot.decide(CFG, {"AAPL": morning()}, {"AAPL": 103.2}, state(), at("10:15", 20))
        self.assertEqual(r["orders"], [])
        self.assertTrue(any("reward:risk" in n for n in r["notes"]))

    def test_most_traded_first_and_three_a_day(self):
        bars = {s: morning(vol=v) for s, v in (("AAPL", 100), ("MSFT", 900), ("NVDA", 500), ("AMZN", 300))}
        r = day_bot.decide(CFG, bars, {}, state(), at("10:15", 20))
        self.assertEqual([o["symbol"] for o in r["orders"]], ["MSFT", "NVDA", "AMZN"])
        self.assertTrue(r["done"])
        spent = sum(o["qty"] * o["ref"] for o in r["orders"])
        self.assertLessEqual(spent, 5000 * 0.9)                           # the cash buffer survives

    def test_one_slot_left(self):
        bars = {s: morning() for s in ("AAPL", "MSFT")}
        r = day_bot.decide(CFG, bars, {}, state(trades=2, risk_used=40.0, cash=2000.0, deployed=3000.0), at("10:15", 20))
        self.assertEqual(len(r["orders"]), 1)

    def test_daily_loss_and_halt_block_everything(self):
        for s in (state(day_pnl=-160.0, equity=4840.0), state(equity=4200.0, cash=4200.0)):
            r = day_bot.decide(CFG, {"AAPL": morning()}, {}, s, at("10:15", 20))
            self.assertEqual(r["orders"], [])

    def test_never_spends_more_than_the_budget_in_a_big_account(self):
        r = day_bot.decide(CFG, {"AAPL": morning()}, {}, state(equity=100000.0, cash=97000.0, deployed=3000.0), at("10:15", 20))
        self.assertEqual(r["orders"][0]["qty"], 14)
        r = day_bot.decide(CFG, {"AAPL": morning()}, {}, state(equity=100000.0, cash=95400.0, deployed=4600.0), at("10:15", 20))
        self.assertEqual(r["orders"], [])


class Timing(unittest.TestCase):
    open_dt, close_dt = at("09:30"), at("16:00")

    def test_run_gate(self):
        self.assertIsNone(day_bot.run_gate(CFG, at("09:43"), self.open_dt, self.close_dt))
        self.assertIsNone(day_bot.run_gate(CFG, at("10:05"), self.open_dt, self.close_dt))       # a late start still works
        self.assertIn("too early", day_bot.run_gate(CFG, at("08:40"), self.open_dt, self.close_dt))
        self.assertIn("too early", day_bot.run_gate(CFG, at("09:20"), self.open_dt, self.close_dt))  # a delayed off-season slot
        self.assertIn("past", day_bot.run_gate(CFG, at("10:40"), self.open_dt, self.close_dt))
        self.assertIn("early close", day_bot.run_gate(CFG, at("09:43"), self.open_dt, at("13:00")))

    def test_next_check(self):
        self.assertEqual(day_bot.next_check(CFG, at("09:41")), at("09:50", 20))    # first bar after the range
        self.assertEqual(day_bot.next_check(CFG, at("09:52")), at("09:55", 20))
        self.assertEqual(day_bot.next_check(CFG, at("10:25", 30)), at("10:30", 20))
        self.assertIsNone(day_bot.next_check(CFG, at("10:30", 30)))

    def test_flatten_plan(self):
        self.assertEqual(day_bot.flatten_plan(CFG, at("15:45"), self.close_dt), ("go", at("15:52")))
        self.assertEqual(day_bot.flatten_plan(CFG, at("15:58"), self.close_dt)[0], "go")           # late: act at once
        self.assertEqual(day_bot.flatten_plan(CFG, at("14:42"), self.close_dt)[0], "early")        # winter's first slot
        self.assertEqual(day_bot.flatten_plan(CFG, at("16:42"), self.close_dt)[0], "missed")
        self.assertEqual(day_bot.flatten_plan(CFG, at("12:40"), at("13:00")), ("go", at("12:52")))


class FakeAlpaca:
    def __init__(self, bars=None, positions=None, orders=None, equity=5000.0, cash=5000.0, stuck=False):
        self._bars, self._positions, self._orders = bars or {}, positions or [], orders or []
        self.equity, self.cash, self.stuck = equity, cash, stuck
        self.submitted, self.calls = [], []

    def account(self):
        return {"equity": str(self.equity), "cash": str(self.cash), "last_equity": "5000"}

    def calendar(self, day):
        return [{"date": day, "open": "09:30", "close": "16:00"}]

    def positions(self):
        return list(self._positions)

    def orders(self, after, status="all"):
        return list(self._orders)

    def bars(self, symbols, start, end, feed, **kw):
        return {s: self._bars.get(s, []) for s in symbols}

    def latest_trades(self, symbols, feed):
        return {}

    def submit(self, order):
        self.submitted.append(order)
        return {"id": "x"}

    def close_all_positions(self):
        self.calls.append("close_all")
        if not self.stuck:
            self._positions = []

    def cancel_all_orders(self):
        self.calls.append("cancel_all")

    def close_position(self, symbol):
        self.calls.append(f"close {symbol}")
        self._positions = [p for p in self._positions if p["symbol"] != symbol]


def order(cid, symbol, side="buy", status="filled", filled="14", qty="14"):
    return {"client_order_id": cid, "symbol": symbol, "side": side, "status": status, "filled_qty": filled, "qty": qty}


class Broker(unittest.TestCase):
    def setUp(self):
        self._sleep, self._notify = day_bot._time.sleep, day_bot.notify
        day_bot._time.sleep = lambda s: None
        self.alerts = []
        day_bot.notify = lambda title, body="": self.alerts.append(title)

    def tearDown(self):
        day_bot._time.sleep, day_bot.notify = self._sleep, self._notify

    def test_cycle_places_the_order(self):
        api = FakeAlpaca(bars={"AAPL": morning()})
        r = day_bot.cycle(api, CFG, at("10:15", 20))
        self.assertEqual(len(api.submitted), 1)
        self.assertEqual(api.submitted[0]["symbol"], "AAPL")
        self.assertEqual(self.alerts, ["Day bot bought AAPL"])
        self.assertFalse(r["done"])

    def test_dry_run_sends_nothing(self):
        api = FakeAlpaca(bars={"AAPL": morning()})
        day_bot.cycle(api, CFG, at("10:15", 20), dry_run=True)
        self.assertEqual(api.submitted, [])

    def test_second_run_the_same_day_does_not_buy_again(self):
        api = FakeAlpaca(bars={"AAPL": morning()}, orders=[order("day-20261110-AAPL-r2100", "AAPL")],
                         positions=[{"symbol": "AAPL", "qty": "14", "market_value": "1421"}], cash=3579.0)
        day_bot.cycle(api, CFG, at("10:15", 20))
        self.assertEqual(api.submitted, [])

    def test_state_counts_todays_entries_only(self):
        api = FakeAlpaca(orders=[
            order("day-20261110-AAPL-r2100", "AAPL"),
            order("day-20261110-MSFT-r1800", "MSFT", status="canceled", filled="0"),   # never filled: not a trade
            order("day-20261109-NVDA-r3000", "NVDA"),                                  # yesterday
            order("3f1c-broker-made-id", "AAPL", side="sell"),                         # a flatten sell
        ])
        s = day_bot.read_state(api, CFG, DAY)
        self.assertEqual((s["trades"], s["risk_used"]), (1, 21.0))
        self.assertIsNone(s["wrong"])

    def test_refuses_the_rotation_bots_account(self):
        api = FakeAlpaca(bars={"AAPL": morning()}, positions=[{"symbol": "XLK", "qty": "10", "market_value": "2300"}])
        with self.assertRaises(RuntimeError):
            day_bot.cycle(api, CFG, at("10:15", 20))
        self.assertEqual(api.submitted, [])
        api = FakeAlpaca(orders=[order("rot-20261101-EEM", "EEM")])
        self.assertIn("another bot", day_bot.read_state(api, CFG, DAY)["wrong"])

    def test_flatten(self):
        api = FakeAlpaca(positions=[{"symbol": "AAPL", "qty": "14", "market_value": "1421"}])
        self.assertTrue(day_bot.flatten_now(api, pause=0))
        self.assertEqual(api.calls, ["close_all"])

    def test_flatten_falls_back_to_one_by_one(self):
        api = FakeAlpaca(positions=[{"symbol": "AAPL", "qty": "14", "market_value": "1421"}], stuck=True)
        self.assertTrue(day_bot.flatten_now(api, pause=0))
        self.assertEqual(api.calls, ["close_all", "cancel_all", "close AAPL"])

    def test_report(self):
        fills = [
            {"transaction_time": "2026-11-10T15:15:21.123456789Z", "symbol": "AAPL", "side": "buy", "qty": "14", "price": "101.50"},
            {"transaction_time": "2026-11-10T16:40:00Z", "symbol": "AAPL", "side": "sell", "qty": "14", "price": "104.50"},
            {"transaction_time": "2026-11-11T15:00:00Z", "symbol": "MSFT", "side": "buy", "qty": "3", "price": "400.00"},
            {"transaction_time": "2026-11-11T15:30:00Z", "symbol": "MSFT", "side": "sell", "qty": "3", "price": "398.00"},
            {"transaction_time": "2026-11-12T15:00:00Z", "symbol": "NVDA", "side": "buy", "qty": "5", "price": "200.00"},   # still open
        ]
        orders = [order("day-20261110-AAPL-r2100", "AAPL"), order("day-20261111-MSFT-r600", "MSFT")]
        md, rows = day_bot.build_report(CFG, fills, orders, 5036.0)
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(rows[0]["pnl"], 42.0)
        self.assertAlmostEqual(rows[0]["R"], 2.0)
        self.assertAlmostEqual(rows[1]["R"], -1.0)
        self.assertIn("Completed trades: **2**", md)
        self.assertIn("+36.00 USD", md)


class Config(unittest.TestCase):
    def test_shipped_config_is_paper_long_only(self):
        cfg = day_bot.load_cfg()
        self.assertIs(cfg["paper"], True)
        self.assertEqual(day_bot.TRADING_URL, "https://paper-api.alpaca.markets")
        self.assertEqual(len(cfg["universe"]), len(set(cfg["universe"])))
        self.assertLessEqual(cfg["max_trades_per_day"] * cfg["max_loss_per_trade_usd"], cfg["max_daily_loss_usd"])
        self.assertLessEqual(cfg["max_trades_per_day"] * cfg["max_position_pct"], 100 - cfg["cash_buffer_pct"])

    def test_live_config_is_refused(self):
        bad = copy.deepcopy(CFG)
        bad["paper"] = False
        p = ROOT / "tests" / "_bad.json"
        p.write_text(json.dumps(bad))
        try:
            with self.assertRaises(SystemExit):
                day_bot.load_cfg(p)
        finally:
            p.unlink()


if __name__ == "__main__":
    unittest.main()
