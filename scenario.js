"use strict";

function simulateScenario(data, defaults, values) {
  const settings = { ...defaults };
  for (const [key, max] of Object.entries({ price: 200, recycle: 100, response: 30 })) {
    if (!Object.hasOwn(values, key)) continue;
    const raw = String(values[key]).trim();
    const value = Number(raw);
    if (!/^[+-]?\d+$/.test(raw) || !Number.isInteger(value) || value < 0 || value > max) {
      throw new RangeError(`Invalid ${key}`);
    }
    settings[key] = value;
  }

  const observed = data.observed;
  const assumptions = data.assumptions;
  const counts = observed.households_2023;
  const litres = assumptions.baseline_litres_per_household;
  const gas = assumptions.baseline_m3_per_household;
  const rates = observed.historical_charge;
  const factors = observed.combustion_kg_co2;
  const weightsByDesign = {
    all: counts.map(() => 1),
    person: observed.people_per_household_2023,
    targeted: [1, 1, 0, 0, 0],
  };
  for (const slot of ["a", "b"]) {
    if (!Object.hasOwn(values, slot)) continue;
    if (!Object.hasOwn(weightsByDesign, values[slot])) throw new RangeError("Invalid dividend design");
    settings[slot] = values[slot];
  }

  const sum = values => values.reduce((total, value) => total + value, 0);
  const weighted = values => sum(counts.map((count, i) => count * values[i]));
  const baseline = weighted(litres.map((volume, i) =>
    volume * factors.per_litre_gasoline + gas[i] * factors.per_m3_natural_gas)) / 1e9;
  const priceScale = settings.price / rates.cad_per_tonne_co2e;
  const fullResponse = settings.response / 100 * settings.price / 100;
  const first = assumptions.first_year;
  const last = assumptions.last_year;
  const years = [];

  for (let year = first; year <= last; year++) {
    const reduction = fullResponse * (year - first + 1) / (last - first + 1);
    const remaining = 1 - reduction;
    const charges = litres.map((volume, i) =>
      (volume * rates.cad_per_litre + gas[i] * rates.cad_per_m3) * priceScale * remaining);
    const revenue = weighted(charges);
    const pool = revenue * settings.recycle / 100;
    const row = {
      year, reduction, emissions_mt_co2: baseline * remaining, charges, revenue, pool,
      retained: revenue - pool,
    };
    for (const slot of ["a", "b"]) {
      const weights = weightsByDesign[settings[slot]];
      const totalWeight = weighted(weights);
      const dividends = weights.map(weight => pool * weight / totalWeight);
      row[slot] = {
        dividends,
        net: dividends.map((payment, i) => payment - charges[i]),
        paid: weighted(dividends),
        eligible_households: weighted(weights.map(weight => Number(weight !== 0))),
      };
    }
    years.push(row);
  }
  return { input_version: data.version, settings, baseline_mt_co2: baseline, years };
}

if (typeof module !== "undefined") module.exports = simulateScenario;
