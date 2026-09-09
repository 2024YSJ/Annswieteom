# -*- coding: utf-8 -*-
"""원본 로고 하나에서 app/ 아래 아이콘 에셋을 전부 다시 만든다.

    cd frontend && python logo/generate_icons.py

만들어지는 파일(모두 커밋 대상):
    app/icon.png             파비콘 — 브라우저 탭
    app/apple-icon.png       iOS 홈 화면 아이콘
    app/opengraph-image.png  링크 공유 카드

로고 출처는 Flaticon(juicy_fish)이고 제작자 표기가 필수다 — README 의
'에셋 출처'와 components/SiteFooter.tsx 참고. 텍스트는 사이트 본문과 같은
Noto Sans KR(OFL)을 쓴다.
"""
import os
from PIL import Image, ImageDraw, ImageFont

SRC = "logo/free-icon-no-bed-13322151.png"
FONT = "C:/Windows/Fonts/NotoSansKR-VF.ttf"

BG = (246, 245, 242, 255)      # --surface
FG = (26, 26, 24, 255)         # --foreground
ACCENT = (176, 32, 47, 255)    # --accent
MUTED = (107, 102, 96, 255)    # --muted-text
WHITE = (255, 255, 255, 255)

logo = Image.open(SRC).convert("RGBA")


def font(size, weight):
    f = ImageFont.truetype(FONT, size)
    f.set_variation_by_axes([weight])
    return f


# --- icon: 브라우저 탭 파비콘 ------------------------------------------------
# 원본은 투명 배경에 검은 선이라 다크 모드 탭 스트립(진회색)에서 거의 안 보인다.
# 로고 자체가 원형이라 사각형보다 흰 원을 깔아야 자연스럽고, 라이트/다크 양쪽에서
# 다 보인다. 원은 4배로 그린 뒤 줄여서 가장자리를 부드럽게 만든다.
ICON, SS, INSET = 512, 4, 26
icon = Image.new("RGBA", (ICON * SS, ICON * SS), (0, 0, 0, 0))
ImageDraw.Draw(icon).ellipse([0, 0, ICON * SS - 1, ICON * SS - 1], fill=WHITE)
icon = icon.resize((ICON, ICON), Image.LANCZOS)
icon.alpha_composite(logo.resize((ICON - INSET * 2,) * 2, Image.LANCZOS), (INSET, INSET))
# 흑/백/투명 + 안티에일리어싱 회색뿐이라 팔레트로 바꾸면 69KB -> 13KB 가 된다.
icon.quantize(colors=128, method=Image.FASTOCTREE).save("app/icon.png", optimize=True)
print("app/icon.png", icon.size, os.path.getsize("app/icon.png"), "bytes")

# --- apple-icon: iOS 홈 화면 아이콘 -----------------------------------------
# 투명 픽셀이 있으면 iOS가 검게 채우므로 배경을 불투명 흰 사각형으로 깐다.
# 모서리 라운딩도 iOS가 알아서 하므로 여기서는 하지 않고, 대신 마크가 잘리지
# 않도록 여백을 넉넉히 준다.
APPLE = 180
apple = Image.new("RGBA", (APPLE, APPLE), WHITE)
mark = logo.resize((round(APPLE * 0.76),) * 2, Image.LANCZOS)
apple.alpha_composite(mark, ((APPLE - mark.width) // 2, (APPLE - mark.height) // 2))
apple.convert("RGB").save("app/apple-icon.png", optimize=True)
print("app/apple-icon.png", apple.size, os.path.getsize("app/apple-icon.png"), "bytes")

# --- opengraph-image: 링크 공유 카드 ----------------------------------------
# 여기서는 흰 원 배경을 쓰지 않는다 — 카드 배경이 이미 밝은 크림색이라 흰 원이
# 옅은 후광처럼 보일 뿐이고, 파비콘과 달리 다크 배경 위에 놓일 일도 없어서
# 원본 로고를 그대로 얹는 쪽이 깔끔하다.
W, H = 1200, 630
og = Image.new("RGBA", (W, H), BG)
d = ImageDraw.Draw(og)
d.rectangle([0, 0, W, 12], fill=ACCENT)          # 문서 머리말 같은 포인트 바

MARK = 300
og.alpha_composite(logo.resize((MARK, MARK), Image.LANCZOS), (140, (H - MARK) // 2 + 6))

x = 520
f_title, f_lead, f_sub = font(104, 900), font(42, 700), font(28, 500)
title = "안 쉬었음"
lead = "우리는 쉬지 않았습니다."
sub = "공백기를 근거 있는 STAR 내러티브로 정리해드려요."


def ink(text, f):
    """(위쪽 여백, 실제 글자 높이). textbbox 의 top 은 글자마다 다른 어센더
    여백을 포함해서, 그대로 쌓으면 줄간격이 들쭉날쭉해진다."""
    _, t, _, b = d.textbbox((0, 0), text, font=f)
    return t, b - t


rule_gap, gap1, gap2, RULE_H = 32, 26, 26, 5
(t0, h0), (t1, h1), (t2, h2) = ink(title, f_title), ink(lead, f_lead), ink(sub, f_sub)
y = (H - (h0 + rule_gap + RULE_H + gap1 + h1 + gap2 + h2)) // 2 + 6

d.text((x, y - t0), title, font=f_title, fill=FG)
y += h0 + rule_gap
d.rectangle([x, y, x + 96, y + RULE_H], fill=ACCENT)   # 제목 밑줄
y += RULE_H + gap1
d.text((x, y - t1), lead, font=f_lead, fill=ACCENT)
y += h1 + gap2
d.text((x, y - t2), sub, font=f_sub, fill=MUTED)

og.convert("RGB").save("app/opengraph-image.png", optimize=True)
print("app/opengraph-image.png", og.size, os.path.getsize("app/opengraph-image.png"), "bytes")
