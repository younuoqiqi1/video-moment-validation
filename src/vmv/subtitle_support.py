"""vmv.subtitle_support

Generic subtitle font loading and narration text normalization.
"""

import os
import re
import shutil
from typing import Optional, Tuple

DEFAULT_FONTS = (
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
)

FILTER_STRING = "subtitles=filename=subtitles.srt:fontsdir=fonts:force_style='FontSize=28,MarginV=40'"


def _is_valid_font(path: str) -> bool:
    return (
        os.path.isfile(path)
        and not os.path.islink(path)
        and os.path.getsize(path) > 0
    )


def prepare_subtitle_assets(
    tmpdir: str, subtitle_font: Optional[str] = None, subtitle_font_name: Optional[str] = None
) -> Tuple[str, str]:
    candidate: Optional[str] = None
    if subtitle_font is not None:
        if (
            isinstance(subtitle_font, str)
            and subtitle_font.lower().endswith((".ttf", ".otf", ".ttc"))
            and _is_valid_font(subtitle_font)
        ):
            candidate = subtitle_font
    else:
        for font_path in DEFAULT_FONTS:
            if _is_valid_font(font_path):
                candidate = font_path
                break

    if not candidate:
        raise ValueError("需要支持中文的本地字体，请提供 --subtitle-font")

    fonts_dir = os.path.join(tmpdir, "fonts")
    os.makedirs(fonts_dir, exist_ok=True)
    ext = os.path.splitext(candidate)[1].lower()
    shutil.copyfile(candidate, os.path.join(fonts_dir, f"font{ext}"))
    family = choose_font_family(os.path.basename(candidate), subtitle_font_name)
    return FILTER_STRING.replace("FontSize=28", "FontName=" + family + ",FontSize=28"), os.path.basename(candidate)


def normalize_subtitle_text(narration: str) -> str:
    if not isinstance(narration, str) or not narration.strip():
        raise ValueError("narration must be a non-empty string")

    text = narration.replace("\r\n", "\n").replace("\r", "\n")
    for ch in text:
        if ord(ch) < 32 and ch not in ("\n", "\t"):
            raise ValueError(f"Disallowed control character: {repr(ch)}")

    text = re.sub(r"\n\s*\n", "\n", text)
    return text.strip()

import re
from typing import Optional


def choose_font_family(
    filename: str, explicit_name: Optional[str] = None
) -> str:
  if explicit_name is not None:
    if re.fullmatch(r"[\w -]+", explicit_name):
      return explicit_name
    raise ValueError(f"Invalid font family name: {explicit_name}")

  fn = filename.lower()
  family_map = {
      "stheiti": "Heiti SC",
      "songti": "Songti SC",
      "notosanscjk": "Noto Sans CJK SC",
      "notoserifcjk": "Noto Serif CJK SC",
  }
  for key, family in family_map.items():
    if key in fn:
      return family

  raise ValueError("请同时提供 --subtitle-font-name 字体家族名")
