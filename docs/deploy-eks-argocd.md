# EKS + ArgoCD 배포 가이드

이 문서는 `backend-record` (FastAPI) 서비스를 **AWS EKS** 에 **ArgoCD(GitOps)** 로 배포하는 방법을 정리합니다.
`backend-auth` 와 동일한 구조를 따르며, 현재는 **개발(dev) 환경만** 사용하고 상용(prod) 관련 내용은 주석으로 남겨두었습니다.

## 환경 구성

| 환경 | 브랜치 | 네임스페이스 | overlay | ArgoCD App |
| --- | --- | --- | --- | --- |
| 개발 | `develop` | `dpyb-record-dev` | `k8s/overlays/dev` | `backend-record-dev` |
<!-- prod 사용 시 아래 행 주석 해제
| 상용 | `main` | `dpyb-record` | `k8s/overlays/prod` | `backend-record-prod` |
-->

> 매니페스트는 **Kustomize base + overlay** 구조라 공통 부분은 한 벌만 관리하고,
> 환경별로 다른 값(레플리카·APP_ENV·이미지 태그)만 overlay 에서 덮어씁니다.

## 큰 그림

```
  develop 브랜치 push
        │
        ▼
[GitHub Actions] 이미지 빌드→ECR 푸시→dev overlay 태그 갱신 커밋
        │
        ▼
[Git] k8s/overlays/dev
        │  (ArgoCD 감시)
        ▼
[EKS] dpyb-record-dev 네임스페이스
```

즉 **사람이 `kubectl apply` 를 직접 하지 않고**, `develop` 에 올리면 ArgoCD 가 자동 반영합니다.
(prod 사용 시 `main` → `dpyb-record` 네임스페이스로 같은 흐름이 하나 더 추가됩니다.)

## 파일 구조

```
Dockerfile / .dockerignore          # FastAPI 앱 컨테이너 이미지
k8s/
  base/                             # 공통 매니페스트 (네임스페이스·이미지태그 없음)
    kustomization.yaml
    configmap.yaml                  # 비민감 설정 (APP_HOST/PORT 등)
    deployment.yaml                 # 앱 실행 (마이그레이션 initContainer + /health 프로브)
    service.yaml                    # ClusterIP Service
    ingress.yaml                    # ALB Ingress (외부 노출)
  overlays/
    dev/                            # namespace dpyb-record-dev, replicas 1, APP_ENV=development
    prod/                           # (주석 상태) namespace dpyb-record, replicas 2, APP_ENV=production
  secret.example.yaml               # 비밀값 생성 "예시" (실제 값은 Git 에 안 올림)
argocd/
  application-dev.yaml              # develop → dev
  application-prod.yaml             # (주석 상태) main → prod
.github/workflows/build-push-ecr.yml # develop 이미지 빌드/푸시 + dev overlay 태그 갱신
```

> ALB 용 `IngressClass`(`eks.amazonaws.com/alb`)는 클러스터 전역 리소스로,
> `backend-auth` 레포의 `k8s/cluster/ingressclass-alb.yaml` 로 이미 1회 적용되어 있습니다.
> `dpyb-dev` 클러스터에 다시 적용할 필요는 없습니다.

## 사전 준비 (한 번만)

1. **EKS 클러스터**(`dpyb-dev`) 에 `kubectl` 접속이 됨
2. **ECR 리포지토리** 생성 (서비스별로 분리된 ECR 사용 중)
   ```bash
   aws ecr create-repository --repository-name dpyb-dev/dpyb-record --region ap-northeast-2
   ```
3. **ArgoCD** 는 `dpyb-dev` 클러스터에 이미 설치되어 있음 (다른 서비스와 공유)
4. **GitHub Actions 용 IAM 역할(OIDC)** — `backend-auth` 에서 쓰는 역할과 동일한 역할을 재사용하려면
   신뢰 정책(trust policy)의 `sub` 조건에 `repo:dont-paw-get/backend-record:*` 를 추가해야 합니다.
   이 리포지토리 전용 역할을 새로 만드는 경우, ECR 푸시 권한(`dpyb-dev/dpyb-record` 리포지토리)을 부여하고
   GitHub 리포지토리 Settings → Secrets and variables → Actions → **Variables** 에
   `AWS_GHA_ROLE_ARN` 으로 등록하세요.

## 채워야 하는 placeholder

- `k8s/overlays/dev/kustomization.yaml` → 이미지 경로는 이미 채워짐(`newTag` 는 최초값이며 이후 CI 가 자동 갱신)
- `k8s/base/ingress.yaml` → (선택) 도메인 `host`
<!-- prod 사용 시: k8s/overlays/prod/kustomization.yaml, configmap-patch.yaml 의 값도 채우세요. -->

## 배포 순서

```bash
# 1) 비밀값(Secret) 은 Git 이 아니라 네임스페이스에 직접 생성
kubectl create namespace dpyb-record-dev
kubectl create secret generic backend-record-secret \
  --namespace dpyb-record-dev \
  --from-literal=DATABASE_URL='postgresql+psycopg://user:pass@dev-rds-host:5432/db' \
  --from-literal=CLOVA_OCR_INVOKE_URL='https://xxxxx.apigw.ntruss.com/custom/v1/00000/xxxxxxxx/general' \
  --from-literal=CLOVA_OCR_SECRET_KEY='xxxxxxxx'

# 2) ArgoCD Application 등록 (이후는 GitOps 자동)
kubectl apply -f argocd/application-dev.yaml

# 3) 동기화 확인
kubectl get applications -n argocd
kubectl get pods,svc,ingress -n dpyb-record-dev
```

<!-- prod 사용 시
kubectl create namespace dpyb-record
kubectl create secret generic backend-record-secret \
  --namespace dpyb-record \
  --from-literal=DATABASE_URL='postgresql+psycopg://user:pass@prod-rds-host:5432/db' \
  --from-literal=CLOVA_OCR_INVOKE_URL='...' \
  --from-literal=CLOVA_OCR_SECRET_KEY='...'
kubectl apply -f argocd/application-prod.yaml
kubectl get pods,svc,ingress -n dpyb-record
-->

이후 `develop` 에 머지하면
→ CI 이미지 빌드/푸시 + dev overlay 태그 갱신 커밋 → ArgoCD 자동 배포됩니다.

## 로컬에서 렌더링/이미지 검증

```bash
# Kustomize 결과 미리보기 (클러스터 없이 가능)
kubectl kustomize k8s/overlays/dev
# kubectl kustomize k8s/overlays/prod   # prod 사용 시

# Dockerfile 검증
docker build -t backend-record:local .
docker run --rm -p 8000:8000 \
  -e DATABASE_URL='postgresql+psycopg://...' \
  -e CLOVA_OCR_INVOKE_URL='...' \
  -e CLOVA_OCR_SECRET_KEY='...' \
  backend-record:local
curl localhost:8000/health   # {"status":"ok"}
```

## 참고: Secret 을 Git 으로 관리하고 싶다면

평문 Secret 은 절대 커밋하지 말고, 아래 중 하나를 사용하세요.

- **SealedSecrets** — `kubeseal` 로 암호화한 SealedSecret 을 커밋
- **External Secrets Operator** — AWS Secrets Manager / SSM Parameter Store 와 연동
