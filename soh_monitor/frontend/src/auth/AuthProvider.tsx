import { createContext, useContext, useEffect, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";

import { ApiError, api, type Role, type UserDto } from "../api/client";

export type Permission = "operate" | "configure" | "administer";

const ROLE_PERMISSIONS: Record<Role, Permission[]> = {
  VIEWER: [],
  OPERATOR: ["operate"],
  ADMIN: ["operate", "configure", "administer"],
};

interface AuthValue {
  user: UserDto | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<UserDto>;
  logout: () => Promise<void>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<UserDto>;
  can: (permission: Permission) => boolean;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const onExpired = () => {
      queryClient.setQueryData(["me"], null);
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== "me" });
      if (location.pathname !== "/login") {
        navigate("/login", { replace: true, state: { expired: true, from: location.pathname } });
      }
    };
    window.addEventListener("soh:session-expired", onExpired);
    return () => window.removeEventListener("soh:session-expired", onExpired);
  }, [queryClient, navigate, location.pathname]);

  const me = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return (await api.me()).user;
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          return null;
        }
        throw error;
      }
    },
    retry: false,
    staleTime: 60_000,
  });

  const loginMutation = useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      api.login(username, password),
    onSuccess: (body) => {
      queryClient.setQueryData(["me"], body.user);
    },
  });

  const logoutMutation = useMutation({
    mutationFn: api.logout,
    onSuccess: () => {
      queryClient.setQueryData(["me"], null);
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== "me" });
    },
  });

  const passwordMutation = useMutation({
    mutationFn: ({ currentPassword, newPassword }: { currentPassword: string; newPassword: string }) =>
      api.changePassword(currentPassword, newPassword),
    onSuccess: (body) => {
      queryClient.setQueryData(["me"], body.user);
    },
  });

  const user = me.data ?? null;

  const value: AuthValue = {
    user,
    loading: me.isLoading,
    login: async (username, password) => {
      const body = await loginMutation.mutateAsync({ username, password });
      return body.user;
    },
    logout: async () => {
      await logoutMutation.mutateAsync();
    },
    changePassword: async (currentPassword, newPassword) => {
      const body = await passwordMutation.mutateAsync({ currentPassword, newPassword });
      return body.user;
    },
    can: (permission) => (user ? ROLE_PERMISSIONS[user.role].includes(permission) : false),
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("AuthProvider 안에서만 쓴다");
  }
  return value;
}
