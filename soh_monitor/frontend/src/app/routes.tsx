import { Navigate, type RouteObject } from "react-router-dom";

import { Layout } from "./Layout";
import { ContractsPage } from "../pages/ContractsPage";
import { PlaceholderPage } from "../pages/PlaceholderPage";

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/contracts" replace /> },
      {
        path: "overview",
        element: (
          <PlaceholderPage
            title="통합 현황"
            milestone="M6 (관리 Frontend 1차)"
            scope={[
              "전체·정상·주의·장애·확인 불가 관측소 수",
              "Direct 수집과 Edge 수집 구분",
              "관측소 지도와 지역별 상태",
              "현재 장애 목록과 마지막 수집 시각",
            ]}
          />
        ),
      },
      {
        path: "stations",
        element: (
          <PlaceholderPage
            title="관측소"
            milestone="M6 (관리 Frontend 1차)"
            scope={[
              "관측소 목록과 카테고리별 상태 컬럼",
              "등록 마법사: 접속정보 → 연결 시험 → 장비 자동 탐지 → 센서·외부 SOH → 프로파일",
              "관측소 상세: 전원·시각·센서·저장소·데이터 품질·수집 이력",
            ]}
          />
        ),
      },
      {
        path: "edges",
        element: (
          <PlaceholderPage
            title="Edge Collector"
            milestone="M8 (Edge 통합)"
            scope={[
              "Edge 목록과 마지막 Heartbeat",
              "할당된 기록계와 수집 성공률",
              "로컬 Spool 사용량과 미전송 Batch",
              "설정 버전·프로그램 버전·인증서 만료",
            ]}
          />
        ),
      },
      {
        path: "profiles",
        element: (
          <PlaceholderPage
            title="프로파일"
            milestone="M6 (관리 Frontend 1차)"
            scope={[
              "수집 주기·재시도 프로파일",
              "Metric 활성화와 임계값 편집",
              "장비별 Override 와 영향 범위 미리보기",
            ]}
          />
        ),
      },
      {
        path: "incidents",
        element: (
          <PlaceholderPage
            title="장애"
            milestone="M4 · M8 (상태 판정과 Edge 상관관계)"
            scope={[
              "현재 장애 목록과 확인 처리",
              "발생·확인·복구 이력",
              "Edge 장애로 억제된 하위 장애 표시",
            ]}
          />
        ),
      },
      { path: "contracts", element: <ContractsPage /> },
      { path: "*", element: <Navigate to="/contracts" replace /> },
    ],
  },
];
