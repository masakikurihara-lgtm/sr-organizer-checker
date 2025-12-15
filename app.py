import streamlit as st
import requests
import pandas as pd
import io
import datetime
from dateutil import parser
import numpy as np
import re
import json

JST = datetime.timezone(datetime.timedelta(hours=9))

# Streamlit の初期設定
st.set_page_config(
    page_title="オーガナイザー確認"
)

# --- 定数設定 ---
ROOM_LIST_URL = "https://mksoul-pro.com/showroom/file/room_list.csv"
ROOM_PROFILE_API = "https://www.showroom-live.com/api/room/profile?room_id={room_id}"
API_EVENT_ROOM_LIST_URL = "https://www.showroom-live.com/api/event/room_list"
HEADERS = {}

GENRE_MAP = {
    112: "ミュージック", 102: "アイドル", 103: "タレント", 104: "声優",
    105: "芸人", 107: "バーチャル", 108: "モデル", 109: "俳優",
    110: "アナウンサー", 113: "クリエイター", 200: "ライバー",
}

# --- ユーティリティ関数 ---

def _safe_get(data, keys, default_value=None):
    """ネストされた辞書から安全に値を取得するヘルパー関数"""
    temp = data
    for key in keys:
        if isinstance(temp, dict) and key in temp:
            temp = temp.get(key)
        else:
            return default_value
    # 取得した値がNone、空の文字列、またはNaNの場合もデフォルト値を返す
    if temp is None or (isinstance(temp, str) and temp.strip() == "") or (isinstance(temp, float) and pd.isna(temp)):
        return default_value
    return temp

def get_official_mark(room_id):
    """簡易的な公/フ判定"""
    try:
        room_id = int(room_id)
        if room_id < 100000:
            return "公"
        elif room_id >= 100000:
            return "フ"
        else:
            return "不明"
    except (TypeError, ValueError):
        return "不明"


def get_room_profile(room_id):
    """ライバー（ルーム）プロフィール情報APIからデータを取得する"""
    url = ROOM_PROFILE_API.format(room_id=room_id)
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException:
        return None


def get_monthly_fan_info(room_id, ym):
    url = "https://www.showroom-live.com/api/active_fan/users"
    params = {
        "room_id": room_id,
        "ym": ym,
        "offset": 0,
        "limit": 1
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        return (
            data.get("total_user_count", "-"),
            data.get("fan_power", "-")
        )
    except Exception:
        return "-", "-"


def get_excluded_avatar_ids():
    url = "https://mksoul-pro.com/tool/pr-liver-update-avatar/excluded_avatar_ids.txt"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return set(line.strip() for line in r.text.splitlines() if line.strip().isdigit())
    except Exception:
        return set()


def count_valid_avatars(profile_data):
    avatar_list = _safe_get(profile_data, ["avatar", "list"], [])
    if not isinstance(avatar_list, list):
        return "-"

    excluded_ids = get_excluded_avatar_ids()
    count = 0

    for url in avatar_list:
        m = re.search(r'/avatar/(\d+)\.png', url)
        if m and m.group(1) not in excluded_ids:
            count += 1

    return count


def get_room_event_meta(profile_event_id, room_id):
    """
    ルーム作成日時・オーガナイザーID取得
    条件① profile.event.event_id
    条件③ event_liver_list.csv
    """
    checked_event_ids = []

    # --- 条件① ---
    if profile_event_id:
        checked_event_ids.append(profile_event_id)

    # --- 条件③ ---
    fallback_event_id = get_event_id_from_event_liver_list(room_id)
    if fallback_event_id:
        checked_event_ids.append(fallback_event_id)

    # --- イベントID候補を順に試す ---
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

    # --- 条件④ ---
    return "-", "-"


def resolve_organizer_name(organizer_id, official_status, room_id):
    """
    オーガナイザーIDに基づいてオーガナイザー名を解決する。
    オーガナイザーリストに見つからない場合、「わかりませんでした<(_ _*)>」を返す。
    """
    NOT_FOUND_MSG = "わかりませんでした<(_ _*)>"

    # --- フリー ---
    if official_status != "公式":
        return "フリー"

    # --- 条件②：MKsoul ---
    if is_mksoul_room(room_id):
        return "MKsoul"

    # --- 条件①：既存オーガナイザー ---
    if organizer_id in (None, "-", 0):
        # 💡 修正点: ハイフンの場合も「わかりませんでした<(_ _*)>」を返す
        return NOT_FOUND_MSG

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

        # 👈 修正: オーガナイザーリストに見つからない場合は指定の文字列を返す
        return NOT_FOUND_MSG

    except Exception:
        # 👈 修正: CSV読み込みなどのエラーが発生した場合も指定の文字列を返す
        return NOT_FOUND_MSG


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



# --- イベント情報取得関数群 ---

def get_total_entries(event_id):
    """イベント参加者総数を取得する（これはページネーションの必要なし）"""
    params = {"event_id": event_id}
    try:
        # 1ページ目を取得して total_entries を確認
        response = requests.get(API_EVENT_ROOM_LIST_URL, headers=HEADERS, params=params, timeout=10)
        if response.status_code == 404:
            return 0
        response.raise_for_status()
        data = response.json()
        return data.get('total_entries', 0)
    except requests.exceptions.RequestException:
        return "N/A"
    except ValueError:
        return "N/A"


def get_event_room_list_data(event_id):
    """
    全参加者リストを取得する。（ページネーション対応を API のメタ情報に基づいて強化）
    """
    all_rooms = []
    page = 1 # ページカウンター ('p' パラメーターの値)
    count = 50 # 1ページあたりの取得件数（SHOWROOM APIの標準値）
    max_pages = 50 # 無限ループ防止のため最大ページ数を設定 (50 * 50 = 2500ルームまで取得を試みる)
    
    # ページネーション制御用のフラグ
    has_next_page = True
    
    while page <= max_pages and has_next_page:
        params = {"event_id": event_id, "p": page, "count": count} 
        try:
            # ページごとにAPIをリクエスト
            resp = requests.get(API_EVENT_ROOM_LIST_URL, headers=HEADERS, params=params, timeout=15)
            
            if resp.status_code == 404:
                # 404エラーの場合はイベントIDが存在しないか終了している
                break
            
            resp.raise_for_status()
            data = resp.json()
            
            current_page_rooms = []
            
            # APIレスポンスからリストデータを抽出
            if isinstance(data, dict):
                # 複数のキー名からルームリストを取得
                for k in ('list', 'room_list', 'event_entry_list', 'entries', 'data', 'event_list'):
                    if k in data and isinstance(data[k], list):
                        current_page_rooms = data[k]
                        break
                
                # --- ★ ページネーション制御の主要な修正点 ★ ---
                next_page = data.get('next_page')
                current_page = data.get('current_page')
                last_page = data.get('last_page')
                
                # next_page が None または last_page を超えている場合は、次のページがないと判断
                if next_page is None or (last_page is not None and next_page > last_page):
                    has_next_page = False
                
            elif isinstance(data, list):
                # リスト形式で返ってきた場合（非推奨だが念のため対応）
                current_page_rooms = data
                # リスト形式の場合は、リストの長さで次のページがあるかを判断（APIの仕様次第で不確実）
                if len(current_page_rooms) < count:
                    has_next_page = False
            else:
                # データ形式が不正
                break

            if not current_page_rooms:
                # ルームリストが空であれば、これ以上データがないと判断してループ終了
                break

            all_rooms.extend(current_page_rooms)
            
            # next_page 情報が取れていればそれを利用、取れていなければページカウンターをインクリメント
            if has_next_page:
                page = page + 1 # 次のページへ

        except Exception as e:
            # ネットワークエラーなどで中断
            print(f"イベントリスト取得エラー: Event ID {event_id}, Page {page}, Error: {e}")
            break
            
    return all_rooms

def get_event_participants_info(event_id, target_room_id, limit=10):
    """
    イベント参加ルーム情報・状況APIから必要な情報を抽出する。
    ターゲットルームの順位、ポイント、レベルを確実に取得する。（検索ロジックを最終強化）
    """
    # ターゲットルームIDを文字列に統一（APIのJSON内のID型と合わせるため）
    target_room_id_str = str(target_room_id).strip()
    
    if not event_id:
        return {"total_entries": "-", "rank": "-", "point": "-", "level": "-", "top_participants": []}

    # 全参加者リストを取得（全ページ分を取得するロジックを信頼する）
    room_list_data = get_event_room_list_data(event_id)
    total_entries = get_total_entries(event_id)
    current_room_data = None
    
    # --- 🎯 ターゲットルームの情報を、取得できたリスト全体から確実に探す（修正ロジック） ---
    # 上位10件以降で見つからない問題を解決するため、全リストを探索
    for room in room_list_data:
        # room_id が存在し、文字列化したものがターゲットIDと一致するか確認
        room_id_in_list = room.get("room_id")
        if room_id_in_list is not None and str(room_id_in_list).strip() == target_room_id_str:
            current_room_data = room
            break # 見つけたらすぐにループを抜ける
            
    # --- 🎯 ターゲットルームの参加状況を確定 ---
    rank = None
    point = None
    level = None
    
    if current_room_data:
        # _safe_get を使用して安全に値を取得
        rank = _safe_get(current_room_data, ["rank"], default_value=None)
        
        point = _safe_get(current_room_data, ["point"], default_value=None)
        if point is None:
            point = _safe_get(current_room_data, ["score"], default_value=None)
        
        level = _safe_get(current_room_data, ["event_entry", "quest_level"], default_value=None)
        if level is None:
            level = _safe_get(current_room_data, ["entry_level"], default_value=None)
        if level is None:
            level = _safe_get(current_room_data, ["event_entry", "level"], default_value=None)
    
    # 取得結果の None を表示用のハイフンに変換 (0や有効な値はそのまま残る)
    rank = "-" if rank is None else rank
    point = "-" if point is None else point
    level = "-" if level is None else level
    # ------------------------------------------------------------------------------------

    # --- 上位10ルームのリストを作成し、エンリッチメント処理に進む ---
    top_participants = room_list_data
    if top_participants:
        # point/score は文字列またはNoneの可能性があるため、intにキャストしてソート
        top_participants.sort(key=lambda x: int(str(x.get('point', x.get('score', 0)) or 0)), reverse=True)
    
    # 上位10件に制限する（表示用）
    top_participants_for_display = top_participants[:limit]


    # ✅ 上位10ルームのプロフィール情報を取得し、データをエンリッチ（統合）
    enriched_participants = []
    for participant in top_participants_for_display:
        room_id = participant.get('room_id')
        
        # 取得必須のキーを初期化（Noneで初期化）
        for key in ['room_level_profile', 'show_rank_subdivided', 'follower_num', 'live_continuous_days', 'is_official_api']: 
            participant[key] = None
            
        if room_id:
            # プロフィールAPIへの呼び出し
            profile = get_room_profile(room_id)
            if profile:
                # プロフィールAPIから取得した「ルームレベル」を 'room_level_profile' として格納
                participant['room_level_profile'] = _safe_get(profile, ["room_level"], None)
                participant['show_rank_subdivided'] = _safe_get(profile, ["show_rank_subdivided"], None)
                participant['follower_num'] = _safe_get(profile, ["follower_num"], None)
                participant['live_continuous_days'] = _safe_get(profile, ["live_continuous_days"], None)
                participant['is_official_api'] = _safe_get(profile, ["is_official"], None)
                
                if not participant.get('room_name'):
                    participant['room_name'] = _safe_get(profile, ["room_name"], f"Room {room_id}")
        
        # イベントの「レベル」を取得 ('event_entry.quest_level' またはその他のキーから)
        participant['quest_level'] = _safe_get(participant, ["event_entry", "quest_level"], None)
        if participant['quest_level'] is None:
            participant['quest_level'] = _safe_get(participant, ["entry_level"], None)
        if participant['quest_level'] is None:
            participant['quest_level'] = _safe_get(participant, ["event_entry", "level"], None)

        # 最終的に quest_level がセットされていない場合、ここでキーを追加（DataFrame化でエラーが出ないように）
        if 'quest_level' not in participant:
            participant['quest_level'] = None

        enriched_participants.append(participant)

    # 応答に必要な情報を返す
    return {
        "total_entries": total_entries if isinstance(total_entries, int) and total_entries > 0 else "-",
        "rank": rank,
        "point": point,
        "level": level, # ターゲットルームのレベル
        "top_participants": enriched_participants, # エンリッチされたリストを返す
    }
# --- イベント情報取得関数群ここまで ---


def display_room_status(profile_data, input_room_id):
    """取得したルームプロフィールデータとイベントデータを表示する"""

    # ★ 取得時刻表示（JST）
    # st.caption(
    #     f"（取得時刻: {datetime.datetime.now(JST).strftime('%Y/%m/%d %H:%M:%S')} 現在）"
    # )

    # st.caption(
    #      f"AIが情報取得の上判断しています（※誤る可能性もあります）"
    # )

    st.caption(
        f"""※ AIが情報収集の上総合的に判断しています  
    ※ 稀に誤る可能性もあります"""
    )
    
    # データを安全に取得
    room_name = _safe_get(profile_data, ["room_name"], "取得失敗")
    room_level = _safe_get(profile_data, ["room_level"], "-") # これはプロフィールのルームレベル
    show_rank = _safe_get(profile_data, ["show_rank_subdivided"], "-")
    next_score = _safe_get(profile_data, ["next_score"], "-")
    prev_score = _safe_get(profile_data, ["prev_score"], "-")
    follower_num = _safe_get(profile_data, ["follower_num"], "-")
    live_continuous_days = _safe_get(profile_data, ["live_continuous_days"], "-")
    is_official = _safe_get(profile_data, ["is_official"], None)
    genre_id = _safe_get(profile_data, ["genre_id"], None)
    event = _safe_get(profile_data, ["event"], {})

    # 加工・整形
    official_status = "公式" if is_official is True else "フリー" if is_official is False else "-"
    genre_name = GENRE_MAP.get(genre_id, f"その他 ({genre_id})" if genre_id else "-")
    
    room_url = f"https://www.showroom-live.com/room/profile?room_id={input_room_id}"
    
    
    # --- 💡 カスタムCSSの定義（既存と新規の分離） ---
    custom_styles = """
    <style>
    /* 全体のフォント統一と余白調整 */
    h3 { 
        margin-top: 20px; 
        padding-top: 10px; 
        border-bottom: none; 
    }

    h4.midashi-1 { 
        padding: 0.5rem 0px 0.5rem;
    }

    /* タイトル領域のスタイル */
    .room-title-container {
        padding: 15px 20px;
        margin-bottom: 20px;
        border-radius: 8px;
        background-color: #f0f2f6; 
        border: 1px solid #e6e6e6;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
        display: flex;
        align-items: center;
    }
    .room-title-container h1 {
        margin: 0;
        padding: 0;
        line-height: 1.2;
        font-size: 28px; 
    }
    .room-title-container .title-icon {
        font-size: 30px; 
        margin-right: 15px;
        color: #ff4b4b; 
    }
    .room-title-container a {
        text-decoration: none; 
        color: #1c1c1c; 
    }
    
    /* 🚀 ルーム基本情報のカスタムメトリック用スタイル (元のコードから維持) */
    .custom-metric-container {
        margin-bottom: 15px; 
        padding: 5px 0;
    }
    .metric-label {
        font-size: 14px; 
        color: #666; 
        font-weight: 600;
        margin-bottom: 5px;
        display: block; 
    }
    .metric-value {
        font-size: 24px !important; 
        font-weight: bold;
        line-height: 1.1;
        color: #1c1c1c;
    }
    
    /* st.metric の値を強制的に揃える (イベント情報セクション用) (元のコードから維持) */
    .stMetric label {
        font-size: 14px; 
        color: #666; 
        font-weight: 600;
        margin-bottom: 5px;
        display: block; 
    }
    .stMetric > div > div:nth-child(2) > div {
        font-size: 24px !important; 
        font-weight: bold;
    }
    
    /* HTMLテーブルのスタイル (既存のイベント上位10ルーム用) */
    .stHtml .dataframe {
        border-collapse: collapse;
        margin-top: 10px; 
        width: 100%; 
        /*max-width: 1000px;*/
        min-width: 800px; 
    }
    
    /* 中央寄せラッパー (テーブル全体を中央に配置) (既存のイベント上位10ルーム用) */
    .center-table-wrapper {
        /*display: flex;*/ /* 既存のコメントアウトを維持（一切変更しない） */
        justify-content: center; 
        width: 100%;
        overflow-x: auto;
    }

    /*
    🔥🔥 イベントテーブル用CSS (既存コード): すべての th と td の text-align をセンターに設定し、優先度を最大化
    */
    
    /* ヘッダーセル (<th>) を強制的に中央寄せ */
    .stMarkdown table.dataframe th {
        text-align: center !important; 
        background-color: #e8eaf6; 
        color: #1a237e; 
        font-weight: bold;
        padding: 8px 10px; 
        /*font-size: 14px;*/
        border-top: 1px solid #c5cae9; 
        border-bottom: 1px solid #c5cae9; 
        white-space: nowrap;
    }
    
    /* データセル (<td>) を強制的に中央寄せ */
    .stMarkdown table.dataframe td {
        text-align: center !important; 
        padding: 6px 10px; 
        /*font-size: 13px;*/
        line-height: 1.4;
        border-bottom: 1px solid #f0f0f0;
        white-space: nowrap; 
    }
    
    /* ルーム名列のデータセル (<td>) のみ、テキストを左寄せに戻す（自然な表示のため） */
    /* 1列目 (ルーム名) のセルをターゲット */
    .stMarkdown table.dataframe td:nth-child(1) {
        text-align: left !important; /* ルーム名のみ左寄せに戻す */
        min-width: 450px;
        /*min-width: 100%; !important;*/
        white-space: normal !important; 
    }

    /* ルーム名列のヘッダーセル (<th>) は中央寄せを維持 */
    .stMarkdown table.dataframe th:nth-child(1) {
        text-align: center !important; 
        min-width: 450px;
        /*min-width: 100%; !important;*/
        white-space: normal !important; 
    }

    /* 2列目以降の幅調整（中央寄せはそのまま） */
    .stMarkdown table.dataframe th:nth-child(2), .stMarkdown table.dataframe td:nth-child(2), /* ルームレベル */
    .stMarkdown table.dataframe th:nth-child(4), .stMarkdown table.dataframe td:nth-child(4), /* フォロワー数 */
    .stMarkdown table.dataframe th:nth-child(5), .stMarkdown table.dataframe td:nth-child(5), /* まいにち配信 */
    .stMarkdown table.dataframe th:nth-child(9), .stMarkdown table.dataframe td:nth-child(9) { /* ポイント */
        width: 10%; 
    }

    /* 中央寄せを維持しつつ幅調整 (ランク、公式 or フリー、ルームID、順位、レベル) */
    .stMarkdown table.dataframe th:nth-child(3), .stMarkdown table.dataframe td:nth-child(3), /* ランク */
    .stMarkdown table.dataframe th:nth-child(6), .stMarkdown table.dataframe td:nth-child(6), /* 公式 or フリー */
    .stMarkdown table.dataframe th:nth-child(7), .stMarkdown table.dataframe td:nth-child(7), /* ルームID */
    .stMarkdown table.dataframe th:nth-child(8), .stMarkdown table.dataframe td:nth-child(8), /* 順位 */
    .stMarkdown table.dataframe th:nth-child(10), .stMarkdown table.dataframe td:nth-child(10) { /* レベル (最終列) */
        width: 8%;
    }
    
    /* ホバーエフェクトの維持 */
    .stMarkdown table.dataframe tbody tr:hover {
        background-color: #f7f9fd; 
    }
    
    
    /* ******************************************* */
    /* 🔥 新規追加: ルーム基本情報テーブル専用CSS (既存とクラス名を完全に分離) */
    /* ******************************************* */

    /* 基本情報テーブルのラッパー */
    .basic-info-table-wrapper {
        width: 100%;
        /*max-width: 1000px;*/ /* イベントテーブルの最大幅に合わせる */
        margin: 0 auto; /* 中央寄せを適用 */
        overflow-x: auto;
    }
    
    /* 基本情報テーブル本体 */
    .basic-info-table {
        border-collapse: collapse;
        width: 100%; 
        margin-top: 10px;
        /*table-layout: fixed;*/ /* レイアウトを固定 */
    }

    /* ヘッダーセル (<th>) - デザインを統一 (既存のe8eaf6系を使用) */
    .basic-info-table th {
        text-align: center !important; 
        background-color: #e8eaf6; 
        color: #1a237e; 
        font-weight: bold;
        padding: 8px 10px; 
        border-top: 1px solid #c5cae9; 
        border-bottom: 1px solid #c5cae9; 
        white-space: nowrap;
        width: 12.5%; /* 8項目で均等に分割 */
    }
    
    /* データセル (<td>) - デザインを統一 (既存のf0f0f0系を使用) */
    .basic-info-table td {
        text-align: center !important; 
        padding: 6px 10px; 
        line-height: 1.4;
        font-size: 22px;
        border-bottom: 1px solid #f0f0f0;
        white-space: nowrap;
        width: 12.5%; /* 8項目で均等に分割 */
        font-weight: 777; /* 値を目立たせる */
    }

    /* ホバーエフェクトの維持 */
    .basic-info-table tbody tr:hover {
        background-color: #f7f9fd; 
    }

    /* 🔵 上位ランクまで30,000以内 */
    .basic-info-highlight-upper {
        background-color: #e3f2fd !important;
        color: #0d47a1;
    }

    /* 🟡 下位ランクまで30,000以内 */
    .basic-info-highlight-lower {
        background-color: #fff9c4 !important;
        color: #795548;
    }
    
    </style>
    """
    st.markdown(custom_styles, unsafe_allow_html=True) # カスタムCSSの適用を維持

    # ヘルパー関数: カスタムスタイルを適用したメトリックを表示（未使用だが残す）
    def custom_metric(label, value):
        st.markdown(
            f'<div class="custom-metric-container">'
            f'<span class="metric-label">{label}</span>'
            f'<div class="metric-value">{value}</div>'
            f'</div>',
            unsafe_allow_html=True
        )


    # --- 1. 🎤 ルーム名/ID (タイトル領域) ---
    st.markdown(
        f'<div class="room-title-container">'
        # f'<span class="title-icon">🎤</span>'
        f'<h1 style="font-size:20px; text-align:left; color:#1f2937; line-height: 1.4;"><a href="{room_url}" target="_blank"><u>{room_name} ({input_room_id})</u></a> のオーガナイザー</h1>'
        f'</div>', 
        unsafe_allow_html=True
    ) 
    
    # st.markdown("<div style='margin-top: 16px;'></div>", unsafe_allow_html=True)
    
    # --- 2. 📊 ルーム基本情報（テーブル化の対象） ---


    # st.markdown(
    #     "<h1 style='font-size:22px; text-align:left; color:#1f2937; padding: 20px 0px 0px 0px;'>📊 ルーム基本情報-2</h1>",
    #     unsafe_allow_html=True
    # )

    now = datetime.datetime.now()
    ym_list = [
        now.strftime("%Y%m"),
        (now.replace(day=1) - datetime.timedelta(days=1)).strftime("%Y%m"),
        (now.replace(day=1) - datetime.timedelta(days=32)).strftime("%Y%m")
    ]

    fan_infos = [get_monthly_fan_info(input_room_id, ym) for ym in ym_list]
    fan_display = [f"{f} / {p}" if f != "-" else "-" for f, p in fan_infos]

    avatar_count = count_valid_avatars(profile_data)

    event_id = _safe_get(profile_data, ["event", "event_id"], None)
    created_at, organizer_id = get_room_event_meta(event_id, input_room_id)
    # resolve_organizer_name 関数が修正されている
    organizer_name = resolve_organizer_name(organizer_id, official_status, input_room_id)

    headers2 = [
        "オーガナイザー"
    ]

    values2 = [
        organizer_name
    ]

    html2 = f"""
    <div class="basic-info-table-wrapper">
    <table class="basic-info-table">
    <thead>
    <tr>{"".join(f"<th>{h}</th>" for h in headers2)}</tr>
    </thead>
    <tbody>
    <tr>{"".join(f"<td>{v}</td>" for v in values2)}</tr>
    </tbody>
    </table>
    </div>
    """

    st.markdown(html2, unsafe_allow_html=True)

    # st.caption(
    #     f"""※取得できないデータなどはハイフン表示となる場合があります。 
    # ※ライバルルームなどで、より詳細な情報や分析データ、見解等が欲しい場合はご相談ください。"""
    # )


# --- メインロジック (認証なしで実行されるように変更) ---
# st.session_stateの初期化 (認証機能に関連するものは削除)
if 'show_status' not in st.session_state:
    st.session_state.show_status = False
if 'input_room_id' not in st.session_state:
    st.session_state.input_room_id = ""


# 💖 オーガナイザー確認 タイトル表示
st.markdown(
    "<h1 style='font-size:28px; text-align:left; color:#1f2937;'>💖 オーガナイザー確認</h1>",
    unsafe_allow_html=True
)
# st.markdown("##### 🔎 ルームIDの入力")

# ルームID入力フィールド
input_room_id_current = st.text_input(
    "確認したいルームIDを入力してください:",
    placeholder="例: 123456",
    key="room_id_input_main",
    value=st.session_state.input_room_id
).strip()
    
if input_room_id_current != st.session_state.input_room_id:
    st.session_state.input_room_id = input_room_id_current
    st.session_state.show_status = False
    
# 実行ボタン
if st.button("確認する"):
    if st.session_state.input_room_id and st.session_state.input_room_id.isdigit():
        st.session_state.show_status = True
    elif st.session_state.input_room_id:
        st.error("ルームIDは数字で入力してください。")
    else:
        st.warning("ルームIDを入力してください。")
            
# st.divider()
    
# 情報の取得と表示
if st.session_state.show_status and st.session_state.input_room_id:
    with st.spinner(f"ルームID {st.session_state.input_room_id} の情報を取得中..."):
        room_profile = get_room_profile(st.session_state.input_room_id)
    if room_profile:
        # display_room_status 関数を呼び出し
        display_room_status(room_profile, st.session_state.input_room_id)
    else:
        st.error(f"ルームID {st.session_state.input_room_id} の情報を取得できませんでした。IDを確認してください。")