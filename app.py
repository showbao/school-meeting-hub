# Version: v2.1 (Clean Production)
# Author: CTO (Gemini)
# Description: 正式版 - 透過 GAS 中繼站上傳檔案，並寫入 Google Sheets

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
# 【請填入您在 GAS 部署後產生的網址】(以 https://script.google.com/... 開頭)
GAS_UPLOAD_URL = "https://script.google.com/macros/s/AKfycbzre2cPuoiie16hiFW1Dto1xFgnvPTqtM3O9u97Ja1qdWoGlSbZ7PEQ8X6rBh_tNpOB/exec"

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
    # 優先嘗試讀取 Streamlit Cloud 的 Secrets
    if "gcp_service_account" in st.secrets:
        creds_dict = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPE)
    # 本機測試時讀取 JSON 檔案
    else:
        try:
            creds = Credentials.from_service_account_file("service_account.json", scopes=SCOPE)
        except:
            return None
    
    return gspread.authorize(creds)

def get_data(gc):
    """讀取 Google Sheet 資料"""
    try:
        # 請確認您的試算表名稱完全一致 (大小寫、空格)
        sh = gc.open("School_Meeting_System")
        
        ws_config = sh.worksheet("config")
        df_config = pd.DataFrame(ws_config.get_all_records())
        
        ws_records = sh.worksheet("records")
        df_records = pd.DataFrame(ws_records.get_all_records())
        
        return sh, df_config, df_records
    except Exception as e:
        # 回傳 None 代表連線失敗或找不到檔案
        return None, None, None

def upload_file_via_gas(file_obj):
    """透過 GAS 中繼站上傳檔案"""
    if file_obj is None:
        return ""
    
    try:
        # 將檔案轉為 Base64 字串傳送
        file_content = file_obj.getvalue()
        base64_str = base64.b64encode(file_content).decode('utf-8')
        
        payload = {
            "file": base64_str,
            "filename": file_obj.name,
            "mimeType": file_obj.type
        }
        
        # 發送 POST 請求給 GAS
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
        st.error("❌ 系統連線失敗：請檢查 Secrets 設定或是 service_account.json 是否存在。")
        return

    # 2. 讀取資料
    sh, df_config, df_records = get_data(gc)
    if sh is None:
        st.error("❌ 找不到試算表：請確認 Google Sheet 名稱是否為 'School_Meeting_System'，且已將機器人 Email 加入共用編輯權限。")
        return

    # 3. 初始化 Session State
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'user_info' not in st.session_state:
        st.session_state.user_info = {}
    if 'cart' not in st.session_state:
        st.session_state.cart = [] 

    # --- 側邊欄：登入/登出 ---
    with st.sidebar:
        st.title("🏫 功能選單")
        
        if not st.session_state.logged_in:
            st.subheader("使用者登入")
            
            # 防呆：如果資料庫是空的
            if df_config.empty:
                st.warning("設定檔 (config) 為空，請先至 Google Sheet 建立帳號。")
            else:
                dept_list = df_config['department'].unique().tolist()
                selected_dept = st.selectbox("選擇處室", dept_list)
                
                groups_in_dept = df_config[df_config['department'] == selected_dept]['group'].tolist()
                selected_group = st.selectbox("選擇組別", groups_in_dept)
                
                password = st.text_input("密碼", type="password")
                
                if st.button("登入"):
                    # 驗證邏輯
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
    tab1, tab2 = st.tabs(["📋 會議紀錄看板", "📝 繕打報告 (需登入)"])

    # === Tab 1: 看板 ===
    with tab1:
        st.header("每週會議紀錄彙整")
        
        if not df_records.empty:
            # 確保日期格式與排序
            df_records['meeting_date'] = pd.to_datetime(df_records['meeting_date']).dt.date
            all_dates = sorted(df_records['meeting_date'].unique(), reverse=True)
            selected_date = st.selectbox("選擇會議日期", all_dates)
            
            st.divider()
            
            # 顯示該日期的資料
            daily_records = df_records[df_records['meeting_date'] == selected_date]
            
            if daily_records.empty:
                 st.info("該日期尚無紀錄。")
            else:
                # 依照處室分群
                departments = daily_records['department'].unique()
                for dept in departments:
                    st.subheader(f"📂 {dept}")
                    dept_data = daily_records[daily_records['department'] == dept]
                    
                    for idx, row in dept_data.iterrows():
                        # 顯示每一點報告
                        with st.expander(f"{row['group']} - {str(row['content'])[:20]}...", expanded=True):
                            st.markdown(f"**報告內容：**\n{row['content']}")
                            
                            # 顯示圖片 (如果有連結)
                            if row['image_url'] and str(row['image_url']).strip() != "":
                                st.image(row['image_url'], caption="附件圖片", use_container_width=True)
                    st.write("---")
        else:
            st.info("目前資料庫中沒有任何紀錄。")

    # === Tab 2: 繕打 ===
    with tab2:
        if not st.session_state.logged_in:
            st.warning("請先由左側欄登入後才能繕打報告。")
        else:
            st.header(f"新增報告 - {st.session_state.user_info['group']}")
            
            col_date, col_dummy = st.columns([1, 2])
            with col_date:
                meeting_date = st.date_input("會議日期")
            
            st.divider()
            
            # 輸入區
            col1, col2 = st.columns([2, 1])
            with col1:
                new_content = st.text_area("輸入報告事項 (單點)", height=120, placeholder="請輸入報告內容...")
            with col2:
                uploaded_file = st.file_uploader("上傳圖片 (支援 jpg, png)", type=['png', 'jpg', 'jpeg'])
            
            # 加入暫存按鈕
            if st.button("➕ 加入暫存清單"):
                if new_content:
                    st.session_state.cart.append({
                        'content': new_content,
                        'file': uploaded_file,
                        'file_name': uploaded_file.name if uploaded_file else "無附件"
                    })
                    st.success("已加入暫存！")
                else:
                    st.error("內容不能為空")

            # 顯示暫存區
            if st.session_state.cart:
                st.markdown("### 🛒 待提交清單 (預覽)")
                st.table(pd.DataFrame(st.session_state.cart)[['content', 'file_name']])
                
                col_clear, col_submit = st.columns([1, 4])
                with col_clear:
                    if st.button("🗑️ 清空暫存"):
                        st.session_state.cart = []
                        st.rerun()
                
                with col_submit:
                    if st.button("🚀 確認送出所有報告", type="primary"):
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        
                        try:
                            ws_records = sh.worksheet("records")
                            total_items = len(st.session_state.cart)
                            
                            for i, item in enumerate(st.session_state.cart):
                                status_text.text(f"正在處理第 {i+1}/{total_items} 筆 (圖片上傳中，請稍候)...")
                                
                                # 透過 GAS 上傳圖片
                                file_link = ""
                                if item['file']:
                                    file_link = upload_file_via_gas(item['file'])
                                
                                # 準備寫入資料
                                new_row = [
                                    str(hash(item['content'] + str(time.time()))), # UUID
                                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # 提交時間
                                    str(meeting_date),                             # 會議日期
                                    st.session_state.user_info['dept'],            # 處室
                                    st.session_state.user_info['group'],           # 組別
                                    item['content'],                               # 內容
                                    file_link                                      # 圖片連結
                                ]
                                
                                ws_records.append_row(new_row)
                                progress_bar.progress((i + 1) / total_items)
                            
                            status_text.text("處理完成！")
                            st.success("✅ 所有報告已成功寫入資料庫！")
                            st.session_state.cart = [] # 清空
                            time.sleep(2)
                            st.rerun()
                            
                        except Exception as e:
                            st.error(f"寫入失敗：{e}")

if __name__ == "__main__":
    main()
