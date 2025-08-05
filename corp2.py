import streamlit as st
import pandas as pd
import datetime
from fredapi import Fred
import altair as alt
from prophet import Prophet

# --- CONFIGURATION ---
st.set_page_config(
    page_title="Treasury Yield & NII Dashboard",
    page_icon="📊",
    layout="wide"
)

# --- FRED API SETUP ---
fred = Fred(api_key="a81fe200758f77f57e2e93b0324eea9b")
yield_codes  = ['GS3M','GS1','GS5','GS10']
yield_labels = {'GS3M':'3M','GS1':'1Y','GS5':'5Y','GS10':'10Y'}

@st.cache_data(ttl=3600)
def get_latest_yields(codes):
    latest = {}
    for code in codes:
        val = fred.get_series_latest_release(code).iloc[-1]
        latest[code] = float(val) / 100
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
start_date     = datetime.date.today() - datetime.timedelta(days=5*365)
historical     = get_historical(yield_codes, start_date)
yields_current = get_latest_yields(yield_codes)

# --- SIDEBAR CONTROLS ---
st.sidebar.header("⚙️ Scenario & Regulatory Presets")

# Custom rate shift
bps_shift = st.sidebar.slider("Custom Rate Shift (bps)", -300, 300, 0, step=25) / 10000

# Regulatory preset definitions
reg_preset = {
    'Parallel +200 bp':       { 'all': 0.02 },
    'Curve Twist':            {'3M':0.02,'1Y':0.01,'5Y':-0.01,'10Y':-0.02},
    'Steepener':              {'3M':-0.01,'1Y':0.0,'5Y':0.01,'10Y':0.02},
    'Flattener':              {'3M':0.01,'1Y':0.02,'5Y':-0.01,'10Y':-0.02}
}
reg_choice = st.sidebar.radio("Regulatory Stress Scenario", list(reg_preset.keys()))

# Combined scenario selector
scenario_options = ['Custom'] + list(reg_preset.keys())
scenario = st.sidebar.selectbox("Select Scenario", scenario_options)

# Build shift map
if scenario == 'Custom':
    shifts = {c: yields_current[c] + bps_shift for c in yield_codes}
else:
    shock = reg_preset[scenario]
    shifts = {}
    for c in yield_codes:
        if 'all' in shock:
            shifts[c] = yields_current[c] + shock['all']
        else:
            shifts[c] = yields_current[c] + shock.get(yield_labels[c], 0)

# Display current yields
st.sidebar.header("📈 Current Treasury Yields")
for c, lbl in yield_labels.items():
    st.sidebar.metric(lbl, f"{yields_current[c]*100:.2f}%")

# Balance sheet inputs ($M)
st.sidebar.header("💼 Balance Sheet Inputs")
cash     = st.sidebar.number_input("Cash Reserves (3M)",    0.0, 1000.0, 40.0)
deposits = st.sidebar.number_input("Deposits (1Y)",         0.0, 1000.0, 130.0)
loans    = st.sidebar.number_input("Loans (5Y)",            0.0, 1000.0, 120.0)
bonds    = st.sidebar.number_input("Bonds (10Y)",           0.0, 1000.0, 80.0)

# Build assets & liabilities
assets = pd.DataFrame([
    {'Type':'Cash',  'Balance':cash,  'Code':'GS3M'},
    {'Type':'Loans', 'Balance':loans, 'Code':'GS5'},
    {'Type':'Bonds', 'Balance':bonds, 'Code':'GS10'}
])
liabilities = pd.DataFrame([
    {'Type':'Deposits','Balance':deposits,'Code':'GS1'}
])

# Helper to compute Income/Expense
def calculate(df, yield_map, field):
    out = df.copy()
    out['Rate'] = out['Code'].map(lambda c: yield_map.get(c,0)*100)
    out[field] = out['Balance'] * out['Rate'] / 100
    return out

# Compute NII for base and shifted
base_inc = calculate(assets, yields_current, 'Income')['Income'].sum()
base_exp = calculate(liabilities, yields_current, 'Expense').get('Expense', pd.Series(0)).sum()
base_nii = base_inc - base_exp

shift_inc = calculate(assets, shifts, 'Income')['Income'].sum()
shift_exp = calculate(liabilities, shifts, 'Expense').get('Expense', pd.Series(0)).sum()
shift_nii = shift_inc - shift_exp

# --- MAIN LAYOUT ---
st.title("📊 Treasury Yield & NII Dashboard")
st.markdown(f"**Scenario:** {scenario} &nbsp;|&nbsp; **Regulatory:** {reg_choice}")

# Key metrics
m1, m2 = st.columns(2)
m1.metric("Baseline NII ($M)", f"${base_nii:.2f}")
m2.metric("Shifted NII ($M)",  f"${shift_nii:.2f}")

# --- Regulatory Stress Comparison ---
st.subheader("🏦 NII under All Regulatory Scenarios")
reg_results = []
for name, shock in reg_preset.items():
    # build yields map
    ym = {}
    for c in yield_codes:
        if 'all' in shock:
            ym[c] = yields_current[c] + shock['all']
        else:
            ym[c] = yields_current[c] + shock.get(yield_labels[c], 0)
    inc = calculate(assets, ym, 'Income')['Income'].sum()
    exp = calculate(liabilities, ym, 'Expense').get('Expense', pd.Series(0)).sum()
    reg_results.append({'Scenario':name, 'NII ($M)':round(inc-exp,2)})
reg_df = pd.DataFrame(reg_results)

col_bar, col_tbl = st.columns([2,1])
with col_bar:
    bar = alt.Chart(reg_df).mark_bar().encode(
        x='Scenario:N',
        y='NII ($M):Q',
        color=alt.condition(alt.datum['NII ($M)'] > 0, alt.value('green'), alt.value('red')),
        tooltip=['Scenario','NII ($M)']
    ).properties(width=600, height=300)
    st.altair_chart(bar, use_container_width=True)
with col_tbl:
    st.table(reg_df.set_index('Scenario'))

# --- Historical Yields Chart ---
st.subheader("📈 Historical Treasury Yields (5Y)")
df_hist = historical.reset_index().rename(columns={'index':'Date'})
df_long = df_hist.melt(id_vars='Date', var_name='Maturity', value_name='Yield')
line = alt.Chart(df_long).mark_line().encode(
    x='Date:T',
    y=alt.Y('Yield:Q', title='Yield (%)'),
    color='Maturity:N',
    tooltip=['Date:T','Maturity:N','Yield:Q']
).interactive().properties(width=900, height=400)
st.altair_chart(line, use_container_width=True)

# --- NII Waterfall for Selected Scenario ---
st.subheader(f"📉 NII Waterfall: {scenario}")
# compute net balances per tenor
net_bal = {
    c: assets.loc[assets.Code==c,'Balance'].sum() - liabilities.loc[liabilities.Code==c,'Balance'].sum()
    for c in yield_codes
}
wf = []
cum=0
wf.append({'Maturity':'Baseline','Start':0,'End':0,'ΔNII':0})
for c in yield_codes:
    delta = net_bal[c] * (shifts[c] - yields_current[c])
    wf.append({'Maturity':yield_labels[c],'Start':cum,'End':cum+delta,'ΔNII':round(delta,2)})
    cum += delta
wf.append({'Maturity':'Total','Start':0,'End':cum,'ΔNII':round(cum,2)})
wf_df = pd.DataFrame(wf)

wc = alt.Chart(wf_df).mark_bar().encode(
    x='Maturity:N',
    y='End:Q',
    y2='Start:Q',
    color=alt.Color('ΔNII:Q', scale=alt.Scale(domain=[wf_df['ΔNII'].min(),0,wf_df['ΔNII'].max()],
                                                range=['red','lightgray','green'])),
    tooltip=['Maturity','ΔNII']
).properties(width=800, height=400)
st.altair_chart(wc, use_container_width=True)

st.markdown("---")
st.caption("© 2025 Treasury Analytics | Powered by FRED & Streamlit")
