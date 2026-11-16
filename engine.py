"""Deterministic household fuel-charge and dividend accounting."""
import json
from pathlib import Path

DATA = json.loads(Path(__file__).with_name("inputs.json").read_text(encoding="utf-8"))
DESIGNS = {
    "all": "Equal per household",
    "person": "Equal per person",
    "targeted": "Lowest two income groups",
}
DEFAULTS = {"price": 80, "recycle": 100, "response": 10, "a": "all", "b": "targeted"}
LIMITS = {"price": (0, 200), "recycle": (0, 100), "response": (0, 30)}


def parse(values):
    settings = DEFAULTS.copy()
    for key, bounds in LIMITS.items():
        value = int(values.get(key, settings[key]))
        if not bounds[0] <= value <= bounds[1]:
            raise ValueError(f"{key} must be between {bounds[0]} and {bounds[1]}.")
        settings[key] = value
    for key in ("a", "b"):
        value = values.get(key, settings[key])
        if value not in DESIGNS:
            raise ValueError("Choose one of the listed dividend designs.")
        settings[key] = value
    return settings


def simulate(values):
    settings = parse(values)
    data = DATA["observed"]
    assumptions = DATA["assumptions"]
    counts = data["households_2023"]
    sizes = data["people_per_household_2023"]
    litres = assumptions["baseline_litres_per_household"]
    gas = assumptions["baseline_m3_per_household"]
    rates = data["historical_charge"]
    factors = data["combustion_kg_co2"]
    price_scale = settings["price"] / rates["cad_per_tonne_co2e"]
    full_response = settings["response"] / 100 * settings["price"] / 100
    first, last = assumptions["first_year"], assumptions["last_year"]
    baseline_mt = sum(
        n * (l * factors["per_litre_gasoline"] + g * factors["per_m3_natural_gas"])
        for n, l, g in zip(counts, litres, gas)
    ) / 1e9
    years = []
    for year in range(first, last + 1):
        reduction = full_response * (year - first + 1) / (last - first + 1)
        remaining = 1 - reduction
        charges = [
            (l * rates["cad_per_litre"] + g * rates["cad_per_m3"]) * price_scale * remaining
            for l, g in zip(litres, gas)
        ]
        revenue = sum(n * charge for n, charge in zip(counts, charges))
        pool = revenue * settings["recycle"] / 100
        designs = {}
        for slot in ("a", "b"):
            design = settings[slot]
            weights = {
                "all": [1] * len(counts),
                "person": sizes,
                "targeted": [1, 1, 0, 0, 0],
            }[design]
            total_weight = sum(n * weight for n, weight in zip(counts, weights))
            dividends = [pool * weight / total_weight for weight in weights]
            designs[slot] = {
                "dividends": dividends,
                "net": [payment - cost for payment, cost in zip(dividends, charges)],
                "paid": sum(n * payment for n, payment in zip(counts, dividends)),
                "eligible_households": sum(n for n, w in zip(counts, weights) if w),
            }
        years.append({
            "year": year, "reduction": reduction, "emissions_mt_co2": baseline_mt * remaining,
            "charges": charges, "revenue": revenue, "pool": pool, "retained": revenue - pool,
            **designs,
        })
    return {"input_version": DATA["version"], "settings": settings,
            "baseline_mt_co2": baseline_mt, "years": years}
