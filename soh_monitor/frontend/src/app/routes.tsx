import { Navigate, Outlet, type RouteObject } from "react-router-dom";

import { Layout } from "./Layout";
import { AuthProvider } from "../auth/AuthProvider";
import { RequireAuth } from "../auth/RequireAuth";
import { ContractsPage } from "../pages/ContractsPage";
import { LoginPage } from "../features/auth/LoginPage";
import { ChangePasswordPage } from "../features/auth/ChangePasswordPage";
import { OverviewPage } from "../features/overview/OverviewPage";
import { EdgesPage } from "../features/edges/EdgesPage";
import { EdgeDetailPage } from "../features/edges/EdgeDetailPage";
import { StationsPage } from "../features/stations/StationsPage";
import { StationWizardPage } from "../features/stations/StationWizardPage";
import { StationDetailPage } from "../features/stations/StationDetailPage";
import { ProfilesPage } from "../features/profiles/ProfilesPage";
import { IncidentsPage } from "../features/incidents/IncidentsPage";
import { SettingsPage } from "../features/settings/SettingsPage";

function Root() {
  return (
    <AuthProvider>
      <Outlet />
    </AuthProvider>
  );
}

export const routes: RouteObject[] = [
  {
    element: <Root />,
    children: [
      { path: "/login", element: <LoginPage /> },
      {
        path: "/change-password",
        element: (
          <RequireAuth>
            <ChangePasswordPage />
          </RequireAuth>
        ),
      },
      {
        path: "/",
        element: (
          <RequireAuth>
            <Layout />
          </RequireAuth>
        ),
        children: [
          { index: true, element: <Navigate to="/overview" replace /> },
          { path: "overview", element: <OverviewPage /> },
          { path: "stations", element: <StationsPage /> },
          {
            path: "stations/new",
            element: (
              <RequireAuth permission="configure">
                <StationWizardPage />
              </RequireAuth>
            ),
          },
          { path: "stations/:stationId", element: <StationDetailPage /> },
          { path: "profiles", element: <ProfilesPage /> },
          { path: "incidents", element: <IncidentsPage /> },
          {
            path: "settings",
            element: (
              <RequireAuth permission="administer">
                <SettingsPage />
              </RequireAuth>
            ),
          },
          { path: "contracts", element: <ContractsPage /> },
          { path: "edges", element: <EdgesPage /> },
          { path: "edges/:edgeId", element: <EdgeDetailPage /> },
          { path: "*", element: <Navigate to="/overview" replace /> },
        ],
      },
    ],
  },
];
