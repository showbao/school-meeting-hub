# Version: v1.1
# Author: CTO (Gemini)
# Description: 支援 Streamlit Cloud 雲端部署 (與 Local 兼容模式)

import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from datetime import datetime
import time

# ====================
# 1. 設定區 (Configuration)
# ====================
# 【請務必確認這裡填的是正確的 ID】
DRIVE_FOLDER_ID = "1O5z7gzPFEA7L_GXbBFmG_fa7Eu0A4onj"

SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# ====================
# 2. 核心功能函式庫
# ====================

@st.cache_resource
def init_connection():
    """
    連線到 Google 服務
    v1.1 更新：優先讀取 Streamlit Cloud 的 Secrets，若無則讀取本地檔案
    """
    creds = None
    
    # 模式 A: 雲端模式 (Streamlit Cloud)
    if "gcp_service_account" in st.secrets:
        creds_dict = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPE)
    
    # 模式 B: 本機模式 (Local)
    else:
        try:
            creds = Credentials.from_service_account_file("service_account.json", scopes=SCOPE)
        except FileNotFoundError:
            st.error("找不到金鑰檔案！在雲端請設定 Secrets，在本機請確認 json 檔案存在。")
            return None, None

    gc = gspread.authorize(creds)
    drive_service = build('drive', 'v3', credentials=creds)
    return gc, drive_service

def get_data(gc):
    """讀取 Google Sheet 資料"""
    try:
        sh = gc.open("School_Meeting_System")
        ws_config = sh.worksheet("config")
        df_config = pd.DataFrame(ws_config.get_all_records())
        ws_records = sh.worksheet("records")
        df_records = pd.DataFrame(ws_records.get_all_records())
        return sh, df_config, df_records
    except Exception as e:
        st.error(f"讀取試算表失敗，請確認試算表名稱是否為 'School_Meeting_System'。錯誤: {e}")
        return None, None, None

def upload_file_to_drive(drive_service, file_obj, folder_id):
    """上傳檔案到 Google Drive 並回傳連結"""
    if file_obj is None:
        return ""
    
    file_metadata = {
        'name': f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file_obj.name}",
        'parents': [folder_id]
    }
    
    media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
    
    file = drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id, webViewLink'
    ).execute()
    
    try:
        drive_service.permissions().create(
            fileId=file.get('id'),
            body={'role': 'reader', 'type': 'anyone'},
        ).execute()
    except:
        pass 
        
    return file.get('webViewLink')

# ====================
# 3. 介面邏輯 (UI Logic)
# ====================

def main():
    st.set_page_config(page_title="校務會議看板", layout="wide", page_icon="🏫")
    
    # 初始化連線
    gc, drive_service = init_connection()
    if gc is None:
        return

    sh, df_config, df_records = get_data(gc)
    if sh is None:
        return

    # 初始化 Session State
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
            dept_list = df_config['department'].unique().tolist() if not df_config.empty else []
            selected_dept = st.selectbox("選擇處室", dept_list)
            
            groups_in_dept = df_config[df_config['department'] == selected_dept]['group'].tolist() if not df_config.empty else []
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
                    time.sleep(1)
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
            # 轉換日期格式確保排序正確
            df_records['meeting_date'] = pd.to_datetime(df_records['meeting_date']).dt.date
            all_dates = sorted(df_records['meeting_date'].unique(), reverse=True)
            selected_date = st.selectbox("選擇會議日期", all_dates)
            
            st.divider()
            
            daily_records = df_records[df_records['meeting_date'] == selected_date]
            departments = daily_records['department'].unique()
            for dept in departments:
                st.subheader(f"📂 {dept}")
                dept_data = daily_records[daily_records['department'] == dept]
                for idx, row in dept_data.iterrows():
                    with st.expander(f"{row['group']} - {str(row['content'])[:20]}...", expanded=True):
                        st.markdown(f"**報告內容：**\n{row['content']}")
                        if row['image_url']:
                            st.markdown(f"[📎 查看附件/圖片]({row['image_url']})")
                            if "drive.google.com" in row['image_url']:
                                file_id = row['image_url'].split('id=')[-1] if 'id=' in row['image_url'] else row['image_url'].split('/')[-2]
                                thumbnail_url = f"https://drive.google.com/thumbnail?id={file_id}&sz=w800"
                                st.image(thumbnail_url, caption="附件預覽", use_container_width=True)
                st.write("---")
        else:
            st.info("目前沒有任何紀錄。")

    # === Tab 2: 繕打 ===
    with tab2:
        if not st.session_state.logged_in:
            st.warning("請先由左側欄登入後才能繕打報告。")
        else:
            st.header(f"新增報告 - {st.session_state.user_info['group']}")
            meeting_date = st.date_input("會議日期")
            st.divider()
            
            col1, col2 = st.columns([2, 1])
            with col1:
                new_content = st.text_area("輸入報告事項 (單點)", height=100)
            with col2:
                uploaded_file = st.file_uploader("上傳圖片/PDF", type=['png', 'jpg', 'jpeg', 'pdf'])
            
            if st.button("➕ 加入暫存清單"):
                if new_content:
                    st.session_state.cart.append({
                        'content': new_content,
                        'file': uploaded_file,
                        'file_name': uploaded_file.name if uploaded_file else "無附件"
                    })
                    st.success("已加入暫存！")
                else:
                    st.error("請輸入內容")

            if st.session_state.cart:
                st.markdown("### 🛒 待提交清單")
                df_cart = pd.DataFrame(st.session_state.cart)
                st.table(df_cart[['content', 'file_name']])
                
                if st.button("🗑️ 清空暫存"):
                    st.session_state.cart = []
                    st.rerun()

                st.markdown("---")
                
                if st.button("🚀 確認送出所有報告", type="primary"):
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    try:
                        ws_records = sh.worksheet("records")
                        total_items = len(st.session_state.cart)
                        for i, item in enumerate(st.session_state.cart):
                            status_text.text(f"正在處理第 {i+1}/{total_items} 筆...")
                            file_link = ""
                            if item['file']:
                                file_link = upload_file_to_drive(drive_service, item['file'], DRIVE_FOLDER_ID)
                            
                            new_row = [
                                str(hash(item['content'] + str(time.time()))),
                                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                str(meeting_date),
                                st.session_state.user_info['dept'],
                                st.session_state.user_info['group'],
                                item['content'],
                                file_link
                            ]
                            ws_records.append_row(new_row)
                            progress_bar.progress((i + 1) / total_items)
                        
                        st.success("✅ 送出成功！")
                        st.session_state.cart = []
                        time.sleep(2)
                        st.rerun()
                    except Exception as e:
                        st.error(f"寫入失敗：{e}")

if __name__ == "__main__":
    main()
