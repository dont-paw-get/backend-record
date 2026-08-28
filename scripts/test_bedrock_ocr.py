"""AWS Bedrock Qwen3-VL OCR 테스트 스크립트.

사용법:
    # 1. 다국어(한/중/일/영/프) 샘플 생성 이미지로 테스트
    uv run python scripts/test_bedrock_ocr.py --lang ko  # 한국어
    uv run python scripts/test_bedrock_ocr.py --lang zh  # 중국어
    uv run python scripts/test_bedrock_ocr.py --lang ja  # 일본어
    uv run python scripts/test_bedrock_ocr.py --lang en  # 영어

    # 2. 사용자가 가진 실제 책/문장 이미지 파일로 테스트
    uv run python scripts/test_bedrock_ocr.py path/to/your/book_cover.jpg
"""
import argparse
import asyncio
import io
import os
import sys
import time
from pathlib import Path

# 프로젝트 루트 디렉터리를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()



from PIL import Image, ImageDraw, ImageFont

from app.core.config import settings
from app.services import bedrock_ocr


def generate_sample_image(lang: str = "ko") -> bytes:
    """테스트용 샘플 책 표지/문장 이미지를 생성한다 (한/중/일/영/프 다국어 지원)."""
    width, height = 650, 320
    image = Image.new("RGB", (width, height), color=(245, 243, 238))
    draw = ImageDraw.Draw(image)

    # 폰트 로드 시도
    font_title = None
    font_body = None
    for font_path in [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/AppleGothic.ttf",
    ]:
        if os.path.exists(font_path):
            try:
                font_title = ImageFont.truetype(font_path, 28)
                font_body = ImageFont.truetype(font_path, 20)
                break
            except Exception:
                pass

    draw.rectangle([(20, 20), (width - 20, height - 20)], outline=(180, 160, 140), width=3)

    if lang == "en":
        draw.text((40, 45), "THE MIDNIGHT LIBRARY", fill=(20, 20, 20), font=font_title)
        draw.text((40, 95), "Matt Haig | Viking Press", fill=(80, 80, 80), font=font_body)
        draw.text(
            (40, 145),
            "\"Between life and death there is a library,\nand within that library, the shelves go on forever.\"",
            fill=(50, 50, 50),
            font=font_body,
        )
    elif lang == "zh":
        draw.text((40, 45), "三体", fill=(20, 20, 20), font=font_title)
        draw.text((40, 95), "刘慈欣 | 重庆出版社", fill=(80, 80, 80), font=font_body)
        draw.text(
            (40, 145),
            "\"给岁月以文明，\n而不是给文明以岁月。\"",
            fill=(50, 50, 50),
            font=font_body,
        )
    elif lang == "ja":
        draw.text((40, 45), "ノルウェイの森", fill=(20, 20, 20), font=font_title)
        draw.text((40, 95), "村上春樹 | 講談社文庫", fill=(80, 80, 80), font=font_body)
        draw.text(
            (40, 145),
            "「僕たちの記憶はどこへ消えていくのだろうか。\n時の流れはすべてを押し流してしまう。」",
            fill=(50, 50, 50),
            font=font_body,
        )
    elif lang == "fr":
        draw.text((40, 45), "L'Étranger", fill=(20, 20, 20), font=font_title)
        draw.text((40, 95), "Albert Camus | Éditions Gallimard", fill=(80, 80, 80), font=font_body)
        draw.text(
            (40, 145),
            "\"Aujourd'hui, maman est morte.\nOu peut-être hier, je ne sais pas.\"",
            fill=(50, 50, 50),
            font=font_body,
        )
    else:
        draw.text((40, 45), "우리가 빛의 속도로 갈 수 없다면", fill=(20, 20, 20), font=font_title)
        draw.text((40, 95), "김초엽 소설집 | 허블", fill=(80, 80, 80), font=font_body)
        draw.text(
            (40, 145),
            "\"가장 멀리서 온 사람의 이야기가\n가장 깊은 곳에 닿는다.\"",
            fill=(50, 50, 50),
            font=font_body,
        )

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


async def main():
    parser = argparse.ArgumentParser(description="AWS Bedrock Qwen3-VL OCR 테스트")
    parser.add_argument("image_path", nargs="?", help="테스트할 이미지 파일 경로 (생략 시 샘플 이미지 생성)")
    parser.add_argument(
        "--lang",
        choices=["ko", "zh", "ja", "en", "fr"],
        default="ko",
        help="샘플 이미지 언어 선택 (ko: 한국어, zh: 중국어, ja: 일본어, en: 영어, fr: 프랑스어)",
    )
    parser.add_argument(
        "--model-id",
        default=settings.BEDROCK_OCR_MODEL_ID,
        help=f"Bedrock 모델 ID (기본값: {settings.BEDROCK_OCR_MODEL_ID})",
    )
    args = parser.parse_args()

    if args.image_path:
        img_path = Path(args.image_path)
        if not img_path.exists():
            print(f"[오류] 이미지 파일을 찾을 수 없습니다: {img_path}")
            sys.exit(1)
        image_bytes = img_path.read_bytes()
        ext = img_path.suffix.lower().lstrip(".")
        image_format = ext if ext in ("png", "jpg", "jpeg", "webp") else "jpeg"
        print(f"[입력] 사용자 이미지 파일: {img_path} ({len(image_bytes):,} bytes)")
    else:
        image_bytes = generate_sample_image(lang=args.lang)
        image_format = "png"
        lang_names = {
            "ko": "한국어",
            "zh": "중국어 원서",
            "ja": "일본어 원서",
            "en": "영어 원서",
            "fr": "프랑스어/유럽어 원서",
        }
        print(f"[입력] 자동 생성된 샘플 책 표지 ({lang_names.get(args.lang, args.lang)}) ({len(image_bytes):,} bytes)")

    print(f"[설정] 모델 ID: {args.model_id}")
    print(f"[설정] AWS Region: {settings.AWS_REGION}")
    print(f"[설정] AWS Profile: {settings.AWS_PROFILE or '(default / env)'}")
    print("=" * 60)
    print("Bedrock Qwen3-VL OCR 호출 중...")

    start_time = time.perf_counter()
    try:
        result = await bedrock_ocr.extract_text_from_image(
            image_bytes=image_bytes,
            image_format=image_format,
            model_id=args.model_id,
        )
    except Exception as e:
        print(f"[오류 발생] {type(e).__name__}: {e}")
        sys.exit(1)

    elapsed = time.perf_counter() - start_time
    print("=" * 60)
    print(
        f"[성공] 응답 시간: {elapsed:.2f}초 | 언어: {result.language} | 신뢰도: {result.confidence} | Request ID: {result.request_id}"
    )
    print("-" * 60)
    print("[추출된 전체 텍스트 (text)]:")
    print(result.text)
    print("-" * 60)
    print(f"[줄 단위 분리 목록 (lines: 총 {len(result.lines)}줄)]:")
    for idx, line in enumerate(result.lines, 1):
        print(f"  {idx}: {line}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
