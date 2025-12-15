import streamlit as st
import requests
import pandas as pd
import datetime
import pytz

JST = pytz.timezone("Asia/Tokyo")

# ----------------------------------------------------------------------
# API
# ----------------------------------------------------------------------
def get_room_profile(room_id):
    try:
        r = requests.get(
            f"https://www.showroom-live.com/api/room/profile?room_id={room_id}",
            timeout=10
        )
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


# ----------------------------------------------------------------------
# 既存関数（変更なし）
# ----------------------------------------------------------------------
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
                created_at = r.get("created_at")
                organizer_id = r.get("organizer_id")

                created_str = "-"
                if created_at:
                    created_str = datetime.datetime.fromtimestamp(
                        created_at, JST
                    ).strftime("%Y/%m/%d %H:%M:%S")

                return created_str, organizer_id

    return "-", "-"


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

        if df.shape[1] == 1:
            split = df.iloc[:, 0].astype(str).str.split(r"\s+", n=1, expand=True)
            split.columns = ["organizer_id", "organizer_name"]
            df = split
        else:
            df.columns = ["organizer_id", "organizer_name"]

        df["organizer_id"] = df["organizer_id"].astype(str).str.strip()
        df["organizer_name"] = df["organizer_name"].astype(str).str.strip()

        row = df[df["organizer_id"] == organizer_id_str]
        if not row.empty:
            return row.iloc[0]["organizer_name"]

        return "-"
    except Exception:
        return "-"


# ----------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------
st.set_page_config(page_title="オーガナイザー確認", layout="centered")

st.markdown(
    """
    <style>
    .wrap { max-width: 420px; margin: auto; }
    .box {
        margin-top: 20px;
        padding: 20px;
        border-radius: 12px;
        background: #f9fafb;
        text-align: center;
        font-size: 16px;
        line-height: 1.8;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown("<div class='wrap'>", unsafe_allow_html=True)
st.markdown("## 🎤 オーガナイザー確認")

room_id = st.text_input("ルームID", placeholder="例：507948", label_visibility="collapsed")

if room_id.isdigit():
    profile = get_room_profile(room_id)

    if profile:
        room_name = profile.get("room_name", "このルーム")
        official_status = "公式" if profile.get("is_official") else "フリー"

        # ★ ここが致命的に抜けていた
        profile_event = profile.get("event") or {}
        profile_event_id = profile_event.get("event_id")

        _, organizer_id = get_room_event_meta(profile_event_id, room_id)
        organizer_name = resolve_organizer_name(
            organizer_id, official_status, room_id
        )

        if organizer_name == "フリー":
            st.markdown(
                f"""
                <div class="box">
                <strong>{room_name}</strong>は、<br>
                フリーライバーです。
                </div>
                """,
                unsafe_allow_html=True
            )
        elif organizer_name == "-":
            st.markdown(
                f"""
                <div class="box">
                <strong>{room_name}</strong>のオーガナイザーですが、<br>
                すみません、<br>
                わかりませんでした･･･
                </div>
                """,
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f"""
                <div class="box">
                <strong>{room_name}</strong>のオーガナイザーは、<br>
                <strong>{organizer_name}</strong><br>
                かと思います。
                </div>
                """,
                unsafe_allow_html=True
            )
    else:
        st.error("ルーム情報を取得できませんでした。")

st.markdown("</div>", unsafe_allow_html=True)
