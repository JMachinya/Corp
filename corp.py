import streamlit as st
import pandas as pd
import datetime
from fredapi import Fred
import altair as alt
from prophet import Prophet

# --- CONFIGURATION ---
st.set_page_config(
    page_title="NII Stress Test Dashboard",
    page_icon="📊",
    layout="wide"
)

# --- FRED SETUP ---
fred = Fred(api_key="a81fe200758f77f57e2e93b0324eea9b")
yield_codes = ['GS3M','GS1','GS5','GS10']
yield_labels = {'GS3M':'3M','GS1':'1Y','GS5':'5Y','GS10':'10Y'}

@st.cache_data(ttl=3600)
def get_latest_yields(codes):
    latest = {}
    for code in codes:
        value = fred.get_series_latest_release(code).iloc[-1]
        latest[code] = float(value) / 100  # decimal
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

# --- SIDEBAR CONTROLS ---
st.sidebar.header("⚙️ Scenario Inputs")
bps_shift = st.sidebar.slider("Custom Rate Shift (bps)", -300, 300, 0, step=25) / 10000
preset = {
    'Baseline (0 bp)': 0,
    'Adverse (-100 bp)': -0.01,
    'Severely Adverse (-250 bp)': -0.025,
    'Rate Hike Shock (+100 bp)': 0.01,
    'Extreme Hike (+200 bp)': 0.02
}
scenario_name = st.sidebar.selectbox("Choose Scenario", ['Custom'] + list(preset.keys()))
shift = bps_shift if scenario_name == 'Custom' else preset[scenario_name]

st.sidebar.header("📈 Current Treasury Yields")
for code,label in yield_labels.items():
    rate = yields_current.get(code,0)
    st.sidebar.metric(label, f"{rate*100:.2f}%")

# Forecast settings
st.sidebar.header("🔮 Forecast Settings")
maturity = st.sidebar.selectbox("Select Maturity for Forecast", list(yield_labels.values()))
horizon_days = st.sidebar.slider("Forecast Horizon (days)", 30, 365, 90, step=30)

st.sidebar.header("💼 Balance Sheet ($M)")
loans   = st.sidebar.number_input("Loans (5Y)",0,1000,120)
bonds   = st.sidebar.number_input("Bonds (10Y)",0,1000,80)
cash    = st.sidebar.number_input("Cash (3M)",0,1000,40)
deposits= st.sidebar.number_input("Deposits (1Y)",0,1000,130)
borrow  = st.sidebar.number_input("Short Borrow (3M)",0,1000,40)
corp    = st.sidebar.number_input("Corp Bonds (3M)",0,1000,20)

# --- BUILD BALANCE SHEETS ---
assets = pd.DataFrame([
    {'Type':'Loans','Balance':loans,'Code':'GS5'},
    {'Type':'Bonds','Balance':bonds,'Code':'GS10'},
    {'Type':'Cash','Balance':cash,'Code':'GS3M'}
])
liabilities = pd.DataFrame([
    {'Type':'Deposits','Balance':deposits,'Code':'GS1'},
    {'Type':'Short Borrow','Balance':borrow,'Code':'GS3M'},
    {'Type':'Corp Bonds','Balance':corp,'Code':'GS3M'}
])

def calculate(sheet,ylds,field):
    df=sheet.copy()
    df['Rate (%)']=df['Code'].map(lambda c: ylds.get(c,0)*100)
    df[field]=(df['Balance']*df['Rate (%)'])/100
    return df

shifted = {c: r+shift for c,r in yields_current.items()}
a_calc = calculate(assets,shifted,'Income')
l_calc = calculate(liabilities,shifted,'Expense')
ii = a_calc['Income'].sum() - l_calc['Expense'].sum()

# --- MAIN ---
st.title("📊 Net Interest Income & Yield Forecast Dashboard")
st.markdown(f"**Scenario:** {scenario_name} | **Shift:** {shift*100:.1f} bps | **Forecast:** {maturity} +{horizon_days}d")

# Metrics
c1,c2,c3 = st.columns(3)
c1.metric("Assets","${:.2f}M".format(assets['Balance'].sum()))
c2.metric("Liabilities","${:.2f}M".format(liabilities['Balance'].sum()))
c3.metric("Resulting NII","${:.2f}M".format(ii))

# Tables
with st.expander("Asset Details",True): st.dataframe(a_calc)
with st.expander("Liability Details",True): st.dataframe(l_calc)

# Scenario chart
st.subheader("📉 Scenario Outcomes")
sc_df=[]
for n,v in preset.items():
    sy={c:r+v for c,r in yields_current.items()}
    ni=calculate(assets,sy,'Income')['Income'].sum()-calculate(liabilities,sy,'Expense')['Expense'].sum()
    sc_df.append({'Scenario':n,'NII':round(ni,2)})
sc_df=pd.DataFrame(sc_df)
chart=alt.Chart(sc_df).mark_bar().encode(x='Scenario',y='NII',color=alt.condition(alt.datum.NII>0,alt.value('green'),alt.value('red')))
st.altair_chart(chart,use_container_width=True)

# Historical trends
st.subheader("📈 Historical Yields (5Y)")
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

# --- Compute & Plot NII Waterfall ---
st.subheader(f"📉 NII Waterfall: {scenario_name}")

# 1) Build per‐tenor ΔNII
deltas = []
baseline_nii = 0.0
stressed_nii = 0.0
for code, label in yield_labels.items():
    bal = balances[label]           # your sidebar input
    r0  = current[code]             # baseline decimal yield
    r1  = r0 + shift                # shocked decimal yield
    i0  = bal * r0
    i1  = bal * r1
    delta = i1 - i0
    deltas.append({'Maturity': label, 'ΔNII': round(delta, 2)})
    baseline_nii += i0
    stressed_nii += i1

# 2) Assemble waterfall DataFrame
wf = pd.DataFrame([{'Maturity':'Baseline','ΔNII':0}] + deltas +
                  [{'Maturity':'Total','ΔNII': round(stressed_nii - baseline_nii, 2)}])
wf['Start'] = wf['ΔNII'].cumsum().shift(fill_value=0)
wf['End']   = wf['Start'] + wf['ΔNII']

# 3) Render with Altair
colors = alt.Scale(domain=[wf['ΔNII'].min(), 0, wf['ΔNII'].max()],
                   range=['red','lightgray','green'])
waterfall = alt.Chart(wf).mark_bar().encode(
    x=alt.X('Maturity:N', title=None),
    y=alt.Y('End:Q', title='Cumulative NII Change'),
    y2='Start:Q',
    color=alt.Color('ΔNII:Q', scale=colors, title='ΔNII'),
    tooltip=['Maturity','ΔNII']
).properties(width=600)

st.altair_chart(waterfall, use_container_width=True)

# Export
st.sidebar.header("Export")
st.sidebar.download_button("Download Scenarios CSV", pd.DataFrame(sc_df).to_csv(index=False), file_name='scenarios.csv', key='scenarios_csv2')

st.markdown("---")
st.caption("© 2025 NII Dashboard | Powered by FRED")
