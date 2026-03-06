import gspread
import pandas as pd
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from pywebpush import webpush, WebPushException
import os
import json
import atexit

app = Flask(__name__, static_folder='.')
CORS(app)

# 구독자 정보 저장 파일
SUBSCRIPTIONS_FILE = 'subscriptions.json'

# VAPID 키 (환경 변수 또는 기본값)
VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY', '')
VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY', '')
VAPID_CLAIMS = {"sub": "mailto:admin@doosool.com"}

# 구독자 정보 로드/저장
def load_subscriptions():
    if os.path.exists(SUBSCRIPTIONS_FILE):
        with open(SUBSCRIPTIONS_FILE, 'r') as f:
            return json.load(f)
    return []

def save_subscriptions(subscriptions):
    with open(SUBSCRIPTIONS_FILE, 'w') as f:
        json.dump(subscriptions, f)

subscriptions = load_subscriptions()

# 환경 변수에서 JSON 인증 정보 가져오기
def get_credentials():
    google_creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
    
    if google_creds_json:
        creds_dict = json.loads(google_creds_json)
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        json_keyfile_path = "united-keyword-269601-c2ab4212683d.json"
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(json_keyfile_path, scope)
    
    return creds

# Google Sheets API 인증
creds = get_credentials()
client = gspread.authorize(creds)

# 스프레드시트 ID
spreadsheet_id = "1DmtzalSHS4HRnwLUxMQyOO0YbCiOe_8plvHnI8MIlUQ"

# 생일자 확인 함수
def check_birthdays():
    try:
        sheet = client.open_by_key(spreadsheet_id).worksheet("출석체크")
        all_data = sheet.get_all_values()
        df = pd.DataFrame(all_data[1:], columns=all_data[0])
        df_filtered = df.iloc[3:, 1:6]
        df_filtered.columns = df_filtered.iloc[0]
        df_filtered = df_filtered[1:].reset_index(drop=True)
        
        df_filtered["생년월일"] = df_filtered["생년월일"].apply(
            lambda x: datetime.strptime(x, "%y%m%d").strftime("%m-%d") if x and len(x) == 6 else ""
        )
        
        today = datetime.now().strftime("%m-%d")
        birthday_people = df_filtered[df_filtered["생년월일"] == today]
        names = birthday_people["이름"].tolist()
        
        return names
    except Exception as e:
        print(f"생일 확인 오류: {e}")
        return []

# 푸시 알림 전송
def send_push_notifications(names):
    if not names or not VAPID_PRIVATE_KEY:
        return
    
    message = f"🎉 오늘의 생일자: {', '.join(names)}님 🎂"
    
    dead_subscriptions = []
    
    for idx, subscription in enumerate(subscriptions):
        try:
            webpush(
                subscription_info=subscription,
                data=json.dumps({
                    "title": "🎂 두술 생일 알림",
                    "body": message,
                    "icon": "/icon.png",
                    "badge": "/badge.png"
                }),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS
            )
            print(f"푸시 알림 전송 성공: {idx}")
        except WebPushException as e:
            print(f"푸시 알림 전송 실패: {e}")
            if e.response and e.response.status_code in [404, 410]:
                dead_subscriptions.append(subscription)
    
    # 만료된 구독 제거
    for sub in dead_subscriptions:
        subscriptions.remove(sub)
    save_subscriptions(subscriptions)

# 매일 자동 확인 작업
def daily_birthday_check():
    print(f"[{datetime.now()}] 생일 자동 확인 시작...")
    names = check_birthdays()
    
    if names:
        print(f"오늘의 생일자: {names}")
        send_push_notifications(names)
    else:
        print("오늘은 생일인 분이 없습니다.")

# 스케줄러 설정
scheduler = BackgroundScheduler()
scheduler.add_job(
    func=daily_birthday_check,
    trigger="cron",
    hour=9,  # 매일 오전 9시
    minute=0,
    timezone="Asia/Seoul"
)
scheduler.start()

# 앱 종료 시 스케줄러 정리
atexit.register(lambda: scheduler.shutdown())

# 정적 파일 제공
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('.', path)

# VAPID 공개 키 제공
@app.route('/api/vapid-public-key', methods=['GET'])
def get_vapid_public_key():
    return jsonify({"publicKey": VAPID_PUBLIC_KEY})

# 푸시 알림 구독
@app.route('/api/subscribe', methods=['POST'])
def subscribe():
    subscription = request.json
    
    # 중복 확인
    if subscription not in subscriptions:
        subscriptions.append(subscription)
        save_subscriptions(subscriptions)
        print(f"새 구독자 추가: 총 {len(subscriptions)}명")
    
    return jsonify({"success": True, "message": "구독 완료"})

# 푸시 알림 구독 해제
@app.route('/api/unsubscribe', methods=['POST'])
def unsubscribe():
    subscription = request.json
    
    if subscription in subscriptions:
        subscriptions.remove(subscription)
        save_subscriptions(subscriptions)
        print(f"구독자 제거: 총 {len(subscriptions)}명")
    
    return jsonify({"success": True, "message": "구독 해제 완료"})

# 생일자 조회 API
@app.route('/api/birthdays', methods=['GET'])
def get_birthdays():
    try:
        names = check_birthdays()
        today = datetime.now().strftime("%m-%d")
        
        return jsonify({
            "success": True,
            "today": today,
            "birthdays": names
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# 수동 알림 테스트
@app.route('/api/test-notification', methods=['POST'])
def test_notification():
    names = check_birthdays()
    if names:
        send_push_notifications(names)
        return jsonify({"success": True, "message": f"알림 전송: {names}"})
    else:
        return jsonify({"success": True, "message": "오늘은 생일자가 없습니다"})

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "ok",
        "message": "서버가 정상 작동 중입니다",
        "subscribers": len(subscriptions),
        "scheduler_running": scheduler.running
    })

if __name__ == '__main__':
    print("🎂 두술 생일 알림 서버 시작!")
    print(f"📡 구독자 수: {len(subscriptions)}명")
    print(f"⏰ 매일 오전 9시에 자동 확인합니다")
    
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
