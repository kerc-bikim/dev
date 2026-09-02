const EXAMPLE_STEPS = [
  "S1. stub / stub으로 로그인합니다.",
  "S2. 이름은 ‘YZ 상시망’, 네트워크는 YZ로 새 프로젝트를 만듭니다.",
  "S3. 프로젝트에서 관측소 위저드를 열고 관측소 코드를 TEST1로 입력합니다.",
  "S4. 사이트명과 운영기관을 확인합니다.",
  "S5. 시작 시각을 입력하고 현재 운영을 선택해 종료 시각을 비웁니다.",
  "S6. 위도·경도·고도와 센서 깊이를 입력합니다.",
  "S7. 센서는 Guralp → CMG-3T를 선택하고 실제 장비 설정 질문에 답합니다.",
  "S8. 기록계는 Quanterra → Q330HR을 선택하고 실제 게인·샘플률 설정에 답합니다.",
  "S9. location 00과 BHZ / BHN / BHE 3성분 패턴을 선택합니다.",
  "S10. 확인 표에서 YZ.TEST1, 기간, 좌표, 채널 방향과 NRL 응답을 검토한 뒤 마칩니다.",
  "S11. 트리에서 TEST1과 각 채널을 열어 메타데이터를 확인하고 필요한 값을 수정합니다.",
  "S12. 응답 곡선을 VEL·DIS·ACC 단위로 확인한 뒤 같은 밴드 3성분에 NRL 응답을 적용합니다.",
  "S13. 검증을 실행하고 오류가 0건인지 확인한 뒤 초안을 저장합니다.",
  "S14. StationXML을 받고, 필요하면 손실 목록을 확인해 dataless SEED 또는 RESP를 내보냅니다.",
];

export function UserManual({ onClose }: { onClose: () => void }) {
  return (
    <article className="manual" aria-labelledby="user-manual-title">
      <div className="manual-heading">
        <div>
          <p className="manual-kicker">PDCC Web 3.8.1</p>
          <h2 id="user-manual-title">사용자 매뉴얼</h2>
          <p className="hint">
            프로젝트 생성부터 StationXML 검증·내보내기까지의 현장 작업 절차입니다.
          </p>
        </div>
        <button type="button" onClick={onClose}>
          이전 화면
        </button>
      </div>

      <nav className="manual-toc" aria-label="사용자 매뉴얼 목차">
        <strong>목차</strong>
        <ol>
          <li><a href="#chapter-1">로그인과 화면</a></li>
          <li><a href="#chapter-2">프로젝트 만들기</a></li>
          <li><a href="#chapter-3">기존 파일 열기</a></li>
          <li><a href="#chapter-4">관측소 위저드</a></li>
          <li><a href="#chapter-5">장비와 NRL 선택</a></li>
          <li><a href="#chapter-6">관측소 정보 편집</a></li>
          <li><a href="#chapter-7">채널 정보 편집</a></li>
          <li><a href="#chapter-8">응답 확인과 적용</a></li>
          <li><a href="#chapter-9">초안·잠금·공동 작업</a></li>
          <li><a href="#chapter-10">관측소 복제</a></li>
          <li><a href="#chapter-11">검증과 오류 수정</a></li>
          <li><a href="#chapter-12">저장·버전·내보내기</a></li>
          <li><a href="#chapter-13">YZ.TEST1 전체 예제</a></li>
        </ol>
      </nav>

      <section id="chapter-1" className="manual-chapter">
        <h3>1장. 로그인과 화면</h3>
        <p>
          발급받은 계정으로 로그인합니다. 상단에는 사용자 역할과 작업 벨이, 하단에는 API·DB·Redis와
          NRL 상태가 표시됩니다. 빨간 상태가 계속되면 편집 내용을 저장하지 말고 관리자에게 알립니다.
        </p>
        <p>
          조회자는 프로젝트를 읽고 StationXML만 받을 수 있습니다. 편집자는 초안 작성과 내보내기를,
          관리자는 사용자·운영 설정을 관리할 수 있습니다.
        </p>
      </section>

      <section id="chapter-2" className="manual-chapter">
        <h3>2장. 프로젝트 만들기</h3>
        <p>
          <strong>새 프로젝트</strong>는 이름, 네트워크 코드, 운영기관으로 빈 StationXML 작업 공간을
          만듭니다. 네트워크 코드는 실제 FDSN 코드를 대문자로 입력합니다. 프로젝트 카드는 관측소·채널
          수, 원본 보관 여부, NRL 적용 여부와 내 역할을 보여 줍니다.
        </p>
      </section>

      <section id="chapter-3" className="manual-chapter">
        <h3>3장. 기존 파일 열기</h3>
        <p>
          <strong>파일 열기</strong>로 StationXML, dataless SEED 또는 RESP를 가져옵니다. 원본 파일은
          그대로 보관되고 편집용 StationXML이 별도로 만들어집니다. 확장자와 실제 형식이 다르거나,
          암호화·손상된 파일, 허용 크기를 넘는 파일은 거부됩니다.
        </p>
        <p>
          변환 경고는 검사 패널에서 확인합니다. 가져오기가 끝난 뒤 원본 버튼으로 최초 파일을 다시
          받을 수 있습니다.
        </p>
      </section>

      <section id="chapter-4" className="manual-chapter">
        <h3>4장. 관측소 위저드</h3>
        <p>
          프로젝트를 열고 <strong>관측소 위저드</strong>를 선택합니다. 식별, 이름, 기간, 위치, 장비,
          채널, 확인 순서로 입력합니다. 현재 운영 중이면 종료 시각을 만들지 않습니다. 채널 패턴은
          보통 수직·북·동 3성분(BHZ/BHN/BHE)을 사용하며 설치 사양과 다르면 직접 입력합니다.
        </p>
        <p>마지막 확인 표에서 NSLC, 기간, 좌표, 방위각, 경사와 응답 유무를 확인한 뒤 마칩니다.</p>
      </section>

      <section id="chapter-5" className="manual-chapter">
        <h3>5장. 장비와 NRL 선택</h3>
        <p>
          장비 명판과 설치 기록을 기준으로 제조사와 모델을 고릅니다. 질문이 하나의 값으로만 결정되면
          자동으로 넘어가며, 게인·코너 주기·샘플률 같은 선택지가 여러 개면 현장 설정과 일치하는 값을
          선택합니다. 확실하지 않으면 <strong>나중에 추가</strong>를 선택하고 추측값을 넣지 않습니다.
        </p>
        <aside className="manual-example">
          예제 장비: 센서 <code>Guralp CMG-3T</code>, 기록계 <code>Quanterra Q330HR</code>.
          모델 이름이 비슷해도 설치 장비와 설정이 다르면 응답이 달라집니다.
        </aside>
      </section>

      <section id="chapter-6" className="manual-chapter">
        <h3>6장. 관측소 정보 편집</h3>
        <p>
          트리에서 관측소 epoch를 선택해 사이트명, 종료일, 위도, 경도, 고도를 수정합니다. 시작일은
          epoch 식별값이므로 직접 바꾸지 않습니다. 좌표나 기간을 바꾸면 채널에도 반영할지 묻습니다.
          같은 설치를 나타내는 채널이면 함께 반영하고, 채널별 값이 따로 관리되는 경우 관측소만
          선택합니다.
        </p>
        <p>각 필드의 <strong>?</strong>를 누르면 이 장으로 돌아와 입력 기준을 확인할 수 있습니다.</p>
      </section>

      <section id="chapter-7" className="manual-chapter">
        <h3>7장. 채널 정보 편집</h3>
        <dl className="manual-fields">
          <div><dt>코드</dt><dd>3자 SEED 채널 코드입니다. 예: BHZ, BHN, BHE.</dd></div>
          <div><dt>location</dt><dd>0–2자 위치 코드입니다. 공백과 00은 서로 다른 코드입니다.</dd></div>
          <div><dt>깊이</dt><dd>지면 기준 센서 깊이(m). 고도에 더하면 지표면 고도입니다.</dd></div>
          <div><dt>방위각</dt><dd>북쪽 0°, 동쪽 90° 기준의 수평 방향입니다.</dd></div>
          <div><dt>경사</dt><dd>수평 0°, 위쪽 +90°, 아래쪽 -90°입니다. 수직 지진계는 보통 -90°입니다.</dd></div>
          <div><dt>샘플링</dt><dd>채널 최종 샘플률(Hz)이며 Q330HR NRL 설정과 일치해야 합니다.</dd></div>
          <div><dt>감도</dt><dd>InstrumentSensitivity입니다. 응답 단계 게인 곱과 일치해야 합니다.</dd></div>
        </dl>
        <p>칸을 벗어나면 서버 버전이 아니라 초안에 저장됩니다. 검사 오류가 나면 값을 되돌려 확인합니다.</p>
      </section>

      <section id="chapter-8" className="manual-chapter">
        <h3>8장. 응답 확인과 적용</h3>
        <p>
          센서와 기록계를 끝까지 선택한 뒤 응답 미리보기를 불러옵니다. 곡선을 변위(DIS), 속도(VEL),
          가속도(ACC) 단위로 바꿔 보고 예상 대역과 극단값을 확인합니다. 같은 location·밴드의 3성분이
          기본 적용 대상으로 선택되므로 제외할 채널은 체크를 풉니다.
        </p>
        <p>자주 쓰는 조합은 장비 세트로 저장할 수 있습니다. ‘옛 NRL’ 경고가 있는 세트는 재선택합니다.</p>
      </section>

      <section id="chapter-9" className="manual-chapter">
        <h3>9장. 초안·잠금·공동 작업</h3>
        <p>
          편집 내용은 먼저 개인 초안에 쌓입니다. <strong>초안 저장</strong>을 눌러 새 서버 버전으로
          확정합니다. 다시 접속했을 때 저장하지 않은 초안이 있으면 이어가거나 마지막 버전으로 버릴 수
          있습니다.
        </p>
        <p>
          한 관측소 epoch는 한 번에 한 명만 수정합니다. 다른 사용자가 수정 중이면 읽기 전용으로
          표시됩니다. 잠금은 편집 중 자동 연장되므로 별도 해제 조작이 필요하지 않습니다.
        </p>
      </section>

      <section id="chapter-10" className="manual-chapter">
        <h3>10장. 관측소 복제</h3>
        <p>
          <strong>관측소 복제</strong>는 선택한 관측소의 채널과 응답을 여러 새 관측소로 복사합니다.
          표에 직접 입력하거나 스프레드시트 행을 붙여넣습니다. 코드가 빈 행은 무시됩니다. 생성 전에
          관측소 코드, 시작일, 좌표가 각 대상에 맞는지 확인합니다.
        </p>
      </section>

      <section id="chapter-11" className="manual-chapter">
        <h3>11장. 검증과 오류 수정</h3>
        <p>
          빠른 검사는 편집 중 기본 문제를 보여 줍니다. 상단 <strong>검증</strong>은 공식 전체 검사를
          작업 큐에서 실행하며, 진행 중에도 편집할 수 있고 이전 결과는 유지됩니다. 오류 행을 누르면
          관련 관측소·채널 필드로 이동합니다.
        </p>
        <p>오류는 내보내기를 막을 수 있습니다. 경고도 의도한 값인지 확인한 뒤 결과 스냅샷을 갱신합니다.</p>
      </section>

      <section id="chapter-12" className="manual-chapter">
        <h3>12장. 저장·버전·내보내기</h3>
        <p>
          검증 후 초안을 저장합니다. 버전 목록에서는 이전 버전을 확인하고 되돌릴 수 있으며, 실행 취소는
          최근 작업을 되돌립니다. <strong>StationXML</strong>은 현재 초안을 받습니다. dataless SEED는
          긴 코멘트·FIR 이름·확장 필드의 변환 손실 목록을 먼저 확인해야 합니다.
        </p>
        <p>
          RESP는 선택 채널 하나, RESP zip은 선택 관측소 전체 채널을 내보냅니다. 현재 편집된 감도가
          반영됩니다. 작업형 내보내기는 상단 작업 벨에서 진행률과 다운로드를 확인합니다.
        </p>
      </section>

      <section id="chapter-13" className="manual-chapter">
        <h3>13장. YZ.TEST1 전체 예제</h3>
        <p>
          아래 절차는 <code>YZ.TEST1</code>에 <code>CMG-3T</code>와 <code>Q330HR</code>을 연결해
          3성분 응답을 만들고 검증하는 기준 예제입니다. 날짜·좌표·장비 세부 설정은 실제 설치 기록으로
          바꿉니다.
        </p>
        <ol className="manual-scenario">
          {EXAMPLE_STEPS.map((step) => <li key={step.slice(0, 4)}>{step}</li>)}
        </ol>
      </section>

      <a className="manual-top-link" href="#user-manual-title">맨 위로</a>
    </article>
  );
}
