import streamlit as st
import requests
import pandas as pd
import datetime

JST = datetime.timezone(datetime.timedelta(hours=9))

ROOM_PROFILE_API = "https://www.showroom-live.com/api/room/profile?room_id={room_id}"

# -------------------------------
# safe_get（既存そのまま）
# -------------------------------
def _safe_get(data, keys, default_value=None):
    temp = data
    for key in keys:
        if isinstance(temp, dict) and key in temp:
            temp = temp.get(key)
        else:
            return default_value
    if temp is None:
        return default_value
    return temp


# -------------------------------
# 既存関数（そのまま）
# -------------------------------
def get_room_profile(room_id):
    try:
        r = requests.get(ROOM_PROFILE_API.format(room_id=room_id), timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def get_event_room_list_data(event_id):
    if not event_id:
        return []

    rooms = []
    page = 1
    while True:
        r = requests.get(
            f"https://www.showroom-live.com/api/event/room_list?event_id={event_id}&p={page}",
            timeout=10
        )
        if r.status_code != 200:
            break

        data = r.json()
        room_list = data.get("room_list", [])
        if not room_list:
            break

        rooms.extend(room_list)
        page += 1

    return rooms


def get_event_id_from_event_liver_list(room_id):
    try:
        df = pd.read_csv(
            "https://mksoul-pro.com/showroom/file/event_liver_list.csv",
            header=None,
            names=["room_id", "event_id"],
            dtype=str
        )
        row = df[df["room_id"] == str(room_id)]
        if not row.empty:
            return row.iloc[0]["event_id"]
        return None
    except Exception:
        return None


def is_mksoul_room(room_id):
    try:
        df = pd.read_csv(
            "https://mksoul-pro.com/showroom/file/room_list.csv",
            dtype=str
        )
        room_ids = set(df.iloc[1:, 0].astype(str).str.strip())
        return str(room_id) in room_ids
    except Exception:
        return False


def get_room_event_meta(profile_event_id, room_id):
    checked_event_ids = []

    if profile_event_id:
        checked_event_ids.append(profile_event_id)

    fallback_event_id = get_event_id_from_event_liver_list(room_id)
    if fallback_event_id:
        checked_event_ids.append(fallback_event_id)

    for event_id in checked_event_ids:
        rooms = get_event_room_list_data(event_id)
        for r in rooms:
            if str(r.get("room_id")) == str(room_id):
                return "-", r.get("organizer_id")

    return "-", "-"


def resolve_organizer_name(organizer_id, official_status, room_id):
    if official_status != "公式":
        return "フリー"

    if is_mksoul_room(room_id):
        return "MKsoul"

    if organizer_id in (None, "-", 0):
        return "-"

    organizer_id_str = str(int(organizer_id))

    try:
        df = pd.read_csv(
            "https://mksoul-pro.com/showroom/file/organizer_list.csv",
            engine="python"
        )
        df.columns = ["organizer_id", "organizer_name"]
        row = df[df["organizer_id"].astype(str) == organizer_id_str]
        if not row.empty:
            return row.iloc[0]["organizer_name"]
        return "-"
    except Exception:
        return "-"


# -------------------------------
# UI
# -------------------------------
st.set_page_config(page_title="オーガナイザー確認", layout="centered")
st.title("🎤 オーガナイザー確認")

room_id = st.text_input("ルームID", placeholder="例：507948")

if room_id.isdigit():
    profile = get_room_profile(room_id)

    if profile:
        room_name = profile.get("room_name", "このルーム")
        official_status = "公式" if profile.get("is_official") else "フリー"

        profile_event_id = _safe_get(profile, ["event", "event_id"], None)

        _, organizer_id = get_room_event_meta(profile_event_id, room_id)
        organizer_name = resolve_organizer_name(
            organizer_id, official_status, room_id
        )

        if organizer_name == "フリー":
            st.success(f"{room_name}はフリーライバーです。")
        elif organizer_name == "-":
            st.warning(f"{room_name}のオーガナイザーは分かりませんでした。")
        else:
            st.success(f"{room_name}のオーガナイザーは「{organizer_name}」です。")
