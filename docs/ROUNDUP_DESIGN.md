# 7 Seas News: roundup design (approved Nov 2026)

The code in `bot/roundup_design.py` is the source of truth. This page explains it in words.
Reference images are in `tests/golden/`.

## Sizes

| What | Size | Where it is used |
|---|---|---|
| TikTok cover | 1080 × 1350 | TikTok slideshow, slide 1 |
| TikTok slides | 1080 × 1350 | The bot's normal post image (with headline), one per story |
| Video | 1080 × 1920, 30 fps, H.264 + AAC | YouTube Shorts and Facebook |
| Video cover / thumbnail | 1080 × 1920 | YouTube thumbnail, Facebook cover, first video frame |
| Story frames | 1080 × 1920 | Post (1080 × 1350) placed at **y = 285** |
| Last frame | 1080 × 1920 | "FOLLOW FOR MORE" |

## Cover (1080 × 1350). All positions are top-left, margin 64

| Element | Font / size | Position | Colour |
|---|---|---|---|
| Background | gradient (26,26,29) → (8,8,9), globe centre (700, 520) r 480, 40 grey dots (seed 7), **5 red pins**, black fade from y 513 to 945 (alpha 245) | full | |
| Logo | logo.png, **330 px wide** | x 64, y 64 | |
| Label box | SemiBold 26, letter-spacing 4 | box x 64, **y 600–652**, text x 84, y 606 | box red, text white |
| "NOV" + "15" | **Bold 190** | x 64, **y 668**, shadow +3,+4 black | NOV white, day **red** |
| "TOP STORIES" | **Bold 84** | x 64, **y 885**, shadow +2,+3 | white |
| Hook (2 short sentences) | **SemiBold 46** | text x 94, y 1012 (2nd line y 1068) | white |
| Hook red bar | 8 px wide | x 64, from y 1010, height 66 (+56 per extra line) | red |
| Weekday "SUNDAY · 2026" | **SemiBold 36**, no letter-spacing | x 64, **y 1150** (1 hook line) or **1170** (2 lines) | grey (205,205,210) |
| Footer line | 4 px | x 64 to 1016, **y 1238** | red |
| "VERIFIED WORLD NEWS · EVERY DAY" | Medium 24 | x 64, y 1268 | grey |
| "SWIPE" + arrow | SemiBold 28, spacing 3; arrow 46 px line + head | right side, y 1264 | white / red |

Hook rule: each sentence must fit on **one line (max 922 px at size 46, about 32 characters)**.
The hook is never wrapped in the middle of a sentence and never shrunk. If it is too long, ask Gemini for a shorter one.
Never write "TODAY'S" and never a story count.

## Video cover (1080 × 1920)
The 1080 × 1350 cover is placed at y 285. Rows 0–284 are filled with the cover's own top colour (pixel 540,2, about 25,25,27).
Rows 1635–1919 are filled with (8,8,8).

## Story frames (1080 × 1920)
1. The bot renders the post at 1080 × 1350 **with `hide_headline=True`** and places it at y 285.
2. Above the post: post rows 170–900 (photo only) zoomed to 1920 high, **blurred with radius 34**, mixed **45 % with black**.
   It fades into the sharp post from y 275 to y 395.
3. Below the post: the post's bottom colour (pixel 540, 1347).
4. Progress line: **y 0–8**, full width. Track is black at 55 %; red fill up to `idx / n`.
5. Counter pill "01 / 13" (always 2 digits each): SemiBold 30, white text. Black pill at 59 %, height 50, radius 25,
   right edge x 1016, top **y 355**, padding 18 each side, no border.
6. Headline typed letter by letter, using the bot's own headline layout (+285 on y).
   Cursor is a red block 13 % of the font size wide, from 18 % to 112 % of the size.
   Typing time = characters × 0.028 s, between 1.4 and 2.4 s. Hold the full headline for 2.2 s.
   The cursor blinks every 9 frames for the first 36 frames of the hold.

## Timing and transitions
- Opening: the video cover held for **1.3 s** with a low "boom", then a red swipe out.
- Swipe: **8 frames** each way, smoothstep easing. The red panel has a white edge 12 px wide, 6 px from the panel edge.
  "out" = red comes in from the right (with a whoosh, played 0.12 s early). "in" = red leaves to the left.
- Each story: swipe in → typing (one click per letter) → hold → swipe out.
- Last frame: swipe in, then hold for **2.6 s**.

## Last frame (1080 × 1920, black (8,8,9))
| Element | Font / size | Position |
|---|---|---|
| Logo | 660 px wide | centred, top y 767 |
| Red bar | 120 × 6 | centred, y 930 |
| "FOLLOW FOR MORE" | **Bold 58**, white | centred, top y 1000 |
| "VERIFIED WORLD NEWS · EVERY DAY" | Medium 30, grey | centred, top y 1085 |

Never use "Follow for Part 2" or "next part".

## Sounds (the bot's own Reel sounds, `main.roundup_audio`)
- boom: at the cover
- key: the Reel typing click for every typed letter (a softer click for spaces)
- whoosh: the Reel whoosh at every swipe to the next story

Same sounds as the single-story Reels (REEL_TYPING_SOUND / REEL_SOUND_VOLUME in settings.py). Music is not built in
(the owner adds it in the apps).
