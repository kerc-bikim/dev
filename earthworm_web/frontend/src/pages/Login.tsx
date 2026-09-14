import { useState } from "react";
import { api } from "../api/client";
import { Field } from "../components/Confirm";

type Props = {
  bootstrap: boolean;
  toast: (m: string) => void;
  onAuthed: () => void;
};

export function LoginPage({ bootstrap, toast, onAuthed }: Props) {
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    try {
      if (bootstrap) {
        await api("/api/auth/bootstrap", {
          method: "POST",
          body: JSON.stringify({
            username,
            display_name: displayName || username,
            password,
          }),
        });
        toast("최초 관리자를 만들었습니다.");
      } else {
        await api("/api/auth/login", {
          method: "POST",
          body: JSON.stringify({ username, password }),
        });
      }
      onAuthed();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <div className="card login-card">
        <p className="kicker">Earthworm Web Control</p>
        <h2>{bootstrap ? "최초 관리자" : "로그인"}</h2>
        <p className="lead">
          {bootstrap
            ? "작업자 테이블이 비어 있습니다. 관리자 계정을 만드세요. 비밀번호는 10자 이상입니다."
            : "표시 이름으로 이력이 남습니다. 공유 API 키는 쓰지 않습니다."}
        </p>
        <Field label="로그인 ID" value={username} onChange={setUsername} />
        {bootstrap && <Field label="표시 이름" value={displayName} onChange={setDisplayName} />}
        <Field label="비밀번호" value={password} onChange={setPassword} type="password" />
        <button className="primary" disabled={busy} onClick={() => void submit()} style={{ marginTop: 12 }}>
          {bootstrap ? "관리자 만들기" : "로그인"}
        </button>
      </div>
    </div>
  );
}
