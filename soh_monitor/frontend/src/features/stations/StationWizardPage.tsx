import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { ApiError, api, type AdapterDto, type IdentityDto } from "../../api/client";
import { BusyButton } from "../../components/BusyButton";
import { SchemaForm, connectionPayload, emptyConnection, type ConnectionDraft } from "../../components/SchemaForm";

const STEPS = ["기본정보", "제조사·수집", "접속정보", "연결 시험", "센서·외부 SOH", "프로파일", "검토"] as const;

interface SensorDraft {
  port: string;
  model: string;
  axisCount: number;
}

interface SohDraft {
  channelNumber: number;
  name: string;
  scale: number;
  offset: number;
}

export function StationWizardPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [controller, setController] = useState<AbortController | null>(null);

  const [networkCode, setNetworkCode] = useState("KS");
  const [stationCode, setStationCode] = useState("");
  const [name, setName] = useState("");
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  const [elevation, setElevation] = useState("");
  const [powerProfile, setPowerProfile] = useState("12V 배터리");

  const [adapterKey, setAdapterKey] = useState("");
  const [model, setModel] = useState("");
  const [collectionMode] = useState("DIRECT");
  const [connection, setConnection] = useState<ConnectionDraft>(emptyConnection());

  const [testResult, setTestResult] = useState<string | null>(null);
  const [identity, setIdentity] = useState<IdentityDto | null>(null);

  const [sensors, setSensors] = useState<SensorDraft[]>([{ port: "A", model: "", axisCount: 3 }]);
  const [channels, setChannels] = useState<SohDraft[]>([]);
  const [collectionProfileId, setCollectionProfileId] = useState("");
  const [metricProfileId, setMetricProfileId] = useState("");

  const adapters = useQuery({ queryKey: ["adapters"], queryFn: api.adapters });
  const collections = useQuery({ queryKey: ["collection-profiles"], queryFn: api.collectionProfiles });
  const metrics = useQuery({ queryKey: ["metric-profiles"], queryFn: api.metricProfiles });

  const adapter: AdapterDto | undefined = useMemo(
    () => (adapters.data?.adapters ?? []).find((item) => item.adapterKey === adapterKey),
    [adapters.data, adapterKey],
  );

  const selectable = (adapters.data?.adapters ?? []).filter((item) => item.selectable);
  const mismatches = useMemo(() => {
    if (!identity) return [];
    const found: string[] = [];
    if (connection.instrumentId && identity.instrumentId && connection.instrumentId !== identity.instrumentId) {
      found.push(`Instrument ID 입력 ${connection.instrumentId} / 장비 ${identity.instrumentId}`);
    }
    if (model && identity.model && model !== identity.model) {
      found.push(`모델 선택 ${model} / 장비 ${identity.model}`);
    }
    if (identity.serialNumber) {
      found.push(`시리얼 탐지 ${identity.serialNumber} (저장 시 이 값을 쓴다)`);
    }
    if (identity.firmwareVersion) {
      found.push(`펌웨어 탐지 ${identity.firmwareVersion}`);
    }
    return found;
  }, [identity, connection.instrumentId, model]);

  function next() {
    if (step === 0 && (!stationCode.trim() || !name.trim() || !networkCode.trim())) {
      setError("네트워크, 관측소 코드, 이름은 필수다");
      return;
    }
    setError(null);
    setStep((value) => Math.min(value + 1, STEPS.length - 1));
  }

  async function runProbe() {
    if (!adapter) return;
    const abort = new AbortController();
    setController(abort);
    setBusy(true);
    setError(null);
    setTestResult(null);
    try {
      const tested = await api.testConnection(connectionPayload(connection, adapter.adapterKey), abort.signal);
      setTestResult(tested.reachable ? tested.message : tested.message);
      if (!tested.reachable) {
        setIdentity(null);
        return;
      }
      const probed = await api.probe(connectionPayload(connection, adapter.adapterKey), abort.signal);
      setIdentity(probed.identity);
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        setError("연결 시험을 취소했다");
      } else {
        setError(err instanceof ApiError ? err.message : "연결 시험에 실패했다");
      }
    } finally {
      setBusy(false);
      setController(null);
    }
  }

  async function save() {
    if (!adapter) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.createStation({
        networkCode,
        stationCode,
        name,
        latitude: latitude ? Number(latitude) : null,
        longitude: longitude ? Number(longitude) : null,
        elevationM: elevation ? Number(elevation) : null,
        powerProfile,
        status: "ACTIVE",
      });
      const device = await api.createDevice(created.station.id, {
        adapterKey: adapter.adapterKey,
        label: model || adapter.manufacturer,
        instrumentId: identity?.instrumentId || connection.instrumentId || null,
        serialNumber: identity?.serialNumber || null,
        firmwareVersion: identity?.firmwareVersion || null,
        collectionMode,
        collectionProfileId: collectionProfileId || null,
        metricProfileId: metricProfileId || null,
        endpoint: {
          scheme: connection.scheme,
          hostname: connection.hostname,
          port: connection.port ? Number(connection.port) : null,
          basePath: connection.basePath || "/",
          tlsVerify: connection.tlsVerify,
          credentialReference: connection.credentialReference || null,
          connectionOptions: connection.username ? { username: connection.username } : {},
        },
      });
      if (sensors.length) {
        await api.replaceSensors(
          device.device.id,
          sensors.map((sensor) => ({
            port: sensor.port,
            model: sensor.model || null,
            axisCount: sensor.axisCount,
          })),
        );
      }
      if (channels.length) {
        await api.replaceExternalSoh(
          device.device.id,
          channels.map((channel) => ({
            channelNumber: channel.channelNumber,
            name: channel.name,
            scale: channel.scale,
            offset: channel.offset,
          })),
        );
      }
      await api.pollNow(device.device.id).catch(() => undefined);
      navigate(`/stations/${created.station.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "저장에 실패했다");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1 className="page-title">관측소 등록</h1>
      <ol className="wizard-steps">
        {STEPS.map((label, index) => (
          <li key={label} className={index === step ? "current" : index < step ? "done" : undefined}>
            {index + 1}. {label}
          </li>
        ))}
      </ol>
      {error && <div className="notice warn">{error}</div>}

      {step === 0 && (
        <div className="card form-grid">
          <label className="field">
            <span>네트워크</span>
            <input value={networkCode} onChange={(event) => setNetworkCode(event.target.value)} required />
          </label>
          <label className="field">
            <span>관측소 코드</span>
            <input value={stationCode} onChange={(event) => setStationCode(event.target.value)} required />
          </label>
          <label className="field">
            <span>이름</span>
            <input value={name} onChange={(event) => setName(event.target.value)} required />
          </label>
          <label className="field">
            <span>위도</span>
            <input value={latitude} onChange={(event) => setLatitude(event.target.value)} />
          </label>
          <label className="field">
            <span>경도</span>
            <input value={longitude} onChange={(event) => setLongitude(event.target.value)} />
          </label>
          <label className="field">
            <span>고도 m</span>
            <input value={elevation} onChange={(event) => setElevation(event.target.value)} />
          </label>
          <label className="field">
            <span>전원 구성</span>
            <input value={powerProfile} onChange={(event) => setPowerProfile(event.target.value)} />
          </label>
        </div>
      )}

      {step === 1 && (
        <div className="card form-grid">
          <label className="field">
            <span>기록계 Adapter</span>
            <select value={adapterKey} onChange={(event) => setAdapterKey(event.target.value)}>
              <option value="">선택</option>
              {(adapters.data?.adapters ?? []).map((item) => (
                <option key={item.adapterKey} value={item.adapterKey} disabled={!item.selectable}>
                  {item.manufacturer} {item.productFamilies.join("/")} {!item.selectable ? "(준비 중)" : ""}
                </option>
              ))}
            </select>
            {selectable.length === 0 && <small>등록 가능한 Adapter 가 없다. 장비 등록을 진행할 수 없다.</small>}
          </label>
          {adapter && (
            <label className="field">
              <span>모델</span>
              <select value={model} onChange={(event) => setModel(event.target.value)}>
                <option value="">모름 (탐지 후 채움)</option>
                {adapter.supportedModels.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="field">
            <span>수집 방식</span>
            <select value={collectionMode} disabled>
              <option value="DIRECT">DIRECT (중앙이 직접 수집)</option>
              <option value="EDGE">EDGE (지역 Edge — M7에서 연다)</option>
            </select>
          </label>
        </div>
      )}

      {step === 2 && adapter && (
        <SchemaForm adapter={adapter} value={connection} onChange={setConnection} />
      )}
      {step === 2 && !adapter && <div className="notice warn">먼저 Adapter 를 고른다.</div>}

      {step === 3 && (
        <div className="card">
          <p>등록 전에 장비가 응답하는지 확인한다. 이 동작만 API 가 관측소망으로 나간다.</p>
          <BusyButton busy={busy} onCancel={() => controller?.abort()} onClick={() => void runProbe()}>
            연결 시험 후 탐지
          </BusyButton>
          {testResult && <p>{testResult}</p>}
          {identity && (
            <table>
              <tbody>
                <tr>
                  <th>제조사</th>
                  <td>{identity.manufacturer ?? "—"}</td>
                </tr>
                <tr>
                  <th>시리얼</th>
                  <td>{identity.serialNumber ?? "—"}</td>
                </tr>
                <tr>
                  <th>Instrument ID</th>
                  <td>{identity.instrumentId ?? "—"}</td>
                </tr>
                <tr>
                  <th>채널 수</th>
                  <td>{identity.channelCount ?? "—"}</td>
                </tr>
                <tr>
                  <th>펌웨어</th>
                  <td>{identity.firmwareVersion ?? "—"}</td>
                </tr>
              </tbody>
            </table>
          )}
          {mismatches.length > 0 && (
            <div className="notice warn">
              입력값과 탐지 결과를 대조했다. 저장하면 탐지한 신원(시리얼·펌웨어·Instrument ID)을 우선한다.
              <ul>
                {mismatches.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {step === 4 && (
        <div className="card">
          <h2>센서</h2>
          {sensors.map((sensor, index) => (
            <div className="form-grid" key={sensor.port + index}>
              <label className="field">
                <span>포트</span>
                <input
                  value={sensor.port}
                  onChange={(event) =>
                    setSensors((rows) => rows.map((row, i) => (i === index ? { ...row, port: event.target.value } : row)))
                  }
                />
              </label>
              <label className="field">
                <span>모델</span>
                <input
                  value={sensor.model}
                  onChange={(event) =>
                    setSensors((rows) => rows.map((row, i) => (i === index ? { ...row, model: event.target.value } : row)))
                  }
                />
              </label>
            </div>
          ))}
          <button className="btn ghost" type="button" onClick={() => setSensors((rows) => [...rows, { port: "B", model: "", axisCount: 3 }])}>
            센서 추가
          </button>
          <h2>외부 SOH</h2>
          <p className="muted">변환식은 value = raw × scale + offset 이다.</p>
          {channels.map((channel, index) => (
            <div className="form-grid" key={channel.channelNumber}>
              <label className="field">
                <span>채널</span>
                <input
                  type="number"
                  value={channel.channelNumber}
                  onChange={(event) =>
                    setChannels((rows) =>
                      rows.map((row, i) => (i === index ? { ...row, channelNumber: Number(event.target.value) } : row)),
                    )
                  }
                />
              </label>
              <label className="field">
                <span>이름</span>
                <input
                  value={channel.name}
                  onChange={(event) =>
                    setChannels((rows) => rows.map((row, i) => (i === index ? { ...row, name: event.target.value } : row)))
                  }
                />
              </label>
              <label className="field">
                <span>scale</span>
                <input
                  type="number"
                  step="any"
                  value={channel.scale}
                  onChange={(event) =>
                    setChannels((rows) =>
                      rows.map((row, i) => (i === index ? { ...row, scale: Number(event.target.value) } : row)),
                    )
                  }
                />
              </label>
              <label className="field">
                <span>offset</span>
                <input
                  type="number"
                  step="any"
                  value={channel.offset}
                  onChange={(event) =>
                    setChannels((rows) =>
                      rows.map((row, i) => (i === index ? { ...row, offset: Number(event.target.value) } : row)),
                    )
                  }
                />
              </label>
            </div>
          ))}
          <button
            className="btn ghost"
            type="button"
            onClick={() =>
              setChannels((rows) => [...rows, { channelNumber: rows.length + 1, name: "외부", scale: 1, offset: 0 }])
            }
          >
            채널 추가
          </button>
        </div>
      )}

      {step === 5 && (
        <div className="card form-grid">
          <label className="field">
            <span>수집 프로파일</span>
            <select value={collectionProfileId} onChange={(event) => setCollectionProfileId(event.target.value)}>
              <option value="">기본값</option>
              {(collections.data?.profiles ?? []).map((profile) => (
                <option key={profile.id} value={profile.id}>
                  {profile.name} ({profile.affectedDeviceCount}대)
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Metric 프로파일</span>
            <select value={metricProfileId} onChange={(event) => setMetricProfileId(event.target.value)}>
              <option value="">기본값</option>
              {(metrics.data?.profiles ?? []).map((profile) => (
                <option key={profile.id} value={profile.id}>
                  {profile.name} ({profile.affectedDeviceCount}대)
                </option>
              ))}
            </select>
          </label>
        </div>
      )}

      {step === 6 && (
        <div className="card">
          <h2>검토</h2>
          <table>
            <tbody>
              <tr>
                <th>관측소</th>
                <td>
                  {networkCode}.{stationCode} {name}
                </td>
              </tr>
              <tr>
                <th>Adapter</th>
                <td>{adapterKey}</td>
              </tr>
              <tr>
                <th>접속</th>
                <td>
                  {connection.scheme}://{connection.hostname}
                  {connection.port ? `:${connection.port}` : ""}
                </td>
              </tr>
              <tr>
                <th>인증</th>
                <td>{connection.credentialReference || "없음 (참조만 저장)"}</td>
              </tr>
              <tr>
                <th>탐지</th>
                <td>{identity?.instrumentId ?? "미실시"}</td>
              </tr>
            </tbody>
          </table>
          <BusyButton busy={busy} className="btn primary" onClick={() => void save()}>
            저장하고 첫 수집 요청
          </BusyButton>
        </div>
      )}

      <div className="toolbar">
        <button className="btn ghost" type="button" disabled={step === 0} onClick={() => setStep((value) => value - 1)}>
          이전
        </button>
        {step < STEPS.length - 1 && (
          <button className="btn primary" type="button" onClick={next} disabled={step === 1 && !adapterKey}>
            다음
          </button>
        )}
      </div>
    </>
  );
}
