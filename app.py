"""Run the Carbon Dividend Policy Lab on this computer."""
import argparse
import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from string import Template
from threading import Timer
from urllib.parse import parse_qs, urlsplit

from engine import DATA, DEFAULTS, simulate
from exchange_rates import BUNDLED_RATES, latest_rates

ROOT = Path(__file__).resolve().parent
PAGE = Template((ROOT / "index.html").read_text(encoding="utf-8"))
POLICY_NAMES = {
    "all": "Share with everyone",
    "person": "Share by household size",
    "targeted": "Support lower-income households",
}
POLICY_HINTS = {
    "all": "Every household is eligible for the same payment, regardless of income or household size.",
    "person": "Each person gets the same share. Larger households get more, regardless of income.",
    "targeted": "Only households in the lowest two income groups are eligible. Those households split the pool equally.",
}
ASSETS = {
    "/lab.css": "text/css",
    "/lab.js": "text/javascript",
    "/README.md": "text/plain",
    "/inputs.json": "application/json",
    **{f"/assets/goal-{number}.jpg": "image/jpeg" for number in ("01", "07", "10", "13")},
}


def dollars(value, signed=False):
    sign = "−" if value < -0.005 else "+" if signed and value >= 0.005 else ""
    return f"{sign}CA${abs(value):,.2f}"


def net(value):
    return f'<span class="{"positive" if value >= 0 else "negative"}">{dollars(value, True)}</span>'


def render(result):
    settings, rows = result["settings"], result["years"]
    final = rows[-1]
    baseline = result["baseline_mt_co2"]

    labels = ["Lowest", "Lower", "Middle", "Higher", "Highest"]
    observed = DATA["observed"]
    external = DATA["external_projection"]
    national = observed["canada_inventory_mt_co2e"]
    local = observed["alberta_inventory_mt_co2e"]
    lo, hi = external["target_range_mt_co2e"]
    wm = external["with_measures_2030_mt_co2e"]
    wam = external["with_additional_measures_2030_mt_co2e"]
    options = {
        slot: "\n".join(
            f'<label><input type="radio" name="{slot}" value="{key}"'
            f'{" checked" if settings[slot] == key else ""}> <span>{value}</span></label>'
            for key, value in POLICY_NAMES.items()
        )
        for slot in ("a", "b")
    }
    household_rows = "".join(
        f'<tr><th scope="row">{label}</th><td>{count:,}</td><td>{dollars(cost)}</td>'
        f'<td>{dollars(a_pay)}</td><td>{net(a_net)}</td><td>{dollars(b_pay)}</td><td>{net(b_net)}</td></tr>'
        for label, count, cost, a_pay, a_net, b_pay, b_net in zip(
            labels, observed["households_2023"], final["charges"],
            final["a"]["dividends"], final["a"]["net"], final["b"]["dividends"], final["b"]["net"])
    )
    emission_rows = "".join(
        f'<tr><th scope="row">{row["year"]}</th><td>{baseline:.3f}</td>'
        f'<td>'
        f'{row["emissions_mt_co2"]:.3f}</td><td>{row["reduction"]:.2%}</td></tr>'
        for row in rows
    )
    query = "&amp;".join(f"{key}={value}" for key, value in settings.items())
    return PAGE.substitute(
        **settings, options_a=options["a"], options_b=options["b"],
        design_a=POLICY_NAMES[settings["a"]], design_b=POLICY_NAMES[settings["b"]],
        hint_a=POLICY_HINTS[settings["a"]], hint_b=POLICY_HINTS[settings["b"]],
        revenue=dollars(final["revenue"] / 1e6) + " million",
        pool=dollars(final["pool"] / 1e6) + " million",
        retained=dollars(final["retained"] / 1e6) + " million",
        reach_a=f'{final["a"]["eligible_households"]:,}', reach_b=f'{final["b"]["eligible_households"]:,}',
        query=query,
        initial=json.dumps({
            "result": result, "defaults": DEFAULTS, "designs": POLICY_NAMES, "hints": POLICY_HINTS,
            "counts": observed["households_2023"], "bundledRates": BUNDLED_RATES,
        }),
        household_rows=household_rows, emission_rows=emission_rows,
        national_2005=national["2005"], national_2024=national["2024"],
        national_change=f'{1 - national["2024"] / national["2005"]:.1%}',
        alberta_2005=local["2005"], alberta_2024=local["2024"],
        target=f"{lo}–{hi}", wm=wm, wam=wam, national_gap=f"{wam-hi}–{wm-hi}",
    ).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlsplit(self.path)
        if url.path in ASSETS:
            self.send_payload((ROOT / url.path[1:]).read_bytes(), ASSETS[url.path])
            return
        if url.path == "/exchange-rates.json":
            self.send_payload(json.dumps(latest_rates()).encode("utf-8"), "application/json")
            return
        if url.path not in ("/", "/scenario.json"):
            self.send_error(404)
            return
        try:
            result = simulate({key: items[-1] for key, items in
                               parse_qs(url.query, keep_blank_values=True, max_num_fields=12).items()})
        except ValueError as exc:
            self.send_error(400, str(exc))
            return
        if url.path == "/scenario.json":
            payload = json.dumps(result, indent=2, allow_nan=False).encode("utf-8")
            content_type = "application/json"
        else:
            payload, content_type = render(result), "text/html"
        self.send_payload(payload, content_type)

    def send_payload(self, payload, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type if content_type.startswith("image/") else f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        url = f"http://127.0.0.1:{server.server_port}/"
        print(f"Carbon Dividend Policy Lab is open at {url}", flush=True)
        if not args.no_browser:
            Timer(0.2, webbrowser.open, args=(url,)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()

