import streamlit as st
import pandas as pd
import datetime
from fredapi import Fred
import altair as alt

# --- CONFIGURATION ---
st.set_page_config(
    page_title="NII Stress Test Dashboard",
    page_icon="📊",
    layout="wide"
)

# --- FRED SETUP ---
fred = Fred(api_key="a81fe200758f77f57e2e93b0324eea9b")
yield_codes  = ['GS3M','GS1','GS5','GS10']
yield_labels = {'GS3M':'3M','GS1':'1Y','GS5':'5Y','GS10':'10Y'}

@st.cache_data(ttl=3600)
def get_latest_yields(codes):
    latest = {}
    for code in codes:
        latest[code] = float(fred.get_series_latest_release(code).iloc[-1]) / 100
    return latest

@st.cache_data(ttl=3600)
def get_historical(codes, start_date):
    df = pd.DataFrame()
    for code in codes:
        series = fred.get_series(code, start_date) / 100
        df[yield_labels[code]] = series
    df.index = pd.to_datetime(df.index)
    return df

# --- LOAD DATA ---
yields_current = get_latest_yields(yield_codes)

# --- SIDEBAR: Rate‐Shock Inputs ---
st.sidebar.header("⚙️ Rate‐Shock Inputs")
bps_shift = st.sidebar.slider("Custom Rate Shift (bps)", -300, 300, 0, step=25) / 10000
preset = {
    'Baseline (0 bp)':                0.00,
    'Adverse (-100 bp)':             -0.01,
    'Severely Adverse (-250 bp)':    -0.025,
    'Rate Hike Shock (+100 bp)':      0.01,
    'Extreme Hike (+200 bp)':         0.02
}
scenario_name = st.sidebar.selectbox(
    "Choose Rate‐Shock Scenario",
    ['Custom'] + list(preset.keys())
)
base_shift = (bps_shift if scenario_name == 'Custom'
              else preset[scenario_name])

# --- SIDEBAR: Regulatory CCAR/ICAAP ---
st.sidebar.header("⚖️ Regulatory Stress Scenario")
macro_scenarios = {
    "Baseline": {
        "shifts": {c: 0.00 for c in yield_codes},
        "desc": ["No stress; consensus forecasts"]
    },
    "Adverse": {
        "shifts": {c: -0.01 for c in yield_codes},
        "desc": ["Moderate recession", "Rising risk premia"]
    },
    "Severely Adverse": {
        "shifts": {c: -0.025 for c in yield_codes},
        "desc": [
            "Severe global recession",
            "10%+ unemployment",
            "Sharp declines in asset prices",
            "Stress in corporate credit & real estate"
        ]
    }
}
macro_choice = st.sidebar.selectbox(
    "Pick CCAR/ICAAP Scenario",
    list(macro_scenarios.keys())
)

# apply flat or regulatory shifts
if macro_choice == "Baseline":
    shifts_map = {c: base_shift for c in yield_codes}
else:
    shifts_map = macro_scenarios[macro_choice]["shifts"]

with st.sidebar.expander("Scenario Assumptions", expanded=False):
    for line in macro_scenarios[macro_choice]["desc"]:
        st.write("• " + line)

# --- Sidebar: show live yields ---
st.sidebar.header("📈 Current Yields")
for code,label in yield_labels.items():
    st.sidebar.metric(label, f"{yields_current[code]*100:.2f}%")

# --- Balance Sheet Inputs ---
st.sidebar.header("💼 Balance Sheet ($M)")
loans    = st.sidebar.number_input("Loans (5Y)",        0,1000,120)
bonds    = st.sidebar.number_input("Bonds (10Y)",       0,1000,80)
cash     = st.sidebar.number_input("Cash (3M)",         0,1000,40)
deposits = st.sidebar.number_input("Deposits (1Y)",     0,1000,130)
borrow   = st.sidebar.number_input("Short Borrow (3M)", 0,1000,40)
corp     = st.sidebar.number_input("Corp Bonds (3M)",   0,1000,20)

# --- BUILD BALANCE SHEETS ---
assets = pd.DataFrame([
    {'Type':'Loans', 'Balance': loans,    'Code':'GS5'},
    {'Type':'Bonds', 'Balance': bonds,    'Code':'GS10'},
    {'Type':'Cash',  'Balance': cash,     'Code':'GS3M'}
])
liabs = pd.DataFrame([
    {'Type':'Deposits',    'Balance': deposits, 'Code':'GS1'},
    {'Type':'Short Borrow','Balance': borrow,   'Code':'GS3M'},
    {'Type':'Corp Bonds',  'Balance': corp,     'Code':'GS3M'}
])

def calc(sheet, yields_map, fld):
    df = sheet.copy()
    df['Rate (%)'] = df['Code'].map(lambda c: yields_map[c]*100)
    df[fld]       = df['Balance'] * df['Rate (%)'] / 100
    return df

# apply the shifts_map
shifted = {c: yields_current[c] + shifts_map[c] for c in yield_codes}

a_calc = calc(assets, shifted, 'Income')
l_calc = calc(liabs,  shifted, 'Expense')
nii    = a_calc['Income'].sum() - l_calc['Expense'].sum()

# --- MAIN LAYOUT ---
st.title("📊 NII Stress Test Dashboard")
st.markdown(
    f"**Rate‐Shock:** {scenario_name} | "
    f"**Regulatory:** {macro_choice}"
)

# Top metrics
c1,c2,c3 = st.columns(3)
c1.metric("Total Assets",     f"${assets['Balance'].sum():.2f}M")
c2.metric("Total Liabilities",f"${liabs['Balance'].sum():.2f}M")
c3.metric("Stressed NII",     f"${nii:.2f}M")

with st.expander("Asset Details", True):
    st.dataframe(a_calc)
with st.expander("Liability Details", True):
    st.dataframe(l_calc)

# --- Rate‐Shock Outcomes Chart ---
st.subheader("📉 Rate‐Shock Outcomes")
rs = []
for name, bp in preset.items():
    m = {c: yields_current[c] + bp for c in yield_codes}
    ni = calc(assets,m,'Income')['Income'].sum() - calc(liabs,m,'Expense')['Expense'].sum()
    rs.append({'Scenario': name, 'NII': round(ni,2)})
df_rs = pd.DataFrame(rs)
chart_rs = alt.Chart(df_rs).mark_bar().encode(
    x='Scenario', y='NII',
    color=alt.condition(alt.datum.NII>0, alt.value('green'), alt.value('red'))
)
st.altair_chart(chart_rs, use_container_width=True)

# --- Regulatory Stress Outcomes Chart ---
st.subheader("📉 Regulatory Stress Outcomes")
ms = []
for name, info in macro_scenarios.items():
    m = {c: yields_current[c] + info['shifts'][c] for c in yield_codes}
    ni = calc(assets,m,'Income')['Income'].sum() - calc(liabs,m,'Expense')['Expense'].sum()
    ms.append({'Scenario': name, 'NII': round(ni,2)})
df_ms = pd.DataFrame(ms)
chart_ms = alt.Chart(df_ms).mark_bar().encode(
    x='Scenario', y='NII',
    color=alt.condition(alt.datum.NII>0, alt.value('green'), alt.value('red'))
)
st.altair_chart(chart_ms, use_container_width=True)

# --- Historical Yields Plot ---
st.subheader("📈 Historical Yields (5 Years)")
hist = get_historical(yield_codes, datetime.date.today() - datetime.timedelta(days=5*365))
df_hist = hist.reset_index().rename(columns={'index':'Date'})
line = alt.Chart(df_hist).transform_fold(
    list(hist.columns),
    as_=['Maturity','Yield']
).mark_line().encode(
    x=alt.X('Date:T', title='Date'),
    y=alt.Y('Yield:Q', title='Yield'),
    color=alt.Color('Maturity:N', title='Maturity'),
    tooltip=[alt.Tooltip('Date:T'), alt.Tooltip('Maturity:N'), alt.Tooltip('Yield:Q')]
).interactive().properties(width=800, height=400)
st.altair_chart(line, use_container_width=True)

# --- NII Waterfall ---
st.subheader(f"📉 NII Waterfall: {scenario_name} / {macro_choice}")
balances = {'3M': cash, '1Y': deposits, '5Y': loans, '10Y': bonds}

# compute deltas
deltas = []
base_nii = 0.0
strs_nii = 0.0
for code,label in yield_labels.items():
    bal = balances[label]
    r0  = yields_current[code]
    r1  = shifted[code]
    i0  = bal * r0
    i1  = bal * r1
    delta = i1 - i0
    deltas.append({'Maturity': label, 'ΔNII': round(delta, 2)})
    base_nii += i0
    strs_nii += i1

wf = pd.DataFrame([{'Maturity':'Baseline','ΔNII':0}] + deltas +
                  [{'Maturity':'Total','ΔNII': round(strs_nii - base_nii, 2)}])
wf['Start'] = wf['ΔNII'].cumsum().shift(fill_value=0)
wf['End']   = wf['Start'] + wf['ΔNII']

colors = alt.Scale(domain=[wf['ΔNII'].min(), 0, wf['ΔNII'].max()],
                   range=['red','lightgray','green'])
waterfall = alt.Chart(wf).mark_bar().encode(
    x=alt.X('Maturity:N', title=None),
    y=alt.Y('End:Q', title='Cumulative NII Change'),
    y2='Start:Q',
    color=alt.Color('ΔNII:Q', scale=colors, title='ΔNII'),
    tooltip=['Maturity','ΔNII']
).properties(width=800)
st.altair_chart(waterfall, use_container_width=True)

st.markdown("---")
st.caption("© 2025 NII Dashboard | Powered by FRED")
