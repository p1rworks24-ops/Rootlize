# Capixe Real-image Semantic Retrieval Benchmark

98 local images from `D:\07_Programs\shotlogue_test`; 24 English queries; cosine ranking; no DB, threshold, result-limit, or Hybrid weighting.

## Aggregate accuracy and measured CPU performance

|Model|License|Top-1|Top-3|Top-5|Top-10|MRR|Dim|Image ms/item|Text ms/query|Peak RSS MB|Payload/checkpoint MB|
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|OpenCLIP ViT-B/32 LAION-2B|MIT|50.0%|66.7%|70.8%|79.2%|0.602|512|56.8|27.8|1507|577.1|
|SigLIP 2 Base/224|Apache-2.0|41.7%|66.7%|70.8%|83.3%|0.562|768|182.4|91.0|1116|1468.1|
|Nomic Embed Vision/Text v1.5|Apache-2.0|29.2%|37.5%|54.2%|75.0%|0.412|768|117.8|9.4|1429|876.2|
|MetaCLIP 2 Worldwide B/32|CC-BY-NC-4.0|54.2%|66.7%|79.2%|79.2%|0.631|512|153.1|212.2|1960|2317.5|
|Jina CLIP v2|CC-BY-NC-4.0|29.2%|37.5%|58.3%|83.3%|0.406|1024|4363.4|457.5|6524|1667.0|

## Best relevant rank by query

|Query|OpenCLIP ViT-B/32 LAION-2B|SigLIP 2 Base/224|Nomic Embed Vision/Text v1.5|MetaCLIP 2 Worldwide B/32|Jina CLIP v2|
|---|---:|---:|---:|---:|---:|
|Windows desktop|1|9|5|1|4|
|Windows desktop screenshot|1|19|20|1|5|
|desktop with application windows|6|5|8|3|7|
|dog|1|1|1|1|1|
|a dog|1|1|1|1|1|
|dog photo|1|1|1|1|1|
|image search application|1|7|10|4|6|
|code editor|3|51|11|23|8|
|browser window|13|2|1|15|4|
|settings screen|21|12|17|3|8|
|command prompt|1|1|2|1|1|
|terminal window|2|1|6|1|5|
|file explorer window|2|1|2|2|5|
|screenshot manager application|4|6|4|5|3|
|video game screenshot|1|2|1|1|1|
|mountain desktop wallpaper|1|1|1|1|1|
|application error message|3|2|17|1|8|
|image gallery|1|3|5|1|10|
|tag management screen|7|1|6|1|1|
|login screen|19|3|43|11|83|
|dark themed application|1|2|5|4|3|
|screen capture settings|41|18|35|28|21|
|folder selection screen|1|1|6|1|18|
|software installation screen|37|1|1|25|12|

## Required-query detailed relevant ranks

### OpenCLIP ViT-B/32 LAION-2B

- `Windows desktop`: ScreenShot_Atest_001.png=1, 20260718_202718.png=2, 20260718_203016.png=3, 20260718_202724.png=4
- `Windows desktop screenshot`: ScreenShot_Atest_001.png=1, 20260718_202718.png=2, 20260718_203016.png=3, 20260718_202724.png=4
- `desktop with application windows`: 20260718_202728.png=6, 20260718_202750.png=17, 20260718_203006.png=37
- `dog`: images.jpg=1, A2.png=2
- `a dog`: A2.png=1, images.jpg=2
- `dog photo`: images.jpg=1, A2.png=2
- `image search application`: 20260801_120339.png=1, organize.png=2, 20260718_202750.png=14, 20260801_114225.png=17, 20260801_132030.png=18, photo_001.png=20, 20260717_000902.png=27, 20260717_001005.png=28, 20260801_135518.png=33, images.png=34, 20260801_114232.png=38, 20260801_120311.png=43, 20260801_114154.png=54
- `code editor`: 20260718_202211.png=3, 20260718_201711.png=23, 20260718_201716.png=24, 20260718_201717.png=25, 20260720_233800.png=31
- `browser window`: 20260718_202750.png=13
- `settings screen`: 20260721_204004.png=21, 20260801_120357.png=28, tags.png=29, 20260718_142639_001.png=40, 20260718_143926_001.png=41, 20260721_203901.png=75

### SigLIP 2 Base/224

- `Windows desktop`: 20260718_202718.png=9, 20260718_203016.png=10, 20260718_202724.png=12, ScreenShot_Atest_001.png=19
- `Windows desktop screenshot`: 20260718_203016.png=19, 20260718_202718.png=20, 20260718_202724.png=22, ScreenShot_Atest_001.png=25
- `desktop with application windows`: 20260718_202728.png=5, 20260718_202750.png=11, 20260718_203006.png=53
- `dog`: images.jpg=1, A2.png=2
- `a dog`: images.jpg=1, A2.png=2
- `dog photo`: images.jpg=1, A2.png=2
- `image search application`: 20260801_114154.png=7, 20260801_135518.png=11, images.png=12, photo_001.png=13, 20260801_120311.png=22, 20260718_202750.png=25, 20260717_000902.png=28, 20260717_001005.png=29, 20260801_120339.png=37, organize.png=38, 20260801_132030.png=40, 20260801_114232.png=43, 20260801_114225.png=46
- `code editor`: 20260720_233800.png=51, 20260718_202211.png=52, 20260718_201711.png=64, 20260718_201716.png=65, 20260718_201717.png=66
- `browser window`: 20260718_202750.png=2
- `settings screen`: 20260721_204004.png=12, 20260718_142639_001.png=15, 20260718_143926_001.png=16, 20260801_120357.png=63, tags.png=64, 20260721_203901.png=95

### Nomic Embed Vision/Text v1.5

- `Windows desktop`: 20260718_202724.png=5, ScreenShot_Atest_001.png=6, 20260718_203016.png=7, 20260718_202718.png=8
- `Windows desktop screenshot`: ScreenShot_Atest_001.png=20, 20260718_202724.png=21, 20260718_203016.png=25, 20260718_202718.png=26
- `desktop with application windows`: 20260718_202728.png=8, 20260718_202750.png=16, 20260718_203006.png=65
- `dog`: A2.png=1, images.jpg=4
- `a dog`: A2.png=1, images.jpg=11
- `dog photo`: A2.png=1, images.jpg=12
- `image search application`: 20260718_202750.png=10, 20260801_114225.png=14, 20260801_114154.png=26, 20260801_114232.png=28, 20260801_132030.png=37, 20260801_120311.png=59, photo_001.png=62, 20260801_135518.png=63, images.png=64, 20260801_120339.png=65, organize.png=66, 20260717_000902.png=70, 20260717_001005.png=71
- `code editor`: 20260718_202211.png=11, 20260720_233800.png=55, 20260718_201716.png=59, 20260718_201717.png=60, 20260718_201711.png=61
- `browser window`: 20260718_202750.png=1
- `settings screen`: 20260721_204004.png=17, 20260718_142639_001.png=30, 20260718_143926_001.png=31, 20260801_120357.png=69, tags.png=70, 20260721_203901.png=95

### MetaCLIP 2 Worldwide B/32

- `Windows desktop`: 20260718_203016.png=1, 20260718_202718.png=2, 20260718_202724.png=3, ScreenShot_Atest_001.png=4
- `Windows desktop screenshot`: ScreenShot_Atest_001.png=1, 20260718_203016.png=2, 20260718_202718.png=3, 20260718_202724.png=4
- `desktop with application windows`: 20260718_202728.png=3, 20260718_202750.png=26, 20260718_203006.png=57
- `dog`: A2.png=1, images.jpg=2
- `a dog`: A2.png=1, images.jpg=2
- `dog photo`: A2.png=1, images.jpg=2
- `image search application`: 20260801_120311.png=4, 20260801_114154.png=5, 20260801_135518.png=8, images.png=9, 20260801_114225.png=12, photo_001.png=17, 20260801_114232.png=23, 20260801_120339.png=25, organize.png=26, 20260717_000902.png=35, 20260717_001005.png=36, 20260718_202750.png=37, 20260801_132030.png=41
- `code editor`: 20260718_202211.png=23, 20260718_201711.png=53, 20260718_201717.png=54, 20260718_201716.png=55, 20260720_233800.png=66
- `browser window`: 20260718_202750.png=15
- `settings screen`: 20260801_120357.png=3, tags.png=4, 20260721_204004.png=13, 20260721_203901.png=63, 20260718_142639_001.png=89, 20260718_143926_001.png=90

### Jina CLIP v2

- `Windows desktop`: 20260718_202724.png=4, 20260718_202718.png=5, 20260718_203016.png=6, ScreenShot_Atest_001.png=7
- `Windows desktop screenshot`: 20260718_202724.png=5, 20260718_202718.png=6, 20260718_203016.png=7, ScreenShot_Atest_001.png=10
- `desktop with application windows`: 20260718_202728.png=7, 20260718_202750.png=8, 20260718_203006.png=60
- `dog`: A2.png=1, images.jpg=2
- `a dog`: A2.png=1, images.jpg=2
- `dog photo`: A2.png=1, images.jpg=2
- `image search application`: 20260718_202750.png=6, 20260801_120339.png=7, organize.png=8, 20260801_114225.png=13, 20260717_000902.png=15, 20260717_001005.png=16, photo_001.png=22, 20260801_135518.png=25, images.png=26, 20260801_132030.png=28, 20260801_120311.png=33, 20260801_114154.png=39, 20260801_114232.png=49
- `code editor`: 20260720_233800.png=8, 20260718_202211.png=9, 20260718_201711.png=32, 20260718_201716.png=33, 20260718_201717.png=34
- `browser window`: 20260718_202750.png=4
- `settings screen`: 20260721_204004.png=8, tags.png=53, 20260801_120357.png=54, 20260718_142639_001.png=70, 20260718_143926_001.png=71, 20260721_203901.png=88

## Decision

1. OpenCLIP ViT-B/32 LAION-2B: recommended migration prototype. Best commercially usable aggregate result and 4/4 Windows desktop ranks 1-4.
2. Current SigLIP 2 Base/224: fallback. Good broad Top-10 but materially weaker on desktop, image-search application, and code-editor intent.
3. Nomic Embed Vision/Text v1.5: Apache alternative, but lower real-library retrieval quality and two-tower integration work.

MetaCLIP 2 is the raw accuracy winner but CC-BY-NC-4.0 prevents commercial product distribution. Jina CLIP v2 is also non-commercial and measured at 4.36 s/image with 6.5 GB peak RSS.
