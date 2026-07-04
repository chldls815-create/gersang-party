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

# [인증] 구글 시트 연결
if "GSPREAD_JSON" in st.secrets:
    creds_dict = json.loads(st.secrets["GSPREAD_JSON"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
else:
    creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)

client = gspread.authorize(creds)
sheet = client.open("거상파티관리")
rooms_sheet = sheet.worksheet("Rooms")
parts_sheet = sheet.worksheet("Participants")

# [디스코드 알림 전송 함수]
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

# [데이터 세척 및 로드] 공백 에러 방지
def clean_records(records):
    cleaned = []
    for r in records:
        # 키(컬럼명)와 값의 앞뒤 공백을 제거하여 정규화
        c = {str(k).strip(): (str(v).strip() if v is not None else '') for k, v in r.items()}
        if c.get('Room_ID'):
            cleaned.append(c)
    return cleaned

@st.cache_data(ttl=1)
def get_data():
    rooms = clean_records(rooms_sheet.get_all_records())
    parts = clean_records(parts_sheet.get_all_records())
    return rooms, parts

st.title("⚔️ 거상 파티 모집 게시판")
room_data, parts_data = get_data()

# URL 파라미터 확인 (링크로 들어온 경우)
query_params = st.query_params
selected_room_id = query_params.get("room")

# [메인 화면 - 방 목록 출력]
for room in room_data:
    room_id_str = str(room.get('Room_ID'))
    is_expanded = (selected_room_id == room_id_str)
    
    if room.get('Status') == '모집중' or is_expanded:
        with st.expander(f"{room.get('Content_Name')} (방번호: {room_id_str} | 파티장: {room.get('Leader_Name')})", expanded=is_expanded):
            
            # 1. 실시간 파티원 목록 필터링
            current_members = [p for p in parts_data if str(p.get('Room_ID')) == room_id_str]
            current_count = len(current_members)
            max_count = int(room.get('Max_Players', 0))
            
            st.write(f"**모집 상태:** {room.get('Status')} | **현재 인원:** {current_count} / {max_count}")
            
            # 2. 파티원 닉네임 및 역할 표(Table) 즉시 표시
            if current_members:
                df = pd.DataFrame(current_members)[['Nickname', 'Role']]
                df.columns = ['캐릭터명', '담당 역할']
                st.table(df)
            
            # 3. 파티 공유 링크 표시
            domain = st.secrets.get("DOMAIN_URL", "https://gersang-party-jhdzpnqxfbmpazvhaidmwu.streamlit.app")
            st.caption("👇 아래 링크를 복사해서 파티원들에게 공유하세요!")
            st.code(f"{domain}/?room={room_id_str}", language=None)
            
            # 4. 역할 필터링 (파티장 제외 + 이미 누군가 선택한 역할 제외)
            taken_roles = [p.get('Role') for p in current_members]
            available_roles = [r for r in ROLES.get(room.get('Content_Name'), []) if r != "파티장" and r not in taken_roles]
            
            tab1, tab2 = st.tabs(["⚔️ 파티 참여", "⚙️ 방 관리"])
            
            # [참여 탭]
            with tab1:
                if available_roles:
                    nickname = st.text_input("본인 캐릭터명 입력", key=f"nick_{room_id_str}")
                    role = st.selectbox("남은 역할 선택", available_roles, key=f"role_{room_id_str}")
                    
                    if st.button("참여 완료하기", key=f"join_{room_id_str}", type="primary"):
                        if nickname.strip() and role:
                            # 1) 참가자 시트에 추가
                            parts_sheet.append_row([room_id_str, nickname.strip(), role])
                            
                            # 2) 방 시트의 정확한 위치를 찾아 인원 업데이트
                            cell = rooms_sheet.find(room_id_str, in_column=1)
                            if cell:
                                new_count = current_count + 1
                                rooms_sheet.update_cell(cell.row, 5, new_count)
                                
                                # 정원이 다 찼을 때 마감 처리 및 디스코드 알림
                                if new_count >= max_count:
                                    rooms_sheet.update_cell(cell.row, 6, "마감")
                                    # 최신 명단을 포함하여 알림 발송
                                    updated_parts = clean_records(parts_sheet.get_all_records())
                                    send_discord_webhook(room_id_str, room.get('Content_Name'), room.get('Leader_Name'), new_count, max_count, "마감", updated_parts)
                            
                            # 3) 캐시 및 URL 파라미터 강제 초기화 후 메인화면 복귀
                            st.cache_data.clear()
                            st.query_params.clear() # 주소창 ?room=X 삭제 (메인화면으로 복귀하는 핵심)
                            st.rerun()
                        else:
                            st.warning("캐릭터명을 정확히 입력해주세요.")
                else:
                    st.success("🎉 모든 모집 역할이 마감되었습니다!")

            # [방 관리 탭]
            with tab2:
                del_name = st.text_input("파티장 캐릭터명 확인", key=f"del_{room_id_str}")
                if st.button("방 삭제하기", key=f"delete_{room_id_str}"):
                    if del_name.strip() == room.get('Leader_Name'):
                        cell = rooms_sheet.find(room_id_str, in_column=1)
                        if cell:
                            rooms_sheet.delete_rows(cell.row)
                        st.cache_data.clear()
                        st.query_params.clear()
                        st.rerun()
                    else:
                        st.error("파티장 캐릭터명이 일치하지 않습니다.")

# [사이드바 - 방 생성]
with st.sidebar:
    st.header("👑 신규 파티 생성")
    content = st.selectbox("콘텐츠 선택", list(ROLES.keys()))
    leader = st.text_input("파티장 캐릭터명")
    
    if st.button("파티방 만들기", type="primary"):
        if leader.strip():
            new_id = len(room_data) + 1
            max_p = len(ROLES[content])
            
            # 방 생성 및 파티장 자동 참가 등록
            rooms_sheet.append_row([new_id, content, leader.strip(), max_p, 1, "모집중"])
            parts_sheet.append_row([new_id, leader.strip(), "파티장"])
            
            # 디스코드 생성 알림
            updated_parts = clean_records(parts_sheet.get_all_records())
            send_discord_webhook(new_id, content, leader.strip(), 1, max_p, "생성", updated_parts)
            
            st.cache_data.clear()
            st.query_params.clear()
            st.rerun()
        else:
            st.warning("파티장 캐릭터명을 입력하세요.")
