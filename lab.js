"use strict";

const byId = id => document.getElementById(id);
const { result: defaultResult, defaults, designs, hints, counts, bundledRates } = JSON.parse(byId("initial").textContent);
const staticInputs = byId("static-inputs");
const modelInputs = staticInputs ? JSON.parse(staticInputs.textContent) : null;
let initial = defaultResult;
if (modelInputs && window.location.search) {
  try {
    initial = simulateScenario(modelInputs, defaults, Object.fromEntries(new URLSearchParams(window.location.search)));
  } catch (error) {
    if (!(error instanceof RangeError)) throw error;
    window.history.replaceState(null, "", window.location.pathname + window.location.hash);
  }
}
const form = document.querySelector("#choices form");
const labels = ["Lowest", "Lower", "Middle", "Higher", "Highest"];
const fields = Object.keys(defaults);
const plans = ["a", "b"];
const currencySelect = byId("display-currency");
const prefixes = { CAD: "CA$", USD: "US$", EUR: "EUR\u00a0", GBP: "GBP\u00a0" };
const fixed = new Intl.NumberFormat("en-CA", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const percent = new Intl.NumberFormat("en-CA", { style: "percent", maximumFractionDigits: 2 });
const count = new Intl.NumberFormat("en-CA");
const ratesKey = "carbon-dividend-lab.bank-of-canada.v1";
let rates = bundledRates;
let ratesRefreshed = false;
let rateRequest;
let retryRatesAt = 0;

function useRates(candidate) {
  if (candidate && /^\d{4}-\d{2}-\d{2}$/.test(candidate.date) && candidate.date >= rates.date &&
      ["USD", "EUR", "GBP"].every(code => {
        const rate = candidate.cadPerUnit?.[code];
        return Number.isFinite(rate) && rate > 0;
      })) {
    rates = candidate;
    return true;
  }
  return false;
}

try {
  useRates(JSON.parse(localStorage.getItem(ratesKey)));
} catch {
  // The bundled rates also work when browser storage is unavailable.
}

const converted = value => value / (rates.cadPerUnit[currencySelect.value] ?? 1);
function money(value, signed = false) {
  const amount = converted(value);
  const sign = amount <= -.005 ? "−" : signed && amount >= .005 ? "+" : "";
  return sign + prefixes[currencySelect.value] + fixed.format(Math.abs(amount));
}
const signed = value => money(value, true);
const final = result => result.years.at(-1);
const same = (a, b) => fields.every(key => a[key] === b[key]);
const query = settings => new URLSearchParams(settings);
const policyName = (slot, settings = current.settings) => {
  const title = designs[settings[slot]];
  return settings.a === settings.b ? title + (slot === "a" ? " (first)" : " (second)") : title;
};

let current = initial;
let preceding = null;
let action = "";
let group = 0;
let history = [];
let timeout;
let request;
let busy = false;

function describe() {
  const { settings } = current;
  if (!preceding) {
    byId("story").textContent = action || "A fuel charge does two things: it raises the cost of each unit of fuel and creates a pool of money to return. How much fuel people use depends on the assumption you choose.";
    return;
  }

  const previous = preceding.settings;
  const row = final(current);
  const old = final(preceding);
  const explanations = [action];
  if (settings.a !== previous.a || settings.b !== previous.b) {
    explanations.push("Changing who qualifies or how payments are split changes who gets a share.");
  }
  if (settings.recycle !== previous.recycle) {
    explanations.push("Changing the share returned " + (row.pool === old.pool
      ? "left the amount to share the same." : "changed how much money households split."));
  }
  if (settings.price !== previous.price) {
    explanations.push("Changing the charge changes the price of each unit of fuel and scales the assumed drop in fuel use.");
  }
  if (settings.response !== previous.response) {
    explanations.push(settings.price === 0
      ? "The fuel-use assumption has no effect while the charge is off."
      : "At a given charge, using less fuel means lower emissions, smaller charges and less money to share.");
  }
  if (row.reduction === old.reduction) {
    explanations.push("Modeled emissions stayed the same.");
  } else {
    explanations.push("Modeled emissions " + (row.reduction > old.reduction ? "fell." : "rose."));
  }
  byId("story").textContent = explanations.filter(Boolean).join(" ");
}

function renderGoals(row) {
  const payment = (slot, index) => money(row[slot].dividends[index]);
  byId("goal-1").textContent = "For the lowest income group, the charge is " + money(row.charges[0]) +
    " per year. After the payment and charge, the balance is " + signed(row.a.net[0]) + " under “" + policyName("a") +
    "” and " + signed(row.b.net[0]) + " under “" + policyName("b") + ".”";
  byId("goal-10").textContent = "From the lowest to the highest income group, average payments are " +
    payment("a", 0) + " and " + payment("a", 4) + " under “" + policyName("a") + ",” and " +
    payment("b", 0) + " and " + payment("b", 4) + " under “" + policyName("b") + ".”";
  byId("goal-13").textContent = row.reduction
    ? "Your charge and fuel-use assumption produce " + percent.format(row.reduction) + " less direct CO₂ in 2030 under both policies."
    : "Your settings keep fuel use and direct CO₂ at the no-charge level under both policies.";
  byId("goal-7").textContent = current.settings.price
    ? "Part of the " + money(row.charges[group]) + " combined fuel charge for the " + labels[group].toLowerCase() +
      " income group comes from natural gas. Compare that group’s payments above to see how much of the combined charge each policy covers."
    : "With the charge off, both policies add zero to natural gas bills and pay no dividend.";
}

function renderEmissions() {
  const { baseline_mt_co2: baseline, years, settings } = current;
  const row = final(current);
  const tonnes = Math.round((baseline - row.emissions_mt_co2) * 1e6);
  byId("climate-summary").textContent = row.reduction
    ? `2030 · ${percent.format(row.reduction)} lower · ${count.format(tonnes)} fewer tonnes of CO₂`
    : "2030 · 0% difference · 0 tonnes of CO₂ difference";
  byId("fuel-response").textContent =
    `The no-charge case holds fuel use steady. At CAD ${settings.price} per tonne, the model assumes ` +
    (row.reduction
      ? `households use ${percent.format(row.reduction)} less of each fuel by 2030, with one quarter of that reduction added each year starting in 2027.`
      : "no change in fuel use, so the lines overlap.") +
    " The fuel-use response is an assumption you can change.";

  const left = 35;
  const right = 358;
  const top = 12;
  const bottom = 178;
  // The pinned no-charge baseline keeps the zero-based scale stable across scenarios.
  const tick = Math.ceil(baseline / 4);
  const y = value => bottom - value / (tick * 4) * (bottom - top);
  const x = index => left + index * (right - left) / (years.length - 1);
  const grid = Array.from({ length: 5 }, (_, index) => {
    const level = index * tick;
    return `<line class="chart-grid" x1="${left}" x2="${right}" y1="${y(level)}" y2="${y(level)}"/>
      <text x="${left - 8}" y="${y(level) + 5}" text-anchor="end">${level}</text>`;
  }).join("");
  const modeled = years.map((year, index) => `${x(index)},${y(year.emissions_mt_co2)}`).join(" ");
  const labelsAndDots = years.map((year, index) =>
    `<circle class="chart-dot" cx="${x(index)}" cy="${y(year.emissions_mt_co2)}" r="4"/>
    <text x="${x(index)}" y="${bottom + 22}" text-anchor="middle">${year.year}</text>`
  ).join("");
  byId("chart").innerHTML = `<svg viewBox="0 0 380 208" focusable="false">
    ${grid}
    <path class="chart-axis" fill="none" d="M ${left} ${top} V ${bottom} H ${right}"/>
    <polyline class="chart-modeled" points="${modeled}"/>
    <line class="chart-baseline" x1="${left}" x2="${right}" y1="${y(baseline)}" y2="${y(baseline)}"/>
    ${labelsAndDots}
  </svg>`;

  const rows = current.years.map(year =>
    '<tr><th scope="row">' + year.year + '</th><td>' + current.baseline_mt_co2.toFixed(3) +
    '</td><td>' + year.emissions_mt_co2.toFixed(3) + '</td><td>' + percent.format(year.reduction) + '</td></tr>'
  ).join("");
  byId("chart-rows").innerHTML = rows;
  byId("emission-rows").innerHTML = rows;
}

function renderMoney() {
  const row = final(current);
  const settings = current.settings;
  const code = currencySelect.value;
  byId("household-currency").textContent = code;
  byId("table-currency").textContent = code;
  byId("snapshot").innerHTML = plans.map(slot =>
    '<div class="tile"><p>' + policyName(slot) + '</p><strong>' + signed(row[slot].net[0]) +
    '</strong><small>After charges and payment · ' + code + '/year</small></div>'
  ).join("") + '<div class="tile climate"><p>Direct carbon emissions</p><strong>' +
    (row.reduction ? percent.format(row.reduction) + ' less' : 'No change') +
    '</strong><small>Both policies vs. no charge</small></div>';
  byId("household-cards").innerHTML = plans.map(slot => {
    const net = row[slot].net[group];
    const outcome = Math.abs(net) < .005 ? "Breaks even" : net > 0 ? "Comes out ahead" : "Pays more than it gets back";
    return '<article class="plan"><div class="home" aria-hidden="true"></div><p>' + labels[group] +
      ' income</p><h3>' + policyName(slot) + '</h3><dl>' +
      '<div><dt>Extra fuel costs</dt><dd>' + money(row.charges[group]) + '</dd></div>' +
      '<div><dt>Money returned</dt><dd>' + money(row[slot].dividends[group]) + '</dd></div>' +
      '<div><dt>Overall gain or loss</dt><dd class="' + (net < -.005 ? "negative" : "positive") + '">' + signed(net) + '</dd></div>' +
      '</dl><p>' + outcome + ' after the charge and payment.</p></article>';
  }).join("");
  const difference = row.b.net[group] - row.a.net[group];
  byId("household-comparison").textContent = Math.abs(converted(difference)) < .005
    ? "The difference between the two plans rounds to " + money(0) + " for this group."
    : "This group ends up with " + money(Math.abs(difference)) + " more under " +
      policyName(difference > 0 ? "b" : "a") + ".";

  const designCaption = plans.map((slot, index) => (index === 0 ? "First · " : "Second · ") + designs[settings[slot]] +
    " (" + count.format(row[slot].eligible_households) + " eligible households)");
  byId("table-designs").replaceChildren(designCaption[0], document.createElement("br"), designCaption[1]);
  byId("household-rows").innerHTML = labels.map((label, index) =>
    '<tr><th scope="row">' + label + '</th><td>' + count.format(counts[index]) +
    '</td><td>' + money(row.charges[index]) + '</td>' + plans.map(slot =>
      '<td>' + money(row[slot].dividends[index]) + '</td><td>' + signed(row[slot].net[index]) + '</td>'
    ).join("") + '</tr>'
  ).join("");
  const millions = value => money(value / 1e6) + " million";
  byId("budget").textContent = "2030 charge revenue is " + millions(row.revenue) + ". Dividends total " +
    millions(row.pool) + ", leaving " + millions(row.retained) + " outside the payout pool.";
  renderGoals(row);
}

function render() {
  renderMoney();
  renderEmissions();
  const download = byId("download");
  if (modelInputs) {
    if (download.href.startsWith("blob:")) URL.revokeObjectURL(download.href);
    download.href = URL.createObjectURL(new Blob([JSON.stringify(current, null, 2)], { type: "application/json" }));
  } else {
    download.href = "scenario.json?" + query(current.settings);
  }
  describe();
}

function describeRate() {
  const code = currencySelect.value;
  byId("currency-provenance").hidden = code === "CAD";
  byId("currency-rate").textContent = code === "CAD" ? "Showing amounts in CAD." :
    `1 ${code} = ${rates.cadPerUnit[code].toFixed(4)} CAD · ${rates.date}` +
    (rateRequest ? " · checking for a newer rate" : ratesRefreshed ? "" : " · cached rate");
}

async function refreshRates() {
  try {
    const response = await fetch("exchange-rates.json", { cache: "no-store" });
    if (!response.ok) return;
    const { rates: candidate, refreshed } = await response.json();
    if (useRates(candidate)) {
      ratesRefreshed = !modelInputs && refreshed === true;
      localStorage.setItem(ratesKey, JSON.stringify(rates));
    }
  } catch {
    // Keep showing the most recent dated rates available on this computer.
  } finally {
    rateRequest = null;
    retryRatesAt = Date.now() + (ratesRefreshed ? 3600000 : 300000);
    if (currencySelect.value !== "CAD") {
      renderMoney();
      describeRate();
    }
  }
}

function readSettings() {
  return Object.fromEntries(fields.map(key => {
    const input = form.elements.namedItem(key);
    return [key, input.type === "number" ? input.valueAsNumber : input.value];
  }));
}

function writeSettings(settings) {
  for (const key of fields) form.elements.namedItem(key).value = settings[key];
  for (const slot of plans) byId(slot + "-hint").textContent = hints[settings[slot]];
}

function updateButtons() {
  byId("undo").disabled = busy || history.length === 0;
  byId("reset").disabled = !busy && same(readSettings(), defaults) && same(current.settings, defaults) && history.length === 0;
}

function cancelUpdate() {
  clearTimeout(timeout);
  request?.abort();
  request = null;
  busy = false;
}

function commit(result, message = "", remember = true) {
  if (remember && !same(current.settings, result.settings)) history.push(current);
  preceding = same(current.settings, result.settings) ? null : current;
  current = result;
  action = message;
  writeSettings(current.settings);
  const search = same(current.settings, defaults) ? "" : "?" + query(current.settings);
  window.history.replaceState(null, "", window.location.pathname + search + window.location.hash);
  byId("update-status").textContent = "";
  render();
  updateButtons();
}

async function fetchResult(settings, message) {
  if (modelInputs) {
    busy = false;
    commit(simulateScenario(modelInputs, defaults, settings), message);
    return;
  }
  const controller = new AbortController();
  request = controller;
  try {
    const response = await fetch("scenario.json?" + query(settings), { signal: controller.signal });
    if (!response.ok) throw new Error("Scenario request failed");
    const result = await response.json();
    if (request === controller) {
      busy = false;
      commit(result, message);
    }
  } catch (error) {
    if (request === controller && error.name !== "AbortError") {
      busy = false;
      byId("update-status").textContent = "Could not update. Showing the last results. Check that the lab is still running and try again.";
      updateButtons();
    }
  } finally {
    if (request === controller) request = null;
  }
}

function scheduleUpdate(delay) {
  cancelUpdate();
  if (!form.matches(":valid")) {
    byId("update-status").textContent = "Enter a whole number in the listed range. Results show the last valid settings.";
  } else if (!same(readSettings(), current.settings)) {
    byId("update-status").textContent = "Updating results…";
    busy = true;
    timeout = setTimeout(() => fetchResult(readSettings(), ""), delay);
  } else {
    byId("update-status").textContent = "";
  }
  updateButtons();
}

form.addEventListener("input", event => {
  const field = event.target;
  if (plans.includes(field.name)) byId(field.name + "-hint").textContent = hints[field.value];
  scheduleUpdate(field.type === "number" ? 250 : 0);
});
form.addEventListener("submit", event => {
  event.preventDefault();
  scheduleUpdate(0);
});
byId("groups").addEventListener("change", event => {
  group = Number(event.target.value);
  render();
});
currencySelect.value = "CAD";
currencySelect.addEventListener("change", () => {
  if (currencySelect.value !== "CAD" && !rateRequest && Date.now() >= retryRatesAt) {
    ratesRefreshed = false;
    rateRequest = refreshRates();
  }
  renderMoney();
  describeRate();
});
byId("undo").addEventListener("click", () => {
  if (history.length) commit(history.pop(), "Last change undone.", false);
  if (byId("undo").disabled) form.elements.a.focus();
});
byId("reset").addEventListener("click", () => {
  cancelUpdate();
  if (same(current.settings, defaults)) {
    commit(current, "Starting settings restored.");
  } else if (same(initial.settings, defaults)) {
    commit(initial, "Starting settings restored.");
  } else {
    writeSettings(defaults);
    busy = true;
    byId("update-status").textContent = "Restoring the starting settings…";
    updateButtons();
    fetchResult(defaults, "Starting settings restored.");
  }
  if (byId("reset").disabled) form.elements.a.focus();
});
byId("details").open = false;
writeSettings(initial.settings);
document.querySelectorAll(".guided, .actions").forEach(element => element.hidden = false);
if (initial.settings.response !== defaults.response || initial.settings.recycle !== defaults.recycle) {
  document.querySelector(".settings").open = true;
}
render();
updateButtons();
