import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
import pandas as pd
import json
import os

# [설정]
ROLES = {
    "제천대성": ["파티장", "딜러1", "딜러2", "딜러3", "딜러4"], 
    "나타의 시련(보통)": ["파티장", "속성몹_(水속성 우선)", "패턴몹 + 불사몹(속성 무관)","패턴몹 + 불사몹(속성 무관)", "침식몹 (속성 무관)"], 
    "나타의 시련(어려움)": ["파티장", "속성몹_(水속성 우선)", "패턴몹 + 불사몹(속성 무관)","패턴몹 + 불사몹(속성 무관)", "침식몹 (속성 무관)"]
}

scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets', "https://www.googleapis.com/auth/drive"]

# 인증 로직
if "GSPREAD_JSON" in st.secrets:
    creds_dict = json.loads(st.secrets["GSPREAD_JSON"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
else:
    creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)

client = gspread.authorize(creds)
sheet = client.open("거상파티관리")
rooms_sheet = sheet.worksheet("Rooms")
parts_sheet = sheet.worksheet("Participants")

# [디스코드 알림] - 이제 함수 내부에서 시트를 다시 읽지 않고 인자로 받은 데이터 활용
def send_discord_webhook(room_id, content, leader, parts_data):
    webhook_url = os.getenv("DISCORD_WEBHOOK", st.secrets.get("DISCORD_WEBHOOK", "https://discord.com/api/webhooks/1522974507948708075/MRh9V7Kaullz8eCXkr6Qme213ihyzZbCEFRtxTOEsKmxZJniAjgIrU00io3cIufqYa1v"))
    # 인자로 받은 parts_data 활용
    member_list = "\n".join([f"- {p['Nickname']} ({p['Role']})" for p in parts_data if str(p['Room_ID']) == str(room_id)])
    message = {"content": f"🚨 **[파티 마감]** {content}\n파티장: {leader}\n\n**파티원 명단:**\n{member_list}"}
    try: requests.post(webhook_url, json=message)
    except: pass

@st.cache_data(ttl=60) # 캐시 시간을 늘려 서버 부하 감소
def get_data():
    return rooms_sheet.get_all_records(), parts_sheet.get_all_records()

st.title("⚔️ 거상 파티 모집 게시판")
room_data, parts_data = get_data()

query_params = st.query_params
selected_room_id = query_params.get("room")

# [메인 화면]
for idx, room in enumerate(room_data):
    if room['Status'] == '모집중' or selected_room_id == str(room['Room_ID']):
        with st.expander(f"{room['Content_Name']} (파티장: {room['Leader_Name']})", expanded=(selected_room_id == str(room['Room_ID']))):
            st.write(f"인원: {room['Current_Players']} / {room['Max_Players']}")
            
            current_members = [p for p in parts_data if str(p['Room_ID']) == str(room['Room_ID'])]
            if current_members:
                st.table(pd.DataFrame(current_members)[['Nickname', 'Role']])
            
            domain = st.secrets.get("DOMAIN_URL", "http://localhost:8501")
            st.info(f"파티 링크: {domain}/?room={room['Room_ID']}")
            
            if st.button("참여하기", key=f"btn_{room['Room_ID']}"):
                st.session_state['selected_room'] = room['Room_ID']
                st.rerun()
            
            if st.session_state.get('selected_room') == room['Room_ID']:
                nickname = st.text_input("캐릭터명", key=f"nick_{room['Room_ID']}")
                available_roles = [r for r in ROLES.get(room['Content_Name'], []) if r not in [p['Role'] for p in current_members]]
                role = st.selectbox("역할 선택", available_roles, key=f"role_{room['Room_ID']}")
                
                if st.button("등록 완료", key=f"ok_{room['Room_ID']}"):
                    # 1. 시트 업데이트 (비동기 처리 느낌)
                    parts_sheet.append_row([room['Room_ID'], nickname, role])
                    new_count = int(room['Current_Players']) + 1
                    rooms_sheet.update_cell(idx + 2, 5, new_count)
                    
                    # 2. 마감 시 처리
                    if new_count >= int(room['Max_Players']):
                        rooms_sheet.update_cell(idx + 2, 6, "마감")
                        # 3. 데이터 다시 읽지 않고 기존 데이터 활용하여 알림
                        parts_data.append({'Room_ID': room['Room_ID'], 'Nickname': nickname, 'Role': role})
                        send_discord_webhook(room['Room_ID'], room['Content_Name'], room['Leader_Name'], parts_data)
                    
                    st.cache_data.clear() # 캐시 비우고 재갱신
                    st.session_state['selected_room'] = None
                    st.rerun()

# [사이드바]
with st.sidebar:
    st.header("👑 파티 생성")
    content = st.selectbox("콘텐츠 선택", list(ROLES.keys()))
    leader = st.text_input("파티장 닉네임")
    if st.button("방 생성"):
        new_id = len(room_data) + 1
        rooms_sheet.append_row([new_id, content, leader, len(ROLES[content]), 1, "모집중"])
        parts_sheet.append_row([new_id, leader, "파티장"])
        st.cache_data.clear()
        st.rerun()
