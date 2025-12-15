import streamlit as st
import requests
import pandas as pd

# ----------------------------------------------------------------------
# 基本設定
# ----------------------------------------------------------------------
st.set_page_config(page_title="オーガナイザー確認", layout="centered")

# ----------------------------------------------------------------------
# API
# ----------------------------------------------------------------------
def get_room_profile(room_id):
    try:
        url = f"https://www.showroom-live.com/api/room/profile?room_id={room_id}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def get_event_room_list(event_id):
    if not event_id:
        return []

    rooms = []
    page = 1
    while True:
        url = f"https://www.showroom-live.com/api/event/room_list?event_id={event_id}&p={page}"
        r = requests.get(url, timeout=10)
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
# 条件① profile.event.event_id
# ----------------------------------------------------------------------
def organizer_from_profile_event(profile, room_id):
    event = profile.get("event")
    if not isinstance(event, dict):
        return None

    event_id = event.get("event_id")
    if not event_id:
        return None

    rooms = get_event_room_list(event_id)
    for r in rooms:
        if str(r.get("room_id")) == str(room_id):
            return r.get("organizer_id")

    return None


# ----------------------------------------------------------------------
# 条件② MKsoul room_list.csv
# ----------------------------------------------------------------------
def is_mksoul_room(room_id):
    try:
        df = pd.read_csv("https://mksoul-pro.com/showroom/file/room_list.csv")
        return str(room_id) in df.iloc[:, 0].astype(str).values
    except Exception:
        return False


# ----------------------------------------------------------------------
# 条件③ event_liver_list.csv
# ----------------------------------------------------------------------
def organizer_from_event_liver_list(room_id):
    try:
        df = pd.read_csv(
            "https://mksoul-pro.com/showroom/file/event_liver_list.csv",
            header=None
        )
        row = df[df.iloc[:, 0].astype(str) == str(room_id)]
        if row.empty:
            return None

        event_id = row.iloc[0, 1]
        rooms = get_event_room_list(event_id)
        for r in rooms:
            if str(r.get("room_id")) == str(room_id):
                return r.get("organizer_id")

        return None
    except Exception:
        return None


# ----------------------------------------------------------------------
# organizer_id → organizer_name
# ----------------------------------------------------------------------
def resolve_organizer_name(organizer_id):
    if organizer_id is None or organizer_id == 0:
        return None

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

        row = df[df["organizer_id"] == str(organizer_id)]
        if not row.empty:
            return row.iloc[0]["organizer_name"]

        return None
    except Exception:
        return None


# ----------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------
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

room_id = st.text_input(
    "ルームID",
    placeholder="例：507948",
    label_visibility="collapsed"
)

if room_id.isdigit():
    profile = get_room_profile(room_id)

    if profile:
        room_name = profile.get("room_name", "このルーム")
        is_official = profile.get("is_official", False)

        organizer_id = organizer_from_profile_event(profile, room_id)

        if organizer_id is None and is_mksoul_room(room_id):
            organizer_name = "MKsoul"
            organizer_id = -1
        else:
            if organizer_id is None:
                organizer_id = organizer_from_event_liver_list(room_id)
            organizer_name = resolve_organizer_name(organizer_id)

        # ---------------- 表示制御 ----------------
        if not is_official:
            st.markdown(
                f"""
                <div class="box">
                <strong>{room_name}</strong>は、<br>
                フリーライバーです。
                </div>
                """,
                unsafe_allow_html=True
            )
        else:
            if organizer_id == 0:
                st.markdown(
                    f"""
                    <div class="box">
                    <strong>{room_name}</strong>は、<br>
                    フリーライバーです。
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            elif organizer_name:
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
        st.error("ルーム情報を取得できませんでした。")

st.markdown("</div>", unsafe_allow_html=True)
