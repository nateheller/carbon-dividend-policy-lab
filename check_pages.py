"""Compare browser calculations to Python and verify the Pages artifact's local links."""

import itertools
import json
import math
from html.parser import HTMLParser
from pathlib import Path
import subprocess
import sys
from urllib.parse import urljoin, urlsplit

from engine import DATA, DEFAULTS, DESIGNS, simulate


def compare(expected, actual):
    if isinstance(expected, dict):
        assert expected.keys() == actual.keys()
        for key in expected:
            compare(expected[key], actual[key])
    elif isinstance(expected, list):
        assert len(expected) == len(actual)
        for left, right in zip(expected, actual):
            compare(left, right)
    elif isinstance(expected, float):
        # Python 3.12 compensates float sums. Subtracting large totals can
        # leave sub-microdollar differences even when the balance is zero.
        assert math.isclose(expected, actual, rel_tol=1e-12, abs_tol=1e-6), (expected, actual)
    else:
        assert expected == actual, (expected, actual)


class PageLinks(HTMLParser):
    def handle_starttag(self, tag, attributes):
        for name, value in attributes:
            if name in {"src", "href", "action"} and value and not urlsplit(value).scheme:
                path = urlsplit(urljoin("https://example.org/carbon-lab/", value)).path
                assert path.startswith("/carbon-lab/"), value
                asset = path.removeprefix("/carbon-lab/") or "index.html"
                assert (Path("dist") / asset).is_file(), value


def main():
    cases = [{}] + [
        dict(zip(DEFAULTS, values))
        for values in itertools.product([0, 80, 137, 200], [0, 63, 100], [0, 10, 30], DESIGNS, DESIGNS)
    ]
    run = subprocess.run(
        ["node", "-e", """
        const simulate = require('./scenario.js');
        const { data, defaults, cases } = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
        console.log(JSON.stringify(cases.map(settings => simulate(data, defaults, settings))));
        """],
        input=json.dumps({"data": DATA, "defaults": DEFAULTS, "cases": cases}),
        capture_output=True, text=True, check=True,
    )
    compare([simulate(case) for case in cases], json.loads(run.stdout))
    subprocess.run([sys.executable, "build_pages.py"], check=True)
    page = Path("dist/index.html").read_text(encoding="utf-8")
    PageLinks().feed(page)
    assert 'id="static-inputs"' in page
    compare(simulate({}), json.loads(Path("dist/scenario.json").read_text(encoding="utf-8")))
    print(f"{len(cases)} scenario comparisons passed. All local HTML links resolve below the repository path.")


if __name__ == "__main__":
    main()
