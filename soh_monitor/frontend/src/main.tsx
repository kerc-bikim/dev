import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { keepPreviousData } from "@tanstack/react-query";
import { RouterProvider, createBrowserRouter } from "react-router-dom";

import { ApiError } from "./api/client";
import { routes } from "./app/routes";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // 상태 화면은 주기 갱신이 필요하지만, 갱신 중 화면이 튀지 않아야 한다.
      staleTime: 15_000,
      placeholderData: keepPreviousData,
      refetchOnWindowFocus: false,
      retry: (count, error) => {
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
          return false;
        }
        return count < 1;
      },
    },
  },
});

const router = createBrowserRouter(routes);

const container = document.getElementById("root");
if (!container) {
  throw new Error("#root 를 찾을 수 없다");
}

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
