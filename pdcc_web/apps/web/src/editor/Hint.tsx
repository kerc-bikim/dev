export function Hint({ text }: { text: string }) {
  return (
    <abbr className="field-hint" title={text}>
      ?
    </abbr>
  );
}
