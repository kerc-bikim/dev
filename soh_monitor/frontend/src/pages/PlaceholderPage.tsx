// 아직 구현되지 않은 화면. 어떤 마일스톤에서 열리는지 화면에 그대로 적는다.
// 빈 화면을 보여 주고 사용자가 원인을 추측하게 만들지 않는다.

export interface PlaceholderPageProps {
  title: string;
  milestone: string;
  scope: string[];
}

export function PlaceholderPage({ title, milestone, scope }: PlaceholderPageProps) {
  return (
    <>
      <h1 className="page-title">{title}</h1>
      <p className="page-subtitle">{milestone} 에서 구현된다.</p>
      <div className="card">
        <h2>이 화면에 들어올 내용</h2>
        <ul>
          {scope.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </div>
    </>
  );
}
