import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../../api/client";
import { useAuth } from "../../auth/AuthProvider";
import { SeverityBadge } from "../../components/SeverityBadge";

export function IncidentsPage() {
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState("open");
  const [message, setMessage] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["incidents", filter],
    queryFn: () => api.incidents(filter),
    refetchInterval: 15_000,
    placeholderData: keepPreviousData,
  });
  const events = useQuery({
    queryKey: ["incident-events", openId],
    queryFn: () => api.incidentEvents(openId!),
    enabled: Boolean(openId),
  });

  const acknowledge = useMutation({
    mutationFn: (id: string) => api.acknowledgeIncident(id, message),
    onSuccess: () => {
      setMessage("");
      void queryClient.invalidateQueries({ queryKey: ["incidents"] });
    },
  });

  return (
    <>
      <h1 className="page-title">장애</h1>
      <p className="page-subtitle">확인은 복구가 아니다. 담당자가 보고 있다는 표시만 남긴다.</p>
      <div className="toolbar">
        <select value={filter} onChange={(event) => setFilter(event.target.value)}>
          <option value="open">열림</option>
          <option value="resolved">복구</option>
          <option value="all">전체</option>
        </select>
      </div>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>관측소</th>
              <th>상태</th>
              <th>처리</th>
              <th>제목</th>
              <th>처음</th>
              <th>확인</th>
              {can("operate") && <th></th>}
            </tr>
          </thead>
          <tbody>
            {(list.data?.incidents ?? []).map((incident) => (
              <tr key={incident.incidentId}>
                <td>{incident.stationCode ?? "—"}</td>
                <td>
                  <SeverityBadge severity={incident.severity} />
                </td>
                <td>{incident.status}</td>
                <td>
                  <button className="linkish" type="button" onClick={() => setOpenId(incident.incidentId)}>
                    {incident.title}
                  </button>
                </td>
                <td>{incident.firstObservedAt?.replace("T", " ").slice(0, 19)}</td>
                <td>
                  {incident.acknowledgedAt
                    ? `${incident.acknowledgedBy ?? "담당자"} · ${incident.acknowledgedAt.replace("T", " ").slice(0, 19)}`
                    : "—"}
                </td>
                {can("operate") && (
                  <td>
                    {incident.status !== "RESOLVED" && incident.status !== "ACKNOWLEDGED" && (
                      <button className="btn ghost" type="button" onClick={() => acknowledge.mutate(incident.incidentId)}>
                        확인
                      </button>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {can("operate") && (
          <label className="field">
            <span>확인 메모</span>
            <input value={message} onChange={(event) => setMessage(event.target.value)} />
          </label>
        )}
      </div>
      {openId && events.data && (
        <div className="card">
          <h2>{events.data.title} 이력</h2>
          <ul>
            {events.data.events.map((event) => (
              <li key={event.occurredAt + event.eventType}>
                {event.occurredAt.replace("T", " ").slice(0, 19)} · {event.eventType}
                {event.actorName ? ` · ${event.actorName}` : ""}
                {event.message ? ` — ${event.message}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}
