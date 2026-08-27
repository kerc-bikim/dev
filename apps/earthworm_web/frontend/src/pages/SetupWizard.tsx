import { useEffect, useState } from "react";
import { api, type Check, type RingRow } from "../api/client";
import { Field } from "../components/Confirm";

const STEPS = ["디렉터리", "설치 ID", "링 구성", "검증"];

type Props = { onDone: () => void; toast: (m: string) => void; needBootstrap?: boolean };

export function SetupWizard({ onDone, toast, needBootstrap }: Props) {
  const [step, setStep] = useState(0);
  const [home, setHome] = useState("");
  const [version, setVersion] = useState("");
  const [runDir, setRunDir] = useState("");
  const [retention, setRetention] = useState("14");
  const [inst, setInst] = useState("INST_UNKNOWN");
  const [insts, setInsts] = useState<string[]>(["INST_UNKNOWN"]);
  const [rings, setRings] = useState<RingRow[]>([]);
  const [checks, setChecks] = useState<Check[]>([]);
  const [busy, setBusy] = useState(false);
  const [adminUser, setAdminUser] = useState("");
  const [adminName, setAdminName] = useState("");
  const [adminPass, setAdminPass] = useState("");

  useEffect(() => {
    api<{
      directories: { EW_HOME: string; EW_VERSION: string; EW_RUN_DIR: string; retention_days: number };
      installations: string[];
      rings: RingRow[];
    }>("/api/setup/defaults")
      .then((d) => {
        setHome(d.directories.EW_HOME);
        setVersion(d.directories.EW_VERSION);
        setRunDir(d.directories.EW_RUN_DIR);
        setRetention(String(d.directories.retention_days));
        setInsts(d.installations);
        setRings(d.rings);
      })
      .catch((e: Error) => toast(e.message));
  }, [toast]);

  async function next() {
    setBusy(true);
    try {
      if (step === 0) {
        await api("/api/setup/directories", {
          method: "PUT",
          body: JSON.stringify({
            EW_HOME: home,
            EW_VERSION: version,
            EW_RUN_DIR: runDir,
            retention_days: Number(retention),
          }),
        });
      } else if (step === 1) {
        await api("/api/setup/installation", {
          method: "PUT",
          body: JSON.stringify({ EW_INSTALLATION: inst }),
        });
      } else if (step === 2) {
        await api("/api/setup/rings", { method: "PUT", body: JSON.stringify({ rings }) });
      }
      if (step === 2) {
        const v = await api<{ ok: boolean; checks: Check[] }>("/api/setup/validate", { method: "POST" });
        setChecks(v.checks);
      }
      setStep((s) => Math.min(3, s + 1));
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function complete() {
    setBusy(true);
    try {
      const v = await api<{ ok: boolean; checks: Check[] }>("/api/setup/validate", { method: "POST" });
      setChecks(v.checks);
      if (!v.ok) {
        toast("검증을 통과하지 못했습니다");
        return;
      }
      if (needBootstrap) {
        await api("/api/auth/bootstrap", {
          method: "POST",
          body: JSON.stringify({
            username: adminUser,
            display_name: adminName || adminUser,
            password: adminPass,
          }),
        });
      }
      await api("/api/setup/complete", { method: "POST" });
      toast("초기 설정 완료. 이후 메뉴가 열렸습니다.");
      onDone();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <p className="kicker">초기 설정</p>
      <h2>Earthworm 기반 구성</h2>
      <p className="lead">디렉터리와 링을 먼저 만듭니다. 완료 전에는 모듈 기동 메뉴가 잠깁니다.</p>
      <div className="steps">
        {STEPS.map((n, i) => (
          <span key={n} className={`step ${i === step ? "on" : ""} ${i < step ? "done" : ""}`}>
            {i + 1}. {n}
          </span>
        ))}
      </div>
      {step === 0 && (
        <div className="card">
          <h3>단계 A — 기본 디렉터리</h3>
          <div className="grid cols-2">
            <Field label="EW_HOME" value={home} onChange={setHome} />
            <Field label="EW_VERSION" value={version} onChange={setVersion} />
            <Field label="EW_RUN_DIR" value={runDir} onChange={setRunDir} />
            <Field label="로그 보관 일수" value={retention} onChange={setRetention} type="number" />
          </div>
          <p className="lead">
            생성: <code>{runDir}/params</code> · <code>log</code> · <code>data</code>
          </p>
          <button className="primary" disabled={busy} onClick={() => void next()}>
            다음
          </button>
        </div>
      )}
      {step === 1 && (
        <div className="card">
          <h3>단계 B — 설치 ID 와 테이블 파일</h3>
          <label>EW_INSTALLATION</label>
          <select value={inst} onChange={(e) => setInst(e.target.value)}>
            {insts.map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
          <p className="lead" style={{ marginTop: 12 }}>
            earthworm.d / global / commonvars 를 EW_PARAMS 로 복사합니다. GetUtil 은 params 만 읽습니다.
          </p>
          <div className="row">
            <button onClick={() => setStep(0)}>이전</button>
            <button className="primary" disabled={busy} onClick={() => void next()}>
              다음
            </button>
          </div>
        </div>
      )}
      {step === 2 && (
        <div className="card">
          <h3>단계 C — 링 이름 · 키 · 크기 · 순서</h3>
          <p className="lead">첫 startstop 링은 제어 메시지용입니다. FLAG_RING 은 목록에 넣지 않습니다.</p>
          <table>
            <thead>
              <tr>
                <th>순서</th>
                <th>이름</th>
                <th>키</th>
                <th>KiB</th>
                <th>startstop</th>
              </tr>
            </thead>
            <tbody>
              {rings.map((r, i) => (
                <tr key={i}>
                  <td>{r.in_startstop && i === rings.findIndex((x) => x.in_startstop) ? "첫 줄" : i + 1}</td>
                  <td>
                    <input
                      value={r.name}
                      onChange={(e) => {
                        const nextR = [...rings];
                        nextR[i] = { ...r, name: e.target.value };
                        setRings(nextR);
                      }}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      value={r.key}
                      onChange={(e) => {
                        const nextR = [...rings];
                        nextR[i] = { ...r, key: Number(e.target.value) };
                        setRings(nextR);
                      }}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      value={r.size}
                      onChange={(e) => {
                        const nextR = [...rings];
                        nextR[i] = { ...r, size: Number(e.target.value) };
                        setRings(nextR);
                      }}
                    />
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      checked={r.in_startstop}
                      onChange={(e) => {
                        const nextR = [...rings];
                        nextR[i] = { ...r, in_startstop: e.target.checked };
                        setRings(nextR);
                      }}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row">
            <button onClick={() => setStep(1)}>이전</button>
            <button className="primary" disabled={busy} onClick={() => void next()}>
              다음
            </button>
          </div>
        </div>
      )}
      {step === 3 && (
        <div className="card">
          <h3>단계 D — 검증</h3>
          <ul>
            {checks.map((c) => (
              <li key={c.name} className={c.ok ? "hb-ok" : "hb-bad"}>
                {c.ok ? "통과" : "실패"} — {c.name}
                {c.detail ? ` (${c.detail})` : ""}
              </li>
            ))}
          </ul>
          <p className="lead">완료해도 startstop 은 자동 기동하지 않습니다. 대시보드에서 시작하세요.</p>
          {needBootstrap && (
            <div className="grid cols-2" style={{ marginBottom: 12 }}>
              <Field label="관리자 로그인 ID" value={adminUser} onChange={setAdminUser} />
              <Field label="표시 이름" value={adminName} onChange={setAdminName} />
              <Field label="비밀번호 (10자 이상)" value={adminPass} onChange={setAdminPass} type="password" />
            </div>
          )}
          <div className="row">
            <button onClick={() => setStep(2)}>이전</button>
            <button className="primary" disabled={busy} onClick={() => void complete()}>
              초기 설정 완료
            </button>
          </div>
        </div>
      )}
    </>
  );
}
