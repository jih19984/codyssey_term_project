# AWS EC2 배포 가이드 (Docker Compose + Caddy + nip.io)

EC2 한 대에 **Caddy(HTTPS) → FastAPI → PostgreSQL**을 Docker Compose로 띄운다. 도메인을 사지 않고 `nip.io`로 무료 HTTPS 인증서를 받는다.

```text
브라우저 ──https(443)──▶ Caddy ──http──▶ web(FastAPI :8000) ──▶ postgres(:5432)
                        인증서 자동 발급        외부에 안 열림          외부에 안 열림
```

| 파일 | 역할 |
|---|---|
| `docker-compose.prod.yml` | 운영용 서비스 구성 (postgres, web, caddy) |
| `Caddyfile` | HTTPS 처리, `web:8000`으로 요청 전달 |
| `.env.prod.example` | 서버의 `.env`를 만들 때 쓰는 틀 |

---

## 1. EC2 인스턴스 만들기 (AWS 콘솔)

1. 리전을 고른다. 예: 서울 `ap-northeast-2`.
2. **EC2 → 인스턴스 시작**에서 다음과 같이 설정한다.
   - AMI: **Ubuntu Server 24.04 LTS**
   - 인스턴스 유형: **t3.micro** (프리 티어)
   - 키 페어: 새로 만들고 `.pem` 파일을 보관한다.
   - 스토리지: 20GB
3. **보안 그룹 인바운드 규칙**을 다음과 같이 둔다.

   | 포트 | 소스 | 용도 |
   |---|---|---|
   | 22 | **내 IP** | SSH |
   | 80 | 0.0.0.0/0 | 인증서 발급, https 리다이렉트 |
   | 443 | 0.0.0.0/0 | HTTPS |

   8000(앱)과 5432(DB)는 **열지 않는다.**
4. **탄력적 IP(Elastic IP)** 를 할당해서 인스턴스에 연결한다. 이렇게 하면 인스턴스를 껐다 켜도 주소가 바뀌지 않는다. 공인 IPv4 요금이 소액 발생한다.

## 2. 접속과 Docker 설치

```bash
chmod 400 my-key.pem
ssh -i my-key.pem ubuntu@<탄력적 IP>
```

서버에 접속한 뒤 다음을 실행한다.

```bash
# Docker 설치 (공식 스크립트)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
exit   # 다시 접속해야 docker 그룹이 적용된다
```

t3.micro는 메모리가 1GB라서 이미지를 빌드하다 멈출 수 있다. 스왑을 2GB 추가해 둔다.

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 3. 코드 받기와 `.env` 작성

```bash
git clone https://github.com/jih19984/codyssey_term_project.git
cd codyssey_term_project
cp .env.prod.example .env
openssl rand -hex 16   # POSTGRES_PASSWORD에 쓸 값
openssl rand -hex 32   # SESSION_SECRET에 쓸 값
nano .env
```

`.env`는 이렇게 채운다. 탄력적 IP가 `13.125.10.20`이라면 다음과 같다.

```text
DOMAIN=13-125-10-20.nip.io
POSTGRES_PASSWORD=<openssl로 만든 값>
SESSION_SECRET=<openssl로 만든 값>
AI_API_KEY=<Codyssey Neito API 키>
```

## 4. 실행

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
```

처음 실행하면 Caddy가 Let's Encrypt에서 인증서를 받는다. 보통 수십 초 걸린다.

## 5. 확인

- `https://13-125-10-20.nip.io/health`에서 200이 나오는지 본다.
- `http://`로 접속하면 `https://`로 자동 이동하는지 본다.
- 회원가입, 로그인, 채팅, 대화 기록을 차례로 해 본다.

로그는 다음 명령어로 본다.

```bash
docker compose -f docker-compose.prod.yml logs -f web     # 앱 로그 (app.events)
docker compose -f docker-compose.prod.yml logs -f caddy   # 인증서 발급, 프록시 로그
```

## 6. 코드 업데이트

```bash
cd ~/codyssey_term_project
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

컨테이너가 시작될 때 `alembic upgrade head`가 자동으로 실행되어 DB 스키마도 함께 맞춰진다.

---

## 자주 막히는 문제

| 증상 | 원인과 해결 |
|---|---|
| 로그인해도 바로 풀림 | HTTPS가 아닌 주소로 접속했다. 운영 환경의 세션 쿠키는 `Secure`라서 http에서는 전송되지 않는다. `https://...nip.io`로 접속한다. |
| CSS/JS가 안 불러와짐 | `FORWARDED_ALLOW_IPS`가 빠지면 정적 파일 주소가 `http://`로 만들어져 브라우저가 차단한다. `docker-compose.prod.yml`의 설정을 확인한다. |
| 인증서 발급 실패 (caddy 로그) | 보안 그룹에서 80/443이 열려 있는지, `DOMAIN`의 IP가 탄력적 IP와 같은지 확인한다. 발급을 너무 많이 시도하면 Let's Encrypt 요청 제한에 걸릴 수 있으니 잠시 기다린다. |
| `POSTGRES_PASSWORD를 .env에 설정하세요` | `.env`에 해당 값이 비어 있다. |
| 빌드 중 서버가 멈춤 | 메모리가 부족하다. 2단계의 스왑 설정을 확인한다. |
| AI 응답이 504 | `AI_API_KEY`를 확인하고, 서버에서 `copa.codyssey.kr`에 접속할 수 있는지 확인한다. |

## 백업과 정리

```bash
# DB 백업
docker compose -f docker-compose.prod.yml exec -T postgres pg_dump -U chatbot chatbot > backup.sql

# 중지 (데이터 유지)
docker compose -f docker-compose.prod.yml down
```

`down -v`를 실행하면 **DB와 인증서 볼륨까지 삭제**되니 주의한다.

과제가 끝나면 비용이 나가지 않도록 EC2 인스턴스를 종료하고, 탄력적 IP를 **릴리스**한다.
