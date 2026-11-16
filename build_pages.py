"""Render the public GitHub Pages artifact with the Python model and pinned inputs."""

import argparse
import json
from pathlib import Path
from shutil import copy2, copytree

from app import render
from engine import DATA, simulate
from exchange_rates import BUNDLED_RATES, latest_rates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-rates", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    output = root / "dist"
    output.mkdir(exist_ok=True)
    default = simulate({})
    page = render(default).decode("utf-8")
    for attribute in ('href="/', 'src="/', 'action="/'):
        page = page.replace(attribute, attribute[:-1] + "./")
    page = page.replace(
        '<script src="./lab.js" defer></script>',
        '<script src="./scenario.js" defer></script>\n<script src="./lab.js" defer></script>',
    ).replace(
        '</body>',
        '<script id="static-inputs" type="application/json">'
        + json.dumps(DATA).replace("<", "\\u003c")
        + '</script>\n</body>',
    ).replace(
        '<noscript><button type="submit">Update results</button></noscript>',
        '<noscript><p>Enable JavaScript to change the scenario. The tables show the starting settings.</p></noscript>',
    )
    (output / "index.html").write_text(page, encoding="utf-8")
    (output / "scenario.json").write_text(json.dumps(default, indent=2), encoding="utf-8")
    rates = latest_rates() if args.refresh_rates else {"rates": BUNDLED_RATES, "refreshed": False}
    (output / "exchange-rates.json").write_text(json.dumps(rates), encoding="utf-8")
    for name in ("lab.css", "lab.js", "scenario.js", "inputs.json", "README.md"):
        copy2(root / name, output)
    copytree(root / "assets", output / "assets", dirs_exist_ok=True)


if __name__ == "__main__":
    main()
