import { useState } from "react";
import { api, ChannelInfo } from "../api/client";
import {
  channelKey,
  formatChannelLabel,
  groupChannelsByStation,
  nslcHasWildcard,
  parseNslcInput,
  toFdsnLocation,
} from "../utils/nslc";

const SEARCH_CAP = 500;
const DEFAULT_SELECT_CAP = 20;

interface Props {
  query: string;
  onQueryChange: (query: string) => void;
  selected: ChannelInfo[];
  onSelectedChange: (selected: ChannelInfo[]) => void;
  /** One channel only (Single / Compare Time). */
  singleSelect?: boolean;
  /** Keep all matches on one station (Compare Time). */
  singleStation?: boolean;
  disabled?: boolean;
}

export function ManualNslcInput({
  query,
  onQueryChange,
  selected,
  onSelectedChange,
  singleSelect = false,
  singleStation = false,
  disabled = false,
}: Props) {
  const [hits, setHits] = useState<ChannelInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [searched, setSearched] = useState(false);

  const selectedSet = new Set(selected.map(channelKey));

  const search = async () => {
    const parsed = parseNslcInput(query);
    if (!parsed) {
      setError("NET.STA.LOC.CHA 형식으로 입력하세요. 예: IU.ANMO.00.BHZ");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const list = await api.channels(parsed.network || "*", parsed.station || "*", {
        location: toFdsnLocation(parsed.location),
        channel: parsed.channel || "*",
      });
      setHits(list);
      setTruncated(list.length >= SEARCH_CAP);
      setSearched(true);

      if (list.length === 0) {
        onSelectedChange([]);
        return;
      }

      if (list.length === 1) {
        onSelectedChange(list);
        return;
      }
      if (!nslcHasWildcard(parsed) && list.length > 0) {
        onSelectedChange(
          singleSelect || singleStation ? list.slice(0, 1) : list.slice(0, DEFAULT_SELECT_CAP)
        );
        return;
      }
      onSelectedChange([]);
    } catch (e: any) {
      setError(String(e?.message ?? e));
      setHits([]);
    } finally {
      setLoading(false);
    }
  };

  const toggle = (ch: ChannelInfo) => {
    const key = channelKey(ch);
    const isOn = selectedSet.has(key);
    if (singleSelect) {
      onSelectedChange(isOn ? [] : [ch]);
      return;
    }
    if (singleStation) {
      const sameStation = selected.filter(
        (s) => s.network === ch.network && s.station === ch.station
      );
      if (isOn) {
        onSelectedChange(sameStation.filter((s) => channelKey(s) !== key));
      } else {
        onSelectedChange([...sameStation, ch]);
      }
      return;
    }
    if (isOn) {
      onSelectedChange(selected.filter((s) => channelKey(s) !== key));
    } else if (selected.length >= DEFAULT_SELECT_CAP) {
      return;
    } else {
      onSelectedChange([...selected, ch]);
    }
  };

  const selectAll = () => {
    if (singleSelect) return;
    const cap = hits.slice(0, DEFAULT_SELECT_CAP);
    if (singleStation && cap.length > 0) {
      const first = cap[0];
      onSelectedChange(
        cap.filter((c) => c.network === first.network && c.station === first.station)
      );
      return;
    }
    onSelectedChange(cap);
  };

  const selectNone = () => onSelectedChange([]);

  const groups = groupChannelsByStation(hits);
  const showList = searched || hits.length > 0;

  return (
    <div className="nslc-block">
      <div className="field">
        <label>NET.STA.LOC.CHA {loading && "…"}</label>
        <div className="nslc-input-row">
          <input
            type="text"
            value={query}
            disabled={disabled}
            spellCheck={false}
            autoCapitalize="characters"
            placeholder="IU.ANMO.00.BHZ  또는  KG.*.*.BH?"
            onChange={(e) => onQueryChange(e.target.value.toUpperCase())}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void search();
              }
            }}
          />
          <button
            type="button"
            className="btn-ghost nslc-search-btn"
            disabled={disabled || loading || !query.trim()}
            onClick={() => void search()}
          >
            Search
          </button>
        </div>
        <p className="hint">
          점은 구분자입니다. 빈 location은 <code>IU.ANMO..BHZ</code>, 검색은{" "}
          <code>*</code> / <code>?</code> 를 사용하세요.
        </p>
      </div>

      {error && <div className="error" style={{ marginBottom: 10 }}>{error}</div>}

      {showList && !loading && (
        <div className="channel-check-wrap">
          <div className="channel-check-header">
            <span>
              {hits.length === 0
                ? "일치하는 채널이 없습니다"
                : `${hits.length}개 채널${truncated ? " (최대 500개)" : ""}`}
              {selected.length > 0 ? ` · ${selected.length}개 선택` : ""}
            </span>
            {!singleSelect && hits.length > 0 && (
              <span className="channel-check-actions">
                <button type="button" className="btn-ghost" onClick={selectAll}>
                  Select all
                </button>
                <button type="button" className="btn-ghost" onClick={selectNone}>
                  Clear
                </button>
              </span>
            )}
          </div>
          {hits.length > DEFAULT_SELECT_CAP && !singleSelect && (
            <p className="hint">한 번에 최대 {DEFAULT_SELECT_CAP}개 채널까지 선택할 수 있습니다.</p>
          )}
          {hits.length > 0 && (
            <div className="channel-check-list">
              {groups.map((g) => (
                <div key={g.key} className="channel-check-group">
                  {groups.length > 1 && (
                    <div className="channel-check-station">
                      {g.network}.{g.station}
                    </div>
                  )}
                  {g.channels.map((c) => {
                    const key = channelKey(c);
                    return (
                      <label key={key} className="channel-check-item">
                        <input
                          type="checkbox"
                          checked={selectedSet.has(key)}
                          onChange={() => toggle(c)}
                        />
                        <span>{formatChannelLabel(c)}</span>
                      </label>
                    );
                  })}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
