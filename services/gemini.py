import google.generativeai as genai
from config import GEMINI_API_KEY
from models import ParsedResult, PriceEntry
from prompts import VOICE_PROMPT, VISION_PROMPT, TEXT_PROMPT, PRICE_SCHEMA
from sources import get_source_by_alias
import json
import logging

logger = logging.getLogger(__name__)

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")


def _normalize_source(raw: str):
    """Нормализует сырой source из Gemini → (source_id, source_detail)."""
    if not raw:
        return None, None
    return get_source_by_alias(raw)


def _parse_items(data: dict) -> list:
    """Парсит items из ответа Gemini в список PriceEntry."""
    items = []
    for item in data.get("items", []):
        raw_source = item.get("source")
        source, source_detail = _normalize_source(raw_source)
        items.append(PriceEntry(
            product=item["product"],
            price=item["price"],
            unit=item["unit"],
            source=source,
            source_detail=source_detail,
            container=item.get("container"),
            container_weight_kg=item.get("container_weight_kg")
        ))
    return items


def _parse_top_source(data: dict):
    """Нормализует top-level source → (source_id, source_detail)."""
    raw = data.get("source")
    if not raw:
        return None, None
    return get_source_by_alias(raw)


async def transcribe_and_parse(ogg_bytes: bytes) -> ParsedResult:
    """Transcribe voice message and parse prices in one call."""
    try:
        logger.info(f"Voice transcription started: {len(ogg_bytes)} bytes")
        audio_part = {"mime_type": "audio/ogg", "data": ogg_bytes}
        response = model.generate_content(
            [VOICE_PROMPT, audio_part],
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": PRICE_SCHEMA
            }
        )

        logger.info(f"Gemini response received, text: {response.text}")

        try:
            data = response.parsed
            logger.info("Used response.parsed")
        except AttributeError:
            logger.info("Falling back to json.loads(response.text)")
            data = json.loads(response.text)

        logger.info(f"Parsed JSON: {data}")

        items = _parse_items(data)
        parsed_source, parsed_source_detail = _parse_top_source(data)
        language = data.get("language", "ru")

        logger.info(f"Voice parsing complete: {len(items)} items, language={language}, source={parsed_source}, detail={parsed_source_detail}")
        return ParsedResult(source=parsed_source, source_detail=parsed_source_detail, items=items, language=language)
    except Exception as e:
        logger.error(f"Voice parsing error: {str(e)}", exc_info=True)
        raise Exception(f"Voice parsing failed: {str(e)}")


async def parse_photo(image_bytes: bytes) -> ParsedResult:
    """Parse prices from photo/screenshot."""
    try:
        image_part = {"mime_type": "image/jpeg", "data": image_bytes}
        response = model.generate_content(
            [VISION_PROMPT, image_part],
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": PRICE_SCHEMA
            }
        )

        try:
            data = response.parsed
        except AttributeError:
            data = json.loads(response.text)

        items = _parse_items(data)
        parsed_source, parsed_source_detail = _parse_top_source(data)
        language = data.get("language", "ru")

        return ParsedResult(source=parsed_source, source_detail=parsed_source_detail, items=items, language=language)
    except Exception as e:
        raise Exception(f"Photo parsing failed: {str(e)}")


async def parse_free_text(text: str) -> ParsedResult:
    """Parse free-form text input (flexible word order)."""
    prompt = f"""Текст: {text}"""
    try:
        response = model.generate_content(
            [TEXT_PROMPT, prompt],
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": PRICE_SCHEMA
            }
        )

        try:
            data = response.parsed
        except AttributeError:
            data = json.loads(response.text)

        items = _parse_items(data)
        parsed_source, parsed_source_detail = _parse_top_source(data)
        language = data.get("language", "ru")

        return ParsedResult(source=parsed_source, source_detail=parsed_source_detail, items=items, language=language)
    except Exception as e:
        raise Exception(f"Text parsing failed: {str(e)}")
