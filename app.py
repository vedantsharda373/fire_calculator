import json
import math
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

INDIA_LTCG_EXEMPTION = 125000.0
INDIA_LTCG_RATE = 0.125
INDIA_CESS_RATE = 0.04

US_LTCG_THRESHOLDS_2025 = {
    "single": {"zero_max": 48350.0, "fifteen_max": 533400.0},
    "married_joint": {"zero_max": 96700.0, "fifteen_max": 600050.0},
    "head_household": {"zero_max": 64750.0, "fifteen_max": 566700.0},
    "married_separate": {"zero_max": 48350.0, "fifteen_max": 300000.0},
}

US_NIIT_THRESHOLDS = {
    "single": 200000.0,
    "married_joint": 250000.0,
    "head_household": 200000.0,
    "married_separate": 125000.0,
}


def parse_float(data, key, default=0.0):
    value = data.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def parse_int(data, key, default=0):
    value = data.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def parse_text(data, key, default=""):
    value = data.get(key, default)
    if value is None:
        return default
    return str(value)


def get_us_ltcg_rate(total_taxable_income, filing_status):
    thresholds = US_LTCG_THRESHOLDS_2025[filing_status]
    if total_taxable_income <= thresholds["zero_max"]:
        return 0.0
    if total_taxable_income <= thresholds["fifteen_max"]:
        return 0.15
    return 0.20


def withdrawal_tax(gross_withdrawal, gain_ratio, tax_country, us_filing_status, us_other_taxable_income):
    taxable_gain = max(0.0, gross_withdrawal * gain_ratio)

    if tax_country == "US":
        total_taxable_income = us_other_taxable_income + taxable_gain
        ltcg_rate = get_us_ltcg_rate(total_taxable_income, us_filing_status)
        base_tax = taxable_gain * ltcg_rate

        niit_threshold = US_NIIT_THRESHOLDS[us_filing_status]
        niit_excess = max(0.0, total_taxable_income - niit_threshold)
        niit_base = min(taxable_gain, niit_excess)
        niit_tax = niit_base * 0.038

        return {
            "total_tax": base_tax + niit_tax,
            "taxable_gain": taxable_gain,
            "base_tax": base_tax,
            "extra_tax": niit_tax,
            "ltcg_rate_pct": ltcg_rate * 100,
            "extra_tax_label": "NIIT",
        }

    taxable_after_exemption = max(0.0, taxable_gain - INDIA_LTCG_EXEMPTION)
    base_tax = taxable_after_exemption * INDIA_LTCG_RATE
    cess = base_tax * INDIA_CESS_RATE
    return {
        "total_tax": base_tax + cess,
        "taxable_gain": taxable_gain,
        "base_tax": base_tax,
        "extra_tax": cess,
        "ltcg_rate_pct": INDIA_LTCG_RATE * 100,
        "extra_tax_label": "Cess",
    }


def net_spending_from_gross(gross_withdrawal, gain_ratio, tax_country, us_filing_status, us_other_taxable_income):
    details = withdrawal_tax(
        gross_withdrawal,
        gain_ratio,
        tax_country,
        us_filing_status,
        us_other_taxable_income,
    )
    return gross_withdrawal - details["total_tax"]


def gross_needed_for_spending(
    target_spending,
    gain_ratio,
    tax_country,
    us_filing_status,
    us_other_taxable_income,
):
    low = max(0.0, target_spending)
    high = max(target_spending * 1.5, 1.0)

    while (
        net_spending_from_gross(
            high,
            gain_ratio,
            tax_country,
            us_filing_status,
            us_other_taxable_income,
        )
        < target_spending
        and high < 1e11
    ):
        high *= 1.8

    for _ in range(80):
        mid = (low + high) / 2
        if (
            net_spending_from_gross(
                mid,
                gain_ratio,
                tax_country,
                us_filing_status,
                us_other_taxable_income,
            )
            >= target_spending
        ):
            high = mid
        else:
            low = mid

    return high


def calculate_projection(
    current_age,
    retirement_age,
    current_savings,
    current_cost_basis,
    monthly_contribution,
    annual_return,
    annual_spending,
    withdrawal_rate,
    use_coast,
    coast_age,
    tax_country,
    us_filing_status,
    us_other_taxable_income,
):
    years = max(0, retirement_age - current_age)
    monthly_rate = (1 + annual_return) ** (1 / 12) - 1
    pretax_fire_number = annual_spending / withdrawal_rate if withdrawal_rate > 0 else math.inf

    balance = max(0.0, current_savings)
    basis = min(max(0.0, current_cost_basis), balance)

    month = 0
    fire_hit_age = None
    fire_hit_month = None

    for y in range(years):
        age_this_year = current_age + y
        for _ in range(12):
            contribution = 0.0 if (use_coast and age_this_year >= coast_age) else monthly_contribution
            balance = (balance + contribution) * (1 + monthly_rate)
            basis += contribution
            month += 1

            gain_ratio_now = max(0.0, (balance - basis) / balance) if balance > 0 else 0.0
            gross_by_rule_now = balance * withdrawal_rate
            net_supported = net_spending_from_gross(
                gross_by_rule_now,
                gain_ratio_now,
                tax_country,
                us_filing_status,
                us_other_taxable_income,
            )

            if fire_hit_age is None and net_supported >= annual_spending:
                year_fraction = month / 12
                fire_hit_age = round(current_age + year_fraction, 2)
                fire_hit_month = month

    final_balance = max(0.0, balance)
    gain_ratio_retirement = max(0.0, (final_balance - basis) / final_balance) if final_balance > 0 else 0.0

    gross_needed = gross_needed_for_spending(
        annual_spending,
        gain_ratio_retirement,
        tax_country,
        us_filing_status,
        us_other_taxable_income,
    )
    tax_details_needed = withdrawal_tax(
        gross_needed,
        gain_ratio_retirement,
        tax_country,
        us_filing_status,
        us_other_taxable_income,
    )

    tax_adjusted_fire_number = gross_needed / withdrawal_rate if withdrawal_rate > 0 else math.inf
    reaches_fire_by_retirement = final_balance >= tax_adjusted_fire_number

    gross_by_rule = final_balance * withdrawal_rate
    tax_details_by_rule = withdrawal_tax(
        gross_by_rule,
        gain_ratio_retirement,
        tax_country,
        us_filing_status,
        us_other_taxable_income,
    )
    net_by_rule = gross_by_rule - tax_details_by_rule["total_tax"]

    coast_needed_today = (
        tax_adjusted_fire_number / ((1 + annual_return) ** years) if annual_return > -1 else math.inf
    )

    if tax_country == "US":
        tax_config = {
            "country": "US",
            "model": "US federal LTCG + NIIT (simplified)",
            "filing_status": us_filing_status,
            "other_taxable_income": round(us_other_taxable_income, 2),
            "effective_ltcg_rate_pct": round(tax_details_needed["ltcg_rate_pct"], 2),
            "niit_rate_pct": 3.8,
            "niit_threshold": US_NIIT_THRESHOLDS[us_filing_status],
            "threshold_reference_year": 2025,
        }
    else:
        tax_config = {
            "country": "India",
            "model": "Section 112A style LTCG on equity",
            "ltcg_exemption": INDIA_LTCG_EXEMPTION,
            "ltcg_rate_pct": INDIA_LTCG_RATE * 100,
            "cess_rate_pct": INDIA_CESS_RATE * 100,
        }

    return {
        "pretax_fire_number": round(pretax_fire_number, 2),
        "tax_adjusted_fire_number": round(tax_adjusted_fire_number, 2),
        "projected_balance": round(final_balance, 2),
        "reaches_fire_by_retirement": reaches_fire_by_retirement,
        "fire_hit_age": fire_hit_age,
        "years_until_retirement": years,
        "months_until_fire": fire_hit_month,
        "coast_needed_today": round(coast_needed_today, 2),
        "gross_withdrawal_needed": round(gross_needed, 2),
        "estimated_tax_on_needed_withdrawal": round(tax_details_needed["total_tax"], 2),
        "net_spending_from_rule_at_retirement": round(net_by_rule, 2),
        "projected_gain_ratio_pct": round(gain_ratio_retirement * 100, 2),
        "tax_config": tax_config,
    }


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload, code=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, filepath, content_type="text/plain"):
        if not filepath.exists() or not filepath.is_file():
            self.send_error(404)
            return

        body = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/":
            return self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        if path == "/styles.css":
            return self._send_file(STATIC_DIR / "styles.css", "text/css; charset=utf-8")
        if path == "/app.js":
            return self._send_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")

        self.send_error(404)

    def do_POST(self):
        if urlparse(self.path).path != "/api/calculate":
            self.send_error(404)
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length)

        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON"}, 400)
            return

        current_age = parse_int(payload, "currentAge", 25)
        retirement_age = parse_int(payload, "retirementAge", 60)
        current_savings = parse_float(payload, "currentSavings", 0)
        current_cost_basis = parse_float(payload, "currentCostBasis", current_savings)
        monthly_contribution = parse_float(payload, "monthlyContribution", 0)
        annual_return = parse_float(payload, "annualReturn", 7) / 100
        annual_spending = parse_float(payload, "annualSpending", 40000)
        withdrawal_rate = parse_float(payload, "withdrawalRate", 4) / 100
        use_coast = bool(payload.get("useCoast", False))
        coast_age = parse_int(payload, "coastAge", current_age)

        tax_country = parse_text(payload, "taxCountry", "India").strip().upper()
        tax_country = "US" if tax_country == "US" else "India"

        us_filing_status = parse_text(payload, "usFilingStatus", "single").strip().lower()
        if us_filing_status not in US_LTCG_THRESHOLDS_2025:
            us_filing_status = "single"
        us_other_taxable_income = parse_float(payload, "usOtherTaxableIncome", 0)

        if retirement_age <= current_age:
            self._send_json({"error": "Retirement age must be greater than current age."}, 400)
            return

        if use_coast and coast_age < current_age:
            self._send_json({"error": "Coast age must be at least your current age."}, 400)
            return

        if withdrawal_rate <= 0:
            self._send_json({"error": "Withdrawal rate must be greater than 0."}, 400)
            return

        if annual_spending < 0 or current_savings < 0 or monthly_contribution < 0 or current_cost_basis < 0:
            self._send_json({"error": "Values cannot be negative."}, 400)
            return

        if us_other_taxable_income < 0:
            self._send_json({"error": "US other taxable income cannot be negative."}, 400)
            return

        result = calculate_projection(
            current_age=current_age,
            retirement_age=retirement_age,
            current_savings=current_savings,
            current_cost_basis=current_cost_basis,
            monthly_contribution=monthly_contribution,
            annual_return=annual_return,
            annual_spending=annual_spending,
            withdrawal_rate=withdrawal_rate,
            use_coast=use_coast,
            coast_age=coast_age,
            tax_country=tax_country,
            us_filing_status=us_filing_status,
            us_other_taxable_income=us_other_taxable_income,
        )

        self._send_json(result)


def run():
    host = "127.0.0.1"
    port = 8000
    server = HTTPServer((host, port), Handler)
    print(f"FIRE calculator running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
