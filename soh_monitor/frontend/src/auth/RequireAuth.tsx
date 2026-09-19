import { Navigate, useLocation } from "react-router-dom";
import type { ReactNode } from "react";

import { useAuth, type Permission } from "./AuthProvider";

export function RequireAuth({
  children,
  permission,
}: {
  children: ReactNode;
  permission?: Permission;
}) {
  const { user, loading, can } = useAuth();
  const location = useLocation();

  if (loading) {
    return <p>세션을 확인하는 중이다.</p>;
  }
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (user.mustChangePassword && location.pathname !== "/change-password") {
    return <Navigate to="/change-password" replace state={{ from: location.pathname }} />;
  }
  if (permission && !can(permission)) {
    return (
      <div className="notice warn">
        이 화면은 {permission === "administer" ? "관리자" : "설정 권한이 있는 사용자"}만 볼 수 있다.
      </div>
    );
  }
  return children;
}
