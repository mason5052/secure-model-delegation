"""Build 396-point vector figures for the Korean conference paper.

Usage: python build-figures-ko.py --figure all
The output directory is this script's directory. --font accepts a Korean TTF.
"""

import argparse
import math
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parent
BLACK = "#24282D"
BLUE = "#356A93"
GRAY = "#69727B"
LIGHT_GRAY = "#D8DEE3"
PALE_BLUE = "#EDF3F7"


def register_korean_font(explicit_font=None):
    candidates = [Path(explicit_font)] if explicit_font else [
        Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf"),
        Path("/Library/Fonts/NanumGothic.ttf"),
        Path.home() / "Library/Fonts/NanumGothic.ttf",
        Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            pdfmetrics.registerFont(TTFont("Ko", str(candidate)))
            return
    raise FileNotFoundError("Supply an installed Korean TrueType font with --font.")


class Figure:
    def __init__(self, filename, width, height):
        self.width = width
        self.height = height
        self.canvas = canvas.Canvas(
            str(OUT / filename), pagesize=(width, height), pageCompression=1
        )
        self.canvas.setTitle(filename)

    def text(self, x, y, text, size=9.0, align="left", color=BLACK):
        c = self.canvas
        c.setFont("Ko", size)
        c.setFillColor(HexColor(color))
        draw = {"left": c.drawString, "center": c.drawCentredString, "right": c.drawRightString}[align]
        draw(x, self.height - y, text)

    def line(self, x1, y1, x2, y2, color=BLACK, weight=0.65, dashed=False):
        c = self.canvas
        c.setStrokeColor(HexColor(color))
        c.setLineWidth(weight)
        c.setDash(3, 2) if dashed else c.setDash()
        c.line(x1, self.height - y1, x2, self.height - y2)
        c.setDash()

    def arrow(self, x1, y1, x2, y2, weight=0.8, color=BLACK):
        self.line(x1, y1, x2, y2, weight=weight, color=color)
        angle = math.atan2(y2 - y1, x2 - x1)
        c = self.canvas
        p = c.beginPath()
        p.moveTo(x2, self.height - y2)
        for offset in (-0.43, 0.43):
            p.lineTo(x2 - 4 * math.cos(angle + offset), self.height - (y2 - 4 * math.sin(angle + offset)))
        p.close()
        c.setFillColor(HexColor(color))
        c.drawPath(p, fill=1, stroke=0)

    def frame(self, x, y, width, height, dashed=False, weight=0.65, color=BLACK, fill=None):
        c = self.canvas
        c.setStrokeColor(HexColor(color))
        if fill:
            c.setFillColor(HexColor(fill))
        c.setLineWidth(weight)
        c.setDash(3, 2) if dashed else c.setDash()
        c.rect(x, self.height - y - height, width, height, fill=bool(fill), stroke=1)
        c.setDash()

    def polygon(self, points, color=BLACK, fill=None, weight=0.8):
        c = self.canvas
        p = c.beginPath()
        p.moveTo(points[0][0], self.height - points[0][1])
        for x, y in points[1:]:
            p.lineTo(x, self.height - y)
        p.close()
        c.setLineWidth(weight)
        c.setStrokeColor(HexColor(color))
        if fill:
            c.setFillColor(HexColor(fill))
        c.drawPath(p, fill=bool(fill), stroke=1)

    def circle(self, x, y, radius, color=BLACK, fill=None, weight=0.8):
        c = self.canvas
        c.setLineWidth(weight)
        c.setStrokeColor(HexColor(color))
        if fill:
            c.setFillColor(HexColor(fill))
        c.circle(x, self.height - y, radius, fill=bool(fill), stroke=1)

    def document(self, x, y, width, height, color=BLACK, fill="#FFFFFF"):
        fold = 6
        self.polygon(
            [(x, y), (x + width - fold, y), (x + width, y + fold),
             (x + width, y + height), (x, y + height)],
            color=color, fill=fill,
        )
        self.line(x + width - fold, y, x + width - fold, y + fold, color=color)
        self.line(x + width - fold, y + fold, x + width, y + fold, color=color)

    def save(self):
        self.canvas.showPage()
        self.canvas.save()


def draw_architecture():
    f = Figure("architecture-ko.pdf", 396, 230)
    f.text(3, 10, "로컬 컴퓨터 내 실행", 9.5)
    f.frame(0.7, 17, 394.6, 209, color=LIGHT_GRAY, weight=0.7)

    f.text(36, 44, "요청 묶음", 9.5, "center")
    f.document(15, 50, 51, 49, color=LIGHT_GRAY)
    f.document(11, 54, 51, 49, color=GRAY)
    f.document(7, 58, 51, 49)
    for y, label in [(72, "입력"), (86, "대화 이력"), (100, "검색과 로그")]:
        f.text(32, y, label, 8.7, "center")

    f.text(123, 44, "민감 내용 탐지", 9.5, "center")
    f.frame(87, 54, 72, 53, color=GRAY)
    f.text(123, 71, "민감 유형과 위치", 8.5, "center")
    f.line(93, 79, 153, 79, color=LIGHT_GRAY, weight=0.6)
    f.text(123, 95, "대화 조각 복원", 8.7, "center")
    f.arrow(67, 79, 82, 79)
    f.arrow(161, 79, 178, 79)

    f.text(228, 34, "수신 대상 프로필", 9.2, "center", BLUE)
    f.arrow(228, 39, 228, 50, color=BLUE)
    f.polygon([(183, 54), (273, 64), (273, 97), (183, 107)], color=BLUE, fill=PALE_BLUE)
    f.text(225, 75, "허용 집합 구성", 9.0, "center")
    f.text(225, 92, "규칙 기반 점수", 9.0, "center")
    f.text(228, 120, "대상별 경로 선택", 9.2, "center")
    f.arrow(276, 79, 297, 79, color=BLUE)

    f.text(345, 44, "본문 후보 생성", 9.5, "center", BLUE)
    f.document(303, 54, 83, 53, color=BLUE, fill=PALE_BLUE)
    for y, label in [(70, "민감값 대체"), (85, "코드 대체 표식"), (100, "고정 설명")]:
        f.text(344, y, label, 8.7, "center")

    f.line(228, 122, 228, 132)
    f.line(78, 132, 228, 132)
    f.arrow(78, 132, 78, 155)
    f.arrow(228, 132, 228, 144)
    f.document(8, 158, 140, 59)
    f.text(77, 175, "A: 선택 경로 평가", 9.5, "center")
    f.text(77, 192, "감사 로그의 경로 이름", 8.7, "center")
    f.text(77, 208, "작성자 기대 경로와 비교", 8.7, "center")

    f.text(227, 157, "로컬 경로명 선택", 9.2, "center")
    for y, label in [(171, "처리"), (184, "거부"), (197, "설명 요청"), (210, "로컬 요약")]:
        f.circle(181, y - 3, 1.5, color=GRAY, fill=GRAY)
        f.text(188, y, label, 8.7)

    f.arrow(345, 109, 345, 142, color=BLUE)
    f.text(332, 124, "인식한", 8.5, "right", BLUE)
    f.text(332, 136, "보호값", 8.5, "right", BLUE)
    f.circle(345, 158, 14, color=BLUE, fill="#FFFFFF")
    f.text(345, 161, "잔존?", 8.7, "center")
    f.arrow(329, 158, 282, 158, color=GRAY)
    f.text(305, 150, "있음", 8.5, "center", GRAY)
    f.arrow(345, 174, 345, 187, color=BLUE)
    f.text(364, 183, "없음", 8.5, color=BLUE)
    f.document(296, 190, 91, 27, color=BLUE, fill=PALE_BLUE)
    f.text(341, 202, "B: 모의 본문 검사", 9.0, "center")
    f.text(341, 214, "로컬 JSONL 기록", 8.5, "center", BLUE)
    f.save()


def draw_protocol():
    f = Figure("protocol-ko.pdf", 396, 240)
    for x, first, second in [
        (57, "주 평가와 개발", "1,400건"),
        (197, "제어기 고정", "의사결정 로직 유지"),
        (333, "고정 후 새 사례", "추가 210, 스트레스 36"),
    ]:
        f.text(x, 12, first, 9.5, "center")
        f.text(x, 27, second, 8.7, "center", GRAY)
        f.circle(x, 38, 2.5, color=BLUE if x == 197 else GRAY, fill=BLUE if x == 197 else "#FFFFFF")
    f.line(60, 38, 192, 38, color=GRAY, weight=0.7)
    f.arrow(201, 38, 328, 38, color=GRAY, weight=0.7)
    f.text(1, 58, "후속 짝 비교: 같은 1,646건, 두 표시 조건", 10.0)

    f.text(171, 77, "기존 표시 제공", 9.5, "center", BLUE)
    f.text(171, 91, "주 평가 60건에 제공", 8.5, "center", GRAY)
    f.text(323, 77, "표시 제거", 9.5, "center", BLUE)
    f.text(323, 91, "입력은 동일하게 유지", 8.5, "center", GRAY)
    f.line(0, 98, 395, 98, color=GRAY, weight=0.7)
    f.line(94, 99, 94, 225, color=LIGHT_GRAY, weight=0.6)
    f.line(247, 99, 247, 147, color=LIGHT_GRAY, weight=0.6)
    f.line(247, 179, 247, 213, color=LIGHT_GRAY, weight=0.6)

    f.text(5, 122, "일반 실행", 9.5)
    f.text(5, 137, "탐지기 사용", 8.5, color=GRAY)
    for x in (171, 323):
        f.text(x, 116, "실제 대화 탐지", 9.0, "center")
        f.arrow(x, 121, x, 130, color=BLUE)
        f.text(x, 143, "모의 본문 기록", 9.0, "center", BLUE)
    f.line(171, 150, 171, 155, color=BLUE)
    f.line(171, 155, 323, 155, color=BLUE)
    f.line(323, 150, 323, 155, color=BLUE)
    f.text(247, 169, "경로와 기록 본문 동일", 9.2, "center", BLUE)
    f.line(0, 178, 395, 178, color=LIGHT_GRAY, weight=0.7)

    f.text(5, 193, "작성자 유형", 9.5)
    f.text(5, 207, "제공 시험", 9.5)
    f.text(5, 222, "탐지기 생략", 8.5, color=GRAY)
    f.text(171, 189, "작성자 유형과 표시", 9.0, "center")
    f.text(323, 189, "작성자 유형만 제공", 9.0, "center")
    for x in (171, 323):
        f.arrow(x, 194, x, 200)
        f.text(x, 210, "경로 이름만 반환", 9.0, "center")
    f.text(247, 222, "모의 전송 기록 없음", 8.5, "center", GRAY)
    f.text(247, 234, "스트레스 분모: 일반 36 / 작성자 유형 제공 18", 8.5, "center", GRAY)
    f.save()


def draw_baseline():
    f = Figure("baseline-ko.pdf", 396, 195)
    c = f.canvas
    f.text(178, 19, "경로 일치율", 10.0, "center", BLUE)
    f.text(328, 12, "작성자 기준", 9.5, "center")
    f.text(328, 25, "등급 미달률", 9.5, "center")
    panels = [(118, BLUE), (269, GRAY)]
    scale = 1.17
    for x0, color in panels:
        for value in (0, 50, 100):
            x = x0 + scale * value
            f.line(x, 33, x, 165, color=LIGHT_GRAY, weight=0.5)
            f.text(x, 179, str(value), 8.5, "center", GRAY)
    rows = [
        ("게이트웨이 없음", 34.21, 64.86),
        ("항상 로컬 처리", 37.86, 0),
        ("전체 탐지 필터", 34.21, 64.86),
        ("대상 일괄 치환", 63.50, 21.50),
        ("경로 점수 제외", 98.36, 0),
        ("전체 SMD", 94.14, 0),
    ]
    for index, (label, agreement, violation) in enumerate(rows):
        y = 45 + index * 23
        assert pdfmetrics.stringWidth(label, "Ko", 9.0) < 108, label
        f.text(1, y + 3, label, 9.0)
        for (x0, color), value in zip(panels, (agreement, violation)):
            if value:
                c.setFillColor(HexColor(color))
                c.rect(x0, f.height - y - 5, scale * value, 10, stroke=0, fill=1)
            value_label = f"{value:.2f}"
            label_width = pdfmetrics.stringWidth(value_label, "Ko", 8.5)
            if scale * value > label_width + 7:
                f.text(x0 + scale * value - 3, y + 3, value_label, 8.5, "right", "#FFFFFF")
            else:
                f.text(x0 + scale * value + 4, y + 3, value_label, 8.5, color=color)
    f.text(252, 190, "주 평가 1,400건의 비율(%)", 9.0, "center", GRAY)
    f.save()


def draw_live_model():
    f = Figure("live-model-ko.pdf", 396, 294)
    f.text(198, 12, "동일한 새 합성 문맥과 고정 정책", 10.0, "center")
    f.text(198, 27, "과제별 세 조건에서는 수신 프로필만 변경", 8.7, "center", GRAY)
    f.line(62, 36, 334, 36, color=LIGHT_GRAY)
    for x in (62, 198, 334):
        f.arrow(x, 36, x, 47, color=GRAY)
    arms = [
        (0, "A: 로컬 전용", "패턴 검사와 공통 통제", "외부 호출 없음"),
        (136, "B: 규칙과 실제 모델", "패턴 기반 민감성 검사", "외부 도움 필요를 고정"),
        (272, "C: 모델 검사와 정책", "Qwen의 실제 문맥 검사", "처리 가능성 제안"),
    ]
    for x, title, first, second in arms:
        f.frame(x + .5, 49, 123, 56, color=BLUE if x == 272 else GRAY,
                fill=PALE_BLUE if x == 272 else "#FFFFFF")
        f.text(x + 62, 65, title, 9.0, "center")
        f.text(x + 62, 83, first, 8.5, "center")
        f.text(x + 62, 97, second, 8.5, "center", GRAY)
        f.line(x + 62, 106, x + 62, 116, color=GRAY)
    f.line(62, 116, 334, 116, color=GRAY)
    f.arrow(198, 116, 198, 127, color=BLUE)
    f.frame(.5, 129, 395, 36, color=BLUE, fill=PALE_BLUE)
    f.text(198, 144, "공통 실행 경로: 앱의 정책 집행과 본문 변환", 9.5, "center", BLUE)
    f.text(198, 159, "모델의 제안은 권한을 만들지 않음 / 인식한 보호 값 최종 검사", 8.5, "center")
    f.arrow(93, 166, 93, 182, color=GRAY)
    f.arrow(288, 166, 288, 182, color=BLUE)
    f.frame(.5, 184, 183, 44, color=GRAY)
    f.text(92, 201, "로컬 처리 또는 거부·설명 요청", 9.0, "center")
    f.text(92, 218, "처리 경로에서는 실제 Qwen 답변", 8.5, "center", GRAY)
    f.frame(202, 184, 193.5, 44, color=BLUE, fill=PALE_BLUE)
    f.text(299, 201, "앱 HTTP 어댑터 -> 별도 로컬 수신기", 9.0, "center", BLUE)
    f.text(299, 218, "수신 바이트·해시 확인 후 같은 Qwen 실행", 8.5, "center")
    f.arrow(92, 229, 92, 245, color=GRAY)
    f.arrow(299, 229, 299, 245, color=BLUE)
    f.frame(.5, 247, 395, 43, color=LIGHT_GRAY)
    f.text(198, 264, "분리 채점: 경로 / 수신 보호 값 / 지정 문맥 / 실제 답변", 9.2, "center")
    f.text(198, 281, "외부 모델 품질 이득과 독립 사람 정책 판정은 이 경로로 증명되지 않음", 8.5, "center", GRAY)
    f.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--figure", choices=["protocol", "architecture", "baseline", "live-model", "all"], default="all")
    parser.add_argument("--font", help="Path to an installed Korean TrueType font")
    args = parser.parse_args()
    register_korean_font(args.font)
    draw = {"architecture": draw_architecture, "protocol": draw_protocol,
            "baseline": draw_baseline, "live-model": draw_live_model}
    for name in draw if args.figure == "all" else [args.figure]:
        draw[name]()
        print(OUT / (name + "-ko.pdf"))


if __name__ == "__main__":
    main()
