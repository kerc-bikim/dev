/**
 * ringserver WebSocket URL.
 *
 * 가능하면 브라우저 → ringserver 직접 연결한다.
 * (Node `ws` 프록시가 permessage-deflate/재프레이밍으로 FIN 오류를 유발하는 경우가 있음)
 * ringserverUrl 이 없거나 직접 연결이 불가능한 환경만 백엔드 프록시를 사용한다.
 */
export function ringserverWsUrl(
  path: string,
  ringserverHttpUrl?: string | null,
): string {
  const clean = path.startsWith("/") ? path : `/${path}`;
  // DataLink 전용
  const endpoint = clean.includes("datalink") ? "/datalink" : clean;

  if (ringserverHttpUrl) {
    try {
      const u = new URL(ringserverHttpUrl);
      const proto = u.protocol === "https:" ? "wss:" : "ws:";
      return `${proto}//${u.host}${endpoint}`;
    } catch {
      /* fall through to proxy */
    }
  }

  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  if (import.meta.env.DEV) {
    const host = window.location.hostname || "127.0.0.1";
    const port = import.meta.env.VITE_BACKEND_WS_PORT || "8787";
    return `${proto}//${host}:${port}/ringserver${endpoint}`;
  }

  return `${proto}//${window.location.host}/ringserver${endpoint}`;
}
