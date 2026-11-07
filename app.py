# -*- coding: utf-8 -*-
"""
上市公司财务分析小工具 v2
运行：streamlit run app.py
升级点：
  1. 离线缓存（断网自动读本地CSV，不翻车）
  2. 顶部数字卡片（最新营收/净利/毛利率/ROE）
  3. 侧边栏（数据来源说明）
  4. 自动生成一段文字分析结论
"""
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
import io
import os

# ===== 中文字体 =====
matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
matplotlib.rcParams['axes.unicode_minus'] = False

# ===== 离线缓存目录 =====
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data_cache')
os.makedirs(CACHE_DIR, exist_ok=True)

st.set_page_config(page_title="财务分析小工具", layout="wide", page_icon="📊")

# ===== 侧边栏 =====
with st.sidebar:
    st.header("ℹ️ 关于本工具")
    st.write("本工具用于 A 股上市公司近5年财务报表分析。")
    st.markdown("**数据来源**：新浪财经（通过 akshare 库实时抓取）")
    st.markdown("**覆盖报表**：利润表 / 资产负债表 / 现金流量表")
    st.markdown("**输出形式**：数据表格 / 可视化图表 / Excel 下载")
    st.divider()
    st.caption("作者：琼慧 | 2024大数据与会计")
    st.caption("课程：毕业综合测试案例分析")

st.title("📊 上市公司财务分析工具")

# ===== 第1层：输入 =====
col1, col2 = st.columns([2, 1])
with col1:
    query = st.text_input("输入公司名称或股票代码（试试：上海艾录 / 裕同科技 / 合兴包装）", "上海艾录")
with col2:
    years = st.multiselect("选择分析年份", [2021, 2022, 2023, 2024, 2025],
                           default=[2021, 2022, 2023, 2024, 2025])

outputs = st.multiselect(
    "选择你要的输出",
    ["数据表格", "盈利趋势图", "费用结构图", "盈利能力指标图", "现金流对比图", "下载Excel"],
    default=["数据表格", "盈利趋势图", "下载Excel"]
)

# ===== 工具函数：公司名 → 股票代码 =====
def name_to_code(query):
    """把'上海艾录'翻译成'sz301062'"""
    import akshare as ak
    query = query.strip()
    if query.isdigit() and len(query) == 6:
        code = query
    else:
        df = ak.stock_info_a_code_name()
        match = df[df['name'].str.contains(query, na=False)]
        if match.empty:
            return None, None
        row = match.iloc[0]
        code = row['code']
        query = row['name']
    prefix = 'sh' if code.startswith('6') else 'sz'
    return prefix + code, query

# ===== 工具函数：抓数据（带离线缓存）=====
def fetch_financials(stock_code, years, name):
    """
    优先在线抓取；失败则读本地CSV缓存。
    返回 (data, is_offline)
    """
    cache_file = os.path.join(CACHE_DIR, f"{stock_code}.csv")

    # 先试在线
    try:
        import akshare as ak
        income  = ak.stock_financial_report_sina(stock=stock_code, symbol='利润表')
        balance = ak.stock_financial_report_sina(stock=stock_code, symbol='资产负债表')
        cash    = ak.stock_financial_report_sina(stock=stock_code, symbol='现金流量表')

        def annual(df):
            df = df[df['报告日'].astype(str).str.endswith('1231')].copy()
            df['年份'] = df['报告日'].astype(str).str[:4].astype(int)
            return df.set_index('年份')

        inc, bal, csh = annual(income), annual(balance), annual(cash)

        def pick(df, col):
            if col not in df.columns:
                return pd.Series([0.0]*len(years), index=years)
            return pd.to_numeric(df[col].reindex(years), errors='coerce').fillna(0) / 1e8

        data = pd.DataFrame(index=years)
        data['营业总收入'] = pick(inc, '营业总收入')
        data['营业成本']   = pick(inc, '营业成本')
        data['销售费用']   = pick(inc, '销售费用')
        data['管理费用']   = pick(inc, '管理费用')
        data['研发费用']   = pick(inc, '研发费用')
        data['财务费用']   = pick(inc, '财务费用')
        data['净利润']     = pick(inc, '净利润')
        data['经营现金流'] = pick(csh, '经营活动产生的现金流量净额')
        data['所有者权益'] = pick(bal, '所有者权益(或股东权益)合计')
        data['资产总计']   = pick(bal, '资产总计')
        data['负债合计']   = pick(bal, '负债合计')

        data['毛利率%'] = (data['营业总收入']-data['营业成本'])/data['营业总收入']*100
        data['净利率%'] = data['净利润']/data['营业总收入']*100
        data['ROE%']    = data['净利润']/data['所有者权益']*100
        data['资产负债率%'] = data['负债合计']/data['资产总计']*100
        data = data.round(2)

        # 写入缓存
        data.to_csv(cache_file, encoding='utf-8-sig')
        return data, False

    except Exception as e:
        # 在线失败，试离线缓存
        if os.path.exists(cache_file):
            data = pd.read_csv(cache_file, index_col=0)
            data.index = data.index.astype(int)
            # 只保留用户选的年份
            data = data.reindex(years)
            return data, True
        else:
            raise e

# ===== 自动生成文字结论 =====
def generate_conclusion(data, name, years):
    rev_start = data['营业总收入'].iloc[0]
    rev_end   = data['营业总收入'].iloc[-1]
    rev_change = (rev_end - rev_start) / rev_start * 100 if rev_start != 0 else 0

    profit_start = data['净利润'].iloc[0]
    profit_end   = data['净利润'].iloc[-1]

    gm_start = data['毛利率%'].iloc[0]
    gm_end   = data['毛利率%'].iloc[-1]
    gm_change = gm_end - gm_start

    roe_end  = data['ROE%'].iloc[-1]

    # 判断趋势
    if profit_end < 0:
        profit_desc = f"由{profit_start:.2f}亿元**转为亏损{abs(profit_end):.2f}亿元**"
    elif profit_start > 0:
        pct = (profit_end - profit_start) / abs(profit_start) * 100
        profit_desc = f"从{profit_start:.2f}亿元变动至{profit_end:.2f}亿元（{pct:+.1f}%）"

    if gm_change < -3:
        gm_desc = f"毛利率从{gm_start:.1f}%下滑至{gm_end:.1f}%，下降{abs(gm_change):.1f}个百分点，反映成本端压力或产品议价能力减弱"
    elif gm_change > 3:
        gm_desc = f"毛利率从{gm_start:.1f}%提升至{gm_end:.1f}%，盈利空间有所改善"
    else:
        gm_desc = f"毛利率在{gm_start:.1f}%-{gm_end:.1f}%区间波动，整体相对稳定"

    if roe_end < 0:
        roe_desc = f"最新一年ROE为{roe_end:.2f}%，股东回报为负，需警惕持续经营风险"
    elif roe_end < 5:
        roe_desc = f"最新一年ROE仅为{roe_end:.2f}%，股东回报能力偏弱"
    else:
        roe_desc = f"最新一年ROE为{roe_end:.2f}%，股东回报尚可"

    conclusion = (
        f"**{name}**在{years[0]}—{years[-1]}年间，营业总收入从{rev_start:.2f}亿元变动至{rev_end:.2f}亿元"
        f"（{rev_change:+.1f}%），收入规模整体"
        f"{'基本稳定' if abs(rev_change)<15 else ('扩张' if rev_change>0 else '收缩')}。"
        f"净利润{profit_desc}。{gm_desc}。{roe_desc}。"
        f"建议进一步关注公司成本管控能力、期间费用效率及经营现金流与净利润的匹配度。"
    )
    return conclusion

# ===== 主流程 =====
if st.button("开始分析 🚀", type="primary"):
    with st.spinner("正在解析公司名称..."):
        try:
            stock_code, name = name_to_code(query)
        except Exception as e:
            st.error(f"在线解析失败（可能没网）：{e}")
            stock_code, name = None, None

    if not stock_code:
        # 离线模式下，尝试用缓存里已有的公司
        cache_files = [f for f in os.listdir(CACHE_DIR) if f.endswith('.csv')]
        if cache_files:
            st.warning(f"在线解析失败，但发现本地缓存：{', '.join(cache_files)}")
            st.info("离线模式暂不支持新公司名解析。请检查网络后重试，或直接输入6位股票代码。")
        st.error(f"没找到公司：{query}")
        st.stop()

    with st.spinner("正在获取数据（在线抓取 / 离线缓存）..."):
        try:
            data, is_offline = fetch_financials(stock_code, tuple(years), name)
        except Exception as e:
            st.error(f"数据获取失败：{e}")
            st.stop()

    if is_offline:
        st.warning(f"📡 当前为**离线缓存数据**（{name} {stock_code}），非实时抓取")
    else:
        st.success(f"✅ 已识别：{name}（{stock_code}）· 在线实时数据")

    # ===== 顶部数字卡片 =====
    latest = data.iloc[-1]
    st.markdown("### 📌 最新年度概览")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("营业总收入", f"{latest['营业总收入']:.2f} 亿",
              f"{(latest['营业总收入']-data['营业总收入'].iloc[0])/data['营业总收入'].iloc[0]*100:+.1f}%")
    m2.metric("净利润", f"{latest['净利润']:.2f} 亿",
              f"{(latest['净利润']-data['净利润'].iloc[0]):+.2f} 亿")
    m3.metric("毛利率", f"{latest['毛利率%']:.1f}%",
              f"{latest['毛利率%']-data['毛利率%'].iloc[0]:+.1f} pct")
    m4.metric("ROE", f"{latest['ROE%']:.2f}%",
              f"{latest['ROE%']-data['ROE%'].iloc[0]:+.2f} pct")

    st.divider()

    # 输出1：表格
    if "数据表格" in outputs:
        st.subheader("📋 财务数据汇总（单位：亿元）")
        st.dataframe(data, use_container_width=True)

    # 输出2：图1 营收+净利润
    if "盈利趋势图" in outputs:
        st.subheader("📈 营业总收入与净利润趋势")
        fig, ax1 = plt.subplots(figsize=(9, 4.5))
        ax1.bar([str(y) for y in years], data['营业总收入'], color='#4C78A8', alpha=0.8)
        ax1.set_ylabel('营业总收入（亿元）', color='#4C78A8')
        ax2 = ax1.twinx()
        ax2.plot([str(y) for y in years], data['净利润'], color='#E45756',
                 marker='o', linewidth=2)
        ax2.set_ylabel('净利润（亿元）', color='#E45756')
        ax1.set_title(f'{name} 营业收入与净利润趋势')
        st.pyplot(fig)

    # 输出3：图2 费用结构
    if "费用结构图" in outputs:
        st.subheader("💰 期间费用结构")
        fig, ax = plt.subplots(figsize=(9, 4.5))
        import numpy as np
        x = np.arange(len(years))
        ax.bar(x, data['销售费用'], label='销售费用', color='#4C78A8')
        ax.bar(x, data['管理费用'], bottom=data['销售费用'], label='管理费用', color='#F58518')
        ax.bar(x, data['研发费用'], bottom=data['销售费用']+data['管理费用'],
               label='研发费用', color='#54A24B')
        ax.bar(x, data['财务费用'],
               bottom=data['销售费用']+data['管理费用']+data['研发费用'],
               label='财务费用', color='#B279A2')
        ax.set_xticks(x); ax.set_xticklabels([str(y) for y in years])
        ax.set_ylabel('亿元'); ax.legend()
        st.pyplot(fig)

    # 输出4：图3 盈利能力
    if "盈利能力指标图" in outputs:
        st.subheader("📊 盈利能力指标")
        fig, ax = plt.subplots(figsize=(9, 4.5))
        ax.plot([str(y) for y in years], data['毛利率%'], marker='o', label='毛利率%')
        ax.plot([str(y) for y in years], data['净利率%'], marker='s', label='净利率%')
        ax.plot([str(y) for y in years], data['ROE%'],    marker='^', label='ROE%')
        ax.set_ylabel('%'); ax.legend(); ax.grid(alpha=0.3)
        st.pyplot(fig)

    # 输出5：图4 现金流
    if "现金流对比图" in outputs:
        st.subheader("💵 净利润 vs 经营现金流")
        fig, ax = plt.subplots(figsize=(9, 4.5))
        import numpy as np
        x = np.arange(len(years)); w = 0.35
        ax.bar(x-w/2, data['净利润'], w, label='净利润', color='#4C78A8')
        ax.bar(x+w/2, data['经营现金流'], w, label='经营现金流净额', color='#72B7B2')
        ax.set_xticks(x); ax.set_xticklabels([str(y) for y in years])
        ax.axhline(0, color='black', linewidth=0.8); ax.legend()
        st.pyplot(fig)

    # 输出6：下载Excel
    if "下载Excel" in outputs:
        buf = io.BytesIO()
        data.to_excel(buf, index_label='年份', sheet_name=name)
        buf.seek(0)
        st.download_button(
            label="⬇️ 下载 Excel",
            data=buf,
            file_name=f"{name}_财务分析.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    # ===== 自动文字结论 =====
    st.divider()
    st.subheader("🧾 自动分析结论")
    st.write(generate_conclusion(data, name, years))
