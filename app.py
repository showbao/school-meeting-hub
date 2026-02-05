# Version: v2.4 (Unrestricted Upload & Debug Mode)
# Author: CTO (Gemini)
# Description: 解除檔案格式限制 + 強化 GAS 連線錯誤除錯訊息

import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import requests
import base64
from datetime import datetime
import time
import json

# ====================
# 1. 設定區 (Configuration)
# ====================

# 【請務必填入剛剛「新增部署」後產生的 GAS 網址】
GAS_UPLOAD_URL = "https://script.google.com/macros/s/AKfycbzlDx0v2sqhLztOAWAkYaxiqDDeehRMfG7Hwhhm_c6EPfx0zYMGbbVCFIalmb9dc6Ej/exec"

# 【請填入 Google Sheet ID】
SHEET_ID = "1bX4webOXnQ65dNtjAS7Iuo78gRB8GWBKvm03Vif72hM"

SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
]

# ====================
# 2. 核心功能函式庫
# ====================

@st.cache_resource
def init_connection():
    """連線到 Google Sheets (連線物件快取)"""
    creds = None
    if "gcp_service_account" in st.secrets:
        creds_dict = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPE)
    else:
        try:
            creds = Credentials.from_service_account_file("service_account.json", scopes=SCOPE)
        except:
            return None
    return gspread.authorize(creds)

def get_sh(gc):
    """取得試算表物件"""
    try:
        return gc.open_by_key(SHEET_ID)
    except Exception as e:
        return None

@st.cache_data(ttl=60)
def load_data_frames(_gc):
    """讀取資料 (快取 60 秒)"""
    try:
        sh = _gc.open_by_key(SHEET_ID)
        ws_config = sh.worksheet("config")
        df_config = pd.DataFrame(ws_config.get_all_records())
        ws_records = sh.worksheet("records")
        df_records = pd.DataFrame(ws_records.get_all_records())
        return df_config, df_records
    except Exception as e:
        return None, None

def upload_file_via_gas(file_obj):
    """透過 GAS 中繼站上傳檔案 (v2.4 強力除錯版)"""
    if file_obj is None:
        return ""
    
    try:
        # 1. 準備資料
        file_content = file_obj.getvalue()
        base64_str = base64.b64encode(file_content).decode('utf-8')
        
        payload = {
            "file": base64_str,
            "filename": file_obj.name,
            "mimeType": file_obj.type
        }
        
        # 2. 發送請求
        response = requests.post(GAS_UPLOAD_URL, json=payload)
        
        # 3. 解析回應 (這裡最容易出錯，我們加上保護機制)
        try:
            result = response.json()
        except json.JSONDecodeError:
            # 如果回傳的不是 JSON，把回傳的原始文字印出來除錯
            st.error(f"❌ GAS 回傳錯誤 (非 JSON 格式)。\n狀態碼: {response.status_code}\n內容: {response.text[:200]}...")
            return ""
        
        if result.get("status") == "success":
            return result.get("url")
        else:
            st.error(f"GAS 執行錯誤: {result.get('message')}")
            return ""
            
    except Exception as e:
        st.error(f"上傳過程發生例外錯誤: {e}")
        return ""

# ====================
# 3. 介面邏輯 (UI Logic)
# ====================

def main():
    st.set_page_config(page_title="校務會議看板", layout="wide", page_icon="🏫")
    
    # 建立連線
    gc = init_connection()
    if gc is None:
        st.error("❌ 系統連線失敗：Secrets 設定有誤。")
        return

    # 讀取資料
    df_config, df_records = load_data_frames(gc)
    if df_config is None:
        st.error("❌ 無法讀取資料，請檢查 Sheet ID。")
        return

    # Session State
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'user_info' not in st.session_state:
        st.session_state.user_info = {}
    if 'cart' not in st.session_state:
        st.session_state.cart = [] 

    # --- 側邊欄 ---
    with st.sidebar:
        st.title("🏫 功能選單")
        if not st.session_state.logged_in:
            st.subheader("使用者登入")
            if not df_config.empty:
                dept_list = df_config['department'].unique().tolist()
                selected_dept = st.selectbox("選擇處室", dept_list)
                groups_in_dept = df_config[df_config['department'] == selected_dept]['group'].tolist()
                selected_group = st.selectbox("選擇組別", groups_in_dept)
                password = st.text_input("密碼", type="password")
                
                if st.button("登入"):
                    valid_user = df_config[
                        (df_config['department'] == selected_dept) & 
                        (df_config['group'] == selected_group) & 
                        (df_config['password'].astype(str) == str(password))
                    ]
                    if not valid_user.empty:
                        st.session_state.logged_in = True
                        st.session_state.user_info = {'dept': selected_dept, 'group': selected_group}
                        st.success("登入成功！")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error("密碼錯誤")
        else:
            st.info(f"Hi, {st.session_state.user_info['dept']} - {st.session_state.user_info['group']}")
            if st.button("登出"):
                st.session_state.logged_in = False
                st.session_state.user_info = {}
                st.session_state.cart = []
                st.rerun()

    # --- 主畫面 ---
    tab1, tab2 = st.tabs(["📋 看板", "📝 繕打"])

    # Tab 1
    with tab1:
        st.header("每週會議紀錄彙整")
        if st.button("🔄 重新整理"):
            st.cache_data.clear()
            st.rerun()

        if not df_records.empty:
            df_records['meeting_date'] = pd.to_datetime(df_records['meeting_date']).dt.date
            all_dates = sorted(df_records['meeting_date'].unique(), reverse=True)
            selected_date = st.selectbox("選擇會議日期", all_dates)
            st.divider()
            
            daily_records = df_records[df_records['meeting_date'] == selected_date]
            if not daily_records.empty:
                departments = daily_records['department'].unique()
                for dept in departments:
                    st.subheader(f"📂 {dept}")
                    dept_data = daily_records[daily_records['department'] == dept]
                    for idx, row in dept_data.iterrows():
                        with st.expander(f"{row['group']} - {str(row['content'])[:20]}...", expanded=True):
                            st.markdown(f"**報告內容：**\n{row['content']}")
                            if row['image_url'] and str(row['image_url']).strip() != "":
                                # 嘗試顯示圖片，如果不是圖片格式則顯示下載連結
                                if any(ext in str(row['image_url']).lower() for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                                    st.image(row['image_url'], caption="附件圖片", use_container_width=True)
                                else:
                                    st.markdown(f"📎 [點此下載/檢視附件檔案]({row['image_url']})")
                    st.write("---")
            else:
                st.info("該日期無紀錄")

    # Tab 2
    with tab2:
        if not st.session_state.logged_in:
            st.warning("請先登入")
        else:
            st.header(f"新增報告 - {st.session_state.user_info['group']}")
            col_d, _ = st.columns([1,2])
            with col_d:
                meeting_date = st.date_input("會議日期")
            st.divider()
            
            col1, col2 = st.columns([2, 1])
            with col1:
                new_content = st.text_area("輸入內容", height=120)
            with col2:
                # v2.4 修改：移除 type 限制，允許所有檔案
                uploaded_file = st.file_uploader("上傳附件 (不限格式)")
            
            if st.button("➕ 加入暫存"):
                if new_content:
                    st.session_state.cart.append({
                        'content': new_content,
                        'file': uploaded_file,
                        'file_name': uploaded_file.name if uploaded_file else "無附件"
                    })
                    st.success("已加入")
            
            if st.session_state.cart:
                st.markdown("### 🛒 暫存清單")
                st.table(pd.DataFrame(st.session_state.cart)[['content', 'file_name']])
                
                col_c, col_s = st.columns([1, 4])
                with col_c:
                    if st.button("🗑️ 清空"):
                        st.session_state.cart = []
                        st.rerun()
                with col_s:
                    if st.button("🚀 確認送出", type="primary"):
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        try:
                            sh = get_sh(gc) 
                            if sh:
                                ws_records = sh.worksheet("records")
                                total = len(st.session_state.cart)
                                for i, item in enumerate(st.session_state.cart):
                                    status_text.text(f"處理中 {i+1}/{total} (上傳附件中)...")
                                    link = ""
                                    if item['file']:
                                        link = upload_file_via_gas(item['file'])
                                    
                                    ws_records.append_row([
                                        str(hash(item['content'] + str(time.time()))),
                                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                        str(meeting_date),
                                        st.session_state.user_info['dept'],
                                        st.session_state.user_info['group'],
                                        item['content'],
                                        link
                                    ])
                                    progress_bar.progress((i+1)/total)
                                st.success("✅ 成功！")
                                st.session_state.cart = []
                                st.cache_data.clear()
                                time.sleep(2)
                                st.rerun()
                            else:
                                st.error("寫入失敗：無法連接試算表")
                        except Exception as e:
                            st.error(f"執行失敗: {e}")

if __name__ == "__main__":
    main()
