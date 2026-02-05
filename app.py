# Version: v2.2 (ID-Based Locking)
# Author: CTO (Gemini)
# Description: 改用 Sheet ID 強制鎖定試算表，排除檔名誤差

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

# 【請填入 Google Sheet ID】(網址 d/ 和 /edit 中間那串)
SHEET_ID = "1bX4webOXnQ65dNtjAS7Iuo78gRB8GWBKvm03Vif72hM"

SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
]

# ====================
# 2. 核心功能函式庫
# ====================

@st.cache_resource
def init_connection():
    """連線到 Google Sheets"""
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

def get_data(gc):
    """讀取 Google Sheet 資料 (使用 ID 鎖定)"""
    try:
        # v2.2 修改：改用 ID 開啟，絕對精準
        sh = gc.open_by_key(SHEET_ID)
        
        ws_config = sh.worksheet("config")
        df_config = pd.DataFrame(ws_config.get_all_records())
        
        ws_records = sh.worksheet("records")
        df_records = pd.DataFrame(ws_records.get_all_records())
        
        return sh, df_config, df_records
    except Exception as e:
        # 如果還是失敗，我們會把錯誤印出來
        st.error(f"【嚴重錯誤】無法開啟試算表。錯誤訊息: {e}")
        return None, None, None

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
    
    # 診斷資訊：顯示機器人 Email (方便除錯)
    if "gcp_service_account" in st.secrets:
        bot_email = st.secrets["gcp_service_account"]["client_email"]
        # st.caption(f"🔧 System Diagnosis: Bot Email is [{bot_email}]") 
        # ↑ 如果連線成功，建議將上行註解掉，以免暴露資訊

    gc = init_connection()
    if gc is None:
        st.error("❌ 系統連線失敗：Secrets 設定有誤。")
        return

    sh, df_config, df_records = get_data(gc)
    
    # 如果 sh 是 None，代表 ID 錯誤或是機器人真的沒權限
    if sh is None:
        st.warning(f"請再次確認：\n1. 您的 Google Sheet ID 是否正確填入程式碼？\n2. 是否已將機器人加入試算表共用？")
        if "gcp_service_account" in st.secrets:
            st.code(f"請複製此機器人 Email 加入共用：\n{st.secrets['gcp_service_account']['client_email']}")
        return

    # --- 以下邏輯不變 ---
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'user_info' not in st.session_state:
        st.session_state.user_info = {}
    if 'cart' not in st.session_state:
        st.session_state.cart = [] 

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

    tab1, tab2 = st.tabs(["📋 看板", "📝 繕打"])

    with tab1:
        st.header("每週會議紀錄彙整")
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
                            ws_records = sh.worksheet("records")
                            total = len(st.session_state.cart)
                            for i, item in enumerate(st.session_state.cart):
                                status_text.text(f"處理中 {i+1}/{total}...")
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
                            st.success("成功！")
                            st.session_state.cart = []
                            time.sleep(2)
                            st.rerun()
                        except Exception as e:
                            st.error(f"寫入失敗: {e}")

if __name__ == "__main__":
    main()
