# 우선 모듈 · 일괄 구성 보드 · 모노레포

이 문서는 [plan.md](plan.md) 를 보완한다. Earthworm **v8.0b17** 웹 콘솔이 **실제로 먼저 돌릴 모듈**, **한 창에서 인스턴스를 등록·채우고 일괄 적용하는 방법**, **배포 가능한 모노레포 형태**를 확정한다.

대상 바이너리·매뉴얼·제어 규칙(`startstop` / `pau` / `stopmodule` pid / `restart` pid, `pidpau` 웹 금지, 첫 링 `STATUS_RING`)은 본 계획서와 같다. 여기서는 **무엇을 팔레트에 둘지**와 **여러 대를 어떻게 한 번에 운영할지**만 더 좁힌다.

상태: 계획. 현재 앱은 `bin` 전체 스캔 + 토글 + prompt 복제다. 이 문서의 구성 보드·화이트리스트·일괄 적용은 **이후 구현 단계**다.

---

## 18. 왜 우선 목록이 필요한가

Earthworm `bin` 에는 픽커·로케이터·hypoinverse·tankplayer 등 수십 개가 있다. 관측망 수집·중계·아카이브 콘솔은 그 전부를 첫 화면에 펼치면 안 된다.

[모듈 패밀리](diagrams/module-families.html)

운영자가 원하는 흐름은 이것이다.

1. **우선 모듈만** 팔레트에 둔다.
2. 같은 바이너리를 **여러 인스턴스**로 쓴다 (`q3302ew` 관측소마다, `export_scnl` 수신처마다).
3. 인스턴스별 파라미터를 **한 창에서** 채운다.
4. **적용 한 번**으로 `.d` · Module ID · Process · Descriptor · 복제 bin 이 맞고, `startstop` 이 전체를 함께 돌린다.
5. 목록에 없는 모듈은 **필요 시 따로 등록**한다.
6. 웹 콘솔은 저장소 안의 다른 앱(StationXML, PPSD, ringserver UI)과 **모노레포로 배포**할 수 있게 패키지 경계를 둔다.

현재 구현과의 차이:

| 지금 | 이 계획 |
|------|---------|
| `module_catalog.py` 가 `bin` 의 모든 실행파일을 나열 | 팔레트는 **우선 화이트리스트**. 나머지는 “추가 등록” |
| `Modules.tsx` 토글 + `prompt()` 복제 | **구성 보드**: 인스턴스 카드 + 사이트 공통 + 적용 |
| `Variables.tsx` 가 HeartbeatInt 등 소수 공통키만 | 사이트 공통 + 모듈 스키마 필드가 **한 화면** |
| `seed.py` CONTROL_BINS 에 I/O 모듈 스텁이 부족 | 우선 Process 바이너리 스텁·샘플 `.d` 를 시드에 포함 |
| 앱이 저장소 루트에 흩어짐 | `apps/` + 루트 `compose.yaml` Docker 모노레포 |

---

## 19. 우선 모듈 분류

이름은 Earthworm Process 이름(또는 CLI 이름)과 같다. 웹 카탈로그 `family` 키도 이 문자열을 쓴다.

### 19.1 역할 세 갈래

Earthworm 에서 **startstop Process** 와 **사람이 가끔 치는 CLI** 를 한 토글 목록에 섞으면 안 된다.

| 갈래 | `role` | startstop Process? | 구성 보드 |
|------|--------|--------------------|-----------|
| 데이터 I/O | `process` | 예. `Process "name name.d"` | 인스턴스 카드. 켜면 기동 대상 |
| 제어 | `control` | `startstop`·`statmgr` 만 Process. 나머지 CLI | 버튼·확인 대화. 인스턴스 카드 없음 |
| 진단 | `diagnostic` | 아니오 | 링 모니터·wave 메뉴. 인스턴스 카드 없음 |

`statmgr` 는 사용자가 나열하지 않았지만 **startstop 과 함께 필수 Process** 다. 구성 보드는 숨기지 않고 **사이트 공통 / 필수** 칸에 고정한다. 끄면 하트비트 감시가 없어지므로 기본은 켜짐, 잠금.

`pidpau` 는 우선 목록에 있지만 **웹 stop 경로에 쓰지 않는다**. 진단 화면에 “statmgr 가 다시 올리는 종료” 설명만 둔다. 일시중지는 `stopmodule <pid>` 만.

### 19.2 데이터 I/O Process (팔레트 기본)

복제 다발 가능성이 높은 다섯 개는 `fleet: true` 다. 팔레트에서 **인스턴스 추가** 가 기본 동작이고, prompt 복제가 아니다.

| family | 한 줄 | 주로 붙는 링 | 유일해야 하는 것 | fleet |
|--------|-------|--------------|------------------|-------|
| `q3302ew` | Q330 디지타이저 → TRACEBUF2 | `WAVE_RING` | 호스트 UDP `SourcePortControl` / `SourcePortData`, Serial, Module ID | ○ |
| `slink2ew` | SeedLink 서버 → TRACEBUF2 | `WAVE_RING` | Module ID, Stream 신원. 원격 `SLhost` 는 중복 가능 | ○ |
| `export_generic` | 링 메시지를 TCP 로 보냄 | 송신할 링 | 리슨 `ServerIPAdr`+`ServerPort` | ○ |
| `export_scnl` | SCNL 필터 후 TCP 송신 | 송신할 링 | 리슨 주소+포트, `Send_scnl` 집합 | ○ |
| `wave_serverV` | 탱크 파일 웨이브 서버 | `WAVE_RING` | 리슨 포트, `Tank` 경로, `TankStructFile` | ○ |
| `import_generic` | 원격 export 에 접속해 수신 | 넣을 링 | 로컬 Module ID. 원격 `SenderIpAdr`+`SenderPort` 는 대상마다 | |
| `import_pasv` | 패시브 리슨 후 수신 | 넣을 링 | 리슨 `ReceiverIpAdr`+`ReceiverPort` | |
| `tbuf2mseed` | TRACEBUF2 → MiniSEED 메시지 | In / Out 링 | Module ID, 링 쌍 | |
| `mseed2tbuf` | MiniSEED → TRACEBUF2 | In / Out 링 | Module ID, 링 쌍 | |
| `ew2ringserver` | 링 → ringserver (SeedLink 업스트림) | `WAVE_RING` 등 | Module ID, `RSAddress`+`RSPort` | |
| `ew2mseed` | 링 → MiniSEED 파일 | 입력 링 | 출력 디렉터리(인스턴스별 권장) | |
| `ewmseedarchiver` | MiniSEED 아카이브 배치 | 입력 링 | 아카이브 루트 경로 | |

`getmenu` 는 wave_serverV **클라이언트 CLI** 이지 Process 가 아니다. 진단 갈래로 둔다.

### 19.3 제어 CLI · 필수 Process

| 이름 | 웹에서의 역할 | Process? | 비고 |
|------|---------------|----------|------|
| `startstop` | 전체 기동. 웹 Start | 예 (자기 자신) | 명령은 `startstop`. 구성 카드 없음 |
| `statmgr` | 하트비트·에러 로고 감시 | 예 | 필수. Descriptor 목록은 인스턴스 적용 시 갱신 |
| `restart` | 모듈 재개. `restart <pid>` | 아니오 | 대시보드 행 버튼 |
| `reconfigure` | startstop 이 Process 목록을 다시 읽음 | 아니오 | 구성 적용 후, 또는 토글 on |
| `pau` | 전체 종료 | 아니오 | 웹 Stop |
| `stopmodule` | 일시중지 `stopmodule <pid>` | 아니오 | 웹 Pause. 이름 인자 없음 |
| `pidpau` | 프로세스 종료(statmgr 재기동 가능) | 아니오 | 웹 Stop 경로 금지. 진단 문서만 |

### 19.4 진단 CLI

| 이름 | 웹에서의 역할 |
|------|---------------|
| `status` | 대시보드 원본. 주기 호출 + `/ws/status` |
| `getmenu` | 선택 가능한 wave_serverV 에 SCNL 메뉴 조회 |
| `sniffring` | 링 메시지 헤더. 기존 링 모니터 |
| `sniffwave` | TRACEBUF 스니프. 기존 링 모니터 |

진단 도구는 구성 보드 하단 **도구** 줄에만 노출한다. 인스턴스를 복제하지 않는다.

### 19.5 나머지 모듈 — 필요 시 등록

팔레트에 없는 `bin` 항목(`pick_ew`, `eqproc`, `tankplayer`, `copystatus`, …)은 **추가 모듈 등록** 으로만 넣는다.

등록 최소 입력:

1. `bin` 에서 실행파일 선택 (또는 경로가 `EW_HOME/$EW_VERSION/bin` 안인지 검사).
2. 샘플 `.d` 가 있으면 복사, 없으면 빈 템플릿(`MyModuleId`, `RingName`, `HeartBeatInt`).
3. `earthworm.d` Module 상수, `.desc`, `statmgr.d` Descriptor.
4. `family` 는 파일 줄기. `fleet` 기본 false. 운영자가 “이 패밀리도 여러 대” 를 켜면 이후부터 인스턴스 추가가 열린다.
5. 필드 스키마가 없으면 구성 보드는 **키=값 표** + 원문 `.d` 편집으로 떨어진다. 우선 12개만 YAML 스키마를 둔다.

등록한 모듈은 `app.json.extra_families[]` 에 남긴다. 팔레트 “기타” 그룹으로 재방문 시 다시 보인다.

---

## 20. 인스턴스 모델 (복제가 기본 단위)

Earthworm startstop 은 **같은 Process 문자열을 두 줄 넣어도 두 번째로 spawn 하지 않는다**. 그래서 같은 바이너리를 여러 대 쓰려면 **명령 이름이 달라야** 한다. 웹은 기존과 같이 `bin` 을 새 이름으로 복사한다.

```
bin/q3302ew          +  params/q3302ew.d           →  Process "q3302ew q3302ew.d"
bin/q3302ew_sta1     +  params/q3302ew_sta1.d      →  Process "q3302ew_sta1 q3302ew_sta1.d"
bin/q3302ew_sta2     +  params/q3302ew_sta2.d      →  Process "q3302ew_sta2 q3302ew_sta2.d"
```

구성 보드의 **인스턴스 추가** 는 내부적으로 지금의 `clone.py` 트랜잭션과 같다. UI 만 “복제 다이얼로그” 가 아니라 **패밀리에서 카드 한 장 더** 다.

### 20.1 식별자

| 필드 | 규칙 |
|------|------|
| `family` | 원본 바이너리 이름. `q3302ew` |
| `id` | Process 이름 = 복사된 bin 이름. `q3302ew_sta1` |
| `id` 문자 | `^[A-Za-z][A-Za-z0-9_]{0,31}$` (기존 `SAFE_NAME`) |
| Process 명령 | `{id} {id}.d` — 공백 포함 199자 이하 (`MAX_PROCESS_CMD`) |
| Module 상수 | `MOD_` + `id` 대문자. `earthworm.d` 에서 유일 |
| `clone_of` | 원본 family. 첫 인스턴스가 원본 이름을 쓰면 `null` |

원본 이름(`q3302ew`)을 첫 관측소에 써도 된다. 두 번째부터는 접미사를 강제한다. 권장 접미사: `_` + 관측소 또는 역할 (`_sta1`, `_n1`, `_ks`).

### 20.2 한도

| 한도 | 값 | UI |
|------|-----|-----|
| startstop 자식 | `MAX_CHILD` **256** | 인스턴스 추가 거부 |
| Module ID | `earthworm.d` 빈 번호 | 고갈 시 적용 실패 메시지 |
| 동시 sniff 세션 | 2 (기존) | 구성 보드와 무관 |

필수 Process(`startstop` 카운트 방식, `statmgr`) + 우선 I/O 인스턴스 합이 256 을 넘지 않게 카운트한다.

### 20.3 복제 다발 다섯 패밀리 — 운영 패턴

[복제 다발](diagrams/instance-fleet.html)

**q3302ew**  
관측소(또는 Q330)마다 한 인스턴스. 장치 `IPAddress`·`BasePort`·`SerialNumber`·`AuthCode` 가 다르다. 호스트가 받는 UDP `SourcePortControl` / `SourcePortData` 는 **머신에서 유일**. 채널 맵은 인스턴스 `.d` 에 둔다.

**slink2ew**  
업링크 SeedLink 마다, 또는 같은 서버라도 스트림 세트가 다르면 인스턴스를 나눈다. `SLhost`:`SLport` 는 같아도 된다. 구분자는 Module ID + `Stream`/`Selectors`.

**export_scnl / export_generic**  
수신 클라이언트(다른 기관, 내부 import)마다 리슨 포트가 달라야 한다. 커널 `ip_local_port_range` **보다 낮은** 포트를 쓴다 (`ew_linux.bash` 주석과 동일). SCNL 목록은 인스턴스 카드의 반복 필드.

**wave_serverV**  
역할마다 탱크를 나눈다 (실시간 / 아카이브 조회). `ServerPort` 유일, `Tank`·`TankStructFile` 경로는 인스턴스마다 **다른 파일**. 같은 탱크를 두 서버가 열면 깨진다.

`import_generic` 은 fleet 기본값이 아니지만, 송신 기관이 여러 곳이면 추가 등록과 같은 UX 로 인스턴스를 늘릴 수 있게 `fleet` 플래그를 운영자가 켠다.

---

## 21. 구성 보드 — 한 창에서 등록·입력·일괄 운영

[구성 보드](diagrams/compose-board.html)

이후 설정의 **모듈 설정** 화면을 토글 목록에서 구성 보드로 바꾼다. 통합 변수 화면의 공통키는 보드 상단 **사이트 공통** 으로 옮긴다. `Variables` 페이지는 보드로 흡수하거나, 보드의 앵커 탭으로 남긴다.

목표는 “카드마다 저장” 이 아니라, 운영자가 값을 다 채운 뒤 **적용** 한 번에 파일이 맞고, 이어서 **시작** 하면 전체가 같은 startstop 아래 돈다는 것이다.

### 21.1 화면 구역

```
┌─ 사이트 공통 ─────────────────────────────────────────┐
│ Inst  HeartbeatInt  LogFile  기본 WAVE_RING  statmgr   │
└────────────────────────────────────────────────────────┘
┌ 팔레트 ──────┐  ┌ 인스턴스 카드 (스크롤) ──────────────┐
│ 우선 12      │  │ q3302ew_sta1  [스키마 필드…]         │
│  · q3302ew + │  │ q3302ew_sta2                         │
│  · slink2ew +│  │ export_scnl_n1                       │
│  · …         │  │ wave_serverV                         │
│ 기타 등록…   │  │ …                                    │
└──────────────┘  └──────────────────────────────────────┘
┌ 검증 요약 (포트 충돌, 빈 필수값)  [검토] [적용] [시작] ┐
└────────────────────────────────────────────────────────┘
```

- **팔레트 `+`**: fleet 패밀리는 인스턴스 카드를 즉시 추가하고 이름 기본값을 제안한다. 비-fleet 는 카드가 이미 있으면 포커스만, 없으면 원본 이름 카드 하나.
- **기타 등록**: 모달에서 bin 선택 → 카드 추가.
- **카드**: 스키마 필드. 고급은 접은 “원문 `.d`”.
- **검토**: 디스크에 쓰지 않고 검증만 (`POST /api/compose/validate`).
- **적용**: 트랜잭션 기록 (`POST /api/compose/apply`). startstop 이 Alive 면 기본은 파일만 쓰고 “기동 중 모듈은 restart 필요” 배지. 옵션 `reconfigure: true` 로 새 Process 만 띄운다. 이미 돌 고 있는 모듈의 `.d` 변경은 startstop 이 다시 읽지 않으므로 행마다 restart 가 필요하다는 기존 규칙을 그대로 둔다.
- **시작**: 미기동이면 `startstop`. Alive 면 비활성.

한 창에 모든 인스턴스가 보여야 하므로, 카드는 패밀리로 그룹하고 기본은 요약 줄 + 펼침이다. 필터: 패밀리, 검증 오류만.

### 21.2 사이트 공통 (한 번만)

`earthworm_commonvars.d` · `ew_linux.bash` · `statmgr.d` 상단에 해당하는 값.

| 키 | 반영 위치 |
|----|-----------|
| `EW_INSTALLATION` / Inst | `ew_linux.bash`, 각 `.desc` `instId` (기존) |
| `HeartbeatInt` | 공통 vars + 각 `.d` HeartBeatInt + `.desc` `tsec` |
| `LogFile` | 공통 + 모듈 `.d` 가 키를 쓰는 경우 |
| 기본 `WAVE_RING` | 새 I/O 카드의 RingName 초기값. 기존 카드는 덮어쓰지 않음(명시적 “공통 전파” 체크 시만) |
| `statmgr` 로그 수준 | `statmgr.d` |

공통 전파는 위험하므로 기본은 **새 카드 초기값만**. 이미 채운 인스턴스를 일괄 덮어쓰려면 체크박스 “이 적용에서 HeartbeatInt 를 모든 `.d` 에 씀”.

### 21.3 이름·포트 제안

인스턴스 추가 시 백엔드가 제안하고, 운영자가 고친다.

| 패밀리 | 이름 제안 | 포트/경로 제안 |
|--------|-----------|----------------|
| `q3302ew` | `q3302ew_staN` | `SourcePortControl` 16030 부터 짝, Data = Control+1 |
| `slink2ew` | `slink2ew_nN` | 포트 없음. Stream 빈 값이면 검증 실패 |
| `export_generic` | `export_generic_nN` | `ServerPort` 16005, 16006, … |
| `export_scnl` | `export_scnl_nN` | `ServerPort` 16015, … |
| `import_pasv` | `import_pasv_nN` | `ReceiverPort` 16025, … |
| `wave_serverV` | `wave_serverV_nN` | `ServerPort` 16022, … / `Tank` `$EW_DATA_DIR/tanks/{id}.tnk` |

포트는 이미 카드·디스크에 쓰인 리슨 포트를 피해 고른다. 커널 ephemeral 하한(보통 32768) 미만인지는 적용 시 경고.

### 21.4 등록이 “쉽다”는 것의 조작 목표

1. 팔레트에서 `q3302ew` 를 세 번 누른다 → 카드 세 장.
2. 각 카드에 IP·시리얼·Auth·로컬 UDP 만 넣는다. Module ID·bin 복사는 적용이 한다.
3. `export_scnl` 을 한 번 누르고 리슨 포트와 `Send_scnl` 줄을 넣는다.
4. 검토 → 빨간 칸만 고친다.
5. 적용 → 시작.

모듈마다 파일 트리를 열고 `earthworm.d` 숫자를 고르지 않는다.

---

## 22. 모듈 필드 스키마

진실의 원천 파일: `apps/earthworm_web/backend/app/module_fields.yaml`. 프론트는 `/api/modules/schema` 로 받는다. 매뉴얼은 소스 `doc/WEB_DOC` 의 각 cmd HTML.

공통 Process 필드 (스키마가 생략해도 카드 상단에 항상 표시):

| 키 | 의미 |
|----|------|
| `MyModuleId` | 적용 시 할당. 카드에서는 읽기 전용 미리보기 |
| `RingName` 또는 In/Out | 초기 설정에서 만든 링만 콤보 |
| `HeartBeatInt` | 사이트 공통 기본 |
| `LogFile` | 0/1/2 |

아래는 **운영자가 한 창에서 채울 1차 필드**다. 매뉴얼의 모든 키를 1차에 올리지 않는다. 나머지는 고급(원문).

### 22.1 `q3302ew`

| 필드 | 필수 | 유일 범위 | 메모 |
|------|------|-----------|------|
| `IPAddress` | ○ | 인스턴스 | Q330 |
| `BasePort` | ○ | 장치 관례 5330 | |
| `SerialNumber` | ○ | 전역 권장 | |
| `AuthCode` | ○ | 비밀. 파일 권한 유지 | UI 는 password 입력, 저장은 `.d` 평문 (Earthworm 한계) |
| `SourcePortControl` | ○ | **호스트 전역 UDP** | |
| `SourcePortData` | ○ | **호스트 전역 UDP** | Control 과 달라야 함 |
| 채널 맵 줄 | ○ | | 반복 필드. 원문 유지 파서 |

### 22.2 `slink2ew`

| 필드 | 필수 | 메모 |
|------|------|------|
| `SLhost` | ○ | |
| `SLport` | ○ | 기본 18000 |
| `Stream` / `Selectors` | ○ | 빈 구독 방지 |
| `NetworkTimeout` 등 | | 고급 |

### 22.3 `export_generic` · `export_scnl`

| 필드 | 필수 | 유일 범위 |
|------|------|-----------|
| `ServerIPAdr` | ○ | 리슨 IP. `0.0.0.0` 허용하되 방화벽 경고 |
| `ServerPort` | ○ | **호스트 TCP 리슨 전역** |
| `MaxMsgSize` | | 기본 유지 |
| `Send_scnl` / `Send_scn` | `export_scnl` 은 ○ | 반복 줄. wildcard 허용 |
| `export_generic` 필터 | | 로고/타입. 고급 |

같은 IP+포트를 두 export 가 리슨하면 적용을 거절한다.

### 22.4 `import_generic`

| 필드 | 필수 |
|------|------|
| `SenderIpAdr` | ○ 원격 export |
| `SenderPort` | ○ |

로컬 리슨이 아니므로 포트 유일 검사 대상이 아니다. 같은 원격에 두 인스턴스가 붙는 것은 경고만.

### 22.5 `import_pasv`

| 필드 | 필수 | 유일 |
|------|------|------|
| `ReceiverIpAdr` | ○ | |
| `ReceiverPort` | ○ | TCP 리슨 전역 |
| `SenderIpAdr` | ○ | 허용 피어 |

### 22.6 `wave_serverV`

| 필드 | 필수 | 유일 |
|------|------|------|
| `ServerIPAdr` | ○ | |
| `ServerPort` | ○ | TCP 리슨 |
| `Tank` | ○ | **파일 경로 전역** |
| `TankStructFile` | ○ | 파일 경로 전역 |
| `GapThresh` 등 | | 고급 |

`getmenu` 진단은 이 인스턴스의 IP:포트를 콤보로 받는다.

### 22.7 `tbuf2mseed` · `mseed2tbuf`

| 필드 | 필수 |
|------|------|
| `InRing` / `OutRing` 또는 매뉴얼 키 | ○ 서로 다른 링 권장 |
| 패킹/필터 | 고급 |

### 22.8 `ew2ringserver`

| 필드 | 필수 |
|------|------|
| `RSAddress` | ○ |
| `RSPort` | ○ 이 저장소 ringserver 기본과 맞출 것(배포 시 문서화) |
| 인코딩 | 고급 |

웹 콘솔과 ringserver UI 는 **같은 모노레포의 다른 앱**이다. 프로세스 결합은 하지 않고, 기본 호스트/포트만 배포 문서에 교차 링크한다.

### 22.9 `ew2mseed` · `ewmseedarchiver`

| 필드 | 필수 | 유일 권장 |
|------|------|-----------|
| 출력/아카이브 디렉터리 | ○ | 인스턴스별 하위 디렉터리 |
| SCNL 선택 | | 반복 필드 |

디스크 용량 경고는 기존 P2 위젯과 연결한다.

### 22.10 YAML 스케치

```yaml
families:
  q3302ew:
    role: process
    fleet: true
    default_ring: WAVE_RING
    fields:
      - { key: IPAddress, required: true, type: ip }
      - { key: BasePort, required: true, type: port }
      - { key: SerialNumber, required: true, type: string }
      - { key: AuthCode, required: true, type: secret }
      - { key: SourcePortControl, required: true, type: udp_port, unique: host }
      - { key: SourcePortData, required: true, type: udp_port, unique: host }
  export_scnl:
    role: process
    fleet: true
    fields:
      - { key: ServerIPAdr, required: true, type: ip }
      - { key: ServerPort, required: true, type: tcp_listen, unique: host }
      - { key: Send_scnl, required: true, type: lines }
```

파서는 기존 `parse_key_values` + 반복 커맨드(`Send_scnl`, 채널 맵)를 **같은 키 여러 줄** 로 다룬다. 모르는 줄은 라운드트립에서 보존한다.

---

## 23. 검증 (적용 전에 한 창에서)

`POST /api/compose/validate` 는 보드 JSON 만 보고, 디스크와 합쳐 충돌을 돌려준다. 카드 옆과 하단 요약에 같은 코드를 표시한다.

| 코드 | 검사 |
|------|------|
| `dup_process` | Process 이름 중복 |
| `dup_module_id` | `earthworm.d` / 보드 안 Module 상수 중복 |
| `dup_listen` | TCP/UDP 리슨 포트 중복 (export, import_pasv, wave_serverV, q3302ew source) |
| `dup_tank` | Tank / TankStructFile 경로 중복 |
| `missing_ring` | RingName 이 startstop 링 목록에 없음. `FLAG_RING` 사용 금지 |
| `missing_bin` | family 원본 바이너리 없음 |
| `max_child` | 활성 Process 가 256 초과 |
| `cmd_len` | `{id} {id}.d` > 199 |
| `bad_name` | `SAFE_NAME` 실패 |
| `ephemeral_port` | 포트가 `ip_local_port_range` 하한 이상 — 경고 |
| `empty_required` | 스키마 required |
| `auth_empty` | q3302ew AuthCode |

오류가 있으면 적용 HTTP 409. 경고만 있으면 적용 가능, UI 에 노란 배지.

---

## 24. 일괄 적용 트랜잭션

[일괄 적용](diagrams/compose-apply.html)

한 번의 `apply` 가 여러 `clone.py` 호출 + `.d` 패치 + 토글을 묶는다. 중간 실패 시 **그 적용에서 만든 파일만** 롤백한다. 적용 전 `params/` · `earthworm.d` · `startstop_unix.d` · `statmgr.d` 스냅샷을 `backend/data/backups/compose-<ts>/` 에 둔다 (기존 백업 정책과 동일 디렉터리).

순서:

1. 검증. 실패면 디스크 변경 없음.
2. 스냅샷.
3. 새 인스턴스: bin 복사, `.d` 생성, Module ID, `.desc`, Descriptor, `app.json.clones`.
4. 기존 인스턴스: `.d` 키 패치(모르는 줄 보존), 이름 변경은 이 단계에서 하지 않음(삭제 후 추가로만).
5. 사이트 공통 전파(체크된 키만).
6. `startstop_unix.d` Process 줄을 보드의 enabled 와 맞춘다. 새 줄은 주석으로 넣지 않고, 보드에서 켠 것은 활성, 끈 것은 주석(기존 토글과 같음).
7. `app.json.compose_revision` 증가.
8. 옵션 `reconfigure`. Alive 가 아니면 생략. 호출 후 status 로 새 이름 확인.

삭제: 보드에서 카드를 지우고 적용하면 기존 복제 삭제와 같다 (기동 중이면 먼저 `stopmodule`). 원본 family 의 마지막 카드까지 지우는 것은 확인 대화. `statmgr` 카드는 삭제 불가.

적용과 시작을 한 버튼으로 묶지 않는다. 파일이 틀린 채 startstop 이 뜨는 것을 막기 위해 **적용 성공 → 시작** 두 단계다. 다만 미기동 상태에서는 보드 하단에 두 버튼을 나란히 두어 같은 창에서 끝낸다.

---

## 25. API · 프론트 · 시드 변경점

기존 `/api/modules/{id}/clone` 은 유지한다. 구성 보드가 그 위를 쓴다. 단독 복제 API 를 바로 제거하지 않는다.

| 메서드 | 경로 | 역할 |
|--------|------|------|
| GET | `/api/modules/schema` | YAML → JSON. 우선+extra |
| GET | `/api/compose` | 디스크+app.json 을 보드 모델로 |
| POST | `/api/compose/validate` | 보드 JSON → 이슈 목록 |
| POST | `/api/compose/apply` | 트랜잭션 |
| POST | `/api/compose/suggest` | `{ family }` → 이름·포트·탱크 |
| POST | `/api/modules/register` | 기타 bin 등록 |

보드 모델 (스케치):

```json
{
  "site": { "heartbeat_int": 30, "default_wave_ring": "WAVE_RING" },
  "instances": [
    {
      "family": "q3302ew",
      "id": "q3302ew_sta1",
      "enabled": true,
      "values": { "IPAddress": "10.1.2.3", "BasePort": 5330 }
    }
  ]
}
```

프론트:

- `pages/Compose.tsx` (또는 `Modules.tsx` 교체). 네비 라벨 “모듈 설정” 유지.
- 팔레트 / `InstanceCard` / `SiteBar` / `ApplyBar`.
- 미리보기 HTML(`frontend/preview`)에 구성 보드 목 한 장 추가.

시드 (`seed.py` · `fixtures/`):

- CONTROL_BINS 에 우선 I/O 12개 이름을 넣고 스텁 바이너리를 심는다.
- 각 family 의 최소 `.d` / `.desc` 샘플을 `fixtures/earthworm_8.0/params/` 에 둔다. 실기 없이 보드 pytest 가 돌게 한다.
- `getmenu` 스텁은 진단용.

카탈로그: `catalog()` 는 계속 `bin` 을 스캔하되, 응답에 `priority: bool`, `role`, `fleet` 을 붙인다. UI 기본 필터는 `priority || extra`.

---

## 26. 모노레포와 배포

[모노레포](diagrams/monorepo.html)

저장소는 **Docker Compose 모노레포**다. 앱은 `apps/` 아래, 서비스는 루트 `compose.yaml` 이다. 프론트 마이크로프론트 합성은 하지 않는다. 앱마다 UI 포트가 다르다.

### 26.1 레이아웃

```
dev/
  compose.yaml
  apps/
    earthworm_web/
    stationxml_manager/
    PPSD_v1/
    ringserver_seedlink_websocket/
    dataselect/
    recvQSCD20/          # GUI, Compose 프로필 없음
    seedlinkToMp3/
  packages/              # 공유 라이브러리 (비어 있음)
```

| 규약 | 내용 |
|------|------|
| 앱 루트 | `apps/<name>/` 안에서 `backend/`+`frontend/` 또는 해당 스택 |
| 오케스트레이션 | 루트 `docker compose`. 기본 프로필은 Earthworm 웹 |
| 이미지 | 앱별 Dockerfile. Earthworm Rocky tarball 은 **넣지 않음** |
| 시드 | `apps/earthworm_web/fixtures` + 볼륨 `earthworm-home` |
| 태그 | 앱 prefix (`earthworm-web-v0.x`) |
| GUI | `recvQSCD20` 는 호스트/Xvfb |

### 26.2 Compose 서비스

| 서비스 | 프로필 | 포트 |
|--------|--------|------|
| `earthworm-web` + `earthworm-web-ui` | (기본) | 8081 |
| `ppsd-api` + `ppsd-ui` | `ppsd` | 8080 |
| `stationxml-api` + `stationxml-ui` | `stationxml` | 8082 |
| `ringserver-api` + `ringserver-ui` | `ringserver` | 8083 |
| `dataselect` | `tools` | CLI |

UI nginx 가 `/api`·`/ws` 를 같은 오리진으로 프록시한다. 사람 세션 쿠키가 포트가 갈라진 API 로 새지 않는다.

실제 `startstop` 은 `ipc: host` 와 `compose.override.example.yaml` 의 `EW_HOME` 바인드. SysV IPC 가 컨테이너에서 실패하면 웹만 Docker, Earthworm 은 호스트.

### 26.3 같은 저장소 다른 앱

| 앱 | Earthworm 웹 |
|----|----------------|
| ringserver | `ew2ringserver`/`slink2ew` 포트 교차. Compose 프로필 `ringserver` |
| stationxml | SCNL 수동. 프로필 `stationxml` |
| PPSD | 아카이브 소비. 프로필 `ppsd` |
| dataselect | MiniSEED CLI 이미지 |

### 26.4 CI

- `apps/earthworm_web/**` → pytest + frontend build
- `docker compose config` 로 Compose 문법
- 계획 HTML 은 `apps/earthworm_web/scripts/build_plan_html.py`

---

## 27. 구현 단계 (본계획 12절을 이 문서로 재배치)

구현 순서는 **2b(작업자·이력) → 3 → 4**. 작업자 없는 적용은 머지하지 않는다. 티켓 단위·MVP 수락은 [plan_mvp.md](plan_mvp.md) · [plan_ops.md](plan_ops.md).

### 3단계 — 우선 카탈로그와 스키마

- `module_fields.yaml` + `/api/modules/schema`
- 카탈로그에 `priority` / `role` / `fleet`
- 시드에 I/O 12 스텁 + 샘플 `.d`
- 팔레트 UI (아직 일괄 적용 없음). 기타 등록 API

### 4단계 — 구성 보드와 일괄 적용

- `GET/POST /api/compose*`
- 인스턴스 카드, 사이트 공통, 검토/적용/시작
- 포트·탱크·Process 유일 검증 pytest
- 기존 clone API 를 apply 가 호출
- `Variables.tsx` 를 보드 사이트로 흡수

### 5단계 — 로그·스니프 (본계획 4단계와 동일)

구성 보드와 독립. `getmenu` 를 진단에 연결 (wave_serverV 인스턴스 콤보).

### 6단계 — 배포 패키징 (Docker 모노레포)

- 루트 `compose.yaml`. 앱은 `apps/<name>/`
- 기본 프로필: Earthworm 웹 UI `:8081`. 다른 앱은 `--profile`
- `compose.override.example.yaml` 로 `EW_HOME` 바인드 · `ipc: host`
- README 배포 절, 태그 `earthworm-web-v0.x`
- systemd 유닛은 호스트에서 Earthworm 만 돌릴 때 선택

본계획 5단계 P2(포트 인벤토리)는 구성 보드 검증이 대체하므로 **4단계에 흡수**한다. tankplayer 시험 프로파일은 기타 등록으로 미룬다.

---

## 28. 위험 (이 범위만)

| 위험 | 완화 |
|------|------|
| 한 창에 필드가 너무 많음 | 1차 스키마만. 고급은 원문 |
| 적용 중 일부만 기록 | 스냅샷 롤백. 적용 로그 |
| Alive 중 `.d` 변경이 안 먹음 | 배지 + 행 restart. 적용≠시작 |
| AuthCode 가 브라우저·감사 로그에 남음 | password 입력, 로그 마스킹, 파일 권한 |
| 포트가 ephemeral 대역 | 경고 + 제안값 16xxx |
| `bin` 복사본이 업그레이드 때 낡음 | 적용 시 family 원본 mtime/해시 비교, “원본으로 다시 복사” 동작 |
| 모노레포 조기 rename | 1차는 경로 유지 |
| 우선 목록 밖 모듈을 숨겨 운영자가 못 찾음 | 기타 등록 + 카탈로그 필터 “전체 bin” |

---

## 29. 현재 코드 갭 (구현 착수 시 체크)

| 위치 | 갭 |
|------|-----|
| `module_catalog.py` | 화이트리스트·role·fleet 없음 |
| `Modules.tsx` | 토글 + prompt 복제 |
| `Variables.tsx` | 공통키만, I/O 필드 없음 |
| `seed.py` `CONTROL_BINS` | I/O 12개·getmenu 없음 |
| `module_fields.yaml` | 없음 |
| `/api/compose*` | 없음 |
| `deploy/` | 없음 |

이 파일이 닫히는 조건: 3–4단계가 머지되어 우선 12 Process 를 한 창에서 여러 인스턴스로 적용하고, 시드만으로 pytest 가 검증·apply 를 통과하는 것. 그 시점이 **MVP** 다 ([30절](plan_mvp.md)).
