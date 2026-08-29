from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

source = Path(r"D:\07_Programs\shotlogue_test")
paths = [p for p in sorted(source.iterdir()) if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}]
font = ImageFont.load_default()
cell_w, cell_h, thumb_h, columns = 260, 185, 150, 4
rows = (len(paths) + columns - 1) // columns
sheet = Image.new("RGB", (cell_w * columns, cell_h * rows), "white")
draw = ImageDraw.Draw(sheet)
for index, path in enumerate(paths):
    x, y = (index % columns) * cell_w, (index // columns) * cell_h
    with Image.open(path) as source_image:
        image = source_image.convert("RGB")
        image.thumbnail((cell_w - 8, thumb_h - 8))
        sheet.paste(image, (x + (cell_w-image.width)//2, y + 4))
    draw.text((x + 4, y + thumb_h + 2), path.name, fill="black", font=font)
target = Path(__file__).with_name("contact_sheet.jpg")
sheet.save(target, quality=90)
print(target)
