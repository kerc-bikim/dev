import { api, BatchPPSDItem } from "../api/client";
import { channelId } from "../utils/time";

interface Props {
  loading: boolean;
  error: string | null;
  items: BatchPPSDItem[] | null;
  elapsed?: number;
}

export function BatchResultGrid({ loading, error, items, elapsed }: Props) {
  const okCount = items?.filter((i) => i.status === "ok").length ?? 0;
  const errCount = items?.filter((i) => i.status === "error").length ?? 0;

  return (
    <div className="result">
      <div className="result-header">
        <div className="result-title">Multi PPSD Results</div>
        {items && (
          <div className="stats">
            <span className="badge">{okCount} ok</span>
            {errCount > 0 && <span className="badge badge-error">{errCount} failed</span>}
            {elapsed != null && <span className="badge">{elapsed.toFixed(2)}s</span>}
          </div>
        )}
      </div>

      {error && <div className="error">{error}</div>}

      {loading ? (
        <div className="placeholder">
          <div className="spinner" />
          Computing PPSDs in parallel…
        </div>
      ) : items && items.length > 0 ? (
        <div className="grid">
          {items.map((item, idx) => {
            const id = channelId(item.target);
            return (
              <div
                key={`${id}-${idx}`}
                className={`grid-card ${item.status === "error" ? "grid-card-error" : ""}`}
              >
                <div className="grid-card-header">
                  <span className="badge">{id}</span>
                  {item.stats?.from_cache && <span className="badge">cached</span>}
                  {item.status === "error" && (
                    <span className="badge badge-error">error</span>
                  )}
                </div>
                {item.status === "ok" && item.image_url ? (
                  <>
                    <div className="image-frame compact">
                      <img src={api.imageUrl(item.image_url)} alt={id} />
                    </div>
                    {item.stats && (
                      <div className="grid-card-footer">
                        <span>{item.stats.segments_used} segments</span>
                        <a
                          className="download"
                          href={api.imageUrl(item.image_url)}
                          download={`ppsd_${id.replace(/\./g, "_")}.png`}
                        >
                          PNG
                        </a>
                      </div>
                    )}
                  </>
                ) : (
                  <div className="error compact-error">{item.error}</div>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="placeholder">
          Add stations and channels, then click <strong>Compute All</strong>.
        </div>
      )}
    </div>
  );
}
