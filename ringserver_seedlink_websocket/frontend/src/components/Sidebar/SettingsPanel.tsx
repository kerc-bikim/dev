import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { api } from "../../api/client";
import { useAppStore } from "../../store/appStore";
import type { AppSettings } from "../../types";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useTheme } from "@/theme/ThemeProvider";
import { THEME_OPTIONS, type ThemeId } from "@/theme/theme";
import { cn } from "@/lib/utils";

const DURATION_OPTIONS = [15, 30, 60, 120, 180, 240, 300, 600, 900, 1200, 1800, 3600, 7200];

function formatDuration(sec: number) {
  return sec < 60 ? `${sec}초` : sec < 3600 ? `${sec / 60}분` : `${sec / 3600}시간`;
}

export function SettingsPanel() {
  const open = useAppStore((s) => s.settingsOpen);
  const setSettingsOpen = useAppStore((s) => s.setSettingsOpen);
  const settings = useAppStore((s) => s.settings);
  const limits = useAppStore((s) => s.limits);
  const saveSettings = useAppStore((s) => s.saveSettings);
  const estimate = useAppStore((s) => s.estimateMemoryBytes);
  const {
    theme,
    previewTheme,
    mode,
    previewMode,
    setPreviewTheme,
    setPreviewMode,
    commitTheme,
    revertPreview,
  } = useTheme();
  const [testMsg, setTestMsg] = useState("");
  const [testOk, setTestOk] = useState<boolean | null>(null);
  const [testing, setTesting] = useState(false);
  const [draft, setDraft] = useState<AppSettings | null>(settings);

  useEffect(() => {
    if (open) {
      setDraft(settings);
      setPreviewTheme(theme);
      setPreviewMode(mode);
      setTestMsg("");
      setTestOk(null);
    }
    // 열릴 때만 저장된 외관으로 미리보기를 초기화한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, settings, theme, mode]);

  const close = (commit = false) => {
    if (!commit) revertPreview();
    setSettingsOpen(false);
  };

  if (!settings || !draft) {
    return (
      <Dialog open={open} onOpenChange={(next) => !next && close()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>설정</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">설정 로딩…</p>
        </DialogContent>
      </Dialog>
    );
  }

  const mem = estimate();
  const warn = limits && mem > limits.memoryWarnBytes;

  const apply = async () => {
    try {
      commitTheme(previewTheme, previewMode);
      await saveSettings({ ...draft, protocol: "datalink" });
      close(true);
    } catch (e) {
      setTestOk(false);
      setTestMsg(`저장 실패: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const test = async () => {
    setTesting(true);
    setTestMsg("연결 테스트 중…");
    setTestOk(null);
    try {
      await saveSettings({ ringserverUrl: draft.ringserverUrl });
      const res = await api.testRingserver();
      if (res.ok) {
        setTestOk(true);
        setTestMsg(`연결 성공 (${res.status}) ${res.target}`);
      } else {
        setTestOk(false);
        setTestMsg(
          `연결 실패${res.status ? ` (HTTP ${res.status})` : ""}: ${res.error || "알 수 없는 오류"}${
            res.target ? `\n대상: ${res.target}` : ""
          }`,
        );
      }
    } catch (e) {
      setTestOk(false);
      setTestMsg(`연결 테스트 오류: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setTesting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !next && close()}>
      <DialogContent
        className="settings-modal max-w-[520px] p-4 sm:p-4"
        aria-describedby={undefined}
      >
        <DialogHeader>
          <DialogTitle>설정</DialogTitle>
        </DialogHeader>

        <div className="settings-modal-body settings">
          <h3>외관</h3>
          <p className="muted">이 브라우저에만 저장되는 UI 테마입니다.</p>
          <div className="theme-mode-row">
            <span className="theme-mode-label">화면 모드</span>
            <Button
              type="button"
              variant="outline"
              role="switch"
              aria-checked={previewMode === "dark"}
              aria-label="Light/Dark 모드 전환"
              className="theme-mode-toggle"
              onClick={() => setPreviewMode(previewMode === "light" ? "dark" : "light")}
            >
              {previewMode === "light" ? <Sun /> : <Moon />}
              {previewMode === "light" ? "Light" : "Dark"}
            </Button>
          </div>
          <div className="theme-picker" role="radiogroup" aria-label="색상 테마">
            {THEME_OPTIONS.map((opt) => (
              <button
                key={opt.id}
                type="button"
                role="radio"
                aria-checked={previewTheme === opt.id}
                className={cn("theme-card", previewTheme === opt.id && "selected")}
                onClick={() => {
                  const nextTheme = opt.id as ThemeId;
                  setPreviewTheme(nextTheme);
                }}
              >
                <span className="theme-swatches" aria-hidden="true">
                  {opt.swatches[previewMode].map((color) => (
                    <span
                      key={color}
                      className="theme-swatch"
                      style={{ background: color }}
                    />
                  ))}
                </span>
                <span className="theme-card-name">{opt.name}</span>
              </button>
            ))}
          </div>

          <Label>
            Ringserver URL
            <Input
              value={draft.ringserverUrl}
              onChange={(e) => setDraft({ ...draft, ringserverUrl: e.target.value })}
            />
          </Label>
          <Label>
            FDSNWS URL
            <Input
              value={draft.fdsnwsUrl}
              onChange={(e) => setDraft({ ...draft, fdsnwsUrl: e.target.value })}
            />
          </Label>
          <Label>
            Duration (초) — 최대 {limits?.durationMax ?? 86400}
            <Select
              value={String(draft.durationSec)}
              onValueChange={(value) =>
                setDraft({ ...draft, durationSec: Number(value) })
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {!DURATION_OPTIONS.includes(draft.durationSec) && (
                  <SelectItem value={String(draft.durationSec)}>
                    현재 {draft.durationSec}초
                  </SelectItem>
                )}
                {DURATION_OPTIONS.map((sec) => (
                  <SelectItem key={sec} value={String(sec)}>
                    {formatDuration(sec)} ({sec}s)
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Label>
          <Label>
            X축 오른쪽 기준
            <Select
              value={draft.xAxisRightAnchor || "lastData"}
              onValueChange={(value) =>
                setDraft({
                  ...draft,
                  xAxisRightAnchor: value as "now" | "lastData",
                })
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="now">현재 시간</SelectItem>
                <SelectItem value="lastData">마지막 데이터</SelectItem>
              </SelectContent>
            </Select>
          </Label>
          <Label>
            갱신 인터벌 (ms)
            <Input
              type="number"
              min={50}
              max={10000}
              value={draft.refreshIntervalMs}
              onChange={(e) =>
                setDraft({ ...draft, refreshIntervalMs: Number(e.target.value) })
              }
            />
          </Label>
          <Label>
            최대 패널 (1–{limits?.maxPanelsHard ?? 50})
            <Input
              type="number"
              min={1}
              max={limits?.maxPanelsHard ?? 50}
              value={draft.maxPanels}
              onChange={(e) => setDraft({ ...draft, maxPanels: Number(e.target.value) })}
            />
          </Label>

          <p className={warn ? "warn" : "muted"}>
            예상 버퍼 메모리 ≈ {(mem / (1024 * 1024)).toFixed(1)} MB
            {warn ? " (경고: 512MB 초과 가능)" : ""}
          </p>
        </div>

        {testMsg && (
          <p
            className={`settings-test-msg ${
              testOk === false ? "error" : testOk === true ? "ok" : "muted"
            }`}
            role={testOk === false ? "alert" : undefined}
          >
            {testMsg}
          </p>
        )}

        <DialogFooter className="border-t border-border pt-3">
          <Button type="button" onClick={() => void apply()}>
            저장
          </Button>
          <Button type="button" variant="secondary" disabled={testing} onClick={() => void test()}>
            {testing ? "테스트 중…" : "연결 테스트"}
          </Button>
          <Button type="button" variant="outline" onClick={() => close()}>
            닫기
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
