# experiments

신호를 엔진에 넣기 전에 따로 검증하던 프로토타입이에요.

- `banner_proto.py`: 득템 배너 OCR 프로토타입. 검증된 방법은 `clipforge/signals/item_banner.py` 로 옮겼어요.

실험 결과 JSON(전사·채팅 OCR·후보 등)은 실제 방송에서 나온 데이터라 저장소에 넣지 않아요 (`.gitignore` 의 `experiments/*.json`).
같은 결과는 `python -m clipforge.run …` 명령으로 각자의 영상에서 다시 만들 수 있어요.
