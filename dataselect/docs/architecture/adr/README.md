# Architecture Decision Records

형식은 [Nygard ADR](https://github.com/joelparkerhenderson/architecture-decision-record/blob/main/locales/en/templates/decision-record-template-and-example/index.md) 입니다. 상태: Proposed / Accepted / Deprecated / Superseded.

| ID | 제목 | 상태 |
|----|------|------|
| [0001](0001-record-list-not-unpacked-samples.md) | 인덱스는 레코드 리스트, 샘플은 쓸 때 푼다 | Accepted |
| [0002](0002-isolate-local-hooks.md) | `-B`는 local.c, 원본에는 훅만 | Accepted |
| [0003](0003-repack-per-input-record.md) | `-B`는 입력 레코드 단위로 다시 패킹 | Accepted |
| [0004](0004-fatal-repack-no-fallback.md) | `-B` pack 실패 시 원본을 섞지 않는다 | Accepted |
| [0005](0005-v2-sequence-per-channel.md) | miniSEED 2 시퀀스는 채널별 출력 순 | Accepted |

소스 주석이나 커밋에만 있는 결정을 여기로 옮길 때 번호를 이어 갑니다.
