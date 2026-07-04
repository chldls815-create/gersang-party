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
    "나타의 시련(보통)": ["파티장", "1.속성몹_(水속성 우선)", "2.패턴몹 + 불사몹(속성 무관)","3.패턴몹 + 불사몹(속성 무관)", "4.침식몹 (속성 무관)"], 
    "나타의 시련(어려움)": ["파티장", "1.속성몹_(水속성 우선)", "2.패턴몹 + 불사몹(속성 무관)","3.패턴몹 + 불사몹(속성 무관)", "4.침식몹 (속성 무관)"]
}

scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets', "https://www.googleapis.com/auth/drive"]

if "GSPREAD_JSON" in st.secrets:
    creds_dict = json.loads(st.secrets["GSPREAD_JSON"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
else:
    creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)

client = gspread.authorize(creds)
sheet = client.open("거상파티관리")
rooms_sheet = sheet.worksheet("Rooms")
parts_sheet = sheet.worksheet("Participants")

# ---------------- [함수 영역] ----------------

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

def clean_records(records):
    cleaned = []
    for r in records:
        c = {str(k).strip(): (str(v).strip() if v is not None else '') for k, v in r.items()}
        if c.get('Room_ID'): cleaned.append(c)
    return cleaned

@st.cache_data(ttl=2)
def fetch_google_data():
    return clean_records(rooms_sheet.get_all_records()), clean_records(parts_sheet.get_all_records())

# 💡 스마트 동기화: 구글 시트 지연을 해결하기 위한 로컬 데이터 저장소
if 'local_parts' not in st.session_state: st.session_state.local_parts = []
if 'local_rooms' not in st.session_state: st.session_state.local_rooms = []
if 'deleted_rooms' not in st.session_state: st.session_state.deleted_rooms = []

def get_synced_data():
    g_rooms, g_parts = fetch_google_data()
    
    # 파티원 병합 (아직 구글에 반영안된 0.1초 전 데이터도 끌어옴)
    synced_parts = list(g_parts)
    for lp in st.session_state.local_parts:
        if not any(str(p.get('Room_ID')) == str(lp['Room_ID']) and p.get('Nickname') == lp['Nickname'] for p in synced_parts):
            synced_parts.append(lp)
            
    # 방 목록 병합 및 삭제된 방 숨김
    synced_rooms = [r for r in g_rooms if str(r.get('Room_ID')) not in st.session_state.deleted_rooms]
    for lr in st.session_state.local_rooms:
        if not any(str(r.get('Room_ID')) == str(lr['Room_ID']) for r in synced_rooms):
            synced_rooms.append(lr)
            
    return synced_rooms, synced_parts


# ---------------- [메인 화면] ----------------
st.title("⚔️ 거상 파티 모집 게시판")
room_data, parts_data = get_synced_data()

# URL 파라미터 확인
query_params = st.query_params
selected_room_id = query_params.get("room")

for room in room_data:
    room_id_str = str(room.get('Room_ID'))
    is_expanded = (selected_room_id == room_id_str)
    
    # 실시간 인원 카운트
    current_members = [p for p in parts_data if str(p.get('Room_ID')) == room_id_str]
    current_count = len(current_members)
    max_count = int(room.get('Max_Players', 0))
    status = "마감" if current_count >= max_count else room.get('Status', '모집중')
    
    if status == '모집중' or is_expanded:
        expander_title = f"[{current_count}/{max_count}] {room.get('Content_Name')} (파티장: {room.get('Leader_Name')}) - {status}"
        
        with st.expander(expander_title, expanded=is_expanded):
            # 파티원 명단 표 즉시 표시
            if current_members:
                df = pd.DataFrame(current_members)[['Nickname', 'Role']]
                df.columns = ['캐릭터명', '담당 역할']
                st.table(df)
            
            # 파티 공유 링크 표시
            domain = st.secrets.get("DOMAIN_URL", "https://gersang-party-jhdzpnqxfbmpazvhaidmwu.streamlit.app")
            st.code(f"{domain}/?room={room_id_str}", language=None)
            
            # 💡 역할 중복 방지 필터링
            taken_roles = [p.get('Role') for p in current_members]
            available_roles = [r for r in ROLES.get(room.get('Content_Name'), []) if r != "파티장" and r not in taken_roles]
            
            tab1, tab2 = st.tabs(["⚔️ 파티 참여", "⚙️ 방 관리"])
            
            # [참여하기 기능]
            with tab1:
                if available_roles:
                    nickname = st.text_input("본인 캐릭터명 입력", key=f"nick_{room_id_str}")
                    role = st.selectbox("남은 역할 선택", available_roles, key=f"role_{room_id_str}")
                    
                    if st.button("참여 완료하기", key=f"join_{room_id_str}", type="primary"):
                        if nickname.strip() and role:
                            # 1) 로컬 및 시트에 데이터 등록
                            new_part = {'Room_ID': room_id_str, 'Nickname': nickname.strip(), 'Role': role}
                            st.session_state.local_parts.append(new_part) # 즉시 갱신을 위해 메모리에 추가
                            parts_sheet.append_row([room_id_str, nickname.strip(), role])
                            
                            # 2) 마감 시 상태 업데이트 및 알림
                            new_count = current_count + 1
                            cell = rooms_sheet.find(room_id_str, in_column=1)
                            if cell:
                                rooms_sheet.update_cell(cell.row, 5, new_count)
                                if new_count >= max_count:
                                    rooms_sheet.update_cell(cell.row, 6, "마감")
                                    # 병합된 최신 명단으로 디스코드 발송
                                    _, latest_parts = get_synced_data()
                                    send_discord_webhook(room_id_str, room.get('Content_Name'), room.get('Leader_Name'), new_count, max_count, "마감", latest_parts)
                            
                            # 3) 💡 갱신 및 URL 강제 초기화 (메인화면 복귀)
                            st.cache_data.clear()
                            try: st.query_params.clear()
                            except: st.experimental_set_query_params()
                            st.rerun()
                        else:
                            st.warning("캐릭터명을 정확히 입력해주세요.")
                else:
                    st.success("🎉 모든 모집 역할이 마감되었습니다!")

            # [방 삭제 기능]
            with tab2:
                del_name = st.text_input("파티장 캐릭터명 확인", key=f"del_{room_id_str}")
                if st.button("방 삭제하기", key=f"delete_{room_id_str}"):
                    if del_name.strip() == room.get('Leader_Name'):
                        st.session_state.deleted_rooms.append(room_id_str) # 즉시 숨김 처리
                        cell = rooms_sheet.find(room_id_str, in_column=1)
                        if cell:
                            rooms_sheet.delete_rows(cell.row)
                        
                        st.cache_data.clear()
                        try: st.query_params.clear()
                        except: st.experimental_set_query_params()
                        st.rerun()
                    else:
                        st.error("파티장 캐릭터명이 일치하지 않습니다.")

# ---------------- [사이드바 - 방 생성] ----------------
with st.sidebar:
    st.header("👑 신규 파티 생성")
    content = st.selectbox("콘텐츠 선택", list(ROLES.keys()))
    leader = st.text_input("파티장 캐릭터명")
    
    if st.button("파티방 만들기", type="primary"):
        if leader.strip():
            # 안전한 방 번호 생성 (가장 큰 번호 + 1)
            max_id = max([int(r.get('Room_ID', 0)) for r in room_data]) if room_data else 0
            new_id_str = str(max_id + 1)
            max_p = len(ROLES[content])
            
            # 즉시 갱신을 위해 메모리에 추가
            st.session_state.local_rooms.append({'Room_ID': new_id_str, 'Content_Name': content, 'Leader_Name': leader.strip(), 'Max_Players': str(max_p), 'Status': '모집중'})
            st.session_state.local_parts.append({'Room_ID': new_id_str, 'Nickname': leader.strip(), 'Role': '파티장'})
            
            # 구글 시트에 등록
            rooms_sheet.append_row([new_id_str, content, leader.strip(), max_p, 1, "모집중"])
            parts_sheet.append_row([new_id_str, leader.strip(), "파티장"])
            
            # 디스코드 생성 알림
            _, latest_parts = get_synced_data()
            send_discord_webhook(new_id_str, content, leader.strip(), 1, max_p, "생성", latest_parts)
            
            st.cache_data.clear()
            try: st.query_params.clear()
            except: st.experimental_set_query_params()
            st.rerun()
        else:
            st.warning("파티장 캐릭터명을 입력하세요.")
