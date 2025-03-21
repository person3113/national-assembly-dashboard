from PIL import Image, ImageDraw, ImageFont
import os

# 이미지 크기 및 색상 설정
width, height = 200, 200
background_color = (240, 240, 240)
text_color = (70, 70, 70)

# 이미지 생성
img = Image.new('RGB', (width, height), background_color)
draw = ImageDraw.Draw(img)

# 원 그리기 (프로필 이미지 테두리)
circle_border = 2
circle_color = (180, 180, 180)
draw.ellipse((10, 10, width-10, height-10), outline=circle_color, width=circle_border)

# 텍스트 추가
text = "의원"
# 폰트 설정 (기본 폰트 사용)
try:
    # 시스템에 따라 적절한 폰트 경로 지정 필요
    font = ImageFont.truetype("arial.ttf", 40)
except IOError:
    font = ImageFont.load_default()

# 텍스트 중앙 정렬을 위한 위치 계산
text_width, text_height = draw.textsize(text, font=font) if hasattr(draw, 'textsize') else (80, 40)  # 예상 크기
text_position = ((width - text_width) // 2, (height - text_height) // 2)

# 텍스트 그리기
draw.text(text_position, text, font=font, fill=text_color)

# 저장 경로 확인 및 생성
save_dir = "app/static/images"
if not os.path.exists(save_dir):
    os.makedirs(save_dir)

# 이미지 저장
img.save(os.path.join(save_dir, "profile-placeholder.jpg"))

print(f"프로필 이미지가 생성되었습니다: {os.path.join(save_dir, 'profile-placeholder.jpg')}")