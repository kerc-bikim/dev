# Earthworm Web Control

Earthworm **v8.0b17** 를 웹에서 설정·기동·감시하기 위한 콘솔 계획입니다. 구현은 아직 없고, 계획서만 있습니다.

- 계획: [`plan.md`](plan.md) · HTML [`plan.html`](plan.html)
- 웹 흐름: **초기 설정**(디렉터리·링) → **이후 설정**(모듈·제어·로그·스니프)
- 대상 바이너리: [earthworm_v8-0b8_rockylinux9_4.tar.gz](http://www.earthwormcentral.org/distribution/earthworm_v8-0b8_rockylinux9_4.tar.gz) (공식 배포는 HTTP. 크기 130927698 bytes 확인, SHA-256 대조 후 압축 해제)
- 소스: [gitlab.com/seismic-software/earthworm](https://gitlab.com/seismic-software/earthworm.git) 태그 `v8.0b17`
- 매뉴얼: 소스 `doc/WEB_DOC`

백엔드(FastAPI)와 프론트엔드(React + Vite)를 분리합니다. 상세 API·화면·파일 규칙은 계획서를 따릅니다.

HTML 다시 만들기:

```bash
pip install markdown
python scripts/build_plan_html.py
```
