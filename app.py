# Version: v2.3 (Smart Caching)
# Author: CTO (Gemini)
# Description: 加入快取機制 (Cache) 解決 429 API Quota 流量限制問題

import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import requests
import base64
from datetime import datetime
import time

# ====================
# 1. 設定區 (Configuration)
# ====================

# 【請填入 GAS 網址】
GAS_UPLOAD_URL = "https://script.google.com/macros/s/AKfycbzre2cPuoiie16hiFW1Dto1xFgnvPTqtM3O9u97Ja1qdWoGlSbZ7PEQ8X6rBh_tNpOB/exec"

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
    """取得試算表物件 (不快取，確保寫入時是新的)"""
    try:
        return gc.open_by_key(SHEET_ID)
    except Exception as e:
        return None

@st.cache_data(ttl=60)  # <--- 關鍵修改：加入快取，60秒內不會重複讀取 API
def load_data_frames(_gc):
    """讀取資料並轉為 DataFrame (快取 60 秒)"""
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
    """透過 GAS 中繼站上傳檔案"""
    if file_obj is None:
        return ""
    
    try:
        file_content = file_obj.getvalue()
        base64_str = base64.b64encode(file_content).decode('utf-8')
        
        payload = {
            "file": base64_str,
            "filename": file_obj.name,
            "mimeType": file_obj.type
        }
        
        response = requests.post(GAS_UPLOAD_URL, json=payload)
        result = response.json()
        
        if result.get("status") == "success":
            return result.get("url")
        else:
            st.error(f"上傳失敗: {result.get('message')}")
            return ""
            
    except Exception as e:
        st.error(f"連線錯誤: {e}")
        return ""

# ====================
# 3. 介面邏輯 (UI Logic)
# ====================

def main():
    st.set_page_config(page_title="校務會議看板", layout="wide", page_icon="🏫")
    
    # 1. 建立連線
    gc = init_connection()
    if gc is None:
        st.error("❌ 系統連線失敗：Secrets 設定有誤。")
        return

    # 2. 讀取資料 (使用快取)
    df_config, df_records = load_data_frames(gc)
    
    if df_config is None:
        st.error("❌ 無法讀取資料，請稍後再試 (API 冷卻中) 或檢查 Sheet ID。")
        return

    # 3. 初始化 Session State
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
            if df_config.empty:
                st.warning("設定檔 (config) 為空。")
            else:
                dept_list = df_config['department'].unique().tolist()
                selected_dept = st.selectbox("選擇處室", dept_list)
                
                groups_in_dept = df_config[df_config['department'] == selected_dept]['group'].tolist()
                selected_group = st.selectbox("選擇組別", groups_in_dept)
                
                password = st.text_input("密碼", type="password")
                
                if st.button("登入"):
                    # 這裡使用快取的 df_config 進行驗證，不消耗 API
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

    # === Tab 1: 看板 ===
    with tab1:
        st.header("每週會議紀錄彙整")
        if st.button("🔄 重新整理資料"):
            st.cache_data.clear() # 手動清除快取
            st.rerun()

        if not df_records.empty:
            df_records['meeting_date'] = pd.to_datetime(df_records['meeting_date']).dt.date
            all_dates = sorted(df_records['meeting_date'].unique(), reverse=True)
            selected_date = st.selectbox("選擇會議日期", all_dates)
            st.divider()
            
            daily_records = df_records[df_records['meeting_date'] == selected_date]
            
            if daily_records.empty:
                st.info("該日期無紀錄")
            else:
                departments = daily_records['department'].unique()
                for dept in departments:
                    st.subheader(f"📂 {dept}")
                    dept_data = daily_records[daily_records['department'] == dept]
                    
                    for idx, row in dept_data.iterrows():
                        with st.expander(f"{row['group']} - {str(row['content'])[:20]}...", expanded=True):
                            st.markdown(f"**報告內容：**\n{row['content']}")
                            if row['image_url'] and str(row['image_url']).strip() != "":
                                st.image(row['image_url'], caption="附件圖片", use_container_width=True)
                    st.write("---")
        else:
            st.info("尚無紀錄")

    # === Tab 2: 繕打 ===
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
                uploaded_file = st.file_uploader("上傳圖片", type=['png', 'jpg', 'jpeg'])
            
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
                            # 寫入時，重新取得最新的 sh 物件 (不使用快取)
                            sh = get_sh(gc) 
                            if sh:
                                ws_records = sh.worksheet("records")
                                total = len(st.session_state.cart)
                                for i, item in enumerate(st.session_state.cart):
                                    status_text.text(f"處理中 {i+1}/{total} (圖片上傳中)...")
                                    
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
                                
                                st.success("✅ 成功！資料已更新。")
                                st.session_state.cart = []
                                # 關鍵：送出成功後，清除快取，這樣下次讀取才會是新的
                                st.cache_data.clear()
                                time.sleep(2)
                                st.rerun()
                            else:
                                st.error("寫入失敗：無法連接試算表")
                                
                        except Exception as e:
                            # 如果遇到 Quota 錯誤，提示使用者
                            if "429" in str(e):
                                st.error("流量過大 (API Quota)，請休息 1 分鐘後再試。")
                            else:
                                st.error(f"寫入失敗: {e}")

if __name__ == "__main__":
    main()
