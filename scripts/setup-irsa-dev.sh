#!/usr/bin/env bash
# backend-record(dev) IRSA 셋업 스크립트
#
# ServiceAccount(dpyb-record-dev/backend-record)에 연결할 IAM Role 을 만들고
# Bedrock 호출 권한(scripts/bedrock-ocr-policy.json)을 붙인다.
# k8s/overlays/dev/serviceaccount-patch.yaml 의 role-arn 과 이름이 일치해야 한다.
#
# 전제: eksctl, aws CLI 설치 및 dev 계정(594532711953) 권한으로 로그인된 상태.
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:?클러스터 이름을 지정하세요. 예: CLUSTER_NAME=dpyb-dev ./scripts/setup-irsa-dev.sh}"
REGION="${REGION:-ap-northeast-2}"          # 클러스터가 있는 리전
ACCOUNT_ID="594532711953"
NAMESPACE="dpyb-record-dev"
SA_NAME="backend-record"
ROLE_NAME="dpyb-record-dev-bedrock-ocr"     # serviceaccount-patch.yaml 의 role-arn 과 동일해야 함
POLICY_NAME="dpyb-record-dev-bedrock-ocr"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 클러스터에 OIDC provider 가 없으면 연결(이미 있으면 no-op)
eksctl utils associate-iam-oidc-provider \
  --cluster "$CLUSTER_NAME" --region "$REGION" --approve

# 권한 정책 생성(이미 있으면 스킵)
POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${POLICY_NAME}"
if ! aws iam get-policy --policy-arn "$POLICY_ARN" >/dev/null 2>&1; then
  aws iam create-policy \
    --policy-name "$POLICY_NAME" \
    --policy-document "file://${SCRIPT_DIR}/bedrock-ocr-policy.json"
fi

# IAM Role 만 생성(--role-only): ServiceAccount 는 kustomize/ArgoCD 가 관리하므로
# eksctl 이 SA 를 건드리지 않도록 한다. 신뢰정책은 이 SA 로 스코프된다.
eksctl create iamserviceaccount \
  --cluster "$CLUSTER_NAME" --region "$REGION" \
  --namespace "$NAMESPACE" --name "$SA_NAME" \
  --role-name "$ROLE_NAME" \
  --attach-policy-arn "$POLICY_ARN" \
  --role-only \
  --approve

echo
echo "완료. Role ARN: arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
echo "이 ARN 이 k8s/overlays/dev/serviceaccount-patch.yaml 과 일치하는지 확인하세요."
