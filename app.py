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
# [알림 함수]
def send_discord_webhook(title, content_name, leader, current_players, max_players, message_type="마감", parts_data=None):
    webhook_url = os.getenv("DISCORD_WEBHOOK", st.secrets.get("DISCORD_WEBHOOK", "YOUR_DISCORD_WEBHOOK_URL"))
    
    if message_type == "생성":
        description = "새로운 파티가 모집을 시작했습니다!"
        color = 3066993
    else:
        member_list = "\n".join([f"- {p.get('Nickname', '???')} ({p.get('Role', '???')})" for p in parts_data if str(p.get('Room_ID')) == str(title)])
        description = f"정원이 가득 찼습니다!\n\n**파티원 명단:**\n{member_list}"
        color = 15158332

    message = {"embeds": [{"title": f"📢 [파티 {message_type}] {content_name}", "description": description, "color": color, 
                          "fields": [{"name": "파티장", "value": leader, "inline": True}, {"name": "인원", "value": f"{current_players}/{max_players}", "inline": True}]}]}
    try: requests.post(webhook_url, json=message)
    except: pass

@st.cache_data(ttl=10)
def get_data():
    # 데이터 로드 시 빈 행을 걸러내고 안전하게 가져오기
    rooms = [r for r in rooms_sheet.get_all_records() if r.get('Room_ID')]
    parts = [p for p in parts_sheet.get_all_records() if p.get('Room_ID')]
    return rooms, parts

st.title("⚔️ 거상 파티 모집 게시판")
room_data, parts_data = get_data()
query_params = st.query_params
selected_room_id = query_params.get("room")

for idx, room in enumerate(room_data):
    if room.get('Status') == '모집중' or selected_room_id == str(room.get('Room_ID')):
        with st.expander(f"{room.get('Content_Name')} (파티장: {room.get('Leader_Name')})", expanded=(selected_room_id == str(room.get('Room_ID')))):
            st.write(f"인원: {room.get('Current_Players')} / {room.get('Max_Players')}")
            
            # [안전하게 데이터 필터링]
            current_members = [p for p in parts_data if str(p.get('Room_ID')) == str(room.get('Room_ID'))]
            if current_members:
                st.table(pd.DataFrame(current_members)[['Nickname', 'Role']])
            
            domain = st.secrets.get("DOMAIN_URL", "http://localhost:8501")
            st.info(f"파티 링크: {domain}/?room={room.get('Room_ID')}")
            
            tab1, tab2 = st.tabs(["참여/탈퇴", "방 관리"])
            with tab1:
                nickname = st.text_input("닉네임", key=f"nick_{room.get('Room_ID')}")
                available_roles = [r for r in ROLES.get(room.get('Content_Name'), []) if r not in [p.get('Role') for p in current_members]]
                role = st.selectbox("역할", available_roles, key=f"role_{room.get('Room_ID')}")
                if st.button("참여", key=f"join_{room.get('Room_ID')}"):
                    parts_sheet.append_row([room.get('Room_ID'), nickname, role])
                    new_count = int(room.get('Current_Players')) + 1
                    rooms_sheet.update_cell(idx + 2, 5, new_count)
                    if new_count >= int(room.get('Max_Players')):
                        rooms_sheet.update_cell(idx + 2, 6, "마감")
                        send_discord_webhook(room.get('Room_ID'), room.get('Content_Name'), room.get('Leader_Name'), new_count, room.get('Max_Players'), "마감", parts_sheet.get_all_records())
                    st.cache_data.clear(); st.rerun()
            with tab2:
                if st.button("방 삭제", key=f"del_{room.get('Room_ID')}"):
                    rooms_sheet.delete_rows(idx + 2)
                    st.cache_data.clear(); st.rerun()

with st.sidebar:
    st.header("👑 파티 생성")
    content = st.selectbox("콘텐츠 선택", list(ROLES.keys()))
    leader = st.text_input("파티장 닉네임")
    if st.button("방 생성"):
        new_id = len(room_data) + 1
        rooms_sheet.append_row([new_id, content, leader, len(ROLES[content]), 1, "모집중"])
        parts_sheet.append_row([new_id, leader, "파티장"])
        send_discord_webhook(new_id, content, leader, 1, len(ROLES[content]), "생성")
        st.cache_data.clear(); st.rerun()
