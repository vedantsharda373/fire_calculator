const form = document.getElementById('fire-form');
const results = document.getElementById('results');
const useCoast = document.getElementById('useCoast');
const coastAgeWrap = document.getElementById('coastAgeWrap');
const useUSD = document.getElementById('useUSD');
const useUSTax = document.getElementById('useUSTax');
const darkMode = document.getElementById('darkMode');
const usTaxFields = document.getElementById('usTaxFields');
const currencyLabel = document.getElementById('currencyLabel');
const taxCountryLabel = document.getElementById('taxCountryLabel');

function currentCurrencyCode() {
  return useUSD.checked ? 'USD' : 'INR';
}

function currentCurrencySymbol() {
  return useUSD.checked ? '$' : '₹';
}

function money(value) {
  const code = currentCurrencyCode();
  const locale = code === 'USD' ? 'en-US' : 'en-IN';
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency: code,
    maximumFractionDigits: 0
  }).format(value);
}

function syncCurrencyLabels() {
  const symbol = currentCurrencySymbol();
  const code = currentCurrencyCode();
  document.querySelectorAll('.money-unit').forEach((node) => {
    node.textContent = `(${symbol})`;
  });
  currencyLabel.textContent = `${code} (${symbol})`;
}

function syncTaxCountry() {
  const country = useUSTax.checked ? 'US' : 'India';
  taxCountryLabel.textContent = country;
  usTaxFields.classList.toggle('hidden', !useUSTax.checked);
}

function setCoastVisibility() {
  coastAgeWrap.classList.toggle('hidden', !useCoast.checked);
}

function syncTheme() {
  document.body.classList.toggle('dark', darkMode.checked);
  localStorage.setItem('fireDarkMode', darkMode.checked ? '1' : '0');
}

function loadTheme() {
  const stored = localStorage.getItem('fireDarkMode');
  if (stored === '1') {
    darkMode.checked = true;
    document.body.classList.add('dark');
  }
}

useCoast.addEventListener('change', setCoastVisibility);
useUSD.addEventListener('change', syncCurrencyLabels);
useUSTax.addEventListener('change', syncTaxCountry);
darkMode.addEventListener('change', syncTheme);

setCoastVisibility();
loadTheme();
syncCurrencyLabels();
syncTaxCountry();

form.addEventListener('submit', async (e) => {
  e.preventDefault();

  const payload = {
    currentAge: Number(document.getElementById('currentAge').value),
    retirementAge: Number(document.getElementById('retirementAge').value),
    currentSavings: Number(document.getElementById('currentSavings').value),
    currentCostBasis: Number(document.getElementById('currentCostBasis').value),
    monthlyContribution: Number(document.getElementById('monthlyContribution').value),
    annualReturn: Number(document.getElementById('annualReturn').value),
    annualSpending: Number(document.getElementById('annualSpending').value),
    withdrawalRate: Number(document.getElementById('withdrawalRate').value),
    useCoast: useCoast.checked,
    coastAge: Number(document.getElementById('coastAge').value),
    taxCountry: useUSTax.checked ? 'US' : 'India',
    usFilingStatus: document.getElementById('usFilingStatus').value,
    usOtherTaxableIncome: Number(document.getElementById('usOtherTaxableIncome').value),
    inputCurrency: currentCurrencyCode()
  };

  try {
    const res = await fetch('/api/calculate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    let data = null;
    try {
      data = await res.json();
    } catch {
      data = null;
    }

    if (!res.ok) {
      results.classList.remove('hidden');
      const serverMessage = data && data.error ? data.error : `Server error (${res.status})`;
      results.innerHTML = `<p>${serverMessage}</p>`;
      return;
    }

    const reachedText = data.reaches_fire_by_retirement ? 'Yes' : 'No';
    const fireAgeText = data.fire_hit_age !== null ? data.fire_hit_age : 'Not reached before retirement';

    let taxNote = '';
    if (data.tax_config.country === 'US') {
      taxNote = `Tax model: ${data.tax_config.model}. Filing status: ${data.tax_config.filing_status.replace('_', ' ')}. Other taxable income assumed: ${money(data.tax_config.other_taxable_income)}. Federal LTCG thresholds based on ${data.tax_config.threshold_reference_year}.`;
    } else {
      taxNote = `Tax model: ${data.tax_config.model} (${money(data.tax_config.ltcg_exemption)} exemption, ${data.tax_config.ltcg_rate_pct}% tax + ${data.tax_config.cess_rate_pct}% cess).`;
    }

    results.classList.remove('hidden');
    results.innerHTML = `
      <div class="result-grid">
        <div class="result-box">
          <div class="result-label">Tax-adjusted FIRE number</div>
          <div class="result-value">${money(data.tax_adjusted_fire_number)}</div>
        </div>
        <div class="result-box">
          <div class="result-label">Pre-tax FIRE number</div>
          <div class="result-value">${money(data.pretax_fire_number)}</div>
        </div>
        <div class="result-box">
          <div class="result-label">Projected portfolio at retirement</div>
          <div class="result-value">${money(data.projected_balance)}</div>
        </div>
        <div class="result-box">
          <div class="result-label">FIRE reached by retirement</div>
          <div class="result-value">${reachedText}</div>
        </div>
        <div class="result-box">
          <div class="result-label">Estimated FIRE age</div>
          <div class="result-value">${fireAgeText}</div>
        </div>
        <div class="result-box">
          <div class="result-label">Coast amount needed today</div>
          <div class="result-value">${money(data.coast_needed_today)}</div>
        </div>
        <div class="result-box">
          <div class="result-label">Gross withdrawal needed / year</div>
          <div class="result-value">${money(data.gross_withdrawal_needed)}</div>
        </div>
        <div class="result-box">
          <div class="result-label">Estimated tax on that withdrawal</div>
          <div class="result-value">${money(data.estimated_tax_on_needed_withdrawal)}</div>
        </div>
        <div class="result-box">
          <div class="result-label">Net yearly spend from your rule at retirement</div>
          <div class="result-value">${money(data.net_spending_from_rule_at_retirement)}</div>
        </div>
        <div class="result-box">
          <div class="result-label">Projected gain ratio at retirement</div>
          <div class="result-value">${data.projected_gain_ratio_pct}%</div>
        </div>
      </div>
      <div class="note">${taxNote}</div>
    `;
  } catch {
    results.classList.remove('hidden');
    results.innerHTML = '<p>Could not connect to backend. Start the Python server and open the app through http://127.0.0.1:8000</p>';
  }
});
