import { type MouseEvent, useEffect } from "react";

const CHAPTERS = [
  "설치와 docker compose",
  "첫 관리자 계정",
  "기관·사용자·역할",
  "NRL 연결, 캐시, 오프라인 zip",
  "별칭과 NRL 제외 장비",
  "변환기 JAR, 메모리, 타임아웃",
  "백업과 복구 확인",
  "잠금 강제 해제",
  "로그 위치, 실패 작업 대응",
  "업그레이드와 마이그레이션",
];

function chapterPath(chapter: number): string {
  return `/help/admin/${chapter}#admin-chapter-${chapter}`;
}

function openChapter(event: MouseEvent<HTMLAnchorElement>, chapter: number) {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  window.history.pushState({ fromApp: true }, "", chapterPath(chapter));
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.setTimeout(() => {
    document.getElementById(`admin-chapter-${chapter}`)?.scrollIntoView({ block: "start" });
  });
}

export function AdminHelpLink({
  chapter,
  label,
}: {
  chapter: number;
  label: string;
}) {
  return (
    <a
      className="field-hint"
      href={chapterPath(chapter)}
      title={`${label} 관리자 매뉴얼에서 보기`}
      aria-label={`${label} 관리자 매뉴얼에서 보기`}
      onClick={(event) => openChapter(event, chapter)}
    >
      ?
    </a>
  );
}

export function AdminManual({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const match = window.location.pathname.match(/^\/help\/admin\/(10|[1-9])\/?$/);
    const chapter = match?.[1] || window.location.hash.match(/^#admin-chapter-(10|[1-9])$/)?.[1];
    if (!chapter) return;
    window.setTimeout(() => {
      document.getElementById(`admin-chapter-${chapter}`)?.scrollIntoView({ block: "start" });
    });
  }, []);

  return (
    <article className="manual" aria-labelledby="admin-manual-title">
      <div className="manual-heading">
        <div>
          <p className="manual-kicker">PDCC Web 3.8.1</p>
          <h2 id="admin-manual-title">관리자 매뉴얼</h2>
          <p className="hint">
            설치, 계정, NRL, 변환 작업, 백업과 장애 대응을 위한 운영 절차입니다.
          </p>
        </div>
        <button type="button" onClick={onClose}>
          이전 화면
        </button>
      </div>

      <nav className="manual-toc" aria-label="관리자 매뉴얼 목차">
        <strong>목차</strong>
        <ol>
          {CHAPTERS.map((title, index) => {
            const chapter = index + 1;
            return (
              <li key={title}>
                <a href={chapterPath(chapter)} onClick={(event) => openChapter(event, chapter)}>
                  {title}
                </a>
              </li>
            );
          })}
        </ol>
      </nav>

      <section id="admin-chapter-1" className="manual-chapter">
        <h3>1장. 설치와 docker compose</h3>
        <p>
          배포 전에 <code>infra/env.example</code>을 기준으로 환경 변수를 준비하고{" "}
          <code>APP_SECRET</code>, PostgreSQL 비밀번호와 외부 공개 포트를 운영 값으로 바꿉니다.
          데이터베이스와 <code>/data</code> 볼륨은 컨테이너를 다시 만들어도 유지되는 저장소에
          배치합니다.
        </p>
        <pre><code>{`cd pdcc_web
docker compose -f infra/docker-compose.yml up -d --build
docker compose -f infra/docker-compose.yml ps
curl -fsS http://127.0.0.1:8080/health`}</code></pre>
        <p>
          정상 응답은 <code>ok</code>, <code>db</code>, <code>redis</code>가 모두{" "}
          <code>true</code>입니다. 기본 compose에는 작업 worker가 없으므로 공식 검증과
          SEED·RESP 작업을 쓰는 운영 환경에서는 API와 같은 코드·환경 변수로{" "}
          <code>python -m app.jobs.runner</code>를 별도 서비스로 계속 실행합니다.
        </p>
      </section>

      <section id="admin-chapter-2" className="manual-chapter">
        <h3>2장. 첫 관리자 계정</h3>
        <p>
          최초 기동에만 <code>DEV_BOOTSTRAP_ADMIN=true</code>를 설정하면{" "}
          <code>admin</code> 계정이 만들어집니다. <code>admin/admin</code>으로 로그인한 뒤 관리자
          화면에서 실제 운영용 관리자 계정을 다른 아이디와 강한 비밀번호로 생성합니다.
        </p>
        <p>
          운영용 계정 로그인을 확인한 다음 <code>DEV_BOOTSTRAP_ADMIN=false</code>로 바꾸고 API를
          다시 시작합니다. 이 설정이 꺼지면 <code>admin</code> 아이디 로그인은 차단됩니다. 초기
          비밀번호와 기본 <code>APP_SECRET</code>을 운영에 남기지 않습니다.
        </p>
      </section>

      <section id="admin-chapter-3" className="manual-chapter">
        <h3>3장. 기관·사용자·역할</h3>
        <p>
          기관을 먼저 만들고 사용자를 기관에 소속시킵니다. 조회자는 프로젝트 열람과 StationXML
          다운로드만, 편집자는 초안·검증·내보내기, 관리자는 사용자와 운영 설정을 관리합니다.
          비활성화는 과거 기록을 보존하면서 새 로그인을 막습니다.
        </p>
        <p>
          사용자를 만들었다고 모든 프로젝트가 보이지는 않습니다. <strong>프로젝트 멤버</strong>에서
          프로젝트와 사용자를 고르고 프로젝트 역할을 추가합니다. 역할 변경과 비활성화 전에는 진행
          중인 편집·내보내기 작업이 있는지 확인합니다.
        </p>
      </section>

      <section id="admin-chapter-4" className="manual-chapter">
        <h3>4장. NRL 연결, 캐시, 오프라인 zip</h3>
        <dl className="manual-fields">
          <div><dt><code>NRL_BASE_URL</code></dt><dd>EarthScope NRL API 주소입니다.</dd></div>
          <div><dt><code>NRL_TIMEOUT_SEC</code></dt><dd>온라인 요청 제한 시간이며 기본은 30초입니다.</dd></div>
          <div><dt><code>NRL_CACHE_TTL_SEC</code></dt><dd>Redis catalog·prefix 캐시 TTL이며 기본은 3600초입니다.</dd></div>
          <div><dt><code>NRL_MODE</code></dt><dd><code>online</code>, <code>cache-first</code>, <code>offline</code> 중 하나입니다.</dd></div>
          <div><dt><code>NRL_OFFLINE_ZIP</code></dt><dd><code>full_NRL_v2.stationxml.zip</code>의 서버 경로입니다.</dd></div>
        </dl>
        <p>
          온라인 장애 시 유효한 Redis 캐시가 있으면 화면에 <strong>캐시 사용</strong>이 표시됩니다.
          장기 폐쇄망 운영은 관리자 화면에서 전체 zip을 받은 뒤 <strong>오프라인 사용</strong>으로
          전환하고, 위저드 검색과 응답 미리보기를 실제로 확인합니다. zip은 <code>/data</code>의
          영속 볼륨에 두며 대시보드에서 마지막 동기화와 크기를 확인합니다.
        </p>
      </section>

      <section id="admin-chapter-5" className="manual-chapter">
        <h3>5장. 별칭과 NRL 제외 장비</h3>
        <p>
          <strong>NRL 검색 별칭</strong>은 현장에서 쓰는 검색어를 NRL 제조사·모델 이름에 연결합니다.
          저장 즉시 다음 검색부터 적용되므로 실제 검색 결과를 확인한 뒤 사용자에게 알립니다.
        </p>
        <p>
          개별 교정값 때문에 NRL 응답을 적용하면 안 되는 장비는 <strong>NRL 제외 장비</strong>에
          검색어, 표시 이름과 대체 절차를 입력합니다. Certimus·Minimus·Fortimus처럼 RESP 또는
          교정 시트가 필요한 장비를 일반 NRL 모델에 억지로 연결하지 않습니다. 모든 변경은 감사
          로그에서 확인합니다.
        </p>
      </section>

      <section id="admin-chapter-6" className="manual-chapter">
        <h3>6장. 변환기 JAR, 메모리, 타임아웃</h3>
        <dl className="manual-fields">
          <div><dt><code>SEED_CONVERTER_JAR</code></dt><dd>StationXML↔dataless SEED 공식 converter 경로입니다.</dd></div>
          <div><dt><code>CONVERTER_TIMEOUT_SEC</code></dt><dd>converter 실행 제한이며 기본은 60초입니다.</dd></div>
          <div><dt><code>VALIDATOR_JAR</code></dt><dd>공식 StationXML validator 경로입니다.</dd></div>
          <div><dt><code>VALIDATOR_TIMEOUT_SEC</code></dt><dd>validator 실행 제한이며 기본은 60초입니다.</dd></div>
        </dl>
        <p>
          compose 이미지에서 JAR를 쓸 때는 호환 Java runtime을 포함한 API·worker 이미지를 만들고,
          JAR를 양쪽에서 같은 절대 경로로 읽을 수 있게 마운트합니다. Java heap은 컨테이너 메모리
          제한보다 작게 <code>JAVA_TOOL_OPTIONS=-Xmx512m</code>처럼 지정하고, 대형 파일에서만 측정
          후 늘립니다. 제한 시간을 무조건 늘리기 전에 worker CPU·메모리와 JAR stderr를 확인합니다.
          JAR가 없거나 실패하면 지원되는 작업은 Python/ObsPy 대체 경로를 사용하며 경고가 로그와
          결과에 남습니다.
        </p>
      </section>

      <section id="admin-chapter-7" className="manual-chapter">
        <h3>7장. 백업과 복구 확인</h3>
        <p>
          <code>infra/backup-postgres.sh</code>는 custom-format PostgreSQL 덤프를 만들고{" "}
          <code>pg_restore --list</code> 검증이 성공한 경우에만{" "}
          <code>BACKUP_STATUS_FILE</code>에 UTC 성공 시각을 기록합니다. 관리자 대시보드의{" "}
          <strong>마지막 백업 성공</strong>이 갱신됐는지 확인하고 덤프를 별도 저장소에 복제합니다.
        </p>
        <pre><code>{`export BACKUP_DIR=/backup/pdcc
export BACKUP_STATUS_FILE=/data/backup-last-success
infra/backup-postgres.sh
pg_restore --list "$BACKUP_DIR"/pdcc-*.dump >/dev/null`}</code></pre>
        <p>
          복구 전 대상 덤프 검증과 현재 DB 긴급 백업을 수행하고 API·web의 쓰기를 중지합니다.
          <code>pg_restore --clean --if-exists --no-owner</code> 후 헬스, 로그인, 프로젝트 목록,
          StationXML 다운로드를 확인합니다. 복구 자체로 성공 표식을 바꾸지 말고 검증 후 새 백업을
          성공시킵니다. 폐쇄망이면 NRL zip도 별도로 보관합니다.
        </p>
      </section>

      <section id="admin-chapter-8" className="manual-chapter">
        <h3>8장. 잠금 강제 해제</h3>
        <p>
          잠금은 편집 중 30초마다 갱신되고 기본 TTL은 300초입니다. 먼저 사용자에게 편집 종료와 초안
          저장 여부를 확인합니다. 대시보드의 장기 잠금에서 관측소 경로와 편집자를 확인한 뒤, 사용자가
          더 이상 편집하지 않을 때만 관리자 세션으로 강제 해제합니다.
        </p>
        <pre><code>{`curl -b admin-cookie.txt -X DELETE \
  'http://127.0.0.1:8080/api/locks?station_path=sta%3A프로젝트ID%3ANET.STA%23시작시각&force=true'`}</code></pre>
        <p>
          강제 해제는 다른 편집자의 저장과 충돌할 수 있습니다. 해제 후 해당 사용자는 화면을 새로
          열어 최신 버전을 확인해야 하며, 관리자 감사 로그에 <strong>잠금 강제 해제</strong>가
          남았는지 확인합니다.
        </p>
      </section>

      <section id="admin-chapter-9" className="manual-chapter">
        <h3>9장. 로그 위치, 실패 작업 대응</h3>
        <p>
          compose 배포의 API 로그는{" "}
          <code>docker compose -f infra/docker-compose.yml logs --since=1h api</code>로 봅니다.
          worker는 실행한 서비스의 stdout/stderr 또는 서비스 관리자의 로그에서{" "}
          <code>pdcc.worker</code>를 찾습니다. NRL 문제는 <code>pdcc.nrl</code>, 변환 문제는{" "}
          <code>pdcc.seed_convert</code>, validator 문제는 <code>pdcc.validator</code> 기록을
          작업 시각·작업 ID와 함께 확인합니다.
        </p>
        <p>
          대시보드의 최근 실패 작업에서 유형, 사용자, 오류를 확인하고 원인을 먼저 해결합니다. 그 뒤
          상단 작업 목록의 <strong>다시 시도</strong>를 사용하면 같은 스냅샷 작업이 다시 대기열에
          들어갑니다. 대기 상태가 계속되면 worker가 실행 중인지, Redis 연결과 worker heartbeat가
          정상인지 확인합니다. 반복 실패 작업은 원본과 오류 시각을 보존한 뒤 조사합니다.
        </p>
      </section>

      <section id="admin-chapter-10" className="manual-chapter">
        <h3>10장. 업그레이드와 마이그레이션</h3>
        <p>
          릴리스 변경 사항과 환경 변수 차이를 검토하고, 검증된 PostgreSQL 덤프와 폐쇄망 NRL zip을
          확보한 뒤 점검 시간을 알립니다. 진행 중인 편집과 worker 작업이 없는지 확인하고 API·web을
          중지한 다음 새 이미지를 빌드하거나 가져옵니다.
        </p>
        <p>
          현재 버전은 API 시작 시 누락된 테이블·지원 컬럼을 자동 보완합니다. API 시작 로그에서 스키마
          오류가 없는지 확인한 다음 <code>/health</code>, 관리자 로그인, 프로젝트 열기, NRL 검색,
          검증과 내보내기를 순서대로 점검하고 web을 공개합니다. 실패하면 새 쓰기를 막은 상태에서 이전
          이미지와 업그레이드 직전 DB 덤프로 함께 되돌립니다. 이미지 버전만 되돌리고 변경된 DB를
          그대로 두지 않습니다.
        </p>
      </section>

      <a className="manual-top-link" href="#admin-manual-title">맨 위로</a>
    </article>
  );
}
