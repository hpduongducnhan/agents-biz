# BizWithAgents — lệnh dev. Backend: Poetry (Python 3.13) trong backend/; realtime (Node) trong realtime/; web trong frontend/.
# Hạ tầng: mặc định hạ tầng chung trên server (D19); máy chưa có thì `make infra-up` (deploy/compose.infra.yml).
BE = cd backend &&
RT = cd realtime &&
FE = cd frontend &&

.PHONY: be-install be-test be-test-unit be-lint be-fmt be-cov api consume work schedule migrate keys seed-test-users \
	rt-install rt-test rt-typecheck rt-cov realtime infra-up infra-down fe-install fe-dev fe-build fe-lint fe-typecheck fe-test fe-cov \
	ci secrets-scan deploy smoke-prod notify agent-eval openapi openapi-check docs diagrams docs-check dev-up dev-down dev-status fe-preview smoke-local \
	new-module scaffold-check setup check-config skills-sync skills-check fake-llm template-sync new-app new-app-check init-app

be-install:	## venv Python 3.13 + phụ thuộc
	$(BE) poetry env use python3.13 && poetry install

infra-up:	## hạ tầng dự phòng cho máy chưa có hạ tầng chung: Postgres 15432 · Redis 16379 · RabbitMQ 5673 · Mongo 27018 (D19)
	docker compose -f deploy/compose.infra.yml up -d --wait

infra-down:	## dừng hạ tầng dự phòng (giữ volume)
	docker compose -f deploy/compose.infra.yml down

be-test:	## toàn bộ test (cần Postgres / Mongo / Redis / RabbitMQ — .env)
	$(BE) poetry run pytest -q

be-test-unit:	## chỉ unit test
	$(BE) poetry run pytest -q -m "not integration"

be-lint:
	$(BE) poetry run ruff check . ../scripts && poetry run ruff format --check . ../scripts

be-fmt:
	$(BE) poetry run ruff format . ../scripts && poetry run ruff check --fix . ../scripts

be-cov:	## test + ngưỡng độ phủ 90% dòng app/
	$(BE) poetry run pytest -q --cov=app --cov-report=term-missing --cov-fail-under=90

api:
	$(BE) poetry run bw api --reload
consume:
	$(BE) poetry run bw consume
work:
	$(BE) poetry run bw work
schedule:
	$(BE) poetry run bw schedule
migrate:
	$(BE) poetry run bw keys && poetry run bw migrate
keys:
	$(BE) poetry run bw keys
check-config:	## kiểm cấu hình bắt buộc trong .env (không cần DB / broker)
	$(BE) poetry run bw check-config

setup:	## dựng môi trường dev cho bản clone (D28): make setup [MODE=local|shared] [SUPERADMIN=email] [VERIFY=1]
	python3 scripts/setup_env.py --mode $(or $(MODE),local) $(if $(SUPERADMIN),--superadmin $(SUPERADMIN)) $(if $(VERIFY),--verify)

seed-test-users:	## user test dev / E2E (từ chối khi ENV=prod) — chạy sau make migrate
	$(BE) poetry run bw seed-test-users

openapi:	## R7: ghi frontend/src/lib/api/openapi.json từ app api — commit cùng thay đổi operation
	$(BE) poetry run bw dump-openapi

openapi-check:	## CI: openapi.json đã commit phải khớp app
	$(BE) poetry run bw dump-openapi --check

docs:	## sinh trang review HTML: mỗi .claude/**/*.md → .html cạnh nó + .claude/index.html
	$(BE) poetry run python ../scripts/docs_site.py

diagrams:	## sinh lại sơ đồ archify có spec đổi (.claude/**/diagrams/*.<loại>.json — cần Node + skill archify, hoặc ARCHIFY=…) rồi ghi trang
	$(BE) poetry run python ../scripts/docs_site.py --diagrams

docs-check:	## CI: HTML cũ / thiếu / thừa so với .md, link hỏng, .md quá 500 dòng / thiếu backlink / mồ côi → lỗi (R2, R25)
	$(BE) poetry run python ../scripts/docs_site.py --check && poetry run python ../scripts/check_md.py

rt-install:
	$(RT) npm ci
rt-test:	## cần RabbitMQ, vhost bizwithagents_test
	$(RT) npm test
rt-typecheck:
	$(RT) npm run typecheck
rt-cov:
	$(RT) npm run test:cov
realtime:
	$(RT) npm start

fe-install:	## phụ thuộc web + bộ sinh type OpenAPI (frontend/tools/openapi-ts)
	$(FE) npm ci && npm run tools:install
fe-dev:
	$(FE) npm run dev
fe-build:
	$(FE) npm run build
fe-lint:
	$(FE) npm run lint
fe-typecheck:
	$(FE) npm run typecheck
fe-test:
	$(FE) npm test
fe-cov:
	$(FE) npm run test:cov

.PHONY: fe-gen-api fe-api-check
fe-gen-api:	## sinh type TS từ frontend/src/lib/api/openapi.json (R7) — chạy sau mỗi lần bw dump-openapi
	$(FE) npm run gen:api
fe-api-check:	## type đã commit phải trùng bản sinh lại từ openapi.json
	$(FE) npm run check:api

ci: secrets-scan docs-check skills-check openapi-check be-lint be-cov rt-typecheck rt-cov fe-api-check fe-lint fe-typecheck fe-cov fe-build scaffold-check	## chạy tay trước khi deploy

skills-sync:	## chép skill bản gốc .agents/skills/ (Codex, Gemini) sang .claude/skills/ (Claude Code) — D26
	python3 scripts/skills_sync.py
skills-check:	## CI: .claude/skills/ phải khớp .agents/skills/
	python3 scripts/skills_sync.py --check

new-module:	## sinh module CRUD theo khuôn Tasks: make new-module NAME=notes TITLE="Ghi chú" [TITLE_EN="Notes"]
	$(BE) poetry run python ../scripts/scaffold/new_module.py $(NAME) --title "$(TITLE)" $(if $(TITLE_EN),--title-en "$(TITLE_EN)",)
	$(MAKE) openapi fe-gen-api

scaffold-check:	## sinh module thử vào bản sao tạm → lint + test BE / FE của module (trong `make ci`)
	scripts/scaffold/check.sh

new-app:	## tạo app mới từ template: make new-app NAME="Task Hub" SLUG=taskhub PREFIX=th PORTS=83 REDIS_DBS=4,5,6 DEST=../taskhub
	python3 scripts/setup_env.py --tools-only --mode shared
	$(MAKE) be-install
	backend/.venv/bin/python scripts/scaffold/new_app.py --name "$(NAME)" --slug $(SLUG) --prefix $(PREFIX) \
		--ports $(PORTS) --redis-dbs $(REDIS_DBS) --dest $(DEST)

new-app-check:	## giả bản clone ở thư mục tạm → init-app tại chỗ → không còn tên template + lint / test không hạ tầng (trước release)
	scripts/scaffold/check_app.sh

init-app:	## đổi tên app ngay trong bản clone template (D27): make init-app NAME="Task Hub" SLUG=taskhub PREFIX=th PORTS=83 REDIS_DBS=4,5,6
	python3 scripts/setup_env.py --tools-only --mode shared
	$(MAKE) be-install
	backend/.venv/bin/python scripts/scaffold/new_app.py --in-place --name "$(NAME)" --slug $(SLUG) --prefix $(PREFIX) \
		--ports $(PORTS) --redis-dbs $(REDIS_DBS)

template-sync:	## kéo bản sửa của template về app đã đổi tên (D29): make template-sync [REF=template/main] — cần remote template
	@test -f .template.json || { echo "template-sync: thiếu .template.json — chỉ chạy trong app tạo bằng make init-app / new-app"; exit 2; }
	git fetch -q template
	rm -rf debug/template-sync && mkdir -p debug/template-sync
	git archive $(or $(REF),template/main) scripts/scaffold | tar -x -C debug/template-sync
	backend/.venv/bin/python debug/template-sync/scripts/scaffold/template_sync.py --app . --ref $(or $(REF),template/main)
	rm -rf debug/template-sync

secrets-scan:	## quét trước khi push: gitleaks (lịch sử + chưa commit), tên riêng ở .secrets/private-terms.txt, trufflehog nếu có
	scripts/secrets_scan.sh

deploy:	## kích deploy Coolify + chờ + smoke qua domain thật (cấu hình .secrets/coolify.env)
	scripts/deploy.sh

smoke-prod:	## smoke qua domain thật, không ghi dữ liệu (đăng nhập nếu có .secrets/smoke.env): make smoke-prod [URL=…] — mặc định PUBLIC_URL ở .secrets/coolify.env
	scripts/smoke_prod.sh $(URL)

fake-llm:	## server LLM giả kiểu OpenAI (test / E2E agent không cần key thật) ở cổng 8799
	$(BE) poetry run python -m app.agent.testing.fake_llm --port $(or $(PORT),8799)

agent-eval:	## đo router "Assistant" trên bộ câu ý định bằng model thật (cần key ở Studio; ngoài make ci): make agent-eval [LIMIT=20]
	$(BE) poetry run bw agent-eval --limit $(or $(LIMIT),0)

notify:	## báo chủ dự án qua Discord (R28): make notify MSG="…" (cấu hình .secrets/discord.env)
	scripts/notify.sh "$(MSG)"

dev-up:	## stack thử chạy nền cho smoke / E2E (namespace bizwithagents_e2e, khoá JWT riêng), web 127.0.0.1:8201: make dev-up MONGO=on|off
	scripts/dev_stack.sh up $(or $(MONGO),on)

dev-down:	## dừng stack thử chạy nền
	scripts/dev_stack.sh down

dev-status:	## stack thử: service nào đang chạy + chế độ Mongo
	scripts/dev_stack.sh status

fe-preview:	## build rồi phục vụ bundle ở 127.0.0.1:8201 kèm proxy api / ws (chạy tay, cùng cách dev-up)
	$(FE) npm run build && ./node_modules/.bin/vite preview --host 127.0.0.1 --port 8201 --strictPort

smoke-local:	## smoke đầu-cuối qua proxy 127.0.0.1:8201 — stack phải đang chạy đúng chế độ: make smoke-local MONGO=on|off
	@test -n "$(MONGO)" || { echo "thiếu MONGO=on|off — phải khớp chế độ stack đang chạy (make dev-status)"; exit 2; }
	$(RT) SMOKE_EXPECT_MONGO=$(MONGO) node --env-file-if-exists=../.env scripts/smoke_e2e.ts http://127.0.0.1:8201 --profile local
