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

for idx, room in enumerate(room_data):
    if room['Status'] == '모집중' or selected_room_id == str(room['Room_ID']):
        with st.expander(f"{room['Content_Name']} (파티장: {room['Leader_Name']})", expanded=(selected_room_id == str(room['Room_ID']))):
            st.write(f"인원: {room['Current_Players']} / {room['Max_Players']}")
            
            current_members = [p for p in parts_data if str(p['Room_ID']) == str(room['Room_ID'])]
            if current_members:
                st.table(pd.DataFrame(current_members)[['Nickname', 'Role']])
            
            # [기능: 참여하기 / 탈퇴하기 / 방 삭제]
            tab1, tab2 = st.tabs(["참여/탈퇴", "방 관리"])
            
            with tab1:
                nickname = st.text_input("닉네임 입력 (참여/탈퇴 시 사용)", key=f"nick_{room['Room_ID']}")
                
                # 참여하기 로직
                available_roles = [r for r in ROLES.get(room['Content_Name'], []) if r not in [p['Role'] for p in current_members]]
                role = st.selectbox("역할 선택", available_roles, key=f"role_{room['Room_ID']}")
                if st.button("참여하기", key=f"join_{room['Room_ID']}"):
                    parts_sheet.append_row([room['Room_ID'], nickname, role])
                    rooms_sheet.update_cell(idx + 2, 5, int(room['Current_Players']) + 1)
                    if int(room['Current_Players']) + 1 >= int(room['Max_Players']):
                        rooms_sheet.update_cell(idx + 2, 6, "마감")
                        send_discord_webhook(room['Room_ID'], room['Content_Name'], room['Leader_Name'], parts_sheet.get_all_records())
                    st.cache_data.clear(); st.rerun()
                
                # [기능: 탈퇴하기]
                if st.button("탈퇴하기", key=f"leave_{room['Room_ID']}"):
                    for i, p in enumerate(reversed(parts_sheet.get_all_records())):
                        if str(p['Room_ID']) == str(room['Room_ID']) and p['Nickname'] == nickname:
                            parts_sheet.delete_rows(len(parts_sheet.get_all_records()) - i)
                            rooms_sheet.update_cell(idx + 2, 5, int(room['Current_Players']) - 1)
                            st.success(f"{nickname}님 탈퇴 완료"); st.cache_data.clear(); st.rerun()

            with tab2:
                # [기능: 방 삭제]
                del_name = st.text_input("파티장 닉네임 확인", key=f"del_{room['Room_ID']}")
                if st.button("방 삭제하기", key=f"delete_{room['Room_ID']}"):
                    if del_name == room['Leader_Name']:
                        rooms_sheet.delete_rows(idx + 2)
                        for i, p in enumerate(reversed(parts_sheet.get_all_records())):
                            if str(p['Room_ID']) == str(room['Room_ID']):
                                parts_sheet.delete_rows(len(parts_sheet.get_all_records()) - i)
                        st.cache_data.clear(); st.rerun()

with st.sidebar:
    st.header("👑 파티 생성")
    content = st.selectbox("콘텐츠 선택", list(ROLES.keys()))
    leader = st.text_input("파티장 닉네임")
    if st.button("방 생성"):
        new_id = len(room_data) + 1
        rooms_sheet.append_row([new_id, content, leader, len(ROLES[content]), 1, "모집중"])
        parts_sheet.append_row([new_id, leader, "파티장"])
        st.cache_data.clear(); st.rerun()
