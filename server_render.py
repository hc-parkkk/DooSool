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

# 회비 미납자 확인 함수
def check_nonpayment():
    try:
        sheet = client.open_by_key(spreadsheet_id).worksheet("회비")
        all_data = sheet.get_all_values()
        
        # 5행(인덱스 4)이 실제 헤더
        # B열부터 D열(1~3)과 34번째 열부터 46번째 열(33~45) 선택
        df_filtered = pd.concat([
            pd.DataFrame(all_data[5:], columns=all_data[4]).iloc[:, 1:4],
            pd.DataFrame(all_data[5:], columns=all_data[4]).iloc[:, 33:46]
        ], axis=1)
        
        # 현재 날짜 기준 이번 달과 지난 달
        today = datetime.now()
        current_month = today.month
        previous_month = current_month - 1 if current_month > 1 else 12
        
        current_month_str = f"{current_month}월"
        previous_month_str = f"{previous_month}월"
        
        # 이번 달과 지난 달 미납자 (빈 값도 미납으로 처리)
        current_absent = df_filtered[
            (df_filtered[current_month_str] != 'O') & 
            (df_filtered['이름'].notna()) & 
            (df_filtered['이름'] != '')
        ]
        previous_absent = df_filtered[
            (df_filtered[previous_month_str] != 'O') & 
            (df_filtered['이름'].notna()) & 
            (df_filtered['이름'] != '')
        ]
        
        current_names = current_absent['이름'].tolist()
        previous_names = previous_absent['이름'].tolist()
        
        return {
            'current_month': current_month_str,
            'previous_month': previous_month_str,
            'current_names': current_names,
            'previous_names': previous_names
        }
    except Exception as e:
        print(f"회비 미납자 확인 오류: {e}")
        import traceback
        traceback.print_exc()
        return None

# 방출 예정자 확인 함수
def check_exclude_members():
    try:
        sheet = client.open_by_key(spreadsheet_id).worksheet("출석체크")
        all_data = sheet.get_all_values()
        
        # 5행(인덱스 4)이 실제 헤더
        # B열부터 F열(1~5)과 33번째 열부터 45번째 열(32~44) 선택
        df_filtered = pd.concat([
            pd.DataFrame(all_data[5:], columns=all_data[4]).iloc[:, 1:6],
            pd.DataFrame(all_data[5:], columns=all_data[4]).iloc[:, 32:45]
        ], axis=1)
        
        # 현재 날짜 기준 이번 달과 지난 달
        today = datetime.now()
        current_month = today.month
        previous_month = current_month - 1 if current_month > 1 else 12
        
        current_month_str = f"{current_month}월"
        previous_month_str = f"{previous_month}월"
        
        # 제외할 이름 목록
        exclude_names = ['신예슬', '이태욱', '최연주', '전해인', '김현우', '고준호']
        
        # 이번 달과 지난 달 모두 'O' 없고, 신입 아닌 사람
        absent_people = df_filtered[
            (df_filtered[current_month_str] != 'O') & 
            (df_filtered[previous_month_str] != 'O') &
            (df_filtered[current_month_str] != '신입') &
            (df_filtered[previous_month_str] != '신입') &
            (df_filtered['이름'].notna()) &
            (df_filtered['이름'] != '') &
            (~df_filtered['이름'].isin(exclude_names))
        ]
        
        names = absent_people['이름'].tolist()
        
        return {
            'month': current_month_str,
            'names': names
        }
    except Exception as e:
        print(f"방출 예정자 확인 오류: {e}")
        import traceback
        traceback.print_exc()
        return None

# 푸시 알림 전송
def send_push_notifications(title, body):
    if not VAPID_PRIVATE_KEY or not subscriptions:
        print("VAPID 키가 없거나 구독자가 없습니다.")
        return
    
    dead_subscriptions = []
    
    for idx, subscription in enumerate(subscriptions):
        try:
            webpush(
                subscription_info=subscription,
                data=json.dumps({
                    "title": title,
                    "body": body,
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
        message = f"🎉 오늘의 생일자: {', '.join(names)}님 🎂"
        send_push_notifications("🎂 두술 생일 알림", message)
    else:
        print("오늘은 생일인 분이 없습니다.")

# 회비 미납자 자동 확인 작업
def monthly_nonpayment_check():
    print(f"[{datetime.now()}] 회비 미납자 확인 시작...")
    data = check_nonpayment()
    
    if data and (data['current_names'] or data['previous_names']):
        prev_msg = f"📢 {data['previous_month']} 회비 미납: {', '.join(data['previous_names'])}" if data['previous_names'] else ""
        curr_msg = f"📢 {data['current_month']} 회비 미납: {', '.join(data['current_names'])}" if data['current_names'] else ""
        
        message = "\n\n".join(filter(None, [prev_msg, curr_msg]))
        
        print(f"회비 미납자: {message}")
        send_push_notifications("💰 회비 미납 알림", message)
    else:
        print("회비 미납자가 없습니다.")

# 방출 예정자 자동 확인 작업
def monthly_exclude_check():
    print(f"[{datetime.now()}] 방출 예정자 확인 시작...")
    data = check_exclude_members()
    
    if data and data['names']:
        message = f"📢 {data['month']} 방출 예정 명단:\n" + "\n".join(data['names'])
        print(f"방출 예정자: {data['names']}")
        send_push_notifications("⚠️ 방출 예정 알림", message)
    else:
        print("방출 예정자가 없습니다.")

# 알림 시간 설정
notification_settings = {
    'birthday': {'hour': 9, 'minute': 0},  # 생일: 매일 09:00
    'nonpayment': {'days': [1, 5, 10], 'hour': 9, 'minute': 0},  # 회비: 매월 1,5,10일 09:00
    'exclude': {'days': [1, 10, 20, 'last'], 'hour': 9, 'minute': 0}  # 방출: 매월 1,10,20,말일 09:00
}

# 스케줄러 설정
scheduler = BackgroundScheduler()

def update_schedule():
    """스케줄 업데이트"""
    global scheduler
    # 기존 작업 제거
    scheduler.remove_all_jobs()
    
    # 1. 생일 알림 (매일 설정한 시간)
    birthday_settings = notification_settings['birthday']
    scheduler.add_job(
        func=daily_birthday_check,
        trigger="cron",
        hour=birthday_settings['hour'],
        minute=birthday_settings['minute'],
        timezone="Asia/Seoul",
        id="birthday_check"
    )
    
    # 2. 회비 미납자 알림
    nonpayment_settings = notification_settings['nonpayment']
    days_str = ','.join(map(str, nonpayment_settings['days']))
    scheduler.add_job(
        func=monthly_nonpayment_check,
        trigger="cron",
        day=days_str,
        hour=nonpayment_settings['hour'],
        minute=nonpayment_settings['minute'],
        timezone="Asia/Seoul",
        id="nonpayment_check"
    )
    
    # 3. 방출 예정자 알림
    exclude_settings = notification_settings['exclude']
    days_list = []
    for day in exclude_settings['days']:
        if day == 'last':
            days_list.append('last')
        else:
            days_list.append(str(day))
    days_str = ','.join(days_list)
    scheduler.add_job(
        func=monthly_exclude_check,
        trigger="cron",
        day=days_str,
        hour=exclude_settings['hour'],
        minute=exclude_settings['minute'],
        timezone="Asia/Seoul",
        id="exclude_check"
    )
    
    print(f"⏰ 생일 알림: 매일 {birthday_settings['hour']:02d}:{birthday_settings['minute']:02d}")
    print(f"💰 회비 미납 알림: 매월 {','.join(map(str, nonpayment_settings['days']))}일 {nonpayment_settings['hour']:02d}:{nonpayment_settings['minute']:02d}")
    print(f"⚠️  방출 예정 알림: 매월 {','.join(map(str, exclude_settings['days']))}일 {exclude_settings['hour']:02d}:{exclude_settings['minute']:02d}")

# 초기 스케줄 설정
update_schedule()
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

# 회비 미납자 조회 API
@app.route('/api/nonpayment', methods=['GET'])
def get_nonpayment():
    try:
        data = check_nonpayment()
        if data:
            return jsonify({
                "success": True,
                "data": data
            })
        else:
            return jsonify({
                "success": False,
                "error": "데이터를 가져올 수 없습니다"
            }), 500
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# 방출 예정자 조회 API
@app.route('/api/exclude-members', methods=['GET'])
def get_exclude_members():
    try:
        data = check_exclude_members()
        if data:
            return jsonify({
                "success": True,
                "data": data
            })
        else:
            return jsonify({
                "success": False,
                "error": "데이터를 가져올 수 없습니다"
            }), 500
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# 알림 설정 저장
@app.route('/api/set-notification-settings', methods=['POST'])
def set_notification_settings():
    global notification_settings
    
    data = request.json
    notification_type = data.get('type')  # 'birthday', 'nonpayment', 'exclude'
    
    if notification_type not in notification_settings:
        return jsonify({"success": False, "message": "잘못된 알림 타입입니다"}), 400
    
    if notification_type == 'birthday':
        # 생일은 시간만 설정
        hour = data.get('hour', 9)
        minute = data.get('minute', 0)
        
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return jsonify({"success": False, "message": "잘못된 시간 형식입니다"}), 400
        
        notification_settings['birthday']['hour'] = hour
        notification_settings['birthday']['minute'] = minute
        
        update_schedule()
        
        return jsonify({
            "success": True,
            "message": f"생일 알림 시간이 {hour:02d}:{minute:02d}로 설정되었습니다"
        })
    
    else:
        # 회비/방출은 날짜와 시간 모두 설정
        days = data.get('days', [])
        hour = data.get('hour', 9)
        minute = data.get('minute', 0)
        
        if not days or not isinstance(days, list):
            return jsonify({"success": False, "message": "날짜를 입력하세요"}), 400
        
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return jsonify({"success": False, "message": "잘못된 시간 형식입니다"}), 400
        
        # 날짜 유효성 검사
        for day in days:
            if day != 'last' and (not isinstance(day, int) or not (1 <= day <= 31)):
                return jsonify({"success": False, "message": "잘못된 날짜 형식입니다"}), 400
        
        notification_settings[notification_type]['days'] = days
        notification_settings[notification_type]['hour'] = hour
        notification_settings[notification_type]['minute'] = minute
        
        update_schedule()
        
        type_name = "회비 미납" if notification_type == 'nonpayment' else "방출 예정"
        days_str = ','.join(map(str, days))
        
        return jsonify({
            "success": True,
            "message": f"{type_name} 알림이 매월 {days_str}일 {hour:02d}:{minute:02d}로 설정되었습니다"
        })

# 현재 알림 설정 조회
@app.route('/api/get-notification-settings', methods=['GET'])
def get_notification_settings():
    return jsonify({
        "success": True,
        "settings": notification_settings
    })

# 수동 알림 테스트 (즉시 전송)
@app.route('/api/test-notification', methods=['POST'])
def test_notification():
    notification_type = request.json.get('type', 'birthday') if request.json else 'birthday'
    
    if notification_type == 'birthday':
        names = check_birthdays()
        if names:
            message = f"🎉 오늘의 생일자: {', '.join(names)}님 🎂"
            send_push_notifications("🎂 생일 알림", message)
            return jsonify({"success": True, "message": f"생일 알림 전송: {', '.join(names)}님"})
        else:
            send_push_notifications("🎂 테스트 알림", "푸시 알림이 정상 작동합니다!")
            return jsonify({"success": True, "message": "테스트 알림 전송 완료"})
    
    elif notification_type == 'nonpayment':
        data = check_nonpayment()
        if data and (data['current_names'] or data['previous_names']):
            prev_msg = f"📢 {data['previous_month']} 회비 미납: {', '.join(data['previous_names'])}" if data['previous_names'] else ""
            curr_msg = f"📢 {data['current_month']} 회비 미납: {', '.join(data['current_names'])}" if data['current_names'] else ""
            message = "\n\n".join(filter(None, [prev_msg, curr_msg]))
            send_push_notifications("💰 회비 미납 알림", message)
            return jsonify({"success": True, "message": "회비 미납 알림 전송 완료"})
        else:
            return jsonify({"success": True, "message": "회비 미납자가 없습니다"})
    
    elif notification_type == 'exclude':
        data = check_exclude_members()
        if data and data['names']:
            message = f"📢 {data['month']} 방출 예정 명단:\n" + "\n".join(data['names'])
            send_push_notifications("⚠️ 방출 예정 알림", message)
            return jsonify({"success": True, "message": "방출 예정 알림 전송 완료"})
        else:
            return jsonify({"success": True, "message": "방출 예정자가 없습니다"})
    
    return jsonify({"success": False, "message": "잘못된 알림 타입입니다"}), 400

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
