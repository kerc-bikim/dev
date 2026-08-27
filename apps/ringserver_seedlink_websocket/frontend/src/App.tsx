import { useEffect } from "react";
import { AppShell } from "./components/layout/AppShell";
import { useAppStore } from "./store/appStore";
import "./App.css";

export default function App() {
  const init = useAppStore((s) => s.init);
  useEffect(() => {
    void init().catch((e) => {
      console.error(e);
      alert(`초기화 실패: ${e instanceof Error ? e.message : String(e)}`);
    });
  }, [init]);

  return <AppShell />;
}
