import { useEffect } from "react";

const SECTIONS = [
  { id: "overview", label: "한눈에 보기" },
  { id: "excel", label: "엑셀로 만들기" },
  { id: "stationxml", label: "StationXML로 만들기" },
  { id: "seed", label: "Dataless SEED로 만들기" },
  { id: "ui", label: "화면에서 직접 만들기" },
  { id: "catalog", label: "장비와 NRL" },
  { id: "response", label: "응답 곡선·Poles/Zeros" },
  { id: "export", label: "내보내기" },
  { id: "workspace", label: "작업 공간 사용법" },
];

export function HelpPage({ onGoWorkspace }: { onGoWorkspace: () => void }) {
  useEffect(() => {
    const scroll = () => {
      const id = window.location.hash.replace(/^#/, "");
      if (id.startsWith("help-")) {
        document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    };
    scroll();
    window.addEventListener("hashchange", scroll);
    return () => window.removeEventListener("hashchange", scroll);
  }, []);
  return (
    <div className="help-page">
      <aside className="help-toc">
        <h2>메타데이터 생성 방법</h2>
        <p className="muted">엑셀 · StationXML · SEED · 화면 입력</p>
        <nav>
          {SECTIONS.map((item) => (
            <a key={item.id} href={`#help-${item.id}`}>
              {item.label}
            </a>
          ))}
        </nav>
        <button onClick={onGoWorkspace}>작업 공간으로</button>
      </aside>
      <article className="help-body">
        <header className="help-hero">
          <p className="help-kicker">홈 · 도움말</p>
          <h1>지진 메타데이터는 이렇게 만듭니다</h1>
          <p>
            이 도구는 네트워크 → 관측소 → 채널 계층을 SQLite에 두고, 엑셀·StationXML·dataless SEED로
            넣고 뺍니다. 한 채널이 한 행(또는 한 NSLC+시작시간)입니다. 계측기 응답은 채널에 붙는
            StationXML 조각이며, 엑셀만으로는 실을 수 없습니다.
          </p>
        </header>

        <section id="help-overview" className="help-section">
          <h2>한눈에 보기</h2>
          <ol className="help-steps">
            <li>
              <strong>가져오기</strong> — 상단 「가져오기」로 xlsx / xml / seed 파일을 올립니다.
            </li>
            <li>
              <strong>검토</strong> — 왼쪽 트리에서 관측망을 고르고 가운데에서 좌표·장비·시간을
              고칩니다.
            </li>
            <li>
              <strong>응답</strong> — 오른쪽에 곡선이 보입니다. 없으면 NRL을 적용하거나 StationXML을
              다시 가져옵니다.
            </li>
            <li>
              <strong>내보내기</strong> — StationXML은 응답이 없어도 됩니다. Dataless SEED는 모든
              채널에 응답이 있어야 합니다.
            </li>
          </ol>
        </section>

        <section id="help-excel" className="help-section">
          <h2>방법 1. 엑셀로 만들기</h2>
          <p>
            표로 관측망을 처음 만들 때 씁니다. 상단 내보내기 메뉴의 <strong>엑셀 템플릿</strong>을
            받아 <code>channels</code> 시트에 행을 채웁니다. 한 행 = 한 채널입니다.
          </p>
          <ul>
            <li>
              <strong>필수 열:</strong> 네트워크, 관측소, 채널, 위도, 경도, 시작시간, 샘플링레이트
            </li>
            <li>같은 관측소의 사이트명·좌표가 행마다 다르면 가져오기가 실패합니다.</li>
            <li>센서ID·기록계ID는 카탈로그 시트에 있는 값만 쓸 수 있습니다.</li>
            <li>방위각·경사를 비우면 채널 코드 마지막 글자(Z/N/E/1/2)로 추정합니다.</li>
          </ul>
          <p className="note">
            엑셀에는 계측기 응답(Poles/Zeros, FIR)이 없습니다. StationXML을 올린 뒤 엑셀을 다시
            가져와도, 같은 NSLC+시작시간의 기존 응답은 유지됩니다.
          </p>
        </section>

        <section id="help-stationxml" className="help-section">
          <h2>방법 2. StationXML로 만들기</h2>
          <p>
            FDSN StationXML은 좌표·장비와 함께 <strong>응답 단계</strong>를 그대로 가져옵니다.
            파일 확장자는 <code>.xml</code> 또는 <code>.stationxml</code>입니다.
          </p>
          <ul>
            <li>가져온 채널의 응답 출처는 <code>imported</code>가 됩니다.</li>
            <li>제조사·모델이 카탈로그에 없으면 사용자 정의 장비로 자동 추가됩니다.</li>
            <li>샘플링레이트와 시작시간이 없는 채널은 거절됩니다.</li>
          </ul>
        </section>

        <section id="help-seed" className="help-section">
          <h2>방법 3. Dataless SEED로 만들기</h2>
          <p>
            <code>.seed</code> / <code>.dataless</code> / <code>.dlsv</code> 파일을 올리면 네트워크·
            관측소·채널과 응답이 생깁니다. MiniSEED(파형만)는 가져올 수 없습니다. full SEED는
            파형을 버리고 메타만 가져오며 경고를 남깁니다.
          </p>
          <ul>
            <li>채널 코드는 3자, 네트워크 코드는 2자여야 다시 SEED로 내보낼 수 있습니다.</li>
            <li>한글 사이트명은 내보낼 때 관측소 코드로 대체되고 경고가 뜹니다.</li>
            <li>Polynomial / ResponseList 단계는 SEED로 쓸 수 없어 내보내기가 실패합니다.</li>
          </ul>
        </section>

        <section id="help-ui" className="help-section">
          <h2>방법 4. 화면에서 직접 만들기</h2>
          <p>
            파일이 없을 때는 왼쪽 트리 아래 <strong>관측소 추가</strong> · <strong>채널 추가</strong>로
            만듭니다. 네트워크 코드만 넣으면 관측소 저장 시 네트워크가 생깁니다.
          </p>
          <ul>
            <li>관측소 좌표·사이트명은 채널이 아니라 관측소 카드에서만 고칩니다.</li>
            <li>채널의 고유 키는 관측소 + 위치코드 + 채널 + 시작시간입니다.</li>
            <li>이렇게 만든 채널은 응답이 없습니다. NRL 또는 StationXML이 필요합니다.</li>
          </ul>
        </section>

        <section id="help-catalog" className="help-section">
          <h2>장비 카탈로그와 NRL</h2>
          <p>
            센서와 기록계는 카탈로그 ID만 고릅니다. NRL 키가 있는 쌍이면 채널의 <strong>NRL</strong>
            버튼으로 응답을 붙입니다. 내보내기 때 자동으로 붙지 않습니다.
          </p>
          <ul>
            <li>목록에 없는 장비는 채널 수정의 「목록에 없음」 또는 장비 카탈로그 페이지에서 추가합니다.</li>
            <li>ID를 비우면 자동으로 붙습니다. 사용 중인 ID는 삭제할 수 없습니다.</li>
            <li>카탈로그에 NRL 키를 나중에 넣어도 이미 저장된 채널 응답은 바뀌지 않습니다.</li>
          </ul>
        </section>

        <section id="help-response" className="help-section">
          <h2>응답 곡선과 Poles/Zeros</h2>
          <p>
            채널을 고르면 오른쪽에서 진폭·위상 곡선을 봅니다. 겹치기 체크는 최대 8채널입니다.
            Poles/Zeros 단계만 고칠 수 있고, A0(정규화 계수)는 저장 시 다시 계산됩니다.
          </p>
          <ul>
            <li>계산에 실패하면 원본 응답은 그대로 둡니다.</li>
            <li>켤레가 아닌 극은 저장은 되고 경고만 남깁니다.</li>
            <li>수정한 채널의 출처는 <code>edited</code>가 됩니다.</li>
          </ul>
        </section>

        <section id="help-export" className="help-section">
          <h2>내보내기</h2>
          <table>
            <thead>
              <tr>
                <th>형식</th>
                <th>내용</th>
                <th>조건</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>StationXML</td>
                <td>계층 + 응답 blob</td>
                <td>채널이 하나 이상</td>
              </tr>
              <tr>
                <td>Dataless SEED</td>
                <td>메타 + 응답 단계</td>
                <td>모든 채널에 쓸 수 있는 응답</td>
              </tr>
              <tr>
                <td>엑셀</td>
                <td>표 메타데이터</td>
                <td>응답은 포함하지 않음</td>
              </tr>
            </tbody>
          </table>
          <p>
            하단 상태 줄에 Dataless SEED가 왜 막혔는지가 나옵니다. 문제 채널의 NSLC를 눌러 트리에서
            바로 고를 수 있습니다.
          </p>
        </section>

        <section id="help-workspace" className="help-section">
          <h2>작업 공간 사용법</h2>
          <ul>
            <li>
              <strong>왼쪽</strong> — 네트워크 → 관측소 → 채널. NSLC 검색은 상단 칸을 씁니다.
            </li>
            <li>
              <strong>가운데</strong> — 고른 대상의 메타데이터. 같은 관측소의 다른 채널을 겹치기에
              넣을 수 있습니다.
            </li>
            <li>
              <strong>오른쪽</strong> — 응답 곡선과 Poles/Zeros.
            </li>
            <li>
              <strong>작업자</strong> 이름은 변경이력에만 남습니다. 로그인 계정은 없습니다.
            </li>
          </ul>
          <p>
            전체 교체 가져오기는 「기존 목록 교체」를 켠 뒤 확인해야 실행됩니다. 매칭되는 채널의
            응답은 새 파일에 응답이 없어도 유지됩니다.
          </p>
        </section>
      </article>
    </div>
  );
}
