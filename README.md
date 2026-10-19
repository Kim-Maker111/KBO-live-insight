# KBO LIVE INSIGHT — 실시간 KBO 기록 사이트

샘플 점수나 임의의 선수 기록을 넣지 않고 KBO 공식 홈페이지의 응답을 요청해 보여주는 웹 프로젝트입니다.

## 주요 화면

- 날짜/시리즈별 경기 일정과 경기 상태
- 게임센터에서 제공하는 점수 및 선발투수 정보(공식 응답에 있을 때)
- 경기 상세 버튼을 통한 이닝별 점수, 타자·투수 경기 기록
- 공식 팀 순위와 시즌 승률
- 공식 선수 타자/투수 시즌 기록
- 30초 간격 오늘 경기 자동 새로고침, 마지막 갱신 시간
- 데이터 연결 실패 시 오류 메시지 표시(데모 숫자로 대체하지 않음)

## 배포

이 프로젝트는 정적 HTML만 단독으로 호스팅하지 않습니다. 브라우저에서 KBO 쪽으로 직접 요청하면 CORS 제한이 생길 수 있어 FastAPI 서버가 공식 소스를 대신 요청합니다.

### Render 배포

1. ZIP을 풀고 폴더 안의 파일을 GitHub 저장소에 업로드합니다.
2. Render에서 **New + → Web Service**를 선택하고 해당 저장소를 연결합니다.
3. `render.yaml` 설정을 사용합니다. 설정이 자동으로 잡히지 않으면 다음을 입력합니다.
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
4. Deploy가 끝나면 Render가 알려준 `https://...onrender.com` 주소를 엽니다.

### 컴퓨터에서 먼저 실행하기

Python 3.10 이상이 필요합니다.

```bash
pip install -r requirements.txt
uvicorn app:app --reload
```

그 다음 `http://127.0.0.1:8000`으로 접속합니다.

## 데이터 연결 안내

- 일정: `https://www.koreabaseball.com/ws/Schedule.asmx/GetScheduleList`
- 게임센터: `https://www.koreabaseball.com/ws/Main.asmx/GetKboGameList`
- 이닝별 스코어: `https://www.koreabaseball.com/ws/Schedule.asmx/GetScoreBoardScroll`
- 경기 박스스코어: `https://www.koreabaseball.com/ws/Schedule.asmx/GetBoxScoreScroll`
- 팀 순위: `https://www.koreabaseball.com/ws/Main.asmx/GetTeamRank`
- 선수 시즌 기록: KBO 공식 Record 페이지

KBO가 응답 형식을 변경하거나 특정 서버의 접근을 제한하면 일부 메뉴가 데이터를 불러오지 못할 수 있습니다. 그 경우 화면에는 오류가 표시되고 가짜 기록은 표시되지 않습니다. 외부 API의 무단 사용/재배포 조건 및 KBO 이용정책을 확인한 뒤 공개 운영하세요. 사용량을 과도하게 높이지 않도록 요청 캐시를 적용했습니다.

## 파일

- `app.py`: KBO 공식 데이터 프록시 및 응답 정리
- `static/index.html`: 모바일 대응 웹 UI
- `requirements.txt`: Python 의존성
- `render.yaml`: Render 배포 설정

이 프로젝트는 KBO와 제휴된 공식 서비스가 아닙니다.
