import streamlit as st
import pandas as pd
import numpy as np
import datetime
from fredapi import Fred
import altair as alt

# --- CONFIGURATION ---
st.set_page_config(
    page_title="NII Stress Test & Regulatory Projections",
    page_icon="📊",
    layout="wide"
)

# --- FRED SETUP & HELPERS ---
fred = Fred(api_key="a81fe200758f77f57e2e93b0324eea9b")
yield_codes  = ['GS3M','GS1','GS5','GS10']
yield_labels = {'GS3M':'3M','GS1':'1Y','GS5':'5Y','GS10':'10Y'}

@st.cache_data(ttl=3600)
def get_latest_yields(codes):
    return {c: float(fred.get_series_latest_release(c).iloc[-1]) / 100 for c in codes}

@st.cache_data(ttl=3600)
def get_historical(codes, start_date):
    df = pd.DataFrame()
    for c in codes:
        df[yield_labels[c]] = fred.get_series(c, start_date) / 100
    df.index = pd.to_datetime(df.index)
    return df

# load live yields once
yields_current = get_latest_yields(yield_codes)

# common presets
preset = {
    'Baseline (0 bp)':             0.00,
    'Adverse (-100 bp)':          -0.01,
    'Severely Adverse (-250 bp)': -0.025,
    'Rate Hike Shock (+100 bp)':   0.01,
    'Extreme Hike (+200 bp)':      0.02
}
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

# create two tabs
tab1, tab2 = st.tabs(["Stress‐Test Dashboard","CCAR / ICAAP Projections"])

# ----------------------------------------
# Tab 1: NII Stress‐Test & P&L Explain
# ----------------------------------------
with tab1:
    # --- SIDEBAR: Rate‐Shock Inputs ---
    st.sidebar.header("⚙️ Rate‐Shock Inputs")
    bps_shift = st.sidebar.slider("Custom Rate Shift (bps)", -300, 300, 0, step=25) / 10000
    scenario_name = st.sidebar.selectbox(
        "Choose Rate‐Shock Scenario",
        ['Custom'] + list(preset.keys())
    )
    base_shift = bps_shift if scenario_name=='Custom' else preset[scenario_name]

    # --- SIDEBAR: Regulatory CCAR/ICAAP ---
    st.sidebar.header("⚖️ Regulatory Stress Scenario")
    macro_choice = st.sidebar.selectbox("Pick CCAR/ICAAP Scenario", list(macro_scenarios.keys()))
    if macro_choice == "Baseline":
        shifts_map = {c: base_shift for c in yield_codes}
    else:
        shifts_map = macro_scenarios[macro_choice]["shifts"]

    with st.sidebar.expander("Scenario Assumptions", expanded=False):
        for line in macro_scenarios[macro_choice]["desc"]:
            st.write("• " + line)

    # --- SIDEBAR: Show Live Yields ---
    st.sidebar.header("📈 Current Yields")
    for code,label in yield_labels.items():
        st.sidebar.metric(label, f"{yields_current[code]*100:.2f}%")

    # --- SIDEBAR: Balance Sheet Inputs (Rate‐Shock) ---
    st.sidebar.header("💼 Balance Sheet ($M)")
    loans    = st.sidebar.number_input("Loans (5Y)",        0,1000,120)
    bonds    = st.sidebar.number_input("Bonds (10Y)",       0,1000,80)
    cash     = st.sidebar.number_input("Cash (3M)",         0,1000,40)
    deposits = st.sidebar.number_input("Deposits (1Y)",     0,1000,130)
    borrow   = st.sidebar.number_input("Short Borrow (3M)", 0,1000,40)
    corp     = st.sidebar.number_input("Corp Bonds (3M)",   0,1000,20)

    # --- SIDEBAR: P&L Explain Options ---
    st.sidebar.header("🔍 P&L Explain Options")
    default_end   = datetime.date.today()
    default_start = default_end - datetime.timedelta(days=30)
    start_date, end_date = st.sidebar.date_input(
        "Analysis Period", [default_start, default_end]
    )
    bu_choice = st.sidebar.selectbox("Business Unit", ["All","Corporate","Retail"])

    # Starting vs ending balances
    st.sidebar.header("💼 Starting Balances ($M)")
    loans_start    = st.sidebar.number_input("Start Loans (5Y)",        0,1000,100)
    bonds_start    = st.sidebar.number_input("Start Bonds (10Y)",       0,1000,70)
    cash_start     = st.sidebar.number_input("Start Cash (3M)",         0,1000,30)
    deposits_start = st.sidebar.number_input("Start Deposits (1Y)",     0,1000,110)
    borrow_start   = st.sidebar.number_input("Start Short Borrow (3M)", 0,1000,35)
    corp_start     = st.sidebar.number_input("Start Corp Bonds (3M)",   0,1000,15)

    st.sidebar.header("💼 Ending Balances ($M)")
    loans_end    = st.sidebar.number_input("End Loans (5Y)",        0,1000,120)
    bonds_end    = st.sidebar.number_input("End Bonds (10Y)",       0,1000,80)
    cash_end     = st.sidebar.number_input("End Cash (3M)",         0,1000,40)
    deposits_end = st.sidebar.number_input("End Deposits (1Y)",     0,1000,130)
    borrow_end   = st.sidebar.number_input("End Short Borrow (3M)", 0,1000,40)
    corp_end     = st.sidebar.number_input("End Corp Bonds (3M)",   0,1000,20)

    # --- BUILD RATE‐SHOCK & NII CALCS ---
    assets = pd.DataFrame([
        {'Type':'Loans','Balance':loans,'Code':'GS5'},
        {'Type':'Bonds','Balance':bonds,'Code':'GS10'},
        {'Type':'Cash', 'Balance':cash, 'Code':'GS3M'}
    ])
    liabs = pd.DataFrame([
        {'Type':'Deposits','Balance':deposits,'Code':'GS1'},
        {'Type':'Short Borrow','Balance':borrow,'Code':'GS3M'},
        {'Type':'Corp Bonds','Balance':corp,'Code':'GS3M'}
    ])
    def calc(sheet, yields_map, fld):
        df = sheet.copy()
        df['Rate(%)'] = df['Code'].map(lambda c: yields_map[c]*100)
        df[fld] = df['Balance'] * df['Rate(%)'] / 100
        return df

    shifted    = {c: yields_current[c] + shifts_map[c] for c in yield_codes}
    a_calc     = calc(assets, shifted, 'Income')
    l_calc     = calc(liabs,  shifted, 'Expense')
    stressed_nii = a_calc['Income'].sum() - l_calc['Expense'].sum()

    # --- MAIN LAYOUT ---
    st.title("📊 NII Stress Test & P&L Explain")
    st.markdown(f"**Rate‐Shock:** {scenario_name} | **Regulatory:** {macro_choice}")

    # top metrics
    c1,c2,c3 = st.columns(3)
    c1.metric("Total Assets",      f"${assets['Balance'].sum():.2f}M")
    c2.metric("Total Liabilities", f"${liabs['Balance'].sum():.2f}M")
    c3.metric("Stressed NII",      f"${stressed_nii:.2f}M")

    with st.expander("Asset Details", True):
        st.dataframe(a_calc)
    with st.expander("Liability Details", True):
        st.dataframe(l_calc)

    # Rate‐Shock Outcomes
    rs = []
    for name,bp in preset.items():
        m  = {c: yields_current[c] + bp for c in yield_codes}
        ni = calc(assets,m,'Income')['Income'].sum() - calc(liabs,m,'Expense')['Expense'].sum()
        rs.append({'Scenario':name,'NII':round(ni,2)})
    df_rs = pd.DataFrame(rs)
    chart_rs = alt.Chart(df_rs).mark_bar().encode(
        x='Scenario', y='NII',
        color=alt.condition(alt.datum.NII>0, alt.value('green'), alt.value('red'))
    )
    st.subheader("📉 Rate‐Shock Outcomes")
    st.altair_chart(chart_rs, use_container_width=True)

    # Regulatory Stress Outcomes
    ms = []
    for name,info in macro_scenarios.items():
        m  = {c: yields_current[c] + info['shifts'][c] for c in yield_codes}
        ni = calc(assets,m,'Income')['Income'].sum() - calc(liabs,m,'Expense')['Expense'].sum()
        ms.append({'Scenario':name,'NII':round(ni,2)})
    df_ms = pd.DataFrame(ms)
    chart_ms = alt.Chart(df_ms).mark_bar().encode(
        x='Scenario', y='NII',
        color=alt.condition(alt.datum.NII>0, alt.value('green'), alt.value('red'))
    )
    st.subheader("📉 Regulatory Stress Outcomes")
    st.altair_chart(chart_ms, use_container_width=True)

    # Historical Yields
    st.subheader("📈 Historical Yields (5 Years)")
    hist = get_historical(yield_codes, datetime.date.today() - datetime.timedelta(days=5*365))
    df_hist = hist.reset_index().rename(columns={'index':'Date'})
    line = alt.Chart(df_hist).transform_fold(
        list(hist.columns),
        as_=['Maturity','Yield']
    ).mark_line().encode(
        x=alt.X('Date:T',title='Date'),
        y=alt.Y('Yield:Q',title='Yield'),
        color='Maturity:N',
        tooltip=['Date:T','Maturity:N','Yield:Q']
    ).interactive()
    st.altair_chart(line, use_container_width=True)

    # NII Waterfall
    st.subheader("📉 NII Waterfall")
    balances = {'3M':cash,'1Y':deposits,'5Y':loans,'10Y':bonds}
    deltas, b0_sum, b1_sum = [], 0.0, 0.0
    for c,label in yield_labels.items():
        bal = balances[label]
        r0, r1 = yields_current[c], shifted[c]
        i0, i1 = bal*r0, bal*r1
        deltas.append({'Maturity':label,'ΔNII':round(i1-i0,2)})
        b0_sum += i0; b1_sum += i1
    wf1 = pd.DataFrame([{'Maturity':'Baseline','ΔNII':0}] + deltas + [{'Maturity':'Total','ΔNII':round(b1_sum-b0_sum,2)}])
    wf1['Start'] = wf1['ΔNII'].cumsum().shift(fill_value=0)
    wf1['End']   = wf1['Start'] + wf1['ΔNII']
    waterfall1 = alt.Chart(wf1).mark_bar().encode(
        x='Maturity:N', y='End:Q', y2='Start:Q',
        color=alt.condition(alt.datum.ΔNII>0, alt.value('green'), alt.value('red')),
        tooltip=['Maturity','ΔNII']
    )
    st.altair_chart(waterfall1, use_container_width=True)

    # P&L Explain Waterfall
    # build sheets
    bu_map = {'Loans':'Corporate','Bonds':'Corporate','Cash':'Corporate',
              'Deposits':'Retail','Short Borrow':'Corporate','Corp Bonds':'Corporate'}
    def make_sheet(b0,b1):
        return pd.DataFrame([
            {'Type':'Loans','B0':b0[0],'B1':b1[0],'Code':'GS5','BU':bu_map['Loans']},
            {'Type':'Bonds','B0':b0[1],'B1':b1[1],'Code':'GS10','BU':bu_map['Bonds']},
            {'Type':'Cash','B0':b0[2],'B1':b1[2],'Code':'GS3M','BU':bu_map['Cash']},
            {'Type':'Deposits','B0':b0[3],'B1':b1[3],'Code':'GS1','BU':bu_map['Deposits']},
            {'Type':'Short Borrow','B0':b0[4],'B1':b1[4],'Code':'GS3M','BU':bu_map['Short Borrow']},
            {'Type':'Corp Bonds','B0':b0[5],'B1':b1[5],'Code':'GS3M','BU':bu_map['Corp Bonds']}
        ])
    start_df = make_sheet(
        [loans_start,bonds_start,cash_start,deposits_start,borrow_start,corp_start],
        [loans_start,bonds_start,cash_start,deposits_start,borrow_start,corp_start]
    )
    end_df   = make_sheet(
        [loans_end,bonds_end,cash_end,deposits_end,borrow_end,corp_end],
        [loans_end,bonds_end,cash_end,deposits_end,borrow_end,corp_end]
    )
    if bu_choice != "All":
        start_df = start_df[start_df['BU']==bu_choice]
        end_df   = end_df[end_df['BU']==bu_choice]

    # get r0/r1 from historical
    hist2 = get_historical(yield_codes, start_date)
    hist2 = hist2[hist2.index <= pd.to_datetime(end_date)]
    fy, ly = hist2.iloc[0].to_dict(), hist2.iloc[-1].to_dict()
    r0_map = {c: fy[yield_labels[c]] for c in yield_codes}
    r1_map = {c: ly[yield_labels[c]] for c in yield_codes}

    a0 = start_df[start_df['Type'].isin(['Loans','Bonds','Cash'])]
    a1 = end_df[end_df['Type'].isin(['Loans','Bonds','Cash'])]
    l0 = start_df[start_df['Type'].isin(['Deposits','Short Borrow','Corp Bonds'])]
    l1 = end_df[end_df['Type'].isin(['Deposits','Short Borrow','Corp Bonds'])]

    # compute variances
    rate_var   = sum(a0['B0']*(r1_map[c]-r0_map[c]) for c in a0['Code']) \
               - sum(l0['B0']*(r1_map[c]-r0_map[c]) for c in l0['Code'])
    vol_var    = sum((b1-b0)*r0_map[c] for b0,b1,c in zip(a0['B0'],a1['B1'],a0['Code'])) \
               - sum((b1-b0)*r0_map[c] for b0,b1,c in zip(l0['B0'],l1['B1'],l0['Code']))
    mix_var    = sum((b1-b0)*(r1_map[c]-r0_map[c]) for b0,b1,c in zip(a0['B0'],a1['B1'],a0['Code'])) \
               - sum((b1-b0)*(r1_map[c]-r0_map[c]) for b0,b1,c in zip(l0['B0'],l1['B1'],l0['Code']))
    nii0 = sum(a0['B0']*r0_map[c] for c in a0['Code']) - sum(l0['B0']*r0_map[c] for c in l0['Code'])
    nii1 = sum(a1['B1']*r1_map[c] for c in a1['Code']) - sum(l1['B1']*r1_map[c] for c in l1['Code'])

    wf2 = pd.DataFrame([
        {'Step':'Starting NII',    'ΔNII': nii0},
        {'Step':'Rate Variance',   'ΔNII': rate_var},
        {'Step':'Volume Variance', 'ΔNII': vol_var},
        {'Step':'Mix Variance',    'ΔNII': mix_var},
        {'Step':'Ending NII',      'ΔNII': nii1},
    ])
    wf2['Start'] = wf2['ΔNII'].cumsum().shift(fill_value=0)
    wf2['End']   = wf2['Start'] + wf2['ΔNII']

    waterfall2 = alt.Chart(wf2).mark_bar().encode(
        x='Step:N', y='End:Q', y2='Start:Q',
        color=alt.condition(alt.datum.ΔNII>0, alt.value('green'), alt.value('red')),
        tooltip=['Step','ΔNII']
    ).properties(width=800,height=400)

    st.subheader("📈 P&L “Explain” Waterfall & Driver Analysis")
    st.altair_chart(waterfall2, use_container_width=True)
    st.caption(f"P&L Explain for {bu_choice} ({start_date} → {end_date})")
    st.markdown("---")
    st.caption("© 2025 NII Dashboard | Powered by FRED")

# --- Asset‐Liability Gap & Duration Analysis ---
    st.subheader("📊 ALM Gap & Duration & DV01 Analysis")

    # 1) Map each balance‐sheet row into tenor buckets
    tenor_map = {
        'Cash': '0-3M',
        'Short Borrow': '0-3M',
        'Deposits': '3-12M',
        'Loans': '1-5Y',
        'Bonds': '5Y+',
        'Corp Bonds': '5Y+'
    }
    # durations in years (approx)
    dur_map = {'0-3M': 0.25, '3-12M': 0.75, '1-5Y': 3.0, '5Y+': 7.5}

    # attach buckets to your assets & liabilities frames
    assets['Bucket'] = assets['Type'].map(tenor_map)
    liabs ['Bucket'] = liabs ['Type'].map(tenor_map)

    # 2) Compute static repricing gap (assets minus liabilities) per bucket
    gap = (
        assets.groupby('Bucket')['Balance'].sum()
        - liabs.groupby('Bucket')['Balance'].sum()
    ).reindex(dur_map.keys()).fillna(0)
    df_gap = gap.rename("Gap").reset_index()

    # 3) Compute DV01 under each rate‐shock scenario
    dv01_rows = []
    for name, bp in [('Baseline', 0.00), ('Adverse', -0.01), ('Severely Adverse', -0.025)]:
        for _, row in df_gap.iterrows():
            bkt = row['Bucket']
            pos = row['Gap']
            D   = dur_map[bkt]
            # DV01 = change in PV for 1bp shift ≈ position * duration * shift
            dv01 = pos * D * (bp * 100)  # *100 to convert from decimal to bp
            dv01_rows.append({
                'Scenario': name,
                'Bucket':   bkt,
                'DV01':     dv01
            })
    df_dv01 = pd.DataFrame(dv01_rows)

    # 4) Plot the repricing gap
    gap_chart = alt.Chart(df_gap).mark_bar().encode(
        x=alt.X('Bucket:N', title='Tenor Bucket'),
        y=alt.Y('Gap:Q', title='Asset – Liability Gap ($M)'),
        tooltip=['Bucket','Gap']
    ).properties(width=600, height=300)

    # 5) Plot DV01 by scenario
    dv01_chart = alt.Chart(df_dv01).mark_line(point=True).encode(
        x='Bucket:N',
        y=alt.Y('DV01:Q', title='DV01 ($M per bp)'),
        color='Scenario:N',
        strokeDash='Scenario:N',
        tooltip=['Scenario','Bucket','DV01']
    ).properties(width=600, height=300)

    # 6) Layout side‐by‐side
    c1, c2 = st.columns(2)
    with c1:
        st.caption("Repricing Gap by Tenor")
        st.altair_chart(gap_chart, use_container_width=True)
    with c2:
        st.caption("DV01 under Each Rate‐Shock")
        st.altair_chart(dv01_chart, use_container_width=True)


# ----------------------------------------
# Tab 2: CCAR / ICAAP Projections
# ----------------------------------------
# ----------------------------------------
# Tab 2: CCAR / ICAAP Projections
# ----------------------------------------
with tab2:
    st.header("🔮 CCAR / ICAAP Projections")

    # 1) Projection Type & Horizon
    proj_type = st.selectbox(
        "Projection Type",
        ["CCAR – 9 Quarters", "ICAAP – 3 Years", "ICAAP – 5 Years"]
    )

    if "CCAR" in proj_type:
        # 9 quarterly points
        periods = pd.date_range(start=datetime.date.today(), periods=9, freq='Q')
        # Labels: "2025-Q1", "2025-Q2", ...
        labels = [f"{d.year}-Q{((d.month-1)//3)+1}" for d in periods]
    else:
        # e.g. 3 or 5 years
        years = int(proj_type.split("–")[1].split()[0])
        periods = pd.date_range(start=datetime.date.today(), periods=years+1, freq='Y')
        # Labels: "2025", "2026", ...
        labels = [str(d.year) for d in periods]

    # 2) Macro inputs
    st.subheader("Macro Assumptions")
    gdp_growth = st.number_input("GDP Growth Forecast (%)", value=2.0, step=0.1)
    unemp_rate = st.number_input("Unemployment Rate Forecast (%)", value=5.0, step=0.1)
    prov_pct   = st.slider("Loan Loss Provision % of NII", 0.0, 30.0, 10.0)

    # 3) Base NII (pulled from your stress‐test calc)
    base_nii = stressed_nii

    # 4) Build projection table
    proj_data = []
    for i, label in enumerate(labels):
        nii_proj    = base_nii * (1 + gdp_growth/100 - (unemp_rate-5)/100*0.5)
        provisions  = nii_proj * prov_pct/100
        pre_tax_pl  = nii_proj - provisions
        # stub ratios & liquidity
        cet1_ratio  = max(0.04, 0.12 - 0.005*i)
        tier1_ratio = max(0.05, 0.13 - 0.004*i)
        lcr         = max(50, 100 - 2*i)
        nsfr        = max(50, 100 - 1*i)

        proj_data.append({
            "Period":       label,
            "NII":          round(nii_proj,2),
            "Provisions":   round(provisions,2),
            "Pre-Tax P/L":  round(pre_tax_pl,2),
            "CET1 Ratio":   round(cet1_ratio,4),
            "Tier 1 Ratio": round(tier1_ratio,4),
            "LCR (%)":      round(lcr,1),
            "NSFR (%)":     round(nsfr,1)
        })

    df_proj = pd.DataFrame(proj_data).set_index("Period")

    # 5) Display table and charts
    st.subheader("Regulatory P&L & Ratios")
    st.dataframe(df_proj)

    st.subheader("Key Metrics Over Time")
    c1, c2 = st.columns(2)
    c1.line_chart(df_proj[["CET1 Ratio","Tier 1 Ratio"]])
    c2.line_chart(df_proj[["LCR (%)","NSFR (%)"]])
