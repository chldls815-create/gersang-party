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

# [인증]
if "GSPREAD_JSON" in st.secrets:
    creds_dict = json.loads(st.secrets["GSPREAD_JSON"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
else:
    creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)

client = gspread.authorize(creds)
sheet = client.open("거상파티관리")
rooms_sheet = sheet.worksheet("Rooms")
parts_sheet = sheet.worksheet("Participants")

def send_discord_webhook(room_id, content_name, leader, current_players, max_players, message_type, parts_data):
    webhook_url = os.getenv("DISCORD_WEBHOOK", st.secrets.get("DISCORD_WEBHOOK", "YOUR_DISCORD_WEBHOOK_URL"))
    members = [p for p in parts_data if str(p.get('Room_ID')) == str(room_id)]
    member_list = "\n".join([f"- {m.get('Nickname', '???')} ({m.get('Role', '???')})" for m in members])
    
    embed = {
        "title": f"📢 [파티 {message_type}] {content_name}",
        "color": 15158332 if message_type == "마감" else 3066993,
        "fields": [
            {"name": "파티장", "value": leader, "inline": True},
            {"name": "인원", "value": f"{current_players}/{max_players}", "inline": True},
            {"name": "파티원 명단", "value": member_list if member_list else "없음", "inline": False}
        ]
    }
    try: requests.post(webhook_url, json={"embeds": [embed]})
    except: pass

@st.cache_data(ttl=1) # 캐시 TTL을 1초로 줄여 즉각 반영
def get_data():
    return [r for r in rooms_sheet.get_all_records() if r.get('Room_ID')], [p for p in parts_sheet.get_all_records() if p.get('Room_ID')]

st.title("⚔️ 거상 파티 모집 게시판")
room_data, parts_data = get_data()
query_params = st.query_params
selected_room_id = query_params.get("room")

for idx, room in enumerate(room_data):
    if room.get('Status') == '모집중' or selected_room_id == str(room.get('Room_ID')):
        with st.expander(f"{room.get('Content_Name')} (방:{room.get('Room_ID')})", expanded=(selected_room_id == str(room.get('Room_ID')))):
            # [인원 및 파티원 명단 실시간 표시]
            current_members = [p for p in parts_data if str(p.get('Room_ID')) == str(room.get('Room_ID'))]
            st.write(f"**상태:** {room.get('Status')} | **인원:** {len(current_members)} / {room.get('Max_Players')}")
            
            if current_members:
                st.table(pd.DataFrame(current_members)[['Nickname', 'Role']])
            
            domain = st.secrets.get("DOMAIN_URL", "https://gersang-party-jhdzpnqxfbmpazvhaidmwu.streamlit.app")
            st.code(f"{domain}/?room={room.get('Room_ID')}", language=None)
            
            # [역할 선택 중복 방지 로직]
            taken_roles = [p.get('Role') for p in current_members]
            available_roles = [r for r in ROLES.get(room.get('Content_Name'), []) if r != "파티장" and r not in taken_roles]
            
            tab1, tab2 = st.tabs(["참여/탈퇴", "방 관리"])
            with tab1:
                nickname = st.text_input("닉네임", key=f"nick_{room.get('Room_ID')}")
                role = st.selectbox("역할 선택", available_roles, key=f"role_{room.get('Room_ID')}")
                
                if st.button("참여하기", key=f"join_{room.get('Room_ID')}"):
                    if nickname and role:
                        parts_sheet.append_row([room.get('Room_ID'), nickname, role])
                        new_count = len(current_members) + 1
                        rooms_sheet.update_cell(idx + 2, 5, new_count)
                        
                        if new_count >= int(room.get('Max_Players', 0)):
                            rooms_sheet.update_cell(idx + 2, 6, "마감")
                            send_discord_webhook(room.get('Room_ID'), room.get('Content_Name'), room.get('Leader_Name'), new_count, room.get('Max_Players'), "마감", parts_sheet.get_all_records())
                        
                        st.success("참여가 완료되었습니다!")
                        st.cache_data.clear() # 캐시 강제 삭제
                        st.session_state['selected_room'] = None
                        st.rerun()
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
        st.cache_data.clear(); st.rerun()
