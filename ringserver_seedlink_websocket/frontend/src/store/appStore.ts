import { create } from "zustand";
import type {
  AppSettings,
  ConnectionStatus,
  LayoutItem,
  SCNL,
} from "../types";
import { scnlKey } from "../types";
import {
  mergeBandPassPresets,
  BUILTIN_BANDPASS_PRESETS,
} from "../realtime/bandPassPresets";
import { api } from "../api/client";
import { bufferStore } from "../buffer/ringBuffer";
import { ReconnectController } from "../realtime/reconnectController";
import { DEFAULT_CANVAS_COLORS } from "../theme/theme";
import { sanitizeSpectrogramSettings } from "../render/spectrogramSettings";

export type PanelState = {
  scnl: SCNL;
};

type AppState = {
  settings: AppSettings | null;
  limits: { durationMax: number; maxPanelsHard: number; memoryWarnBytes: number } | null;
  layouts: LayoutItem[];
  selectedTree: Set<string>;
  panels: PanelState[];
  selectedPanelKey: string | null;
  connectionStatus: ConnectionStatus;
  connectionDetail: string;
  globalPaused: boolean;
  drawerOpen: boolean;
  settingsOpen: boolean;
  streamsError: string | null;
  controller: ReconnectController | null;

  init: () => Promise<void>;
  refreshLayouts: () => Promise<void>;
  saveSettings: (partial: Partial<AppSettings>, opts?: { applyLive?: boolean }) => Promise<void>;
  toggleTree: (scnl: SCNL) => void;
  setTreeKeys: (keys: string[], selected: boolean) => void;
  clearTreeSelection: () => void;
  plotSelected: () => Promise<void>;
  loadLayout: (layout: LayoutItem) => Promise<void>;
  removePanel: (key: string) => void;
  clearAllPanels: () => void;
  reorderPanels: (from: number, to: number) => void;
  setSelectedPanel: (key: string | null) => void;
  setGlobalPaused: (v: boolean) => void;
  setDrawerOpen: (v: boolean) => void;
  setSettingsOpen: (v: boolean) => void;
  estimateMemoryBytes: () => number;
};

const defaultColors = {
  palette: [...DEFAULT_CANVAS_COLORS.palette],
  channelColorMap: {} as Record<string, string>,
  gapColor: DEFAULT_CANVAS_COLORS.gapColor,
  selectionColor: DEFAULT_CANVAS_COLORS.selectionColor,
};

export const useAppStore = create<AppState>((set, get) => ({
  settings: null,
  limits: null,
  layouts: [],
  selectedTree: new Set(),
  panels: [],
  selectedPanelKey: null,
  connectionStatus: "disconnected",
  connectionDetail: "",
  globalPaused: false,
  drawerOpen: false,
  settingsOpen: false,
  streamsError: null,
  controller: null,

  init: async () => {
    const settings = await api.getSettings();
    // 진폭 모드 기본값: Raw counts
    if (settings.amplitudeMode !== "raw" && settings.amplitudeMode !== "physical") {
      settings.amplitudeMode = "raw";
    }
    if (settings.yScaleMode !== "auto" && settings.yScaleMode !== "uniform") {
      settings.yScaleMode = "auto";
    }
    settings.bandPassPresets = mergeBandPassPresets(
      settings.bandPassPresets || BUILTIN_BANDPASS_PRESETS,
    );
    if (typeof settings.bandPassEnabled !== "boolean") {
      settings.bandPassEnabled = false;
    }
    if (settings.bandPassPresetId === undefined) {
      settings.bandPassPresetId = null;
    }
    if (
      settings.bandPassEnabled &&
      settings.bandPassPresetId &&
      !settings.bandPassPresets.some((p) => p.id === settings.bandPassPresetId)
    ) {
      settings.bandPassEnabled = false;
      settings.bandPassPresetId = null;
    }
    settings.spectrogram = sanitizeSpectrogramSettings(settings.spectrogram);
    const limits = await api.getLimits();
    const layouts = await api.listLayouts();
    const controller = new ReconnectController({
      onStatus: (status, detail) => {
        set({
          connectionStatus: status,
          connectionDetail: detail || "",
        });
      },
      onPacket: () => {
        /* buffers updated in controller */
      },
    });
    controller.setDuration(settings.durationSec);
    controller.setRingserverUrl(settings.ringserverUrl);
    set({ settings, limits, layouts, controller });
  },

  refreshLayouts: async () => {
    set({ layouts: await api.listLayouts() });
  },

  saveSettings: async (partial, opts) => {
    const prev = get().settings;
    const settings = await api.saveSettings({ ...partial, protocol: "datalink" });
    settings.spectrogram = sanitizeSpectrogramSettings(settings.spectrogram);
    const applyLive = opts?.applyLive !== false;
    const controller = get().controller;
    controller?.setDuration(settings.durationSec);
    controller?.setRingserverUrl(settings.ringserverUrl);
    set({ settings });

    for (const p of get().panels) {
      bufferStore.getOrCreate(p.scnl).ensureCapacity(settings.durationSec);
    }

    // 물리량 모드: 현재 패널 메타 즉시 로드
    if (settings.amplitudeMode === "physical") {
      for (const p of get().panels) {
        try {
          const meta = await api.getSensitivity(p.scnl);
          const buf = bufferStore.getOrCreate(p.scnl);
          buf.sensitivity = meta.sensitivity;
          buf.inputUnits = meta.inputUnits;
        } catch {
          /* ignore */
        }
      }
    }

    if (!applyLive) return;

    const panels = get().panels;
    if (!controller || !panels.length) return;

    const urlChanged = !!prev && prev.ringserverUrl !== settings.ringserverUrl;
    const durationChanged = !!prev && prev.durationSec !== settings.durationSec;
    const needResubscribe = urlChanged || durationChanged;

    // 색상/갱신주기/진폭모드는 settings 구독 UI가 즉시 반영.
    // 스트림 관련 변경 시 현재 표출 채널에 바로 재적용.
    if (needResubscribe && (controller.isConnected() || controller.getChannels().length > 0)) {
      await controller.start(
        panels.map((p) => p.scnl),
        { forceNew: urlChanged },
      );
    }
  },

  toggleTree: (scnl) => {
    const key = scnlKey(scnl);
    const next = new Set(get().selectedTree);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    set({ selectedTree: next });
  },

  setTreeKeys: (keys, selected) => {
    const next = new Set(get().selectedTree);
    for (const k of keys) {
      if (selected) next.add(k);
      else next.delete(k);
    }
    set({ selectedTree: next });
  },

  clearTreeSelection: () => set({ selectedTree: new Set() }),

  plotSelected: async () => {
    const { settings, panels, selectedTree, limits, controller } = get();
    if (!settings || !controller) return;
    const max = settings.maxPanels;
    const hard = limits?.maxPanelsHard ?? 50;
    const cap = Math.min(max, hard);
    const selected = [...selectedTree].map((k) => {
      const [network, station, location, channel] = k.split(".");
      return { network: network!, station: station!, location: location!, channel: channel! };
    });
    const existing = new Set(panels.map((p) => scnlKey(p.scnl)));
    const toAdd = selected.filter((s) => !existing.has(scnlKey(s)));
    if (panels.length + toAdd.length > cap) {
      alert(`패널 상한(${cap})을 초과합니다.`);
      return;
    }
    const nextPanels = [
      ...panels,
      ...toAdd.map((scnl) => ({ scnl })),
    ];
    for (const p of nextPanels) bufferStore.getOrCreate(p.scnl).ensureCapacity(settings.durationSec);
    set({ panels: nextPanels });

    if (settings.amplitudeMode === "physical") {
      for (const p of toAdd) {
        try {
          const meta = await api.getSensitivity(p);
          const buf = bufferStore.getOrCreate(p);
          buf.sensitivity = meta.sensitivity;
          buf.inputUnits = meta.inputUnits;
        } catch {
          /* ignore */
        }
      }
    }

    await controller.start(nextPanels.map((p) => p.scnl));
  },

  loadLayout: async (layout) => {
    const { settings, controller } = get();
    if (!settings || !controller) return;
    const channels = layout.payload.channels || [];
    if (channels.length > settings.maxPanels) {
      alert(`레이아웃 채널 수가 maxPanels(${settings.maxPanels})를 초과합니다.`);
      return;
    }
    const patch: Partial<AppSettings> = {};
    if (layout.payload.durationSec) patch.durationSec = layout.payload.durationSec;
    if (layout.payload.refreshIntervalMs)
      patch.refreshIntervalMs = layout.payload.refreshIntervalMs;
    if (layout.payload.amplitudeMode) patch.amplitudeMode = layout.payload.amplitudeMode;
    if (layout.payload.yScaleMode) patch.yScaleMode = layout.payload.yScaleMode;
    if (layout.payload.xAxisRightAnchor) patch.xAxisRightAnchor = layout.payload.xAxisRightAnchor;
    if (layout.payload.waveformColors) patch.waveformColors = layout.payload.waveformColors;
    if (layout.payload.bandPassPresets) {
      patch.bandPassPresets = mergeBandPassPresets(layout.payload.bandPassPresets);
    }
    if (typeof layout.payload.bandPassEnabled === "boolean") {
      patch.bandPassEnabled = layout.payload.bandPassEnabled;
    }
    if (layout.payload.bandPassPresetId !== undefined) {
      patch.bandPassPresetId = layout.payload.bandPassPresetId;
    }
    if (layout.payload.spectrogram) {
      patch.spectrogram = sanitizeSpectrogramSettings(layout.payload.spectrogram);
    }
    patch.protocol = "datalink";
    if (Object.keys(patch).length) await get().saveSettings(patch, { applyLive: false });

    bufferStore.clear();
    const panels = channels.map((scnl) => ({ scnl }));
    const s = get().settings!;
    for (const p of panels) bufferStore.getOrCreate(p.scnl).ensureCapacity(s.durationSec);
    set({ panels, selectedPanelKey: panels[0] ? scnlKey(panels[0].scnl) : null });
    if (s.amplitudeMode === "physical") {
      for (const p of panels) {
        try {
          const meta = await api.getSensitivity(p.scnl);
          const buf = bufferStore.getOrCreate(p.scnl);
          buf.sensitivity = meta.sensitivity;
          buf.inputUnits = meta.inputUnits;
        } catch {
          /* ignore */
        }
      }
    }
    await controller.start(panels.map((p) => p.scnl));
  },

  removePanel: (key) => {
    const panels = get().panels.filter((p) => scnlKey(p.scnl) !== key);
    bufferStore.remove(key);
    set({
      panels,
      selectedPanelKey: get().selectedPanelKey === key ? null : get().selectedPanelKey,
    });
    void get().controller?.updateChannels(panels.map((p) => p.scnl));
  },

  clearAllPanels: () => {
    for (const p of get().panels) bufferStore.remove(scnlKey(p.scnl));
    set({ panels: [], selectedPanelKey: null });
    void get().controller?.updateChannels([]);
  },

  reorderPanels: (from, to) => {
    const panels = [...get().panels];
    const [item] = panels.splice(from, 1);
    if (!item) return;
    panels.splice(to, 0, item);
    set({ panels });
  },

  setSelectedPanel: (key) => set({ selectedPanelKey: key }),
  setGlobalPaused: (v) => set({ globalPaused: v }),
  setDrawerOpen: (v) => set({ drawerOpen: v }),
  setSettingsOpen: (v) => set({ settingsOpen: v }),

  estimateMemoryBytes: () => {
    const s = get().settings;
    if (!s) return 0;
    const n = get().panels.length || s.maxPanels;
    return n * s.durationSec * 100 * 4;
  },
}));

export { defaultColors };
