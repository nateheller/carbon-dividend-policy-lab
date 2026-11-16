import io
import json
import unittest
from unittest.mock import Mock, patch

from app import Handler, render
from engine import DATA, DEFAULTS, simulate
import exchange_rates


class PolicyLabTests(unittest.TestCase):
    def test_default_and_hand_calculation(self):
        result = simulate({})
        self.assertEqual(result, simulate(DEFAULTS))
        self.assertEqual([row["year"] for row in result["years"]], [2027, 2028, 2029, 2030])
        final = result["years"][-1]
        self.assertAlmostEqual(result["baseline_mt_co2"], 12.67855699035, places=8)
        self.assertAlmostEqual(final["charges"][0], 238.5928)
        self.assertAlmostEqual(final["reduction"], 0.08)
        self.assertAlmostEqual(final["emissions_mt_co2"], result["baseline_mt_co2"] * 0.92)
        self.assertEqual(final["b"]["eligible_households"], 667880)

    def test_budget_by_design_and_year(self):
        counts = DATA["observed"]["households_2023"]
        for design in ("all", "person", "targeted"):
            result = simulate({"b": design, "recycle": 64})
            for row in result["years"]:
                self.assertAlmostEqual(row["pool"] + row["retained"], row["revenue"], delta=1e-5)
                self.assertAlmostEqual(row["pool"], row["b"]["paid"], delta=1e-5)
                aggregate_net = sum(n * net for n, net in zip(counts, row["b"]["net"]))
                self.assertAlmostEqual(aggregate_net, -row["retained"], delta=1e-5)

    def test_targeting_and_person_weights(self):
        final = simulate({"a": "person"})["years"][-1]
        self.assertEqual(final["b"]["dividends"][2:], [0, 0, 0])
        self.assertEqual(final["b"]["dividends"][0], final["b"]["dividends"][1])
        values = final["a"]["dividends"]
        self.assertAlmostEqual(values[-1] / values[0], 3.70 / 1.58)

    def test_zero_charge(self):
        result = simulate({"price": 0, "response": 30})
        for row in result["years"]:
            self.assertEqual(row["emissions_mt_co2"], result["baseline_mt_co2"])
            self.assertEqual(row["revenue"], 0)
            self.assertEqual(row["b"]["net"], [0] * 5)

    def test_fixed_demand_and_no_recycling(self):
        result = simulate({"response": 0, "recycle": 0})
        row = result["years"][-1]
        self.assertEqual(row["emissions_mt_co2"], result["baseline_mt_co2"])
        self.assertEqual(row["retained"], row["revenue"])
        self.assertEqual(row["a"]["net"], [-charge for charge in row["charges"]])

    def test_upper_bounds_and_response_direction(self):
        fixed = simulate({"price": 200, "response": 0})["years"][-1]
        responsive = simulate({"price": 200, "response": 30})["years"][-1]
        self.assertAlmostEqual(responsive["reduction"], 0.60)
        self.assertGreater(responsive["emissions_mt_co2"], 0)
        self.assertLess(responsive["revenue"], fixed["revenue"])

    def test_validation(self):
        for params in ({"price": -1}, {"price": 201}, {"response": "nan"},
                       {"recycle": 101}, {"a": "other"}, {"price": ""}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                simulate(params)

    def test_front_end_routes_settings_into_results(self):
        page = render(simulate({"price": "100", "a": "person", "b": "all"})).decode()
        self.assertIn('name="price" type="number" value="100"', page)
        self.assertIn('<input type="radio" name="a" value="person" checked>', page)
        payload = page.split('<script id="initial" type="application/json">')[1].split("</script>")[0]
        self.assertEqual(json.loads(payload)["result"], simulate({"price": "100", "a": "person", "b": "all"}))
        self.assertIn('Explore the details', page)
        self.assertIn('a=person&amp;b=all', page)
        self.assertIn('Alberta pilot', page)
        self.assertIn('<option value="CAD" selected>', page)
        self.assertIn('CA$291.76', page)
        self.assertEqual(json.loads(payload)["bundledRates"], exchange_rates.BUNDLED_RATES)

    def test_dividend_choices_leave_charges_and_emissions_unchanged(self):
        before = simulate({})
        after = simulate({"a": "person", "b": "all", "recycle": 65})
        for previous, current in zip(before["years"], after["years"]):
            for key in ("charges", "revenue", "emissions_mt_co2", "reduction"):
                self.assertEqual(previous[key], current[key])
            self.assertNotEqual(previous["b"]["dividends"], current["b"]["dividends"])

    def test_http_handler_serves_scenario_and_rejects_invalid_price(self):
        handler = Handler.__new__(Handler)
        handler.wfile = io.BytesIO()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.send_error = Mock()
        handler.path = "/scenario.json?price=120&response=15&a=person"
        handler.do_GET()
        handler.send_response.assert_called_once_with(200)
        data = json.loads(handler.wfile.getvalue())
        self.assertAlmostEqual(data["years"][-1]["reduction"], 0.18)
        self.assertEqual(data["settings"]["a"], "person")
        handler.path = "/?price=201"
        handler.do_GET()
        self.assertEqual(handler.send_error.call_args.args[0], 400)

    def test_rates_refresh_and_reuse_last_good_snapshot_offline(self):
        observations = {"observations": [{
            "d": "2026-11-16",
            "FXUSDCAD": {"v": "1.43"},
            "FXEURCAD": {"v": "1.57"},
            "FXGBPCAD": {"v": "1.89"},
        }]}
        with patch.multiple(exchange_rates, _next_fetch=0, _rates=exchange_rates.BUNDLED_RATES,
                            _refreshed=False), patch.object(exchange_rates, "urlopen") as request:
            request.side_effect = OSError
            self.assertEqual(exchange_rates.latest_rates(), {
                "rates": exchange_rates.BUNDLED_RATES, "refreshed": False,
            })
            request.side_effect = lambda *args, **kwargs: io.BytesIO(json.dumps(observations).encode())
            exchange_rates._next_fetch = 0
            refreshed = exchange_rates.latest_rates()
            self.assertTrue(refreshed["refreshed"])
            self.assertEqual(refreshed["rates"]["date"], "2026-11-16")
            self.assertEqual(refreshed["rates"]["cadPerUnit"]["USD"], 1.43)

            request.side_effect = OSError
            exchange_rates._next_fetch = 0
            self.assertEqual(exchange_rates.latest_rates(), {"rates": refreshed["rates"], "refreshed": False})

    def test_rates_reject_incomplete_or_invalid_observations(self):
        row = {"d": "2026-11-16", "FXUSDCAD": {"v": "1.43"}, "FXEURCAD": {"v": "1.57"}}
        with self.assertRaises(KeyError):
            exchange_rates.parse_rates({"observations": [row]})
        for value in ("NaN", "Infinity", "0", "-1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                exchange_rates.parse_rates({"observations": [{**row, "FXGBPCAD": {"v": value}}]})


if __name__ == "__main__":
    unittest.main()
