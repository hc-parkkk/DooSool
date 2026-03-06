import gspread
import pandas as pd
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
import os
import json

app = Flask(__name__, static_folder='.')
CORS(app)

# 환경 변수에서 JSON 인증 정보 가져오기
def get_credentials():
    # Render 환경 변수에서 JSON 문자열 가져오기
    google_creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
    
    if google_creds_json:
        # 환경 변수에서 가져온 경우 (Render 배포)
        creds_dict = json.loads(google_creds_json)
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        # 로컬에서 실행하는 경우
        json_keyfile_path = "united-keyword-269601-c2ab4212683d.json"
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(json_keyfile_path, scope)
    
    return creds

# Google Sheets API 인증
creds = get_credentials()
client = gspread.authorize(creds)

# 스프레드시트 ID
spreadsheet_id = "1DmtzalSHS4HRnwLUxMQyOO0YbCiOe_8plvHnI8MIlUQ"

# 정적 파일 제공 (PWA)
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('.', path)

@app.route('/api/birthdays', methods=['GET'])
def get_birthdays():
    try:
        # 스프레드시트 열기
        sheet = client.open_by_key(spreadsheet_id).worksheet("출석체크")
        
        # 전체 데이터 가져오기
        all_data = sheet.get_all_values()
        
        # 첫 번째 행을 헤더로 사용하여 DataFrame 변환
        df = pd.DataFrame(all_data[1:], columns=all_data[0])
        
        # B열부터 F열까지만 선택
        df_filtered = df.iloc[3:, 1:6]
        
        # 첫 번째 행을 열 이름으로 지정
        df_filtered.columns = df_filtered.iloc[0]
        df_filtered = df_filtered[1:].reset_index(drop=True)
        
        # 생년월일 컬럼 변환 (예: "960605" → "06-05" 형식)
        df_filtered["생년월일"] = df_filtered["생년월일"].apply(
            lambda x: datetime.strptime(x, "%y%m%d").strftime("%m-%d") if x and len(x) == 6 else ""
        )
        
        # 오늘 날짜 확인
        today = datetime.now().strftime("%m-%d")
        
        # 오늘이 생일인 사람 필터링
        birthday_people = df_filtered[df_filtered["생년월일"] == today]
        
        # 이름 목록 추출
        names = birthday_people["이름"].tolist()
        
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

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "ok",
        "message": "서버가 정상 작동 중입니다"
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
