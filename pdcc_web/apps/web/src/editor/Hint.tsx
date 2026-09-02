import type { MouseEvent } from "react";

export function Hint({ text, chapter }: { text: string; chapter: string }) {
  function openManual(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    window.history.pushState({ fromApp: true }, "", `/help/user#${chapter}`);
    window.dispatchEvent(new PopStateEvent("popstate"));
    window.setTimeout(() => {
      document.getElementById(chapter)?.scrollIntoView({ block: "start" });
    });
  }

  return (
    <a
      className="field-hint"
      href={`/help/user#${chapter}`}
      title={text}
      aria-label={`${text} 사용자 매뉴얼에서 보기`}
      onClick={openManual}
    >
      ?
    </a>
  );
}
